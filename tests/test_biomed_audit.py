from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.biomed_evidence.citation_auditor import (
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
    CitationAuditRequest,
)
from plugins.biomed_evidence.service import (
    BiomedEvidenceService,
    _build_answer_revision,
    _normalize_llm_answer_text,
)
from plugins.biomed_evidence.guardrails import RESEARCH_USE_DISCLAIMER


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
        "revise",
        "post_audit",
        "finalize",
    }
    assert trace_payload is not None
    assert trace_payload["revision"] is not None
    assert len(trace_again) == 10


def test_answer_revision_softens_overclaim() -> None:
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
    assert revision.revision_action == "revise"
    assert revision.softened_claims
    assert "causes Alzheimer's disease progression" not in revision.final_answer
    assert "is associated with Alzheimer's disease progression" in revision.final_answer


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
    assert any(step.step == "post_audit" and step.status == "completed" for step in audited.trace)
