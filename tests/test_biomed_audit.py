from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.biomed_evidence.citation_auditor import (
    _recommended_action,
    extract_atomic_claims,
    find_conflicting_evidence,
    validate_citation_support,
)
from plugins.biomed_evidence.mock_data import MOCK_EVIDENCE
from plugins.biomed_evidence.schemas import (
    AnswerRevision,
    AnswerWithEvidenceRequest,
    AnswerWithEvidenceResult,
    Citation,
    CitationAuditResult,
    CitationAuditRequest,
    ClaimAuditItem,
    EvidenceItem,
    LogicAuditResult,
    LogicFactExport,
    UncertaintyAudit,
)
from plugins.biomed_evidence.service import (
    BiomedEvidenceService,
    _build_answer_revision,
    _llm_advisory_verifier_payload,
    _normalize_llm_answer_text,
    _remove_failed_claim_lines,
)
from plugins.biomed_evidence.guardrails import RESEARCH_USE_DISCLAIMER


def _uncertainty(calibrated: bool = True) -> UncertaintyAudit:
    return UncertaintyAudit(
        expected_uncertainty="medium",
        observed_uncertainty="medium",
        calibrated=calibrated,
    )


def _failed_claim(
    text: str,
    *,
    role: str,
    verdict: str = "overclaimed",
    claim_type: str = "association",
    paper_id: str = "PMID:1",
) -> ClaimAuditItem:
    return ClaimAuditItem(
        claim_id=f"claim-{abs(hash((text, role))) % 100000}",
        claim=text,
        claim_type=claim_type,
        claim_role=role,
        cited_paper_ids=[paper_id],
        evidence_ids=[f"ev-{paper_id}"],
        verdict=verdict,
        support_score=0.55,
        reason="Suggestive evidence does not support definitive wording.",
    )


def _audit_with_failed_claims(
    failed_claims: list[ClaimAuditItem],
    *,
    action: str = "revise",
) -> CitationAuditResult:
    return CitationAuditResult(
        audit_id="audit-role-test",
        run_id="run-role-test",
        claim_audits=failed_claims,
        uncertainty_audit=_uncertainty(calibrated=False),
        claim_support_rate=0.5,
        citation_precision=1.0,
        unsupported_claim_rate=0.0,
        overclaim_rate=1.0 if failed_claims else 0.0,
        conflict_awareness=True,
        uncertainty_calibrated=False,
        failed_claims=failed_claims,
        recommended_action=action,
        created_at="2026-06-30T00:00:00+00:00",
    )


def _answer_result(answer: str) -> AnswerWithEvidenceResult:
    return AnswerWithEvidenceResult(
        run_id="run-role-test",
        answer=answer,
        citations=[_citation("PMID:1")],
        evidence_summary=[],
        conflicting_evidence=[],
        limitations=[],
        uncertainty_level="high",
        disclaimer=RESEARCH_USE_DISCLAIMER,
    )


def _citation(paper_id: str) -> Citation:
    return Citation(
        paper_id=paper_id,
        title=paper_id,
        source="mock",
        cited_claim="mock cited claim",
    )


def test_citation_audit_marks_supported_claim() -> None:
    evidence = MOCK_EVIDENCE["MOCK-PMID-1001"]
    result = validate_citation_support(
        answer=(
            "- Disease-associated microglia were enriched in higher Braak stage "
            "samples and correlated with amyloid pathology. [MOCK-PMID-1001]"
        ),
        citations=[_citation("MOCK-PMID-1001")],
        evidence_items=evidence,
        observed_uncertainty="low",
    )

    assert result.claim_support_rate == 1.0
    assert result.citation_precision == 1.0
    assert result.claim_audits[0].verdict == "supported"
    assert result.recommended_action == "pass"


def test_citation_precision_uses_answer_citations_not_full_packet() -> None:
    result = validate_citation_support(
        answer=(
            "- Disease-associated microglia were enriched in higher Braak stage "
            "samples and correlated with amyloid pathology. [MOCK-PMID-1001]"
        ),
        citations=[_citation("MOCK-PMID-1001"), _citation("MOCK-PMID-1002")],
        evidence_items=[
            *MOCK_EVIDENCE["MOCK-PMID-1001"],
            *MOCK_EVIDENCE["MOCK-PMID-1002"],
        ],
        observed_uncertainty="low",
    )

    assert result.citation_precision == 1.0
    assert result.packet_citation_utilization == 0.5


def test_conflict_awareness_ignores_unreferenced_packet_evidence() -> None:
    inconclusive = MOCK_EVIDENCE["MOCK-PMID-1003"][0].model_copy(
        update={"evidence_direction": "inconclusive"}
    )
    result = validate_citation_support(
        answer=(
            "- Disease-associated microglia were enriched in higher Braak stage "
            "samples and correlated with amyloid pathology. [MOCK-PMID-1001]"
        ),
        citations=[_citation("MOCK-PMID-1001")],
        evidence_items=[*MOCK_EVIDENCE["MOCK-PMID-1001"], inconclusive],
        observed_uncertainty="low",
    )

    assert result.conflict_awareness is True
    assert result.recommended_action == "pass"


def test_llm_answer_text_normalizes_literal_newlines() -> None:
    text = _normalize_llm_answer_text("Line one\\n- Claim [MOCK-PMID-1001]")

    assert text == "Line one\n- Claim [MOCK-PMID-1001]"


def test_citation_audit_ignores_markdown_section_headings() -> None:
    evidence = MOCK_EVIDENCE["MOCK-PMID-1001"]
    answer = (
        "**Recent evidence linking microglial activation to Alzheimer's disease progression**\n"
        "- Microglial activation is associated with Alzheimer's disease progression. [MOCK-PMID-1001]"
    )

    claims = extract_atomic_claims(answer)
    result = validate_citation_support(
        answer=answer,
        citations=[_citation("MOCK-PMID-1001")],
        evidence_items=evidence,
    )

    assert [claim.text for claim in claims] == [
        "Microglial activation is associated with Alzheimer's disease progression."
    ]
    assert result.claim_support_rate == 1.0
    assert result.failed_claims == []


def test_atomic_claim_splitter_handles_statistics_citations_and_abbreviations() -> None:
    claims = extract_atomic_claims(
        "RECOVERY Collaborative Group et al. reported no 28-day mortality benefit "
        "(26.8% vs. 25.0%; rate ratio 1.09; 95% CI 0.97 to 1.23) [PMID:32622389]. "
        "Patients allocated to hydroxychloroquine were less likely to be discharged "
        "alive within 28 days (59.6% vs. 62.9%; rate ratio 0.90; 95% CI 0.83 to 0.98) "
        "[PMID:32622389]."
    )

    assert [claim.text for claim in claims] == [
        "RECOVERY Collaborative Group et al. reported no 28-day mortality benefit (26.8% vs. 25.0%; rate ratio 1.09; 95% CI 0.97 to 1.23).",
        "Patients allocated to hydroxychloroquine were less likely to be discharged alive within 28 days (59.6% vs. 62.9%; rate ratio 0.90; 95% CI 0.83 to 0.98).",
    ]


def test_audit_treats_off_scope_citation_as_irrelevant() -> None:
    answer = "Hydroxychloroquine improves hospitalized COVID-19 outcomes [PMID:PREP]."
    evidence = EvidenceItem(
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
        scope_match="false",
        scope_mismatch_reasons=["Excluded term matched: prophylaxis"],
    )

    result = validate_citation_support(
        answer=answer,
        citations=[_citation("PMID:PREP")],
        evidence_items=[evidence],
    )

    assert result.claim_audits[0].verdict == "irrelevant_citation"
    assert "off-scope" in result.claim_audits[0].reason


def test_citation_audit_allows_causal_limitation_language() -> None:
    evidence = MOCK_EVIDENCE["MOCK-PMID-1001"]
    answer = (
        "- Disease-associated microglia were enriched in higher Braak stage samples "
        "and correlated with amyloid pathology, indicating an association with "
        "Alzheimer's disease progression. [MOCK-PMID-1001] However, the study was "
        "cross-sectional, limiting causal interpretation. [MOCK-PMID-1001]"
    )

    result = validate_citation_support(
        answer=answer,
        citations=[_citation("MOCK-PMID-1001")],
        evidence_items=evidence,
    )

    assert all(item.verdict != "overclaimed" for item in result.claim_audits)
    assert result.failed_claims == []


def test_citation_audit_detects_association_to_causation_overclaim() -> None:
    evidence = MOCK_EVIDENCE["MOCK-PMID-1001"]
    result = validate_citation_support(
        answer="Microglial activation causes Alzheimer's disease progression. [MOCK-PMID-1001]",
        citations=[_citation("MOCK-PMID-1001")],
        evidence_items=evidence,
        observed_uncertainty="low",
    )

    assert result.overclaim_rate == 1.0
    assert result.claim_audits[0].verdict == "overclaimed"
    assert "causality" in (result.claim_audits[0].overclaim_reason or "")
    assert result.recommended_action == "revise"


def test_peripheral_logic_failures_do_not_force_revise() -> None:
    failed = [
        _failed_claim(
            "The vaginal microbiome is associated with higher odds of high-risk HPV.",
            role="supporting_context",
        ),
        _failed_claim(
            "No refuting evidence was identified in the supplied search.",
            role="search_meta",
            verdict="insufficient_evidence",
        ),
    ]

    action = _recommended_action(
        failed_claims=failed,
        uncertainty_audit=_uncertainty(calibrated=True),
        conflict_awareness=True,
        evidence_items=[],
    )

    assert action == "pass_with_limitations"


def test_core_overclaim_still_forces_revise() -> None:
    failed = [
        _failed_claim(
            "Persistent high-risk HPV infection causes cervical cancer.",
            role="core_answer",
            verdict="overclaimed",
            claim_type="causal",
        )
    ]

    action = _recommended_action(
        failed_claims=failed,
        uncertainty_audit=_uncertainty(calibrated=True),
        conflict_awareness=True,
        evidence_items=[],
    )

    assert action == "revise"


def test_revision_removes_peripheral_and_search_meta_failed_claims() -> None:
    draft = (
        "Persistent high-risk HPV infection causes cervical cancer. [PMID:1]\n"
        "The vaginal microbiome is associated with higher odds of high-risk HPV. [PMID:1]\n"
        "No refuting evidence was identified in the supplied search. [PMID:1]"
    )
    failed = [
        _failed_claim(
            "The vaginal microbiome is associated with higher odds of high-risk HPV.",
            role="supporting_context",
        ),
        _failed_claim(
            "No refuting evidence was identified in the supplied search.",
            role="search_meta",
            verdict="insufficient_evidence",
        ),
    ]

    revision = _build_answer_revision(
        draft_result=_answer_result(draft),
        audit=_audit_with_failed_claims(failed, action="pass_with_limitations"),
        clinical_boundary=False,
        use_llm_revision=True,
        fallback_reason_override="test",
    )

    assert "Persistent high-risk HPV infection causes cervical cancer" in revision.final_answer
    assert "vaginal microbiome" not in revision.final_answer
    assert "No refuting evidence" not in revision.final_answer
    assert "is the is associated with of" not in revision.final_answer
    assert revision.revision_action == "revise"
    assert revision.revision_action_detail == "removed_peripheral_claims"


def test_revision_removes_core_overclaim_instead_of_emitting_template_claim() -> None:
    draft = "Persistent high-risk HPV infection causes cervical cancer. [PMID:1]"
    failed = [
        _failed_claim(
            "Persistent high-risk HPV infection causes cervical cancer.",
            role="core_answer",
            verdict="overclaimed",
            claim_type="causal",
        )
    ]

    revision = _build_answer_revision(
        draft_result=_answer_result(draft),
        audit=_audit_with_failed_claims(failed, action="revise"),
        clinical_boundary=False,
        use_llm_revision=True,
        fallback_reason_override="test",
    )

    assert "The cited evidence supports a narrower claim" not in revision.final_answer
    assert "is the is associated with of" not in revision.final_answer
    assert revision.revision_action == "abstain"


def test_revision_keeps_audit_operation_notes_out_of_final_answer() -> None:
    draft = (
        "Smoking causes lung cancer. [PMID:1]\n"
        "Background or contextual evidence:"
    )
    failed = [
        _failed_claim(
            "Background or contextual evidence:",
            role="core_answer",
            verdict="not_cited",
        )
    ]

    revision = _build_answer_revision(
        draft_result=_answer_result(draft),
        audit=_audit_with_failed_claims(failed, action="revise"),
        clinical_boundary=False,
        use_llm_revision=True,
        fallback_reason_override="test",
    )

    assert "Background or contextual evidence" not in revision.final_answer
    assert "Audit limitations:" not in revision.final_answer
    assert "Removed unsupported claim:" not in revision.final_answer
    assert revision.added_limitations


def test_nonclinical_refuse_or_abstain_keeps_supported_revised_answer() -> None:
    draft = (
        "Hydroxychloroquine did not reduce 28-day mortality in hospitalized COVID-19 patients. [PMID:1]\n"
        "Background or contextual evidence:"
    )
    failed = [
        _failed_claim(
            "Background or contextual evidence:",
            role="core_answer",
            verdict="not_cited",
        )
    ]

    revision = _build_answer_revision(
        draft_result=_answer_result(draft),
        audit=_audit_with_failed_claims(failed, action="refuse_or_abstain"),
        clinical_boundary=False,
        use_llm_revision=True,
        fallback_reason_override="test",
    )

    assert revision.revision_action == "revise"
    assert revision.refusal_reason is None
    assert "Hydroxychloroquine did not reduce 28-day mortality" in revision.final_answer
    assert "I cannot help diagnose a patient" not in revision.final_answer


def test_established_causal_risk_factor_review_is_not_overclaimed() -> None:
    evidence = EvidenceItem(
        evidence_id="ev-smoking-sclc",
        paper_id="PMID:SMOKE",
        claim=(
            "IARC monograph and public health consensus evidence identify tobacco "
            "smoking as an established causal risk factor and primary cause of lung cancer."
        ),
        finding=(
            "IARC monograph and public health consensus evidence identify tobacco "
            "smoking as an established causal risk factor and primary cause of lung cancer."
        ),
        evidence_direction="supports",
        entities=[],
        methods=["IARC monograph", "public health consensus review"],
        limitations=["Abstract-level packet does not extract quantitative estimates."],
        confidence="high",
        evidence_span=(
            "IARC monograph and public health consensus evidence identify tobacco "
            "smoking as an established causal risk factor and primary cause of lung cancer."
        ),
    )

    result = validate_citation_support(
        answer=(
            "Tobacco smoking is an established causal risk factor for lung cancer. "
            "[PMID:SMOKE]"
        ),
        citations=[_citation("PMID:SMOKE")],
        evidence_items=[evidence],
        observed_uncertainty="low",
    )

    assert result.claim_audits[0].verdict == "supported"
    assert result.recommended_action in {"pass", "pass_with_limitations"}


def test_established_causal_risk_audit_ignores_off_topic_inconclusive_uncertainty() -> None:
    direct = EvidenceItem(
        evidence_id="ev-asbestos-direct",
        paper_id="PMID:ASBESTOS",
        claim="Asbestos exposure is an established causal risk factor for mesothelioma.",
        finding="Asbestos exposure is an established causal risk factor for mesothelioma.",
        evidence_direction="supports",
        methods=["systematic review", "public health consensus"],
        confidence="high",
        evidence_span="Asbestos exposure is an established causal risk factor for mesothelioma.",
    )
    off_topic = EvidenceItem(
        evidence_id="ev-cannabis-off-topic",
        paper_id="PMID:CANNABIS",
        claim="Cannabis smoking appeared to be associated with lung cancer at an earlier age.",
        finding="Cannabis smoking appeared to be associated with lung cancer at an earlier age.",
        evidence_direction="inconclusive",
        confidence="high",
        evidence_span="Cannabis smoking appeared to be associated with lung cancer at an earlier age.",
    )

    result = validate_citation_support(
        answer=(
            "Asbestos exposure is an established causal risk factor for "
            "mesothelioma. [PMID:ASBESTOS]"
        ),
        citations=[_citation("PMID:ASBESTOS")],
        evidence_items=[direct, off_topic],
        observed_uncertainty="low",
    )

    assert result.uncertainty_audit.expected_uncertainty == "low"
    assert result.uncertainty_calibrated is True


def test_citation_audit_marks_uncited_claim() -> None:
    result = validate_citation_support(
        answer="Microglial activation is associated with disease progression.",
        citations=[],
        evidence_items=MOCK_EVIDENCE["MOCK-PMID-1001"],
        observed_uncertainty="medium",
    )

    assert result.unsupported_claim_rate == 1.0
    assert result.claim_audits[0].verdict == "not_cited"
    assert result.recommended_action == "revise"


def test_post_audit_repair_removes_empty_markdown_section() -> None:
    answer = (
        f"{RESEARCH_USE_DISCLAIMER}\n\n"
        "**Evidence**\n"
        "- The abundance of activated microglia correlated with Braak stage and amyloid pathology [MOCK-PMID-1001].\n\n"
        "**Interpretation**\n"
        "Microglial activation causes Alzheimer's disease progression."
    )
    audit = validate_citation_support(
        answer=answer,
        citations=[_citation("MOCK-PMID-1001")],
        evidence_items=MOCK_EVIDENCE["MOCK-PMID-1001"],
    )

    repaired, removed = _remove_failed_claim_lines(answer, audit.failed_claims)

    assert removed == ["Microglial activation causes Alzheimer's disease progression."]
    assert "**Evidence**" in repaired
    assert "**Interpretation**" not in repaired
    assert "causes Alzheimer's disease progression" not in repaired


def test_post_audit_repair_does_not_remove_support_lines_for_short_failed_claim() -> None:
    answer = (
        "Evidence supporting the hypothesis:\n"
        "- Cigarette smoking is the primary risk factor for development of SCLC [40163214]\n"
        "- A vast majority of lung cancer deaths are attributable to cigarette smoking [22054876]\n\n"
        "Inconclusive evidence:\n"
        "- Smoking and cancer. [6801462]\n"
    )
    failed = [
        ClaimAuditItem(
            claim_id="claim-short",
            claim="Smoking and cancer.",
            claim_type="association",
            cited_paper_ids=["6801462"],
            verdict="insufficient_evidence",
            reason="Empty abstract.",
        )
    ]

    repaired, removed = _remove_failed_claim_lines(answer, failed)

    assert removed == ["Smoking and cancer."]
    assert "Cigarette smoking is the primary risk factor" in repaired
    assert "A vast majority of lung cancer deaths" in repaired
    assert "Smoking and cancer." not in repaired
    assert "Inconclusive evidence:" not in repaired


def test_conflict_audit_returns_mixed_evidence() -> None:
    evidence = [
        *MOCK_EVIDENCE["MOCK-PMID-1001"],
        *MOCK_EVIDENCE["MOCK-PMID-1003"],
        *MOCK_EVIDENCE["MOCK-PMID-1004"],
    ]
    result = find_conflicting_evidence(
        claim="Microglial activation is associated with Alzheimer's disease progression.",
        topic="microglial activation Alzheimer's disease progression",
        evidence_items=evidence,
    )

    assert result.verdict == "mixed_evidence"
    assert result.supporting_papers
    assert result.contradicting_papers
    assert result.conflict_axes


@pytest.mark.asyncio
async def test_service_audit_answer_run_is_idempotent(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        answer = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
            )
        )
        first = service.audit_answer_run(answer.run_id)
        second = service.audit_answer_run(answer.run_id)
        rows, total = service.list_answer_audits(run_id=answer.run_id)
    finally:
        await service.aclose()

    assert first is not None
    assert second is not None
    assert first.audit_id == second.audit_id
    assert total == 1
    assert rows[0]["audit_id"] == first.audit_id


@pytest.mark.asyncio
async def test_answer_with_audit_persists_revision_and_trace(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
                use_llm_revision=True,
            )
        )
        trace_payload = service.get_answer_trace(audited.answer_result.run_id)
        service.storage.save_agent_trace_steps(audited.trace)
        trace_again = service.storage.list_agent_trace_steps(audited.answer_result.run_id)
    finally:
        await service.aclose()

    assert audited.audit.audit_id
    assert audited.revision.revision_id
    assert audited.revision.revision_mode in {"deterministic", "fallback"}
    assert audited.revision.fallback_reason
    assert audited.final_answer == audited.answer_result.answer
    assert {step.step for step in audited.trace} == {
        "classify",
        "plan",
        "validate_plan",
        "retrieve",
        "extract",
        "draft",
        "audit",
        "advisory_verify",
        "revise",
        "post_audit",
        "finalize",
    }
    assert trace_payload is not None
    assert trace_payload["revision"] is not None
    assert len(trace_again) == 11


def test_answer_revision_removes_overclaim_without_template_claim() -> None:
    evidence = MOCK_EVIDENCE["MOCK-PMID-1001"]
    draft = (
        f"{RESEARCH_USE_DISCLAIMER}\n\n"
        "- Microglial activation causes Alzheimer's disease progression. [MOCK-PMID-1001]"
    )
    audit = validate_citation_support(
        answer=draft,
        citations=[_citation("MOCK-PMID-1001")],
        evidence_items=evidence,
        run_id="run-overclaim",
        observed_uncertainty="low",
    )
    result = AnswerWithEvidenceResult(
        run_id="run-overclaim",
        answer=draft,
        citations=[_citation("MOCK-PMID-1001")],
        evidence_summary=evidence,
        conflicting_evidence=[],
        limitations=[],
        uncertainty_level="low",
        disclaimer=RESEARCH_USE_DISCLAIMER,
    )

    revision = _build_answer_revision(
        draft_result=result,
        audit=audit,
        clinical_boundary=False,
    )

    assert isinstance(revision, AnswerRevision)
    assert revision.revision_action == "abstain"
    assert "causes Alzheimer's disease progression" not in revision.final_answer
    assert "The cited evidence supports a narrower claim" not in revision.final_answer


def test_answer_revision_keeps_supported_lines_when_removing_short_failed_claim() -> None:
    support = EvidenceItem(
        evidence_id="ev-support",
        paper_id="PMID:1",
        claim="Asbestos exposure is an established causal risk factor for mesothelioma.",
        finding="Asbestos exposure is an established causal risk factor for mesothelioma.",
        evidence_direction="supports",
        confidence="high",
        evidence_span="Asbestos exposure is an established causal risk factor for mesothelioma.",
    )
    weak = EvidenceItem(
        evidence_id="ev-weak",
        paper_id="PMID:2",
        claim="Asbestos and mesothelioma.",
        finding="Asbestos and mesothelioma.",
        evidence_direction="inconclusive",
        confidence="low",
        evidence_span="Asbestos and mesothelioma.",
    )
    draft = (
        "Evidence supporting the hypothesis:\n"
        "- Asbestos exposure is an established causal risk factor for mesothelioma [PMID:1]\n\n"
        "Inconclusive evidence:\n"
        "- Asbestos and mesothelioma. [PMID:2]\n"
    )
    failed = ClaimAuditItem(
        claim_id="claim-short",
        claim="Asbestos and mesothelioma.",
        claim_type="association",
        cited_paper_ids=["PMID:2"],
        verdict="insufficient_evidence",
        reason="Inconclusive evidence cannot support an unhedged positive claim.",
    )
    audit = CitationAuditResult(
        audit_id="audit-short",
        run_id="run-short-failed",
        claim_audits=[
            ClaimAuditItem(
                claim_id="claim-supported",
                claim=(
                    "Asbestos exposure is an established causal risk factor for "
                    "mesothelioma."
                ),
                claim_type="causal",
                cited_paper_ids=["PMID:1"],
                verdict="supported",
                reason="Supported by cited evidence.",
            ),
            failed,
        ],
        uncertainty_audit=UncertaintyAudit(
            expected_uncertainty="high",
            observed_uncertainty="high",
            calibrated=True,
        ),
        claim_support_rate=0.5,
        citation_precision=1.0,
        unsupported_claim_rate=0.5,
        overclaim_rate=0.0,
        conflict_awareness=False,
        uncertainty_calibrated=True,
        failed_claims=[failed],
        recommended_action="revise",
        created_at="2026-06-29T00:00:00+00:00",
    )
    result = AnswerWithEvidenceResult(
        run_id="run-short-failed",
        answer=draft,
        citations=[_citation("PMID:1"), _citation("PMID:2")],
        evidence_summary=[support, weak],
        conflicting_evidence=[],
        limitations=[],
        uncertainty_level="high",
        disclaimer=RESEARCH_USE_DISCLAIMER,
    )

    revision = _build_answer_revision(
        draft_result=result,
        audit=audit,
        clinical_boundary=False,
        use_llm_revision=True,
        fallback_reason_override="test",
    )

    assert "Asbestos exposure is an established causal risk factor" in revision.final_answer
    assert "- Asbestos and mesothelioma." not in revision.final_answer
    assert "Inconclusive evidence:" not in revision.final_answer


class _FakeRevisionResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeRevisionProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools, model, max_tokens, tool_choice="auto", disable_thinking=False):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        return _FakeRevisionResponse(
            json.dumps(
                {
                    "final_answer": payload["draft_answer"],
                    "changed_claims": [],
                    "removed_claims": [],
                    "softened_claims": [],
                    "added_limitations": [],
                    "uncertainty_level": "high",
                }
            )
        )


class _FakeUncitedRevisionProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools, model, max_tokens, tool_choice="auto", disable_thinking=False):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        return _FakeRevisionResponse(
            json.dumps(
                {
                    "final_answer": (
                        payload["draft_answer"]
                        + "\n\nMicroglial activation causes Alzheimer's disease progression."
                    ),
                    "changed_claims": ["Added interpretation sentence."],
                    "removed_claims": [],
                    "softened_claims": [],
                    "added_limitations": [],
                    "uncertainty_level": "high",
                }
            )
        )


class _FakeChangedSupportedRevisionProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools, model, max_tokens, tool_choice="auto", disable_thinking=False):
        self.calls += 1
        return _FakeRevisionResponse(
            json.dumps(
                {
                    "final_answer": (
                        "The abundance of activated microglia correlated with "
                        "Braak stage and amyloid pathology. [A. Jensen et al., "
                        "2025; MOCK-PMID-1001]"
                    ),
                    "changed_claims": ["Focused answer on the directly supported claim."],
                    "removed_claims": [],
                    "softened_claims": [],
                    "added_limitations": [],
                    "uncertainty_level": "medium",
                }
            )
        )


class _FakeAdvisoryVerifierProvider:
    def __init__(self, *, disagree: bool = False) -> None:
        self.disagree = disagree
        self.calls = 0

    async def chat(self, messages, tools, model, max_tokens, tool_choice="auto", disable_thinking=False):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        claim_audits = payload["deterministic_audit"]["claim_audits"]
        first = claim_audits[0]
        if self.disagree:
            action = "revise"
            verdict = "overclaimed"
            risk = "high"
            rationale = "Advisory verifier judged the claim as stronger than the supplied evidence."
        else:
            action = "pass"
            verdict = first["verdict"]
            risk = "low"
            rationale = "Advisory verifier agreed with deterministic audit."
        return _FakeRevisionResponse(
            json.dumps(
                {
                    "advisory_action": action,
                    "claim_reviews": [
                        {
                            "claim_id": first["claim_id"],
                            "claim": first["claim"],
                            "advisory_verdict": verdict,
                            "advisory_action": action,
                            "risk_level": risk,
                            "cited_paper_ids": first["cited_paper_ids"],
                            "rationale": rationale,
                        }
                    ],
                    "warnings": [],
                    "errors": [],
                }
            )
        )


class _FailingAdvisoryVerifierProvider:
    async def chat(
        self, messages, tools, model, max_tokens, tool_choice="auto", disable_thinking=False
    ):
        raise RuntimeError("verifier kaboom")


def test_advisory_verifier_payload_sends_slim_audit_summary() -> None:
    claim = _failed_claim("Smoking causes lung cancer.", role="core_answer")
    claim = claim.model_copy(
        update={
            "logic_audit": LogicAuditResult(
                claim_id=claim.claim_id,
                evidence_ids=claim.evidence_ids,
                logic_verdict="overclaimed",
                entailment_score=0.35,
                reason="long logic details",
                logic_fact_export=LogicFactExport(
                    export_id="facts-heavy",
                    claim_id=claim.claim_id,
                    text="x" * 10000,
                ),
            )
        }
    )
    payload = _llm_advisory_verifier_payload(
        request=AnswerWithEvidenceRequest(question="Does smoking cause lung cancer?"),
        draft_result=_answer_result("Smoking causes lung cancer. [PMID:1]"),
        audit=_audit_with_failed_claims([claim]),
    )

    claim_payload = payload["deterministic_audit"]["claim_audits"][0]
    assert "logic_audit" not in claim_payload
    assert len(json.dumps(payload)) < 5000


@pytest.mark.asyncio
async def test_answer_with_audit_records_verifier_fallback_without_provider(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
                use_llm_verifier=True,
            )
        )
        trace_payload = service.get_answer_trace(audited.answer_result.run_id)
    finally:
        await service.aclose()

    assert audited.advisory_verifier is not None
    assert audited.advisory_verifier.verifier_mode == "fallback"
    assert audited.advisory_verifier.fallback_reason
    assert trace_payload is not None
    latest_advisory = trace_payload["latest_advisory_verifier"]
    assert isinstance(latest_advisory, dict)
    assert latest_advisory["verifier_mode"] == "fallback"
    assert any(
        step.step == "advisory_verify" and step.status == "completed"
        for step in audited.trace
    )


@pytest.mark.asyncio
async def test_advisory_verifier_fallback_records_exception_detail(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=_FailingAdvisoryVerifierProvider(),
        revision_model="fake-advisory-verifier",
    )
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
                use_llm_verifier=True,
            )
        )
    finally:
        await service.aclose()

    assert audited.advisory_verifier is not None
    assert audited.advisory_verifier.verifier_mode == "fallback"
    assert "RuntimeError: verifier kaboom" in (
        audited.advisory_verifier.fallback_reason or ""
    )


@pytest.mark.asyncio
async def test_answer_with_audit_can_use_advisory_verifier_provider(
    tmp_path: Path,
) -> None:
    provider = _FakeAdvisoryVerifierProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-advisory-verifier",
    )
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
                use_llm_verifier=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert audited.advisory_verifier is not None
    assert audited.advisory_verifier.verifier_mode == "llm"
    assert audited.advisory_verifier.llm_model == "fake-advisory-verifier"
    assert audited.advisory_verifier.claim_reviews
    assert audited.advisory_verifier.high_risk_disagreement_count == 0


@pytest.mark.asyncio
async def test_advisory_verifier_records_high_risk_disagreement(
    tmp_path: Path,
) -> None:
    provider = _FakeAdvisoryVerifierProvider(disagree=True)
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-advisory-verifier",
    )
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
                use_llm_verifier=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert audited.advisory_verifier is not None
    assert audited.advisory_verifier.high_risk_disagreement_count >= 1
    assert audited.advisory_verifier.disagreements[0].high_risk is True
    assert any(
        "Advisory verifier flagged high-risk disagreement" in item
        for item in audited.revision.added_limitations
    )


@pytest.mark.asyncio
async def test_answer_with_audit_can_use_injected_revision_provider(tmp_path: Path) -> None:
    provider = _FakeRevisionProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-biomed-reviser",
    )
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
                use_llm_revision=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert audited.revision.revision_mode == "llm"
    assert audited.revision.llm_model == "fake-biomed-reviser"
    assert audited.revision.llm_prompt_hash
    assert audited.revision.post_revision_audit_id
    assert audited.audit.audit_id == audited.revision.post_revision_audit_id
    assert any(step.step == "post_audit" and step.status == "completed" for step in audited.trace)


@pytest.mark.asyncio
async def test_llm_revision_repairs_uncited_model_sentence(tmp_path: Path) -> None:
    provider = _FakeUncitedRevisionProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-biomed-reviser",
    )
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
                use_llm_revision=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert audited.revision.revision_mode == "llm"
    assert "causes Alzheimer's disease progression" not in audited.final_answer
    assert audited.audit.recommended_action in {"pass", "pass_with_limitations"}


@pytest.mark.asyncio
async def test_changed_final_answer_returns_post_revision_audit(tmp_path: Path) -> None:
    provider = _FakeChangedSupportedRevisionProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-biomed-reviser",
    )
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_papers=5,
                use_llm_revision=True,
            )
        )
    finally:
        await service.aclose()

    assert audited.final_answer != audited.draft_answer
    assert audited.revision.post_revision_audit_id
    assert audited.audit.audit_id == audited.revision.post_revision_audit_id
    assert [item.claim for item in audited.audit.claim_audits] == [
        "The abundance of activated microglia correlated with Braak stage and amyloid pathology."
    ]
