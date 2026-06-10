from __future__ import annotations

from pathlib import Path

import pytest

from plugins.biomed_evidence.citation_auditor import (
    find_conflicting_evidence,
    validate_citation_support,
)
from plugins.biomed_evidence.mock_data import MOCK_EVIDENCE
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    Citation,
)
from plugins.biomed_evidence.service import BiomedEvidenceService


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
