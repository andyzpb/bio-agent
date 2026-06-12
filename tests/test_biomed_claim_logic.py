from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


class _FakeLogicResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLogicParserProvider:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid
        self.calls = 0

    async def chat(self, **kwargs: Any) -> _FakeLogicResponse:
        self.calls += 1
        if self.invalid:
            return _FakeLogicResponse(
                json.dumps({"claim_frames": [{"claim_id": "broken"}]})
            )
        messages = kwargs["messages"]
        payload = json.loads(str(messages[-1]["content"]))
        return _FakeLogicResponse(json.dumps(_logic_parser_payload_response(payload)))


def _logic_parser_payload_response(payload: dict[str, Any]) -> dict[str, Any]:
    claim_frames: list[dict[str, Any]] = []
    for claim in payload["claims"]:
        text = str(claim["claim_text"])
        lowered = text.lower()
        predicate = (
            "causes_or_drives"
            if "driv" in lowered or "caus" in lowered
            else "increases" if "increas" in lowered else "associated_with"
        )
        claim_frames.append(
            {
                "claim_id": claim["claim_id"],
                "claim_text": text,
                "subject": {
                    "text": "microglial activation",
                    "entity_type": "biological_process",
                    "source_span": "microglial activation",
                },
                "predicate": predicate,
                "object": {
                    "text": "Alzheimer's disease progression",
                    "entity_type": "disease",
                    "source_span": "Alzheimer's disease progression",
                },
                "polarity": "positive",
                "modality": "strong" if predicate == "causes_or_drives" else "moderate",
                "population": "human" if "human" in lowered else "unspecified",
                "claim_strength": "causal" if predicate == "causes_or_drives" else "association",
                "scope": ["microglial activation", "Alzheimer's disease progression"],
                "qualifiers": [],
                "hedging": "may" in lowered or "suggest" in lowered,
                "source_spans": [text],
            }
        )
    evidence_frames: list[dict[str, Any]] = []
    for item in payload["evidence_items"]:
        evidence_text = str(item["evidence_text"])
        joined = " ".join(
            [
                evidence_text,
                " ".join(str(value) for value in item.get("methods", [])),
                " ".join(str(value) for value in item.get("limitations", [])),
            ]
        ).lower()
        animal = "mouse" in joined or "animal" in joined
        evidence_frames.append(
            {
                "evidence_id": item["evidence_id"],
                "paper_id": item["paper_id"],
                "evidence_text": evidence_text,
                "subject": {
                    "text": "microglial activation",
                    "entity_type": "biological_process",
                    "source_span": "Microglial activation",
                },
                "predicate": "associated_with",
                "object": {
                    "text": "Alzheimer's disease progression",
                    "entity_type": "disease",
                    "source_span": "Alzheimer",
                },
                "polarity": "positive",
                "modality": "moderate",
                "population": "animal" if animal else "human",
                "model_system": "mouse model" if animal else "human cohort",
                "study_design": "preclinical" if animal else "observational",
                "evidence_strength": (
                    "animal_or_in_vitro" if animal else "observational"
                ),
                "limitations": item.get("limitations", []),
                "source_spans": [evidence_text],
            }
        )
    return {"claim_frames": claim_frames, "evidence_frames": evidence_frames}


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
async def test_answer_with_audit_uses_provider_backed_logic_parser(
    tmp_path: Path,
) -> None:
    provider = _FakeLogicParserProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-logic-parser",
    )
    try:
        result = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_papers=3,
                use_llm_claim_logic=True,
                export_logic_facts=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    logic_audits = [
        item.logic_audit for item in result.audit.claim_audits if item.logic_audit
    ]
    assert logic_audits
    assert all(
        logic.claim_frame is not None and logic.claim_frame.parser_mode == "llm"
        for logic in logic_audits
    )
    assert all(
        logic.claim_frame is not None
        and logic.claim_frame.parser_model == "fake-logic-parser"
        for logic in logic_audits
    )
    assert any(logic.logic_fact_export is not None for logic in logic_audits)
    audit_step = next(step for step in result.trace if step.step == "audit")
    logic_trace = audit_step.metadata["logic_audit"]
    assert isinstance(logic_trace, dict)
    parser_modes = logic_trace.get("parser_mode_counts")
    assert isinstance(parser_modes, dict)
    assert parser_modes.get("llm", 0) >= len(logic_audits)
    assert logic_trace["parser_models"] == ["fake-logic-parser"]


@pytest.mark.asyncio
async def test_answer_with_audit_falls_back_when_logic_parser_schema_is_invalid(
    tmp_path: Path,
) -> None:
    provider = _FakeLogicParserProvider(invalid=True)
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-logic-parser",
    )
    try:
        result = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_papers=3,
                use_llm_claim_logic=True,
                export_logic_facts=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    logic_audits = [
        item.logic_audit for item in result.audit.claim_audits if item.logic_audit
    ]
    assert logic_audits
    assert all(
        logic.claim_frame is not None and logic.claim_frame.parser_mode == "fallback"
        for logic in logic_audits
    )
    assert any(
        "schema validation" in warning
        for logic in logic_audits
        for warning in logic.warnings
    )
    audit_step = next(step for step in result.trace if step.step == "audit")
    logic_trace = audit_step.metadata["logic_audit"]
    assert isinstance(logic_trace, dict)
    parser_modes = logic_trace.get("parser_mode_counts")
    assert isinstance(parser_modes, dict)
    assert parser_modes.get("fallback", 0) >= len(logic_audits)


@pytest.mark.asyncio
async def test_clinical_answer_with_audit_skips_claim_logic(tmp_path: Path) -> None:
    provider = _FakeLogicParserProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-logic-parser",
    )
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
    assert provider.calls == 0
