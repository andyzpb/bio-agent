from __future__ import annotations

from pathlib import Path

import pytest

from plugins.biomed_evidence.claim_logic import audit_claim_logic
from plugins.biomed_evidence.claim_logic_export import normalize_symbol
from plugins.biomed_evidence.citation_auditor import validate_citation_support
from plugins.biomed_evidence.schemas import (
    AtomicClaim,
    BiomedicalEntity,
    Citation,
    EvidenceItem,
    AnswerWithEvidenceRequest,
)
from plugins.biomed_evidence.service import BiomedEvidenceService


def _citation(paper_id: str = "PMID:123") -> Citation:
    return Citation(
        paper_id=paper_id,
        title="Mock paper",
        source="mock",
        cited_claim="mock",
    )


def _animal_association_evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_1",
        paper_id="PMID:123",
        claim="Microglial activation was associated with amyloid pathology in a mouse model.",
        finding="Microglial activation was associated with amyloid pathology in a mouse model.",
        evidence_direction="supports",
        entities=[
            BiomedicalEntity(name="microglial activation", entity_type="cell_type"),
            BiomedicalEntity(name="amyloid pathology", entity_type="disease"),
        ],
        methods=["mouse model"],
        limitations=["Animal model evidence may not translate to humans."],
        confidence="medium",
        evidence_span="Microglial activation was associated with amyloid pathology in a mouse model.",
    )


def test_claim_logic_detects_association_to_causation_and_animal_to_human() -> None:
    claim = AtomicClaim(
        claim_id="claim_1",
        text="Microglial activation drives Alzheimer's disease progression in humans.",
        claim_type="causal",
        cited_paper_ids=["PMID:123"],
    )

    result = audit_claim_logic(
        claim,
        [_animal_association_evidence()],
        export_facts=True,
    )

    assert result.logic_verdict == "overclaimed"
    assert "association_does_not_entail_causation" in result.rules_triggered
    assert "animal_evidence_does_not_entail_human_claim" in result.rules_triggered
    assert result.logic_fact_export is not None
    assert "claim_predicate(claim_1, causes_or_drives)." in (
        result.logic_fact_export.text or ""
    )
    assert "triggered_rule(claim_1, ev_1, association_does_not_entail_causation)." in (
        result.logic_fact_export.text or ""
    )
    assert "logic_verdict(claim_1, overclaimed)." in (
        result.logic_fact_export.text or ""
    )


def test_logic_fact_export_is_deterministic_and_normalizes_symbols() -> None:
    claim = AtomicClaim(
        claim_id="claim_1",
        text="Microglial activation drives Alzheimer's disease progression in humans.",
        claim_type="causal",
        cited_paper_ids=["PMID:123"],
    )
    first = audit_claim_logic(
        claim, [_animal_association_evidence()], export_facts=True
    )
    second = audit_claim_logic(
        claim, [_animal_association_evidence()], export_facts=True
    )

    assert first.logic_fact_export is not None
    assert second.logic_fact_export is not None
    assert first.logic_fact_export.text == second.logic_fact_export.text
    assert first.logic_fact_export.export_id == second.logic_fact_export.export_id
    assert (
        normalize_symbol("Alzheimer's disease progression")
        == "alzheimer_s_disease_progression"
    )


def test_citation_audit_can_attach_logic_audit_and_fact_export() -> None:
    answer = (
        "Microglial activation increases Alzheimer's disease progression "
        "in humans. [PMID:123]"
    )
    result = validate_citation_support(
        answer=answer,
        citations=[_citation()],
        evidence_items=[_animal_association_evidence()],
        use_llm_claim_logic=True,
        export_logic_facts=True,
    )

    claim_audit = result.claim_audits[0]
    assert claim_audit.logic_audit is not None
    assert claim_audit.logic_audit.logic_fact_export is not None
    assert "animal_evidence_does_not_entail_human_claim" in (
        claim_audit.logic_audit.rules_triggered
    )
    assert claim_audit.verdict == "overclaimed"
    assert result.recommended_action == "revise"


@pytest.mark.asyncio
async def test_answer_with_audit_records_logic_audit_trace(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_papers=5,
                use_llm_claim_logic=True,
                export_logic_facts=True,
            )
        )
    finally:
        await service.aclose()

    audit_step = next(step for step in result.trace if step.step == "audit")
    logic_trace = audit_step.metadata["logic_audit"]
    assert isinstance(logic_trace, dict)
    assert logic_trace["enabled"] is True
    assert logic_trace["claim_count"] >= 1
    assert logic_trace["fact_export_count"] >= 1


@pytest.mark.asyncio
async def test_clinical_answer_with_audit_skips_claim_logic(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What dose should my mother take for Alzheimer disease?",
                source="mock",
                use_llm_claim_logic=True,
                export_logic_facts=True,
            )
        )
    finally:
        await service.aclose()

    audit_step = next(step for step in result.trace if step.step == "audit")
    logic_trace = audit_step.metadata["logic_audit"]
    assert isinstance(logic_trace, dict)
    assert logic_trace["enabled"] is False
    assert logic_trace["claim_count"] == 0
    assert logic_trace["fact_export_count"] == 0
    assert result.final_action == "refuse"
    assert not result.answer_result.citations
    assert not result.answer_result.evidence_summary
    assert all(item.logic_audit is None for item in result.audit.claim_audits)
