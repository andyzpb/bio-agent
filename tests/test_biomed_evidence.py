from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from agent.plugins.decorators import _derive_params_schema
from plugins.biomed_evidence.literature_client import (
    PubMedLiteratureClient,
    parse_pubmed_articles,
)
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    BiomedProjectCreateRequest,
    BiomedicalPaper,
    EvidenceExtractionRequest,
    EvidenceItem,
    FullTextIngestionRequest,
    GenerateProjectEvidenceBriefRequest,
    LiteratureAccessCheckRequest,
    LiteratureSearchRequest,
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
    assert len(result.retrieval_bundle.deduped_paper_ids) == len(
        set(result.retrieval_bundle.deduped_paper_ids)
    )
    assert result.retrieval_bundle.duplicate_paper_ids
    assert result.evidence_summary
    assert {item.retrieval_intent for item in result.evidence_summary}
    assert result.evidence_packet is not None
    assert result.evidence_packet.coverage_matrix
    assert result.evidence_packet.retrieval_manifest_ids
    assert set(result.evidence_packet.evidence_ids) == {
        item.evidence_id for item in result.evidence_summary
    }
    assert set(result.evidence_packet.paper_ids) == {
        item.paper_id for item in result.evidence_summary
    }


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
    assert item.document_id == ingested.document.document_id
    assert item.section_id == ingested.sections[0].section_id
    assert item.section_label == "Results"
    assert item.char_start is not None
    assert item.char_end is not None
    assert item.source_hash == ingested.sections[0].source_hash
    assert graph is not None
    evidence_nodes = [node for node in graph.nodes if node.type == "EvidenceSpan"]
    assert any(node.properties.get("source_scope") == "full_text" for node in evidence_nodes)


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
