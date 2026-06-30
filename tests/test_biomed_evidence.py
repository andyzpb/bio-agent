from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from agent.plugins.decorators import _derive_params_schema
from plugins.biomed_evidence import service
from plugins.biomed_evidence.literature_client import (
    PubMedLiteratureClient,
    parse_bioc_json_full_text,
    parse_pubmed_articles,
)
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    AnswerWithEvidenceResult,
    AnswerRevision,
    BiomedProjectCreateRequest,
    BiomedicalQueryPlan,
    BiomedicalPaper,
    Citation,
    EvidenceExtractionRequest,
    EvidenceItem,
    FullTextEnhancementRequest,
    FullTextIngestionRequest,
    FullTextReanalysisRequest,
    GenerateProjectEvidenceBriefRequest,
    LiteratureAccessCheckRequest,
    LiteraturePaperRecord,
    LiteratureSearchRequest,
    LiteratureSearchCoverage,
    LiteratureSearchResult,
    LiteratureSourceTrace,
    PlanBiomedicalSearchRequest,
    ProjectClaimRecordRequest,
    ProjectPaperDecisionRequest,
    RetrievalManifest,
    SearchBiomedicalLiteratureRequest,
    WatchSnapshot,
    WatchTopicCreateRequest,
)
from plugins.biomed_evidence.guardrails import RESEARCH_USE_DISCLAIMER
from plugins.biomed_evidence.service import BiomedEvidenceService


SMOKING_SCLC_EVIDENCE = EvidenceItem(
    evidence_id="ev-smoking-sclc",
    paper_id="PMID:SMOKE",
    claim=(
        "Public health consensus and IARC monograph reviews identify tobacco "
        "smoking as an established causal risk factor and primary cause of lung "
        "cancer; SCLC is strongly linked to smoking."
    ),
    finding=(
        "IARC monograph and public health consensus evidence identify tobacco "
        "smoking as an established causal risk factor and primary cause of lung "
        "cancer, and report that most SCLC patients have a tobacco-use history."
    ),
    evidence_direction="supports",
    entities=[],
    methods=["IARC monograph", "public health consensus review"],
    limitations=["Current packet does not extract dose-response effect sizes."],
    confidence="high",
    evidence_span=(
        "IARC monograph and public health consensus evidence identify tobacco "
        "smoking as an established causal risk factor and primary cause of lung "
        "cancer, and report that most SCLC patients have a tobacco-use history."
    ),
)


class _FakeLogicResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeFullTextLogicProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, **kwargs: Any) -> _FakeLogicResponse:
        self.calls += 1
        payload = json.loads(str(kwargs["messages"][-1]["content"]))
        return _FakeLogicResponse(json.dumps(_logic_parser_payload_response(payload)))


def _logic_parser_payload_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_frames": [
            {
                "claim_id": claim["claim_id"],
                "claim_text": claim["claim_text"],
                "subject": {"text": "hydroxychloroquine", "entity_type": "drug"},
                "predicate": "associated_with",
                "object": {"text": "clinical outcomes", "entity_type": "disease"},
                "polarity": "negative",
                "modality": "suggestive",
                "population": "human",
                "claim_strength": "association",
                "scope": [],
                "qualifiers": [],
                "hedging": True,
                "source_spans": [claim["claim_text"]],
            }
            for claim in payload["claims"]
        ],
        "evidence_frames": [
            {
                "evidence_id": item["evidence_id"],
                "paper_id": item["paper_id"],
                "evidence_text": item["evidence_text"],
                "subject": {"text": "hydroxychloroquine", "entity_type": "drug"},
                "predicate": "associated_with",
                "object": {"text": "clinical outcomes", "entity_type": "disease"},
                "polarity": "negative",
                "modality": "suggestive",
                "population": "human",
                "model_system": None,
                "study_design": "randomized_trial",
                "evidence_strength": "interventional",
                "limitations": item.get("limitations", []),
                "source_spans": [item["evidence_text"]],
            }
            for item in payload["evidence_items"]
        ],
    }


@pytest.mark.asyncio
async def test_mock_answer_is_citation_grounded(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question=(
                    "What recent evidence links microglial activation to "
                    "Alzheimer's disease progression?"
                )
            )
        )
    finally:
        await service.aclose()

    assert result.not_medical_advice is True
    assert result.retrieval_id
    assert result.retrieval_manifest is not None
    assert result.retrieval_manifest.returned_paper_ids
    assert result.citations
    assert result.evidence_summary
    assert "research support only" in result.disclaimer
    assert RESEARCH_USE_DISCLAIMER not in result.answer
    assert any(
        item.evidence_direction == "supports" for item in result.evidence_summary
    )


@pytest.mark.asyncio
async def test_mock_answer_abstains_when_retrieved_evidence_is_off_topic(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question=(
                    "What evidence supports or refutes that persistent high-risk "
                    "human papillomavirus infection causes cervical cancer?"
                ),
                source="mock",
                max_papers=5,
                use_llm_planner=True,
                execute_support_refute=True,
            )
        )
    finally:
        await service.aclose()

    assert result.evidence_summary
    assert not result.citations
    assert "could not retrieve citation-backed evidence" in result.answer
    assert "microglia" not in result.answer.lower()
    assert "alzheimer" not in result.answer.lower()
    assert result.project_context_trace is not None
    assert result.project_context_trace["direct_answer_evidence_ids"] == []
    assert result.evidence_packet is not None
    assert result.evidence_packet.stop_reason == "no_relevant_evidence"


def test_established_causal_risk_factor_changes_interpretation_template() -> None:
    maturity = service._derive_evidence_maturity(
        question="Does smoking cause lung cancer and SCLC?",
        evidence=[SMOKING_SCLC_EVIDENCE],
    )
    answer = service._compose_answer(
        question="Does smoking cause lung cancer and SCLC?",
        evidence=[SMOKING_SCLC_EVIDENCE],
        papers={
            "PMID:SMOKE": BiomedicalPaper(
                paper_id="PMID:SMOKE",
                title="Smoking and lung cancer",
                source="mock",
                abstract="",
                authors=["Authority"],
                publication_date="2024",
            )
        },
        project_context=None,
        evidence_maturity=maturity,
    )

    assert maturity == "established_causal_risk_factor"
    assert "established causal risk-factor relationship" in answer
    assert "not a clinical or causal conclusion" not in answer


def test_causal_risk_maturity_ignores_secondary_cessation_outcomes() -> None:
    evidence = [
        EvidenceItem(
            evidence_id="ev-1",
            paper_id="PMID:1",
            claim="Cigarette smoking causes lung cancer.",
            finding="A vast majority of lung cancer deaths are attributable to cigarette smoking.",
            evidence_direction="supports",
            evidence_span=(
                "A vast majority of lung cancer deaths are attributable to cigarette "
                "smoking."
            ),
            confidence="high",
        ),
        EvidenceItem(
            evidence_id="ev-2",
            paper_id="PMID:2",
            claim="Quitting smoking improves outcomes in lung cancer patients.",
            finding="positive impact of quitting smoking in lung cancer patients",
            evidence_direction="supports",
            evidence_span="positive impact of quitting smoking in lung cancer patients",
            confidence="medium",
        ),
        EvidenceItem(
            evidence_id="ev-3",
            paper_id="PMID:3",
            claim="Smoking reduction from heavy to light smoking decreases lung cancer risk.",
            finding=(
                "Compared with continuing heavy smokers, reduced CPD decreased "
                "lung cancer risk."
            ),
            evidence_direction="supports",
            methods=["systematic review", "meta-analysis"],
            confidence="high",
        ),
    ]

    assert (
        service._derive_evidence_maturity(
            question=(
                "What evidence supports or refutes that cigarette smoking causes "
                "lung cancer?"
            ),
            evidence=evidence,
        )
        == "established_causal_risk_factor"
    )


def test_compose_answer_omits_contextual_background_when_direct_evidence_exists() -> None:
    direct = EvidenceItem(
        evidence_id="ev-direct",
        paper_id="PMID:DIRECT",
        claim="Cigarette smoking is a major risk factor for lung cancer.",
        finding="Cigarette smoking is a major risk factor for lung cancer.",
        evidence_direction="supports",
        confidence="high",
    )
    context = EvidenceItem(
        evidence_id="ev-context",
        paper_id="PMID:CONTEXT",
        claim="Current smoking is associated with emotional problems after diagnosis.",
        finding="Current smoking is associated with emotional problems after diagnosis.",
        evidence_direction="background",
        confidence="medium",
    )

    answer = service._compose_answer(
        question="What evidence supports that cigarette smoking causes lung cancer?",
        evidence=[direct, context],
        papers={},
        project_context=None,
    )

    assert "Evidence supporting the hypothesis:" in answer
    assert "Cigarette smoking is a major risk factor" in answer
    assert "Background or contextual evidence:" not in answer
    assert "emotional problems after diagnosis" not in answer


def test_background_only_evidence_is_not_described_as_supporting_association() -> None:
    item = EvidenceItem(
        evidence_id="ev-background",
        paper_id="PMID:BACKGROUND",
        claim="Background reproductive biology evidence.",
        finding=(
            "The paper reports pregnancies in hermaphrodites but does not establish "
            "self-fertilisation."
        ),
        evidence_direction="background",
        entities=[],
        methods=[],
        limitations=["Does not address self-fertilisation directly."],
        confidence="medium",
    )
    answer = service._compose_answer(
        question="Would a hermaphrodite become pregnant through self-fertilisation?",
        evidence=[item],
        papers={
            "PMID:BACKGROUND": BiomedicalPaper(
                paper_id="PMID:BACKGROUND",
                title="Background paper",
                source="pubmed",
                abstract="",
                authors=["Researcher"],
                publication_date="2024",
            )
        },
        project_context=None,
    )

    assert "Background or contextual evidence:" in answer
    assert "supports a research association" not in answer
    assert "does not directly answer" in answer


def test_established_causal_risk_maturity_is_not_smoking_specific() -> None:
    evidence = [
        EvidenceItem(
            evidence_id="ev-asbestos-1",
            paper_id="PMID:ASBESTOS",
            claim="Asbestos exposure is an established causal risk factor for mesothelioma.",
            finding="Asbestos exposure is an established causal risk factor for mesothelioma.",
            evidence_direction="supports",
            evidence_span=(
                "Public health consensus and systematic review evidence identify "
                "asbestos exposure as an established causal risk factor for mesothelioma."
            ),
            methods=["systematic review", "public health consensus"],
            confidence="high",
        )
    ]

    assert (
        service._derive_evidence_maturity(
            question=(
                "What evidence supports or refutes that asbestos exposure causes "
                "mesothelioma?"
            ),
            evidence=evidence,
        )
        == "established_causal_risk_factor"
    )


def test_causal_risk_maturity_requires_established_causal_evidence_not_question_wording() -> None:
    evidence = [
        EvidenceItem(
            evidence_id="ev-apap-association",
            paper_id="PMID:APAP",
            claim=(
                "Prenatal paracetamol exposure is associated with ADHD and ASD "
                "in observational studies."
            ),
            finding=(
                "Systematic review and meta-analysis evidence reports observational "
                "associations, but sibling analyses attenuate estimates toward null."
            ),
            evidence_direction="inconclusive",
            evidence_span=(
                "Existing evidence does not clearly link maternal paracetamol use "
                "during pregnancy with autism or ADHD in offspring."
            ),
            methods=["systematic review", "meta-analysis", "sibling analysis"],
            limitations=["observational confounding", "familial confounding"],
            confidence="high",
        ),
        EvidenceItem(
            evidence_id="ev-apap-negated-causal",
            paper_id="PMID:APAP-REG",
            claim="Regulatory summaries do not establish that paracetamol causes autism.",
            finding=(
                "Public health guidance states that there is no evidence paracetamol "
                "use in pregnancy causes autism in children."
            ),
            evidence_direction="supports",
            evidence_span=(
                "There is no evidence paracetamol use in pregnancy causes autism "
                "in children."
            ),
            methods=["public health guidance"],
            confidence="high",
        ),
    ]

    maturity = service._derive_evidence_maturity(
        question=(
            "What evidence supports or refutes the hypothesis that prenatal "
            "acetaminophen exposure causes autism or ADHD in offspring?"
        ),
        evidence=evidence,
    )

    assert maturity != "established_causal_risk_factor"
    assert maturity == "established_association"


def test_relevance_gate_keeps_off_topic_inconclusive_out_of_main_answer() -> None:
    direct = EvidenceItem(
        evidence_id="ev-asbestos-direct",
        paper_id="PMID:ASBESTOS",
        claim="Asbestos exposure is an established causal risk factor for mesothelioma.",
        finding="Asbestos exposure is an established causal risk factor for mesothelioma.",
        evidence_direction="supports",
        evidence_span="Asbestos exposure is an established causal risk factor for mesothelioma.",
        methods=["systematic review", "public health consensus"],
        confidence="high",
    )
    off_topic = EvidenceItem(
        evidence_id="ev-cannabis-off-topic",
        paper_id="PMID:CANNABIS",
        claim="Cannabis smoking is suspected to be a risk factor for lung cancer.",
        finding="Cannabis smoking appeared to be associated with lung cancer at an earlier age.",
        evidence_direction="inconclusive",
        evidence_span="Cannabis smoking appeared to be associated with lung cancer at an earlier age.",
        confidence="high",
    )

    split = service._split_answer_evidence(
        question="What evidence supports or refutes that asbestos exposure causes mesothelioma?",
        evidence=[direct, off_topic],
    )
    answer = service._compose_answer(
        question="What evidence supports or refutes that asbestos exposure causes mesothelioma?",
        evidence=split.direct,
        papers={},
        project_context=None,
        evidence_maturity="established_causal_risk_factor",
    )

    assert split.direct == [direct]
    assert split.contextual == [off_topic]
    assert "Cannabis smoking" not in answer
    assert (
        service._uncertainty(split.direct, "established_causal_risk_factor") == "low"
    )
    assert service._packet_limitation_level([direct, off_topic]) == "medium"
    assert service._review_priority([direct, off_topic]) == "medium"


def test_trace_answer_run_uses_latest_revision_as_display_answer(tmp_path: Path) -> None:
    service_instance = BiomedEvidenceService(tmp_path)
    try:
        run = AnswerWithEvidenceResult(
            run_id="biomed-run-revised-display",
            answer="Draft answer with an overclaimed causal interpretation.",
            citations=[],
            evidence_summary=[],
            conflicting_evidence=[],
            limitations=[],
            uncertainty_level="high",
            disclaimer=RESEARCH_USE_DISCLAIMER,
        )
        service_instance.storage.save_answer_run(run, question="Does exposure cause outcome?")
        revision = AnswerRevision(
            revision_id="revision-revised-display",
            run_id=run.run_id,
            audit_id="audit-revised-display",
            revision_mode="llm",
            draft_answer=run.answer,
            final_answer="Revised answer: evidence does not establish causality.",
            revision_action="revise",
            created_at="2026-06-29T00:00:00+00:00",
        )
        service_instance.storage.save_answer_revision(revision)

        trace = service_instance.get_answer_trace(run.run_id)
    finally:
        service_instance.storage.close()

    assert trace is not None
    answer_run = cast(dict[str, Any], trace["answer_run"])
    assert answer_run["answer"] == revision.final_answer


def test_unknown_answer_citations_are_detected() -> None:
    assert service._unknown_answer_citations(
        "Claim [MOCK-PMID-40163214] and supported claim [40163214].",
        [
            service.Citation(
                paper_id="40163214",
                title="Known paper",
                source="pubmed",
                cited_claim="Known claim",
            )
        ],
    ) == ["MOCK-PMID-40163214"]


@pytest.mark.asyncio
async def test_clinical_question_is_refused(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="My patient has memory loss. What treatment should I prescribe?"
            )
        )
    finally:
        await service.aclose()

    assert not result.citations
    assert "cannot help diagnose" in result.answer.lower()
    assert result.uncertainty_level == "high"


@pytest.mark.asyncio
async def test_patient_specific_dose_question_is_refused(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What dose should my mother take for Alzheimer disease?"
            )
        )
    finally:
        await service.aclose()

    assert not result.citations
    assert "recommend treatment" in result.answer.lower()
    assert result.uncertainty_level == "high"


@pytest.mark.asyncio
async def test_project_memory_prioritizes_saved_and_excludes_rejected(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        project = service.create_project(
            BiomedProjectCreateRequest(
                name="Microglia project",
                research_question="microglial activation and Alzheimer's disease progression",
                include_keywords=["microglial activation", "Alzheimer's disease"],
            )
        )
        seed = await service.search_with_manifest(
            SearchBiomedicalLiteratureRequest(
                query="microglial activation Alzheimer's disease progression",
                max_results=3,
                source="mock",
            )
        )
        rejected = seed.items[0].paper_id
        saved = seed.items[1].paper_id
        service.save_project_paper_decision(
            project.project_id,
            ProjectPaperDecisionRequest(
                paper_id=rejected,
                source="mock",
                decision="rejected",
                reason="Reviewer excluded this paper.",
            ),
        )
        service.save_project_paper_decision(
            project.project_id,
            ProjectPaperDecisionRequest(
                paper_id=saved,
                source="mock",
                decision="saved",
                reason="Reviewer marked as high priority.",
            ),
        )
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                project_id=project.project_id,
                source="mock",
                max_papers=3,
            )
        )
    finally:
        await service.aclose()

    assert result.project_id == project.project_id
    assert result.project_context_trace["memory_used"] is True
    assert result.retrieval_manifest is not None
    assert rejected not in result.retrieval_manifest.returned_paper_ids
    assert result.retrieval_manifest.returned_paper_ids[0] == saved
    assert all(item.paper_id != rejected for item in result.evidence_summary)
    assert result.project_context_trace["dropped_rejected_paper_ids"] == [rejected]


@pytest.mark.asyncio
async def test_project_memory_is_not_loaded_for_clinical_boundary(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        project = service.create_project(
            BiomedProjectCreateRequest(
                name="Clinical boundary project",
                research_question="Alzheimer disease evidence review",
            )
        )
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What dose should my mother take for Alzheimer disease?",
                project_id=project.project_id,
            )
        )
    finally:
        await service.aclose()

    assert result.project_id is None
    assert result.project_context_used is None
    assert result.project_context_trace["memory_used"] is False
    assert result.project_context_trace["clinical_boundary_blocked_memory"] is True
    assert not result.citations


def test_project_brief_only_promotes_audit_linked_claims(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        project = service.create_project(
            BiomedProjectCreateRequest(name="Brief project")
        )
        service.save_project_claim_record(
            project.project_id,
            ProjectClaimRecordRequest(
                claim="Memory-only claim should stay out of audited findings.",
                status="needs_review",
            ),
        )
        first_brief = service.generate_project_evidence_brief(
            GenerateProjectEvidenceBriefRequest(project_id=project.project_id)
        )
        service.save_project_claim_record(
            project.project_id,
            ProjectClaimRecordRequest(
                claim="Audited claim can enter the project brief.",
                status="supported",
                evidence_ids=["evidence-1"],
                audit_ids=["audit-1"],
                verifier_ids=["verifier-1"],
            ),
        )
        second_brief = service.generate_project_evidence_brief(
            GenerateProjectEvidenceBriefRequest(project_id=project.project_id)
        )
    finally:
        service.close()

    assert first_brief.included_claim_ids == []
    assert "Project memory is context only" in second_brief.content
    assert second_brief.audit_ids == ["audit-1"]
    assert second_brief.included_evidence_ids == ["evidence-1"]


@pytest.mark.asyncio
async def test_plan_biomedical_search_builds_valid_retrieval_plan(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_results=5,
            )
        )
    finally:
        await service.aclose()

    assert result.classification.intent == "research_question"
    assert result.query_plan is not None
    assert result.query_plan.primary_query
    assert result.query_plan.support_queries
    assert result.query_plan.refute_queries
    assert result.validation.valid is True
    assert result.search_request is not None
    assert result.search_request.source == "mock"


@pytest.mark.asyncio
async def test_plan_biomedical_search_accepts_covid_randomized_trial_query(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question=(
                    "What randomized trial evidence supports or refutes the "
                    "hypothesis that hydroxychloroquine improves outcomes in "
                    "hospitalized COVID-19 patients?"
                ),
                source="pubmed",
                max_results=5,
            )
        )
    finally:
        await service.aclose()

    assert result.classification.intent == "research_question"
    assert result.validation.valid is True
    assert result.search_request is not None
    assert "supports refutes hypothesis" not in result.validation.compiled_query
    assert '"Randomized Controlled Trial"[Publication Type]' in (
        result.validation.compiled_query
    )


@pytest.mark.asyncio
async def test_plan_biomedical_search_accepts_exposure_outcome_research_question(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question=(
                    "What evidence supports or refutes the hypothesis that prenatal "
                    "acetaminophen/paracetamol exposure causes autism spectrum "
                    "disorder or ADHD in offspring?"
                ),
                source="pubmed",
                max_results=5,
            )
        )
    finally:
        await service.aclose()

    assert result.classification.intent == "research_question"
    assert result.classification.allowed_next_step == "plan_retrieval"
    assert result.validation.valid is True
    assert result.search_request is not None
    assert result.search_request.query


@pytest.mark.asyncio
async def test_plan_biomedical_search_keeps_non_research_question_out_of_scope(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What evidence supports that my laptop battery is draining quickly?",
                source="pubmed",
                max_results=5,
            )
        )
    finally:
        await service.aclose()

    assert result.classification.intent == "out_of_scope"
    assert result.classification.allowed_next_step == "abstain"
    assert result.query_plan is None
    assert result.validation.valid is False


@pytest.mark.asyncio
async def test_plan_biomedical_search_derives_answer_scope_for_hcq_rct(
    tmp_path: Path,
) -> None:
    biomed = BiomedEvidenceService(tmp_path)
    try:
        result = await biomed.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question=(
                    "In adult patients hospitalized with COVID-19, does randomized "
                    "trial evidence show that hydroxychloroquine improves clinical "
                    "outcomes compared with usual care or placebo?"
                ),
                source="pubmed",
                max_results=5,
            )
        )
    finally:
        await biomed.aclose()

    assert result.query_plan is not None
    scope = result.query_plan.answer_scope
    assert scope is not None
    assert "hospitalized" in scope.population_terms
    assert "covid-19" in scope.population_terms
    assert "hydroxychloroquine" in scope.intervention_terms
    assert "usual care" in scope.comparator_terms
    assert "placebo" in scope.comparator_terms
    assert "mortality" in scope.outcome_terms
    assert "randomized trial" in scope.required_study_terms
    assert "prophylaxis" in scope.exclude_terms


@pytest.mark.asyncio
async def test_llm_planner_pubmed_query_uses_structured_terms_not_question_text(
    tmp_path: Path,
) -> None:
    provider = _FakeMessyPubMedPlannerProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-planner",
    )
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="Does an antiviral improve outcomes in hospitalized patients?",
                source="pubmed",
                max_results=5,
                use_llm_planner=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert result.classification.classifier_mode == "llm"
    assert result.validation.valid is True
    assert result.search_request is not None
    assert "hypothesis" not in result.validation.compiled_query
    assert "improves outcomes" not in result.validation.compiled_query
    assert "antiviral hospitalized patients" in result.validation.compiled_query
    assert '"Randomized Controlled Trial"[MeSH Terms]' not in (
        result.validation.compiled_query
    )
    assert (
        result.validation.compiled_query.count(
            '"Randomized Controlled Trial"[Publication Type]'
        )
        == 1
    )
    assert '"Randomized Controlled Trial"[Publication Type]' in (
        result.validation.compiled_query
    )


def test_answer_scope_marks_non_covid_pediatric_evidence_off_scope() -> None:
    scope = service._derive_answer_scope(
        "In adult patients hospitalized with COVID-19, does hydroxychloroquine improve mortality?"
    )
    item = EvidenceItem(
        evidence_id="ev-off",
        paper_id="PMID:off",
        claim="Hydroxychloroquine was studied in childhood interstitial lung disease.",
        finding="Hydroxychloroquine was studied in childhood interstitial lung disease.",
        evidence_direction="supports",
        entities=[],
        methods=["randomized trial"],
        limitations=[],
        confidence="medium",
        evidence_span="Hydroxychloroquine was studied in childhood interstitial lung disease.",
    )

    assessed = service._apply_scope_assessment(item, scope)

    assert assessed.scope_match == "false"
    assert assessed.scope_mismatch_reasons


def test_scope_filter_keeps_rejected_evidence_out_of_answer_pool() -> None:
    in_scope = EvidenceItem(
        evidence_id="ev-in",
        paper_id="PMID:recovery",
        claim="Hydroxychloroquine did not improve outcomes in hospitalized COVID-19 patients.",
        finding="Hydroxychloroquine did not improve outcomes in hospitalized COVID-19 patients.",
        evidence_direction="contradicts",
        entities=[],
        methods=["randomized trial"],
        limitations=[],
        confidence="high",
        evidence_span="Hydroxychloroquine did not improve outcomes in hospitalized COVID-19 patients.",
        scope_match="true",
    )
    off_scope = EvidenceItem(
        evidence_id="ev-off",
        paper_id="PMID:prep",
        claim="Low-dose hydroxychloroquine prophylaxis safety was evaluated.",
        finding="Low-dose hydroxychloroquine prophylaxis safety was evaluated.",
        evidence_direction="supports",
        entities=[],
        methods=[],
        limitations=[],
        confidence="medium",
        evidence_span="Low-dose hydroxychloroquine prophylaxis safety was evaluated.",
        scope_match="false",
        scope_mismatch_reasons=["Excluded term matched: prophylaxis"],
    )

    answer_evidence, rejected = service._split_scope_evidence([in_scope, off_scope])

    assert answer_evidence == [in_scope]
    assert rejected == [off_scope]


def test_hcq_demo_scope_accepts_direct_rct_and_rejects_prep() -> None:
    scope = service._derive_answer_scope(
        "In adult patients hospitalized with COVID-19, does randomized trial evidence show that hydroxychloroquine improves clinical outcomes?"
    )
    direct = EvidenceItem(
        evidence_id="ev-direct",
        paper_id="PMID:RECOVERY",
        claim="Hydroxychloroquine did not improve outcomes in hospitalized COVID-19 patients.",
        finding="Hydroxychloroquine did not improve outcomes in hospitalized COVID-19 patients in a randomized trial.",
        evidence_direction="contradicts",
        entities=[],
        methods=["randomized trial"],
        limitations=[],
        confidence="high",
        evidence_span="Hydroxychloroquine did not improve outcomes in hospitalized COVID-19 patients in a randomized trial.",
    )
    prep = EvidenceItem(
        evidence_id="ev-prep",
        paper_id="PMID:PREP",
        claim="Hydroxychloroquine prophylaxis safety was evaluated.",
        finding="Hydroxychloroquine prophylaxis safety was evaluated.",
        evidence_direction="supports",
        entities=[],
        methods=[],
        limitations=[],
        confidence="medium",
        evidence_span="Hydroxychloroquine prophylaxis safety was evaluated.",
    )

    assessed = [
        service._apply_scope_assessment(direct, scope),
        service._apply_scope_assessment(prep, scope),
    ]
    accepted, rejected = service._split_scope_evidence(assessed)

    assert [item.evidence_id for item in accepted] == ["ev-direct"]
    assert [item.evidence_id for item in rejected] == ["ev-prep"]


@pytest.mark.asyncio
async def test_plan_biomedical_search_refuses_clinical_query_before_retrieval(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What dose should my mother take for Alzheimer disease?",
                source="mock",
                max_results=5,
            )
        )
    finally:
        await service.aclose()

    assert result.classification.intent == "clinical_or_patient_specific"
    assert result.classification.clinical_boundary is True
    assert result.query_plan is None
    assert result.validation.valid is False
    assert result.search_request is None


@pytest.mark.asyncio
async def test_answer_with_planner_executes_support_refute_bundle(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_papers=5,
                use_llm_planner=True,
                execute_support_refute=True,
            )
        )
    finally:
        await service.aclose()

    assert result.retrieval_bundle is not None
    assert result.retrieval_bundle.executed_multi_query is True
    intents = {record.intent for record in result.retrieval_bundle.records}
    assert {"primary", "support", "refute"} <= intents
    assert {"background", "mechanism", "limitation"} <= intents
    assert result.retrieval_bundle.subquestions
    assert result.retrieval_bundle.coverage_matrix
    assert result.retrieval_bundle.stop_reason in {
        "coverage_sufficient",
        "gap_followup_complete",
    }
    assert result.retrieval_manifest is not None
    assert (
        result.retrieval_bundle.records[0].retrieval_id
        == result.retrieval_manifest.retrieval_id
    )


@pytest.mark.asyncio
async def test_support_refute_retrieval_respects_total_paper_budget(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    calls = 0

    async def fake_search_literature(
        request: LiteratureSearchRequest,
    ) -> LiteratureSearchResult:
        nonlocal calls
        calls += 1
        ids = [f"FAKE-{calls}-{index}" for index in range(request.max_results)]
        manifest = RetrievalManifest(
            retrieval_id=f"retrieval-{calls}",
            source=request.source,
            original_query=request.query,
            compiled_query=request.query,
            page_size=request.max_results,
            pages_requested=1,
            pages_completed=1,
            raw_result_count=len(ids),
            deduped_result_count=len(ids),
            returned_paper_ids=ids,
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:00+00:00",
        )
        return LiteratureSearchResult(
            source=request.source,
            query=request.query,
            query_used=request.query,
            retrieval_intent=request.retrieval_intent,
            items=[
                LiteraturePaperRecord(
                    paper_id=paper_id,
                    source=request.source,
                    title=paper_id,
                    source_rank=index,
                    abstract_available=True,
                )
                for index, paper_id in enumerate(ids, start=1)
            ],
            retrieval_manifest=manifest,
            coverage=LiteratureSearchCoverage(
                item_count=len(ids),
                abstract_count=len(ids),
                abstract_coverage=1.0,
                stored_paper_count=len(ids),
            ),
            source_trace=LiteratureSourceTrace(
                source=request.source,
                query_used=request.query,
                compiled_query=request.query,
                retrieval_intent=request.retrieval_intent,
                stored_paper_ids=ids,
            ),
        )

    service.search_literature = fake_search_literature  # type: ignore[method-assign]
    try:
        planning = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_results=10,
                use_llm_planner=True,
            )
        )
        assert planning.search_request is not None
        metadata, _manifest, bundle, _intents, _retrieval_ids = (
            await service._retrieve_answer_papers(
                request=AnswerWithEvidenceRequest(
                    question="What evidence links microglial activation to Alzheimer's disease progression?",
                    source="mock",
                    max_papers=2,
                    use_llm_planner=True,
                    execute_support_refute=True,
                ),
                planning_result=planning,
                search_request=planning.search_request,
                run_id="test-run",
            )
        )
    finally:
        await service.aclose()

    assert bundle is not None
    assert len(metadata) == 2
    assert len(bundle.deduped_paper_ids) == 2


@pytest.mark.asyncio
async def test_deterministic_planner_uses_broader_refute_limitation_queries(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question=(
                    "What evidence links microglial activation to "
                    "Alzheimer disease progression?"
                ),
                source="pubmed",
                max_results=10,
            )
        )
    finally:
        await service.aclose()

    assert result.query_plan is not None
    assert [query.lower() for query in result.query_plan.refute_queries] == [
        "microglial activation alzheimer disease progression conflicting evidence",
        "microglial activation alzheimer disease progression review limitations",
    ]
    assert all(
        "negative results limitations" not in query
        for query in result.query_plan.refute_queries
    )


@pytest.mark.asyncio
async def test_mock_search_fetch_extract_and_storage_idempotency(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        search_result = await service.search_with_manifest(
            SearchBiomedicalLiteratureRequest(
                query="microglial activation Alzheimer's disease",
                max_results=3,
            )
        )
        items = search_result.items
        assert items
        assert search_result.retrieval_manifest.source == "mock"
        assert search_result.retrieval_manifest.compiled_query
        assert search_result.retrieval_manifest.deduped_result_count == len(items)
        paper = await service.fetch(service_module_fetch_request(items[0].paper_id))
        assert paper is not None
        request = EvidenceExtractionRequest(
            paper=paper,
            research_question="microglial activation Alzheimer's disease",
        )
        first = service.extract_evidence(request)
        second = service.extract_evidence(request)
        rows, total = service.list_evidence(paper_id=paper.paper_id)
    finally:
        await service.aclose()

    assert first.evidence
    assert second.evidence
    assert total == len(first.evidence)
    assert rows[0]["paper_id"] == paper.paper_id


def service_module_fetch_request(paper_id: str):
    from plugins.biomed_evidence.schemas import FetchBiomedicalPaperRequest

    return FetchBiomedicalPaperRequest(paper_id=paper_id, source="mock")


def test_empty_abstract_returns_reason(tmp_path: Path) -> None:
    from plugins.biomed_evidence.schemas import BiomedicalPaper

    service = BiomedEvidenceService(tmp_path)
    try:
        result = service.extract_evidence(
            EvidenceExtractionRequest(
                paper=BiomedicalPaper(
                    paper_id="NO-ABSTRACT",
                    source="mock",
                    title="No abstract paper",
                )
            )
        )
    finally:
        service.close()

    assert result.evidence == []
    assert result.reason and "not fabricated" in result.reason


def test_pubmed_xml_parser_extracts_metadata() -> None:
    xml = """
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>12345</PMID>
          <Article>
            <Journal>
              <JournalIssue><PubDate><Year>2025</Year><Month>Jan</Month><Day>02</Day></PubDate></JournalIssue>
              <Title>Journal of Mock Biology</Title>
            </Journal>
            <ArticleTitle>Microglia and disease progression</ArticleTitle>
            <Abstract><AbstractText>Microglia were associated with disease stage.</AbstractText></Abstract>
            <AuthorList><Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author></AuthorList>
          </Article>
          <MeshHeadingList><MeshHeading><DescriptorName>Microglia</DescriptorName></MeshHeading></MeshHeadingList>
          <KeywordList><Keyword>neuroinflammation</Keyword></KeywordList>
        </MedlineCitation>
        <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/mock</ArticleId></ArticleIdList></PubmedData>
      </PubmedArticle>
    </PubmedArticleSet>
    """
    papers = parse_pubmed_articles(xml)
    assert len(papers) == 1
    assert papers[0].paper_id == "12345"
    assert papers[0].publication_date == "2025-01-02"
    assert papers[0].doi == "10.1/mock"
    assert papers[0].authors == ["Ada Lovelace"]


class _FakePubMedResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakePlannerResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeFalseAbstainRecoveryProvider:
    def __init__(self) -> None:
        self.planner_calls = 0
        self.verifier_calls = 0

    async def chat(
        self,
        messages,
        tools,
        model,
        max_tokens,
        tool_choice="auto",
        disable_thinking=False,
    ):
        system = str(messages[0]["content"])
        payload = json.loads(messages[-1]["content"])
        if "classify biomedical user questions" in system:
            self.planner_calls += 1
            return _FakePlannerResponse(
                json.dumps(
                    {
                        "classification": {
                            "intent": "out_of_scope",
                            "normalized_question": payload["question"],
                            "clinical_boundary": False,
                            "needs_clarification": False,
                            "risk_flags": ["non_biomedical"],
                            "allowed_next_step": "abstain",
                            "rationale": "mistaken non-biomedical classification",
                        },
                        "query_plan": payload["deterministic_query_plan"],
                    }
                )
            )
        if "advisory biomedical claim verifier" in system:
            self.verifier_calls += 1
            return _FakePlannerResponse(
                json.dumps(
                    {
                        "advisory_action": "pass_with_limitations",
                        "claim_reviews": [
                            {
                                "claim": payload["answer"],
                                "advisory_verdict": "not_cited",
                                "advisory_action": "pass_with_limitations",
                                "risk_level": "medium",
                                "cited_paper_ids": [],
                                "rationale": (
                                    "The question is a biomedical literature question "
                                    "about reproductive biology and could be supported "
                                    "by evidence."
                                ),
                            }
                        ],
                        "warnings": [
                            "The answer incorrectly categorizes the user's question as not a biomedical literature research question."
                        ],
                        "errors": [],
                    }
                )
            )
        raise AssertionError(f"Unexpected fake provider call: {system}")


class _FakePlannerProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self,
        messages,
        tools,
        model,
        max_tokens,
        tool_choice="auto",
        disable_thinking=False,
    ):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        return _FakePlannerResponse(
            json.dumps(
                {
                    "classification": {
                        "intent": "research_question",
                        "normalized_question": payload["question"],
                        "clinical_boundary": False,
                        "needs_clarification": False,
                        "risk_flags": [],
                        "allowed_next_step": "plan_retrieval",
                        "rationale": "fake planner classification",
                    },
                    "query_plan": {
                        "primary_query": "microglial activation Alzheimer disease progression",
                        "mesh_terms": ["Alzheimer Disease", "Microglia"],
                        "include_terms": ["neuroinflammation"],
                        "exclude_terms": ["dosage"],
                        "study_types": ["longitudinal"],
                        "species_terms": [],
                        "support_queries": [
                            "microglial activation Alzheimer disease progression association"
                        ],
                        "refute_queries": [
                            "microglial activation Alzheimer disease progression negative results"
                        ],
                        "max_results": 5,
                        "rationale": "fake planner query plan",
                    },
                }
            )
        )


class _FakeEchoPlannerProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self,
        messages,
        tools,
        model,
        max_tokens,
        tool_choice="auto",
        disable_thinking=False,
    ):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        return _FakePlannerResponse(
            json.dumps(
                {
                    "deterministic_classification": payload[
                        "deterministic_classification"
                    ],
                    "deterministic_query_plan": payload["deterministic_query_plan"],
                }
            )
        )


class _FakeMessyPubMedPlannerProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self,
        messages,
        tools,
        model,
        max_tokens,
        tool_choice="auto",
        disable_thinking=False,
    ):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        return _FakePlannerResponse(
            json.dumps(
                {
                    "classification": {
                        "intent": "research_question",
                        "normalized_question": payload["question"],
                        "clinical_boundary": False,
                        "needs_clarification": False,
                        "risk_flags": [],
                        "allowed_next_step": "plan_retrieval",
                        "rationale": "fake planner classification",
                    },
                    "query_plan": {
                        "primary_query": (
                            "does treatment support or refute the hypothesis "
                            "that it improves outcomes"
                        ),
                        "mesh_terms": [
                            "Respiratory Tract Infections",
                            "Randomized Controlled Trial",
                        ],
                        "include_terms": ["antiviral", "hospitalized patients"],
                        "exclude_terms": [],
                        "publication_types": ["Randomized Controlled Trial"],
                        "study_types": ["randomized_trial", "human"],
                        "species_terms": ["Humans"],
                        "support_queries": [
                            "treatment improves outcomes supporting evidence"
                        ],
                        "refute_queries": [
                            "treatment improves outcomes refuting evidence"
                        ],
                        "max_results": 5,
                        "rationale": "fake messy planner query plan",
                    },
                }
            )
        )


class _FakeExtractorProvider:
    def __init__(
        self,
        *,
        grounded: bool = True,
        terminal_punctuation_trim: bool = False,
    ) -> None:
        self.grounded = grounded
        self.terminal_punctuation_trim = terminal_punctuation_trim
        self.calls = 0

    async def chat(
        self,
        messages,
        tools,
        model,
        max_tokens,
        tool_choice="auto",
        disable_thinking=False,
    ):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        abstract = str(payload["paper"]["abstract"])
        if self.grounded and abstract and self.terminal_punctuation_trim and ", although" in abstract:
            span = abstract.split(", although")[0].split(". ")[-1].strip() + "."
        elif self.grounded and abstract:
            span = abstract.split(".")[0].strip() + "."
        else:
            span = "This sentence is not present in the supplied abstract."
        return _FakePlannerResponse(
            json.dumps(
                {
                    "evidence": [
                        {
                            "claim": "LLM extracted span-grounded evidence.",
                            "finding": span,
                            "evidence_direction": "supports",
                            "evidence_span": span,
                            "confidence": "medium",
                            "entities": [
                                {"name": "microglia", "entity_type": "cell_type"}
                            ],
                            "methods": [],
                            "datasets_or_cohorts": [],
                            "limitations": ["Abstract-only extraction."],
                        }
                    ]
                }
            )
        )


class _FakeFullTextEvidenceReaderProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self,
        messages,
        tools,
        model,
        max_tokens,
        tool_choice="auto",
        disable_thinking=False,
    ):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        chunk = payload["chunk"]["text"]
        span = (
            "Hydroxychloroquine did not reduce 28-day mortality in hospitalized "
            "COVID-19 patients."
        )
        assert span in chunk
        return _FakePlannerResponse(
            json.dumps(
                {
                    "spans": [
                        {
                            "span": span,
                            "direction": "contradicts",
                            "claim_type": "treatment",
                            "population": "human",
                            "outcome": "28-day mortality",
                            "why_relevant": "Direct trial outcome in the requested population.",
                            "limitations": ["Open-label trial."],
                        }
                    ]
                }
            )
        )


class _FakeSynthesisProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(
        self,
        messages,
        tools,
        model,
        max_tokens,
        tool_choice="auto",
        disable_thinking=False,
    ):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        evidence = payload["evidence_items"][0]
        paper_id = evidence["paper_id"]
        finding = evidence["finding"]
        return _FakePlannerResponse(
            json.dumps(
                {
                    "final_answer": (
                        f"{payload['research_only_boundary']}\n\n"
                        f"- {finding} [{paper_id}]"
                    ),
                    "uncertainty_level": "high",
                    "added_limitations": [],
                }
            )
        )


@pytest.mark.asyncio
async def test_plan_biomedical_search_can_use_injected_llm_planner(
    tmp_path: Path,
) -> None:
    provider = _FakePlannerProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-light-router",
    )
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_results=5,
                use_llm_planner=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert result.classification.classifier_mode == "llm"
    assert result.query_plan is not None
    assert result.query_plan.planner_mode == "llm"
    assert result.query_plan.llm_model == "fake-light-router"
    assert result.validation.valid is True
    assert result.search_request is not None


@pytest.mark.asyncio
async def test_llm_planner_can_rescue_nonclinical_out_of_scope_classification(
    tmp_path: Path,
) -> None:
    provider = _FakePlannerProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-light-router",
    )
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What evidence supports that quantum entanglement changes memory?",
                source="mock",
                max_results=5,
                use_llm_planner=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert result.classification.intent == "research_question"
    assert result.classification.classifier_mode == "llm"
    assert result.validation.valid is True
    assert result.search_request is not None


@pytest.mark.asyncio
async def test_llm_planner_cannot_downgrade_biomedical_question_to_abstain(
    tmp_path: Path,
) -> None:
    provider = _FakeFalseAbstainRecoveryProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-light-router",
    )
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="Would a hermaphrodite become pregnant through self-fertilisation?",
                source="pubmed",
                max_results=5,
                use_llm_planner=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.planner_calls == 1
    assert result.classification.intent == "research_question"
    assert result.classification.allowed_next_step == "plan_retrieval"
    assert result.validation.valid is True
    assert result.search_request is not None


@pytest.mark.asyncio
async def test_answer_audit_runs_retrieval_when_llm_planner_attempts_false_abstain(
    tmp_path: Path,
) -> None:
    provider = _FakeFalseAbstainRecoveryProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-router-verifier",
    )
    try:
        result = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="Would a hermaphrodite become pregnant through self-fertilisation?",
                source="mock",
                max_papers=3,
                use_llm_planner=True,
                use_llm_verifier=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.planner_calls == 1
    assert provider.verifier_calls >= 1
    assert result.answer_result.retrieval_id is not None
    assert result.answer_result.question_classification is not None
    assert result.answer_result.question_classification.intent == "research_question"
    assert "not appear to be a biomedical literature research question" not in (
        result.final_answer
    )


@pytest.mark.asyncio
async def test_answer_can_use_span_grounded_llm_extractor(tmp_path: Path) -> None:
    provider = _FakeExtractorProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-extractor",
    )
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=2,
                use_llm_extractor=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls >= 1
    assert result.evidence_summary
    assert {item.extraction_mode for item in result.evidence_summary} == {"llm"}
    assert all(
        item.extractor_model == "fake-extractor" for item in result.evidence_summary
    )
    assert all(
        item.evidence_span and item.evidence_span == item.finding
        for item in result.evidence_summary
    )


@pytest.mark.asyncio
async def test_llm_extractor_accepts_trimmed_terminal_punctuation(
    tmp_path: Path,
) -> None:
    provider = _FakeExtractorProvider(terminal_punctuation_trim=True)
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-extractor",
    )
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
                use_llm_extractor=True,
            )
        )
    finally:
        await service.aclose()

    items = [
        item
        for item in result.evidence_summary
        if item.paper_id == "MOCK-PMID-1001"
    ]
    assert items
    assert items[0].extraction_mode == "llm"
    assert items[0].evidence_span.endswith("amyloid pathology")
    assert not items[0].evidence_span.endswith(".")


@pytest.mark.asyncio
async def test_answer_falls_back_when_llm_extractor_span_is_ungrounded(
    tmp_path: Path,
) -> None:
    provider = _FakeExtractorProvider(grounded=False)
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-extractor",
    )
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=2,
                use_llm_extractor=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls >= 1
    assert result.evidence_summary
    assert {item.extraction_mode for item in result.evidence_summary} == {"fallback"}
    assert all(item.extractor_model is None for item in result.evidence_summary)


@pytest.mark.asyncio
async def test_answer_can_use_audit_gated_llm_synthesis(tmp_path: Path) -> None:
    provider = _FakeSynthesisProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-synthesizer",
    )
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=2,
                use_llm_synthesis=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert result.synthesis_mode == "llm"
    assert result.synthesis_model == "fake-synthesizer"
    assert result.synthesis_prompt_hash
    assert result.synthesis_fallback_reason is None
    assert "[MOCK-PMID-" in result.answer
    assert RESEARCH_USE_DISCLAIMER not in result.answer


@pytest.mark.asyncio
async def test_plan_biomedical_search_accepts_llm_echoed_deterministic_payload(
    tmp_path: Path,
) -> None:
    provider = _FakeEchoPlannerProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-light-router",
    )
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_results=5,
                use_llm_planner=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert result.classification.classifier_mode == "llm"
    assert result.query_plan is not None
    assert result.query_plan.planner_mode == "llm"
    assert result.validation.valid is True
    assert result.search_request is not None
    assert result.search_request.query


class _FakePubMedClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, *, params: dict[str, Any]):
        self.calls.append((url, dict(params)))
        if url.endswith("esearch.fcgi"):
            retstart = int(params.get("retstart", 0))
            pmid = "9001" if retstart == 0 else "9002"
            return _FakePubMedResponse(f"""
                <eSearchResult>
                  <Count>2</Count>
                  <IdList><Id>{pmid}</Id></IdList>
                </eSearchResult>
                """)
        return _FakePubMedResponse("""
            <PubmedArticleSet>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>9001</PMID>
                  <Article>
                    <ArticleTitle>Microglia page one</ArticleTitle>
                    <Abstract><AbstractText>Microglia activation was observed.</AbstractText></Abstract>
                  </Article>
                </MedlineCitation>
              </PubmedArticle>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>9002</PMID>
                  <Article>
                    <ArticleTitle>Microglia page two</ArticleTitle>
                    <Abstract><AbstractText>Microglia activation was replicated.</AbstractText></Abstract>
                  </Article>
                </MedlineCitation>
              </PubmedArticle>
            </PubmedArticleSet>
            """)


class _FlakyPubMedClient(_FakePubMedClient):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    async def get(self, url: str, *, params: dict[str, Any]):
        if url.endswith("esearch.fcgi") and not self.failed_once:
            self.failed_once = True
            raise httpx.ConnectError("temporary PubMed network failure")
        return await super().get(url, params=params)


class _RateLimitedPubMedClient(_FakePubMedClient):
    def __init__(self) -> None:
        super().__init__()
        self.rate_limited_once = False

    async def get(self, url: str, *, params: dict[str, Any]):
        self.calls.append((url, dict(params)))
        if url.endswith("esearch.fcgi") and not self.rate_limited_once:
            self.rate_limited_once = True
            request = httpx.Request("GET", url)
            return httpx.Response(
                429,
                request=request,
                headers={"Retry-After": "2"},
                text="too many requests",
            )
        return await super().get(url, params=params)


class _ZeroThenRelaxedPubMedClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, *, params: dict[str, Any]):
        self.calls.append((url, dict(params)))
        if url.endswith("esearch.fcgi"):
            term = str(params.get("term") or "")
            if "[MeSH Terms]" in term or " NOT " in term:
                return _FakePubMedResponse("""
                    <eSearchResult>
                      <Count>0</Count>
                      <IdList></IdList>
                    </eSearchResult>
                    """)
            return _FakePubMedResponse("""
                <eSearchResult>
                  <Count>1</Count>
                  <IdList><Id>9101</Id></IdList>
                </eSearchResult>
                """)
        return _FakePubMedResponse("""
            <PubmedArticleSet>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>9101</PMID>
                  <Article>
                    <ArticleTitle>Fertility in ovotesticular disorder of sex development</ArticleTitle>
                    <Abstract><AbstractText>Pregnancy and fertility questions are discussed in ovotesticular disorder of sex development.</AbstractText></Abstract>
                  </Article>
                </MedlineCitation>
              </PubmedArticle>
            </PubmedArticleSet>
            """)


@pytest.mark.asyncio
async def test_pubmed_search_relaxes_overconstrained_zero_result_query(
    tmp_path: Path,
) -> None:
    fake = _ZeroThenRelaxedPubMedClient()
    service = BiomedEvidenceService(
        tmp_path,
        http_client=cast(httpx.AsyncClient, fake),
    )
    try:
        result = await service.search_with_manifest(
            SearchBiomedicalLiteratureRequest(
                query="intersex ovotesticular self fertilization pregnancy",
                source="pubmed",
                max_results=3,
                mesh_terms=["Hermaphroditism", "Fertilization", "Pregnancy"],
                exclude_terms=["case report"],
            )
        )
    finally:
        await service.aclose()

    assert [item.paper_id for item in result.items] == ["9101"]
    manifest = result.retrieval_manifest
    assert manifest.deduped_result_count == 1
    assert any("relaxed" in warning for warning in manifest.warnings)
    esearch_terms = [
        str(params["term"]) for url, params in fake.calls if url.endswith("esearch.fcgi")
    ]
    assert "[MeSH Terms]" in esearch_terms[0]
    assert "[MeSH Terms]" not in esearch_terms[1]


@pytest.mark.asyncio
async def test_pubmed_search_trace_records_pagination_with_fake_http() -> None:
    fake = _FakePubMedClient()
    client = PubMedLiteratureClient(client=cast(httpx.AsyncClient, fake))

    result = await client.search_with_trace(
        "microglia",
        max_results=2,
        page_size=1,
    )

    assert [item.paper_id for item in result.items] == ["9001", "9002"]
    assert result.trace["pages_completed"] == 2
    assert result.trace["raw_result_count"] == 2
    starts = [
        params["retstart"] for url, params in fake.calls if url.endswith("esearch.fcgi")
    ]
    assert starts == [0, 1]


@pytest.mark.asyncio
async def test_pubmed_search_trace_records_retry_and_redacts_api_key() -> None:
    fake = _FlakyPubMedClient()
    client = PubMedLiteratureClient(
        client=cast(httpx.AsyncClient, fake),
        api_key="secret-key",
        retry_backoff_seconds=0.0,
    )

    result = await client.search_with_trace(
        "microglia",
        max_results=2,
        page_size=2,
    )

    assert result.items
    warnings = cast(list[str], result.trace["warnings"])
    assert any("ConnectError" in item for item in warnings)
    params = cast(list[dict[str, object]], result.trace["request_parameters"])
    assert params[0]["api_key"] == "***redacted***"


@pytest.mark.asyncio
async def test_pubmed_client_respects_retry_after_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _RateLimitedPubMedClient()
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("plugins.biomed_evidence.literature_client.asyncio.sleep", fake_sleep)
    client = PubMedLiteratureClient(
        client=cast(httpx.AsyncClient, fake),
        retry_backoff_seconds=0.0,
        rate_limit_requests_per_second=0.0,
    )

    result = await client.search_with_trace("microglia", max_results=1, page_size=1)

    assert result.items
    assert 2.0 in sleeps
    warnings = cast(list[str], result.trace["warnings"])
    assert any("status=429" in item and "retrying" in item for item in warnings)


@pytest.mark.asyncio
async def test_pubmed_client_rate_limits_sequential_eutils_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePubMedClient()
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("plugins.biomed_evidence.literature_client.asyncio.sleep", fake_sleep)
    client = PubMedLiteratureClient(
        client=cast(httpx.AsyncClient, fake),
        rate_limit_requests_per_second=2.0,
    )

    await client.search_with_trace("microglia", max_results=1, page_size=1)

    assert any(delay >= 0.45 for delay in sleeps)


@pytest.mark.asyncio
async def test_literature_access_check_reports_mock_readiness(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.check_literature_access(
            LiteratureAccessCheckRequest(
                source="mock",
                query="microglia Alzheimer",
                max_results=2,
            )
        )
    finally:
        await service.aclose()

    assert result.ok is True
    assert result.ready is True
    assert result.live is False
    assert result.item_count >= 1
    assert result.abstract_count >= 1
    assert result.retrieval_manifest is not None
    assert result.retrieval_manifest.source == "mock"


@pytest.mark.asyncio
async def test_search_literature_returns_normalized_mock_records_and_trace(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.search_literature(
            LiteratureSearchRequest(
                source="mock",
                query="microglia Alzheimer",
                max_results=2,
                mesh_terms=["Microglia"],
                article_types=["Review"],
                retrieval_intent="support",
            )
        )
    finally:
        await service.aclose()

    assert result.source == "mock"
    assert result.live is False
    assert result.retrieval_intent == "support"
    assert result.items
    assert result.items[0].source_rank == 1
    assert result.items[0].paper_id
    assert result.items[0].abstract_available is True
    assert result.items[0].abstract
    assert result.coverage.item_count == len(result.items)
    assert result.coverage.abstract_count >= 1
    assert result.coverage.stored_paper_count == len(result.items)
    assert result.source_trace.stored_paper_ids
    assert result.source_trace.retrieval_intent == "support"
    assert result.retrieval_manifest.source == "mock"
    assert result.retrieval_manifest.returned_paper_ids
    assert "mock:mesh_terms" in result.retrieval_manifest.unsupported_filters
    assert "mock:publication_types" in result.retrieval_manifest.unsupported_filters


@pytest.mark.asyncio
async def test_literature_access_check_reports_pubmed_readiness_with_fake_http(
    tmp_path: Path,
) -> None:
    fake = _FakePubMedClient()
    service = BiomedEvidenceService(
        tmp_path,
        http_client=cast(httpx.AsyncClient, fake),
    )
    service.pubmed_client.retry_backoff_seconds = 0.0
    try:
        result = await service.check_literature_access(
            LiteratureAccessCheckRequest(
                source="pubmed",
                query="microglia",
                max_results=2,
            )
        )
    finally:
        await service.aclose()

    assert result.ok is True
    assert result.ready is True
    assert result.live is True
    assert result.item_count == 2
    assert result.abstract_count == 2
    assert result.abstract_coverage == 1.0
    assert result.stored_paper_count == 2
    assert result.retrieval_manifest is not None
    assert result.retrieval_manifest.source == "pubmed"
    assert result.retrieval_manifest.api_endpoints
    assert any("NCBI_EMAIL is not configured" in item for item in result.warnings)


@pytest.mark.asyncio
async def test_search_literature_returns_pubmed_manifest_with_fake_http(
    tmp_path: Path,
) -> None:
    fake = _FakePubMedClient()
    service = BiomedEvidenceService(
        tmp_path,
        http_client=cast(httpx.AsyncClient, fake),
    )
    service.pubmed_client.retry_backoff_seconds = 0.0
    try:
        result = await service.search_literature(
            LiteratureSearchRequest(
                source="pubmed",
                query="microglia Alzheimer",
                max_results=2,
                mesh_terms=["Microglia"],
                article_types=["Review"],
                exclude_terms=["case report"],
                retrieval_intent="refute",
            )
        )
    finally:
        await service.aclose()

    assert result.source == "pubmed"
    assert result.live is True
    assert result.query_used == result.retrieval_manifest.compiled_query
    assert '"Microglia"[MeSH Terms]' in result.query_used
    assert '"Review"[Publication Type]' in result.query_used
    assert "NOT" in result.query_used
    assert result.coverage.item_count == len(result.items)
    assert result.coverage.abstract_count >= 1
    assert result.coverage.stored_paper_count >= 1
    assert result.source_trace.live is True
    assert result.source_trace.retrieval_intent == "refute"
    assert result.source_trace.stored_paper_ids
    assert result.retrieval_manifest.api_endpoints


@pytest.mark.asyncio
async def test_search_literature_rejects_missing_project(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        with pytest.raises(ValueError, match="project not found"):
            await service.search_literature(
                LiteratureSearchRequest(
                    source="mock",
                    query="microglia Alzheimer",
                    project_id="missing-project",
                )
            )
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_watch_check_scores_and_dedupes_decisions(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        watch = service.create_watch(
            WatchTopicCreateRequest(
                topic="spatial transcriptomics in tumor microenvironment",
                include_keywords=["spatial transcriptomics", "tumor microenvironment"],
                preferred_methods=["spatial transcriptomics"],
                min_relevance_score=0.7,
            )
        )
        first = await service.check_watch(watch.watch_id)
        second = await service.check_watch(watch.watch_id)
        decisions, total = service.list_watch_decisions(watch_id=watch.watch_id)
    finally:
        await service.aclose()

    assert first is not None
    assert first.retrieval_manifest is not None
    assert first.snapshot is not None
    assert first.snapshot.new_paper_ids
    assert first.decisions
    assert second is not None
    assert second.snapshot is not None
    assert second.snapshot.new_paper_ids == []
    assert second.decisions == []
    assert total == len(decisions)
    assert all(item.retrieval_id and item.snapshot_id for item in decisions)
    assert any(item.decision == "push" for item in decisions)


def test_full_text_ingestion_extracts_locator_backed_evidence(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        paper = BiomedicalPaper(
            paper_id="MOCK-FULLTEXT-1",
            source="mock",
            title="Full text microglia study",
            abstract="Abstract-level summary only.",
        )
        service.storage.upsert_paper(paper)
        ingested = service.ingest_full_text(
            FullTextIngestionRequest(
                paper_id=paper.paper_id,
                source="mock",
                content=(
                    "## Results\n"
                    "Microglial activation was associated with Alzheimer's disease "
                    "progression in a longitudinal human cohort. The cohort study "
                    "requires validation in independent samples."
                ),
            )
        )
        extracted = service.extract_full_text_evidence(
            paper_id=paper.paper_id,
            source="mock",
            research_question="microglial activation Alzheimer progression",
        )
        graph = service.get_graph_v1(paper_id=paper.paper_id, validate=True)
    finally:
        service.storage.close()

    assert ingested.ok is True
    assert ingested.document is not None
    assert ingested.sections
    assert extracted is not None
    assert extracted.evidence
    item = extracted.evidence[0]
    assert item.source_scope == "full_text"
    assert not any("abstract" in limitation.lower() for limitation in item.limitations)
    assert item.confidence == "medium"
    assert item.document_id == ingested.document.document_id
    assert item.section_id == ingested.sections[0].section_id
    assert item.section_label == "Results"
    assert item.char_start is not None
    assert item.char_end is not None
    assert item.source_hash == ingested.sections[0].source_hash
    assert graph is not None
    evidence_nodes = [node for node in graph.nodes if node.type == "EvidenceSpan"]
    assert any(node.properties.get("source_scope") == "full_text" for node in evidence_nodes)


def test_full_text_evidence_sentence_splitter_keeps_vs_statistics(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        paper = BiomedicalPaper(
            paper_id="MOCK-FULLTEXT-STATS",
            source="mock",
            title="Hydroxychloroquine hospitalized COVID-19 trial",
            abstract="Abstract-level summary only.",
        )
        service.storage.upsert_paper(paper)
        service.ingest_full_text(
            FullTextIngestionRequest(
                paper_id=paper.paper_id,
                source="mock",
                content=(
                    "## Results\n"
                    "Allocation to hydroxychloroquine was associated with a longer "
                    "time until discharge alive from hospital than usual care "
                    "(median 16 days vs. 13 days)."
                ),
            )
        )
        extracted = service.extract_full_text_evidence(
            paper_id=paper.paper_id,
            source="mock",
            research_question="hydroxychloroquine hospitalized COVID-19 outcomes",
        )
    finally:
        service.storage.close()

    assert extracted is not None
    assert extracted.evidence
    span = extracted.evidence[0].evidence_span
    assert span is not None
    assert "vs. 13 days" in span
    assert span.endswith("(median 16 days vs. 13 days).")


@pytest.mark.asyncio
async def test_full_text_reanalysis_uses_provider_backed_logic_parser(
    tmp_path: Path,
) -> None:
    provider = _FakeFullTextLogicProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-fulltext-logic",
    )
    try:
        run = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="Does hydroxychloroquine improve hospitalized COVID-19 outcomes?",
                source="mock",
                max_papers=1,
            )
        )
        paper_id = run.answer_result.retrieval_manifest.returned_paper_ids[0]
        service.ingest_full_text(
            FullTextIngestionRequest(
                paper_id=paper_id,
                source="mock",
                content=(
                    "## Results\n"
                    "Among patients hospitalized with Covid-19, those who received "
                    "hydroxychloroquine did not have a lower incidence of death at "
                    "28 days than those who received usual care."
                ),
            )
        )
        await service.enhance_run_with_full_text(
            FullTextEnhancementRequest(run_id=run.answer_result.run_id)
        )
        reanalyzed = await service.reanalyze_run_with_full_text(
            FullTextReanalysisRequest(
                run_id=run.answer_result.run_id,
                use_llm_claim_logic=True,
                export_logic_facts=True,
            )
        )
    finally:
        await service.aclose()

    assert reanalyzed is not None
    assert provider.calls >= 1
    audit_step = next(step for step in reanalyzed.trace if step.step == "audit")
    logic_trace = audit_step.metadata["logic_audit"]
    assert isinstance(logic_trace, dict)
    assert logic_trace["parser_models"] == ["fake-fulltext-logic"]
    assert logic_trace["parser_mode_counts"]["llm"] >= 1


@pytest.mark.asyncio
async def test_full_text_enhancement_uses_llm_span_reader(
    tmp_path: Path,
) -> None:
    provider = _FakeFullTextEvidenceReaderProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-fulltext-reader",
    )
    try:
        run = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question=(
                    "What randomized trial evidence supports or refutes that "
                    "hydroxychloroquine improves outcomes in hospitalized COVID-19?"
                ),
                source="mock",
                max_papers=1,
            )
        )
        paper_id = run.answer_result.retrieval_manifest.returned_paper_ids[0]
        service.ingest_full_text(
            FullTextIngestionRequest(
                paper_id=paper_id,
                source="mock",
                content=(
                    "## Methods\n"
                    "Patients were randomized in an open-label platform trial.\n\n"
                    "## Results\n"
                    "Hydroxychloroquine did not reduce 28-day mortality in hospitalized "
                    "COVID-19 patients. The study stopped early for lack of efficacy.\n\n"
                    "## References\n"
                    "Hydroxychloroquine trials and COVID-19 review articles."
                ),
            )
        )
        await service.enhance_run_with_full_text(
            FullTextEnhancementRequest(run_id=run.answer_result.run_id)
        )
        stored = service.storage.get_answer_run(run.answer_result.run_id)
    finally:
        await service.aclose()

    assert provider.calls >= 1
    assert stored is not None
    full_text_items = [
        item for item in stored.evidence_summary if item.source_scope == "full_text"
    ]
    assert full_text_items
    item = full_text_items[0]
    assert item.extraction_mode == "llm_span"
    assert item.evidence_direction == "contradicts"
    assert item.extractor_model == "fake-fulltext-reader"
    assert item.evidence_span == (
        "Hydroxychloroquine did not reduce 28-day mortality in hospitalized "
        "COVID-19 patients."
    )
    assert item.char_start is not None and item.char_start >= 0
    assert item.char_end is not None and item.char_end > item.char_start
    assert "References" not in item.finding


def _full_text_reanalysis_item(
    paper_id: str,
    index: int,
    *,
    direction: str = "supports",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"ev-{paper_id}-{index}",
        paper_id=paper_id,
        claim=f"{paper_id} full-text claim {index}",
        finding=f"{paper_id} full-text finding {index}",
        evidence_direction=cast(Any, direction),
        entities=[],
        methods=[],
        datasets_or_cohorts=[],
        limitations=[],
        confidence="medium",
        evidence_span=f"{paper_id} full-text finding {index}",
        source_scope="full_text",
        section_id=f"section-{paper_id}-{index}",
        section_label="Results",
        char_start=0,
        char_end=20,
        source_hash=f"hash-{paper_id}-{index}",
    )


@pytest.mark.asyncio
async def test_full_text_reanalysis_balances_evidence_across_papers(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        papers = ["PAPER-A", "PAPER-B", "PAPER-C"]
        for paper_id in papers:
            service.storage.upsert_paper(
                BiomedicalPaper(
                    paper_id=paper_id,
                    source="mock",
                    title=f"{paper_id} trial",
                    abstract="Abstract.",
                )
            )
        evidence = [
            *[
                _full_text_reanalysis_item("PAPER-A", index)
                for index in range(12)
            ],
            _full_text_reanalysis_item("PAPER-B", 0, direction="contradicts"),
            _full_text_reanalysis_item("PAPER-C", 0),
        ]
        run = AnswerWithEvidenceResult(
            run_id="biomed-run-balanced-fulltext",
            answer="Draft answer.",
            citations=[],
            evidence_summary=evidence,
            conflicting_evidence=[
                item for item in evidence if item.evidence_direction == "contradicts"
            ],
            limitations=[],
            uncertainty_level="medium",
            disclaimer=RESEARCH_USE_DISCLAIMER,
        )
        service.storage.save_answer_run(run, question="Does treatment improve outcomes?")

        reanalyzed = await service.reanalyze_run_with_full_text(
            FullTextReanalysisRequest(
                run_id=run.run_id,
                max_evidence_items=4,
            )
        )
    finally:
        await service.aclose()

    assert reanalyzed is not None
    selected_papers = {
        item.paper_id for item in reanalyzed.answer_result.evidence_summary
    }
    assert selected_papers == {"PAPER-A", "PAPER-B", "PAPER-C"}
    trace = reanalyzed.answer_result.project_context_trace
    assert trace["full_text_reanalysis_available_paper_count"] == 3
    assert trace["full_text_reanalysis_used_paper_count"] == 3
    assert "single paper" not in str(trace.get("full_text_reanalysis_coverage_warning", ""))


@pytest.mark.asyncio
async def test_full_text_reanalysis_extracts_cached_documents_for_related_papers(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        for paper_id in ["PAPER-A", "PAPER-B"]:
            service.storage.upsert_paper(
                BiomedicalPaper(
                    paper_id=paper_id,
                    source="mock",
                    title=f"{paper_id} smoking lung cancer study",
                    abstract="Abstract.",
                )
            )
        initial = _full_text_reanalysis_item("PAPER-A", 0)
        service.ingest_full_text(
            FullTextIngestionRequest(
                paper_id="PAPER-B",
                source="mock",
                content=(
                    "## Results\n"
                    "PAPER-B smoking exposure was associated with increased lung cancer risk."
                ),
            )
        )
        run = AnswerWithEvidenceResult(
            run_id="biomed-run-cached-fulltext",
            answer="Draft answer.",
            citations=[
                Citation(
                    paper_id="PAPER-B",
                    title="PAPER-B",
                    source="mock",
                    cited_claim="PAPER-B cached full text.",
                )
            ],
            evidence_summary=[initial],
            conflicting_evidence=[],
            limitations=[],
            uncertainty_level="medium",
            disclaimer=RESEARCH_USE_DISCLAIMER,
            query_plan=BiomedicalQueryPlan(
                plan_id="plan-cached-fulltext",
                question="Does smoking cause lung cancer?",
                source="mock",
                primary_query="smoking lung cancer",
            ),
        )
        service.storage.save_answer_run(
            run,
            question="Does smoking cause lung cancer?",
        )

        reanalyzed = await service.reanalyze_run_with_full_text(
            FullTextReanalysisRequest(
                run_id=run.run_id,
                max_evidence_items=4,
            )
        )
    finally:
        await service.aclose()

    assert reanalyzed is not None
    selected_papers = {
        item.paper_id for item in reanalyzed.answer_result.evidence_summary
    }
    assert {"PAPER-A", "PAPER-B"}.issubset(selected_papers)


def test_full_text_evidence_prefers_results_sections(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        paper = BiomedicalPaper(
            paper_id="MOCK-FULLTEXT-RANK",
            source="mock",
            title="Full text microglia ranking study",
            abstract="Abstract-level summary only.",
        )
        service.storage.upsert_paper(paper)
        ingested = service.ingest_full_text(
            FullTextIngestionRequest(
                paper_id=paper.paper_id,
                source="mock",
                content=(
                    "## Discussion\n"
                    "Microglial activation may be relevant to Alzheimer's disease.\n\n"
                    "## Results\n"
                    "Microglial activation was associated with Alzheimer's disease progression "
                    "in a longitudinal human cohort."
                ),
            )
        )
        extracted = service.extract_full_text_evidence(
            paper_id=paper.paper_id,
            source="mock",
            research_question="microglial activation Alzheimer progression",
        )
    finally:
        service.storage.close()

    assert ingested.ok is True
    assert extracted is not None
    assert extracted.evidence
    assert extracted.evidence[0].section_label == "Results"


def test_full_text_evidence_skips_non_finding_sections(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        paper = BiomedicalPaper(
            paper_id="PMID-FULLTEXT-NOISE",
            source="pubmed",
            title="Paracetamol pregnancy neurodevelopment umbrella review",
            abstract="Abstract-level summary only.",
        )
        service.storage.upsert_paper(paper)
        service.ingest_full_text(
            FullTextIngestionRequest(
                paper_id=paper.paper_id,
                source="pubmed",
                content=(
                    "## Results\n"
                    "Existing evidence does not clearly link maternal paracetamol use "
                    "during pregnancy with autism or ADHD in offspring.\n\n"
                    "## References\n"
                    "Prenatal Exposure to Acetaminophen and Risk for Attention Deficit "
                    "Hyperactivity Disorder and Autistic Spectrum Disorder: A Systematic "
                    "Review, Meta-Analysis, and Meta-Regression Analysis of Cohort Studies.\n\n"
                    "## Competing interests\n"
                    "All authors completed the ICMJE disclosure form and report no "
                    "financial relationships with organisations related to this work."
                ),
            )
        )
        extracted = service.extract_full_text_evidence(
            paper_id=paper.paper_id,
            source="pubmed",
            research_question=(
                "Does prenatal acetaminophen exposure cause autism or ADHD?"
            ),
        )
    finally:
        service.storage.close()

    assert extracted is not None
    assert extracted.evidence
    labels = {item.section_label for item in extracted.evidence}
    assert "Results" in labels
    assert "References" not in labels
    assert "Competing interests" not in labels


def test_full_text_extraction_uses_question_terms_when_entities_are_unknown(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        paper = BiomedicalPaper(
            paper_id="PMID-HCQ",
            source="pubmed",
            title="Hydroxychloroquine in hospitalized Covid-19",
            abstract="Abstract-level summary only.",
        )
        service.storage.upsert_paper(paper)
        ingested = service.ingest_full_text(
            FullTextIngestionRequest(
                paper_id=paper.paper_id,
                source="pubmed",
                content=(
                    "## Results\n"
                    "Among patients hospitalized with Covid-19, those who received "
                    "hydroxychloroquine did not have a lower incidence of death at "
                    "28 days than those who received usual care."
                ),
            )
        )

        extracted = service.extract_full_text_evidence(
            paper_id=paper.paper_id,
            source="pubmed",
            research_question=(
                "Does hydroxychloroquine improve outcomes in hospitalized Covid-19?"
            ),
        )
    finally:
        service.storage.close()

    assert ingested.ok is True
    assert extracted is not None
    assert extracted.evidence
    item = extracted.evidence[0]
    assert item.source_scope == "full_text"
    assert item.evidence_direction == "contradicts"
    assert item.entities
    assert item.entities[0].entity_type == "other"
    assert "hydroxychloroquine" in item.finding.lower()


def test_parse_bioc_json_full_text_extracts_passages() -> None:
    payload = {
        "documents": [
            {
                "passages": [
                    {
                        "infons": {"section_type": "Results"},
                        "text": "Microglia were associated with pathology.",
                    },
                    {
                        "infons": {"section_type": "Methods"},
                        "text": "A cohort design was used.",
                    },
                ]
            }
        ]
    }

    text = parse_bioc_json_full_text(payload)

    assert "## Results" in text
    assert "Microglia were associated with pathology." in text
    assert "## Methods" in text


def test_parse_bioc_json_full_text_accepts_live_collection_payload() -> None:
    payload = [
        {
            "source": "PMC",
            "documents": [
                {
                    "passages": [
                        {
                            "infons": {"section_type": "Results"},
                            "text": "Open full text passage.",
                        }
                    ]
                }
            ],
        }
    ]

    text = parse_bioc_json_full_text(payload)

    assert "## Results" in text
    assert "Open full text passage." in text


def test_parse_bioc_json_full_text_skips_malformed_empty_passages() -> None:
    payload = {
        "documents": [
            {
                "passages": [
                    {},
                    {"text": "  "},
                    {"infons": {"type": "Discussion"}, "text": "Validated passage."},
                ]
            },
            "bad-document",
            {"passages": [{"text": "Second document passage."}]},
        ]
    }

    text = parse_bioc_json_full_text(payload)

    assert text.count("##") == 2
    assert "## Discussion" in text
    assert "Validated passage." in text
    assert "## Full text" in text
    assert "Second document passage." in text
    assert parse_bioc_json_full_text({"documents": "bad"}) == ""


def test_watch_graph_drift_reports_paper_and_claim_changes(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        watch = service.create_watch(
            WatchTopicCreateRequest(topic="microglia Alzheimer drift")
        )
        service.storage.upsert_evidence(
            EvidenceItem(
                evidence_id="ev-drift-base",
                paper_id="PAPER-BASE",
                claim="Microglial activation is associated with Alzheimer's disease.",
                finding="Microglial activation is associated with Alzheimer's disease.",
                evidence_direction="supports",
                confidence="medium",
                evidence_span="Microglial activation is associated with Alzheimer's disease.",
            ),
            paper_source="mock",
        )
        service.storage.upsert_evidence(
            EvidenceItem(
                evidence_id="ev-drift-compare",
                paper_id="PAPER-COMPARE",
                claim="Microglial activation was not associated after adjustment.",
                finding="Microglial activation was not associated after adjustment.",
                evidence_direction="contradicts",
                confidence="medium",
                evidence_span="Microglial activation was not associated after adjustment.",
            ),
            paper_source="mock",
        )
        service.storage.save_retrieval_manifest(
            _test_retrieval_manifest(
                "ret-base",
                returned_paper_ids=["PAPER-BASE"],
                started_at="2026-06-15T00:00:00+00:00",
            )
        )
        service.storage.save_retrieval_manifest(
            _test_retrieval_manifest(
                "ret-compare",
                returned_paper_ids=["PAPER-BASE", "PAPER-COMPARE"],
                started_at="2026-06-15T01:00:00+00:00",
            )
        )
        service.storage.save_watch_snapshot(
            WatchSnapshot(
                snapshot_id="watch-snapshot-base",
                watch_id=watch.watch_id,
                retrieval_id="ret-base",
                paper_ids=["PAPER-BASE"],
                new_paper_ids=["PAPER-BASE"],
                created_at="2026-06-15T00:00:00+00:00",
            )
        )
        service.storage.save_watch_snapshot(
            WatchSnapshot(
                snapshot_id="watch-snapshot-compare",
                watch_id=watch.watch_id,
                retrieval_id="ret-compare",
                paper_ids=["PAPER-BASE", "PAPER-COMPARE"],
                new_paper_ids=["PAPER-COMPARE"],
                created_at="2026-06-15T01:00:00+00:00",
            )
        )
        drift = service.get_watch_graph_drift(watch.watch_id)
    finally:
        service.storage.close()

    assert drift.status == "ok"
    assert drift.advisory_only is True
    assert drift.base_snapshot_id == "watch-snapshot-base"
    assert drift.compare_snapshot_id == "watch-snapshot-compare"
    assert drift.summary["paper_added"] == 1
    assert any(change.change_type == "claim_added" for change in drift.changes)


def _test_retrieval_manifest(
    retrieval_id: str,
    *,
    returned_paper_ids: list[str],
    started_at: str,
) -> RetrievalManifest:
    return RetrievalManifest(
        retrieval_id=retrieval_id,
        source="mock",
        original_query="microglia Alzheimer drift",
        compiled_query="microglia Alzheimer drift",
        page_size=len(returned_paper_ids),
        pages_requested=1,
        pages_completed=1,
        raw_result_count=len(returned_paper_ids),
        deduped_result_count=len(returned_paper_ids),
        returned_paper_ids=returned_paper_ids,
        started_at=started_at,
        finished_at=started_at,
    )


def test_tool_schema_derives_literal_and_list_types() -> None:
    from typing import Literal

    async def sample(
        self,
        event,
        source: Literal["pubmed", "mock"],
        tags: list[str],
        enabled: bool = True,
    ):
        return ""

    schema = _derive_params_schema(sample)
    props = schema["properties"]
    assert props["source"]["enum"] == ["pubmed", "mock"]
    assert props["source"]["type"] == "string"
    assert props["tags"]["type"] == "array"
    assert props["tags"]["items"]["type"] == "string"
    assert props["enabled"]["type"] == "boolean"


@pytest.mark.asyncio
async def test_biomed_plugin_registers_tools(tmp_path: Path) -> None:
    from agent.plugins.manager import PluginManager
    from agent.plugins.registry import plugin_registry
    from agent.tools.registry import ToolRegistry
    from bus.event_bus import EventBus

    plugin_registry._handlers._handlers.clear()
    plugin_registry._classes.clear()
    plugin_registry._instances.clear()
    bus = EventBus()
    tools = ToolRegistry()
    manager = PluginManager(
        plugin_dirs=[Path(__file__).parents[1] / "plugins"],
        event_bus=bus,
        tool_registry=tools,
        workspace=tmp_path,
    )
    try:
        await manager.load_all()
        assert tools.has_tool("check_literature_access")
        assert tools.has_tool("search_literature")
        assert tools.has_tool("search_biomedical_literature")
        assert tools.has_tool("plan_biomedical_search")
        assert tools.has_tool("answer_with_evidence")
        assert tools.has_tool("answer_with_audit")
        assert tools.has_tool("create_biomed_project")
        assert tools.has_tool("record_project_paper_decision")
        assert tools.has_tool("save_project_paper")
        assert tools.has_tool("reject_project_paper")
        assert tools.has_tool("record_project_claim")
        assert tools.has_tool("save_project_claim")
        assert tools.has_tool("list_project_evidence")
        assert tools.has_tool("generate_project_evidence_brief")
        assert tools.has_tool("validate_citation_support")
        assert tools.has_tool("audit_biomedical_answer")
        assert tools.has_tool("find_conflicting_evidence")
        raw = await tools.execute(
            "answer_with_evidence",
            {
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
            },
        )
        payload = json.loads(str(raw))
        assert payload["citations"]
        audited_raw = await tools.execute(
            "answer_with_audit",
            {
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
            },
        )
        audited_payload = json.loads(str(audited_raw))
        assert audited_payload["audit"]["audit_id"]
        assert audited_payload["revision"]["revision_id"]
        assert audited_payload["trace"]
    finally:
        await manager.terminate_all()
        await bus.aclose()
        plugin_registry._handlers._handlers.clear()
        plugin_registry._classes.clear()
        plugin_registry._instances.clear()
