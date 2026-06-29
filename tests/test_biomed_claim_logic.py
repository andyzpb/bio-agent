from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from plugins.biomed_evidence import service as biomed_service_module
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


COFACTOR_TEXT = (
    "Viral load and viral type are the main cofactors for progression from "
    "infection to cervical intraepithelial lesions and cancer"
)
AZITHROMYCIN_CLAIM = (
    "When azithromycin was added to standard of care "
    "(which included hydroxychloroquine), clinical outcomes did not improve."
)
AZITHROMYCIN_EVIDENCE = (
    "In patients with severe COVID-19, adding azithromycin to standard of care "
    "treatment (which included hydroxychloroquine) did not improve clinical "
    "outcomes."
)
RECOVERY_CLAIM = (
    "The RECOVERY trial demonstrated that hydroxychloroquine did not reduce "
    "28-day mortality in hospitalized patients."
)
RECOVERY_EVIDENCE = (
    "Among patients hospitalized with Covid-19, those who received "
    "hydroxychloroquine did not have a lower incidence of death at 28 days "
    "than those who received usual care."
)
IN_VITRO_MECHANISM_TEXT = (
    "Cigarette smoke and e-cigs increase proinflammatory cytokine expression "
    "in cells and affect protein regulation, leading to an increased lung "
    "cancer risk."
)


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


def _cofactor_evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_cofactor",
        paper_id="PMID:28964706",
        claim=COFACTOR_TEXT,
        finding=COFACTOR_TEXT,
        evidence_direction="supports",
        entities=[],
        methods=["review"],
        limitations=["Review-level evidence."],
        confidence="medium",
        evidence_span=COFACTOR_TEXT,
    )


def _azithromycin_evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_azithro",
        paper_id="32896292",
        claim=AZITHROMYCIN_EVIDENCE,
        finding=AZITHROMYCIN_EVIDENCE,
        evidence_direction="inconclusive",
        entities=[],
        methods=["randomized trial"],
        limitations=["Trial-level evidence."],
        confidence="medium",
        evidence_span=AZITHROMYCIN_EVIDENCE,
    )


def _recovery_evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_recovery",
        paper_id="33031652",
        claim=RECOVERY_EVIDENCE,
        finding=RECOVERY_EVIDENCE,
        evidence_direction="supports",
        entities=[],
        methods=["randomized trial"],
        limitations=["Trial-level evidence."],
        confidence="high",
        evidence_span=RECOVERY_EVIDENCE,
    )


def _in_vitro_mechanism_evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_in_vitro",
        paper_id="37458647",
        claim=IN_VITRO_MECHANISM_TEXT,
        finding=IN_VITRO_MECHANISM_TEXT,
        evidence_direction="supports",
        entities=[],
        methods=["in vitro cell model"],
        limitations=["Abstract-level cell-model evidence."],
        confidence="medium",
        evidence_span=IN_VITRO_MECHANISM_TEXT,
        source_scope="abstract",
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


class _ChunkLimitedLogicParserProvider(_FakeLogicParserProvider):
    def __init__(self, *, max_evidence_items: int, max_claims: int = 99) -> None:
        super().__init__()
        self.max_evidence_items = max_evidence_items
        self.max_claims = max_claims
        self.extra_claim_in_evidence_chunks = False
        self.evidence_batch_sizes: list[int] = []
        self.claim_batch_sizes: list[int] = []

    async def chat(self, **kwargs: Any) -> _FakeLogicResponse:
        messages = kwargs["messages"]
        payload = json.loads(str(messages[-1]["content"]))
        self.claim_batch_sizes.append(len(payload["claims"]))
        self.evidence_batch_sizes.append(len(payload["evidence_items"]))
        if len(payload["claims"]) > self.max_claims:
            self.calls += 1
            return _FakeLogicResponse('{"claim_frames": [{"claim_id": "truncated')
        if len(payload["evidence_items"]) > self.max_evidence_items:
            self.calls += 1
            return _FakeLogicResponse('{"claim_frames": [{"claim_id": "truncated')
        response = _logic_parser_payload_response(payload)
        if self.extra_claim_in_evidence_chunks and not payload["claims"]:
            response["claim_frames"] = [
                {
                    "claim_id": "extra-claim",
                    "claim_text": "extra claim",
                }
            ]
        self.calls += 1
        return _FakeLogicResponse(json.dumps(response))


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


def test_deterministic_parser_maps_cofactor_progression_to_contribution() -> None:
    claim = AtomicClaim(
        claim_id="claim_cofactor",
        text=COFACTOR_TEXT,
        claim_type="background",
    )

    result = audit_claim_logic(claim, [_cofactor_evidence()], export_facts=True)

    assert result.claim_frame.predicate == "contributes_to"
    assert result.claim_frame.claim_strength == "contribution"
    assert "cofactor" in result.claim_frame.qualifiers
    assert result.evidence_frames[0].predicate == "contributes_to"
    assert result.logic_verdict in {"entailed", "partially_entailed"}
    assert "association_does_not_entail_causation" not in result.rules_triggered
    assert result.logic_fact_export is not None
    assert "claim_predicate(claim_cofactor, contributes_to)." in (
        result.logic_fact_export.text or ""
    )


def test_contribution_evidence_partially_supports_causal_claim() -> None:
    claim = AtomicClaim(
        claim_id="claim_causal",
        text=(
            "Viral load and viral type drive progression from infection to "
            "cervical intraepithelial lesions and cancer"
        ),
        claim_type="causal",
    )

    result = audit_claim_logic(claim, [_cofactor_evidence()])

    assert result.claim_frame.predicate == "causes_or_drives"
    assert result.evidence_frames[0].predicate == "contributes_to"
    assert result.logic_verdict == "partially_entailed"
    assert "contribution_partially_entails_causation" in result.rules_triggered


def test_contribution_evidence_does_not_support_sufficient_cause_claim() -> None:
    claim = AtomicClaim(
        claim_id="claim_sufficient",
        text=(
            "Viral load and viral type are sufficient causes of progression from "
            "infection to cervical intraepithelial lesions and cancer"
        ),
        claim_type="causal",
    )

    result = audit_claim_logic(claim, [_cofactor_evidence()])

    assert result.logic_verdict == "overclaimed"
    assert "contribution_does_not_entail_sufficient_causation" in (
        result.rules_triggered
    )


def test_llm_logic_parser_normalizes_cofactor_predicate_drift() -> None:
    raw_claim = {
        "claim_id": "claim_cofactor",
        "claim_text": COFACTOR_TEXT,
        "subject": {"text": "viral load and viral type", "entity_type": "biological_process"},
        "predicate": "causes_or_drives",
        "object": {"text": "progression", "entity_type": "disease"},
        "polarity": "positive",
        "modality": "definitive",
        "claim_strength": "causal",
        "qualifiers": [],
    }
    raw_evidence = {
        "evidence_id": "ev_cofactor",
        "paper_id": "PMID:28964706",
        "evidence_text": COFACTOR_TEXT,
        "subject": {"text": "viral load and viral type", "entity_type": "biological_process"},
        "predicate": "associated_with",
        "object": {"text": "progression", "entity_type": "disease"},
        "polarity": "positive",
        "modality": "definitive",
        "population": "human",
        "study_design": "review",
        "evidence_strength": "review_or_guideline",
    }

    claim_frames = biomed_service_module._logic_claim_frames_from_llm(
        [raw_claim],
        claims=[
            AtomicClaim(
                claim_id="claim_cofactor",
                text=COFACTOR_TEXT,
                claim_type="background",
            )
        ],
        model="fake",
        prompt_hash="hash",
    )
    evidence_frames = biomed_service_module._logic_evidence_frames_from_llm(
        [raw_evidence],
        evidence_items=[_cofactor_evidence()],
        model="fake",
        prompt_hash="hash",
    )

    claim_frame = claim_frames["claim_cofactor"]
    evidence_frame = evidence_frames["ev_cofactor"]
    assert claim_frame.predicate == "contributes_to"
    assert claim_frame.claim_strength == "contribution"
    assert "cofactor" in claim_frame.qualifiers
    assert any("contributes_to" in warning for warning in claim_frame.parser_warnings)
    assert evidence_frame.predicate == "contributes_to"
    assert any(
        "contributes_to" in warning for warning in evidence_frame.parser_warnings
    )


def test_deterministic_parser_maps_negative_trial_finding_to_no_observed_benefit() -> None:
    claim = AtomicClaim(
        claim_id="claim_azithro",
        text=AZITHROMYCIN_CLAIM,
        claim_type="clinical_implication",
        cited_paper_ids=["32896292"],
    )

    result = audit_claim_logic(claim, [_azithromycin_evidence()])

    assert result.claim_frame.predicate == "no_observed_benefit"
    assert result.claim_frame.modality == "moderate"
    assert "comparator_scoped" in result.claim_frame.qualifiers
    assert "outcome_scoped" in result.claim_frame.qualifiers
    assert result.evidence_frames[0].predicate == "no_observed_benefit"
    assert result.evidence_frames[0].modality == "moderate"
    assert result.logic_verdict == "entailed"


def test_llm_logic_parser_normalizes_negative_trial_finding_drift() -> None:
    raw_claim = {
        "claim_id": "claim_azithro",
        "claim_text": AZITHROMYCIN_CLAIM,
        "subject": {"text": "azithromycin", "entity_type": "drug"},
        "predicate": "has_no_effect",
        "object": {"text": "clinical outcomes", "entity_type": "disease"},
        "polarity": "negative",
        "modality": "definitive",
        "population": "human",
        "claim_strength": "treatment",
        "qualifiers": [],
    }
    raw_evidence = {
        "evidence_id": "ev_azithro",
        "paper_id": "32896292",
        "evidence_text": AZITHROMYCIN_EVIDENCE,
        "subject": {"text": "azithromycin", "entity_type": "drug"},
        "predicate": "uncertain_or_inconclusive",
        "object": {"text": "clinical outcomes", "entity_type": "disease"},
        "polarity": "negative",
        "modality": "inconclusive",
        "population": "human",
        "study_design": "randomized_trial",
        "evidence_strength": "interventional",
    }

    claim_frames = biomed_service_module._logic_claim_frames_from_llm(
        [raw_claim],
        claims=[
            AtomicClaim(
                claim_id="claim_azithro",
                text=AZITHROMYCIN_CLAIM,
                claim_type="clinical_implication",
            )
        ],
        model="fake",
        prompt_hash="hash",
    )
    evidence_frames = biomed_service_module._logic_evidence_frames_from_llm(
        [raw_evidence],
        evidence_items=[_azithromycin_evidence()],
        model="fake",
        prompt_hash="hash",
    )

    claim_frame = claim_frames["claim_azithro"]
    evidence_frame = evidence_frames["ev_azithro"]
    assert claim_frame.predicate == "no_observed_benefit"
    assert claim_frame.modality == "moderate"
    assert "outcome_scoped" in claim_frame.qualifiers
    assert any(
        "no_observed_benefit" in warning for warning in claim_frame.parser_warnings
    )
    assert evidence_frame.predicate == "no_observed_benefit"
    assert evidence_frame.modality == "moderate"
    assert any(
        "no_observed_benefit" in warning for warning in evidence_frame.parser_warnings
    )


def test_aligned_negative_trial_finding_is_not_overclaimed_from_modality_mismatch() -> None:
    answer = f"{AZITHROMYCIN_CLAIM} [32896292]"
    evidence = _azithromycin_evidence()
    base = validate_citation_support(
        answer=answer,
        citations=[_citation("32896292")],
        evidence_items=[evidence],
    )
    claim = base.claims[0]
    claim_frames = biomed_service_module._logic_claim_frames_from_llm(
        [
            {
                "claim_id": claim.claim_id,
                "claim_text": AZITHROMYCIN_CLAIM,
                "subject": {"text": "azithromycin", "entity_type": "drug"},
                "predicate": "has_no_effect",
                "object": {"text": "clinical outcomes", "entity_type": "disease"},
                "polarity": "negative",
                "modality": "definitive",
                "population": "human",
                "claim_strength": "treatment",
            }
        ],
        claims=[claim],
        model="fake",
        prompt_hash="hash",
    )
    evidence_frames = biomed_service_module._logic_evidence_frames_from_llm(
        [
            {
                "evidence_id": evidence.evidence_id,
                "paper_id": evidence.paper_id,
                "evidence_text": AZITHROMYCIN_EVIDENCE,
                "subject": {"text": "azithromycin", "entity_type": "drug"},
                "predicate": "uncertain_or_inconclusive",
                "object": {"text": "clinical outcomes", "entity_type": "disease"},
                "polarity": "negative",
                "modality": "inconclusive",
                "population": "human",
                "study_design": "randomized_trial",
                "evidence_strength": "interventional",
            }
        ],
        evidence_items=[evidence],
        model="fake",
        prompt_hash="hash",
    )

    result = validate_citation_support(
        answer=answer,
        citations=[_citation("32896292")],
        evidence_items=[evidence],
        use_llm_claim_logic=True,
        logic_claim_frames=claim_frames,
        logic_evidence_frames=evidence_frames,
    )

    audit = result.claim_audits[0]
    assert audit.verdict == "partial_support"
    assert audit.logic_audit is not None
    assert audit.logic_audit.logic_verdict == "entailed"


def test_trial_scoped_no_observed_benefit_allows_moderate_evidence() -> None:
    answer = f"{RECOVERY_CLAIM} [33031652]"
    evidence = _recovery_evidence()
    base = validate_citation_support(
        answer=answer,
        citations=[_citation("33031652")],
        evidence_items=[evidence],
    )
    claim = base.claims[0]
    claim_frames = biomed_service_module._logic_claim_frames_from_llm(
        [
            {
                "claim_id": claim.claim_id,
                "claim_text": RECOVERY_CLAIM,
                "subject": {"text": "hydroxychloroquine", "entity_type": "drug"},
                "predicate": "no_observed_benefit",
                "object": {"text": "28-day mortality", "entity_type": "disease"},
                "polarity": "negative",
                "modality": "definitive",
                "population": "human",
                "claim_strength": "background",
            }
        ],
        claims=[claim],
        model="fake",
        prompt_hash="hash",
    )
    evidence_frames = biomed_service_module._logic_evidence_frames_from_llm(
        [
            {
                "evidence_id": evidence.evidence_id,
                "paper_id": evidence.paper_id,
                "evidence_text": RECOVERY_EVIDENCE,
                "subject": {"text": "hydroxychloroquine", "entity_type": "drug"},
                "predicate": "no_observed_benefit",
                "object": {"text": "28-day mortality", "entity_type": "disease"},
                "polarity": "negative",
                "modality": "moderate",
                "population": "human",
                "study_design": "randomized_trial",
                "evidence_strength": "interventional",
            }
        ],
        evidence_items=[evidence],
        model="fake",
        prompt_hash="hash",
    )

    result = validate_citation_support(
        answer=answer,
        citations=[_citation("33031652")],
        evidence_items=[evidence],
        use_llm_claim_logic=True,
        logic_claim_frames=claim_frames,
        logic_evidence_frames=evidence_frames,
    )

    audit = result.claim_audits[0]
    assert audit.verdict == "supported"
    assert audit.logic_audit is not None
    assert audit.logic_audit.logic_verdict == "entailed"
    assert "weak_evidence_does_not_support_definitive_claim" not in (
        audit.logic_audit.rules_triggered
    )


def test_trial_no_observed_benefit_only_partially_supports_universal_no_effect() -> None:
    claim = AtomicClaim(
        claim_id="claim_no_effect",
        text="Azithromycin has no effect on COVID-19 clinical outcomes.",
        claim_type="clinical_implication",
        cited_paper_ids=["32896292"],
    )

    result = audit_claim_logic(claim, [_azithromycin_evidence()])

    assert result.claim_frame.predicate == "has_no_effect"
    assert result.evidence_frames[0].predicate == "no_observed_benefit"
    assert result.logic_verdict == "partially_entailed"
    assert "trial_no_observed_benefit_partially_entails_no_effect" in (
        result.rules_triggered
    )


def test_abstract_in_vitro_text_match_is_scope_limited_not_pure_overclaim() -> None:
    answer = f"{IN_VITRO_MECHANISM_TEXT} [37458647]"
    evidence = _in_vitro_mechanism_evidence()
    base = validate_citation_support(
        answer=answer,
        citations=[_citation("37458647")],
        evidence_items=[evidence],
    )
    claim = base.claims[0]
    claim_frames = biomed_service_module._logic_claim_frames_from_llm(
        [
            {
                "claim_id": claim.claim_id,
                "claim_text": IN_VITRO_MECHANISM_TEXT,
                "subject": {"text": "cigarette smoke and e-cigs", "entity_type": "other"},
                "predicate": "causes_or_drives",
                "object": {"text": "lung cancer risk", "entity_type": "disease"},
                "polarity": "positive",
                "modality": "strong",
                "population": "human",
                "claim_strength": "mechanistic",
            }
        ],
        claims=[claim],
        model="fake",
        prompt_hash="hash",
    )
    evidence_frames = biomed_service_module._logic_evidence_frames_from_llm(
        [
            {
                "evidence_id": evidence.evidence_id,
                "paper_id": evidence.paper_id,
                "evidence_text": IN_VITRO_MECHANISM_TEXT,
                "subject": {"text": "cigarette smoke and e-cigs", "entity_type": "other"},
                "predicate": "causes_or_drives",
                "object": {"text": "lung cancer risk", "entity_type": "disease"},
                "polarity": "positive",
                "modality": "definitive",
                "population": "in_vitro",
                "study_design": "in_vitro",
                "evidence_strength": "animal_or_in_vitro",
            }
        ],
        evidence_items=[evidence],
        model="fake",
        prompt_hash="hash",
    )

    result = validate_citation_support(
        answer=answer,
        citations=[_citation("37458647")],
        evidence_items=[evidence],
        use_llm_claim_logic=True,
        logic_claim_frames=claim_frames,
        logic_evidence_frames=evidence_frames,
    )

    audit = result.claim_audits[0]
    assert audit.verdict == "partial_support"
    assert audit.overclaim_reason is None
    assert any("Full text or scope review" in note for note in audit.reviewer_notes)
    assert audit.logic_audit is not None
    assert audit.logic_audit.logic_verdict == "overclaimed"
    assert "in_vitro_evidence_does_not_entail_human_claim" in audit.logic_audit.rules_triggered


def test_llm_logic_parser_normalizes_uncertain_modality() -> None:
    raw = {
        "claim_id": "claim_1",
        "claim_text": "Evidence is uncertain.",
        "subject": {"text": "evidence", "entity_type": "method"},
        "predicate": "uncertain_or_inconclusive",
        "object": {"text": "outcome", "entity_type": "disease"},
        "polarity": "uncertain",
        "modality": "uncertain",
    }

    frames = biomed_service_module._logic_claim_frames_from_llm(
        [raw],
        claims=[
            AtomicClaim(
                claim_id="claim_1",
                text="Evidence is uncertain.",
                claim_type="uncertainty",
            )
        ],
        model="fake",
        prompt_hash="hash",
    )

    frame = frames["claim_1"]
    assert frame.modality == "inconclusive"
    assert any("uncertain" in warning for warning in frame.parser_warnings)


def test_llm_logic_parser_normalizes_null_entities() -> None:
    evidence = _animal_association_evidence()
    raw = {
        "evidence_id": evidence.evidence_id,
        "paper_id": evidence.paper_id,
        "evidence_text": evidence.evidence_span,
        "subject": None,
        "predicate": "associated_with",
        "object": None,
        "population": "animal",
        "study_design": "preclinical",
        "evidence_strength": "animal_or_in_vitro",
    }

    frames = biomed_service_module._logic_evidence_frames_from_llm(
        [raw],
        evidence_items=[evidence],
        model="fake",
        prompt_hash="hash",
    )

    frame = frames[evidence.evidence_id]
    assert frame.parser_mode == "llm"
    assert frame.subject.text == "unspecified"
    assert frame.object.text == "unspecified"
    assert any("missing subject" in warning for warning in frame.parser_warnings)
    assert any("missing object" in warning for warning in frame.parser_warnings)


def test_llm_logic_parser_flags_human_trial_rat_model_system() -> None:
    evidence = EvidenceItem(
        evidence_id="ev_human",
        paper_id="PMID:1",
        claim="Hospitalized adults were enrolled in a randomized trial.",
        finding="Hospitalized adults were enrolled in a randomized trial.",
        evidence_direction="supports",
        entities=[],
        methods=["randomized trial"],
        limitations=[],
        confidence="high",
        evidence_span="Hospitalized adults were enrolled in a randomized trial.",
    )
    raw = {
        "evidence_id": "ev_human",
        "paper_id": "PMID:1",
        "evidence_text": evidence.evidence_span,
        "subject": {"text": "adults", "entity_type": "organism"},
        "predicate": "treats",
        "object": {"text": "COVID-19", "entity_type": "disease"},
        "population": "human",
        "model_system": "rat",
        "study_design": "randomized_trial",
    }

    frames = biomed_service_module._logic_evidence_frames_from_llm(
        [raw],
        evidence_items=[evidence],
        model="fake",
        prompt_hash="hash",
    )

    frame = frames["ev_human"]
    assert frame.model_system == "human cohort"
    assert any("model_system" in warning for warning in frame.parser_warnings)


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

    assert provider.calls >= 1
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
async def test_claim_logic_parser_splits_large_evidence_batches(
    tmp_path: Path,
) -> None:
    provider = _ChunkLimitedLogicParserProvider(max_evidence_items=2, max_claims=2)
    provider.extra_claim_in_evidence_chunks = True
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-logic-parser",
    )
    evidence = [
        _animal_association_evidence().model_copy(
            update={"evidence_id": f"ev_{index}", "paper_id": f"PMID:{index}"}
        )
        for index in range(17)
    ]
    answer = " ".join(
        (
            "Microglial activation increases Alzheimer's disease progression "
            f"in cohort {index}. [PMID:{index}]"
        )
        for index in range(11)
    )
    try:
        outcome = await service._llm_claim_logic_frames_or_fallback(
            answer=answer,
            citations=[_citation(f"PMID:{index}") for index in range(17)],
            evidence_items=evidence,
        )
    finally:
        await service.aclose()

    assert outcome.fallback_reason is None
    assert max(provider.claim_batch_sizes) <= 2
    assert max(provider.evidence_batch_sizes) <= 2
    assert sum(provider.claim_batch_sizes) == 11
    assert sum(provider.evidence_batch_sizes) == 17
    assert len(outcome.evidence_frames) == 17
    assert len(outcome.claim_frames) == 11


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

    assert provider.calls >= 1
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


@pytest.mark.asyncio
async def test_llm_claim_logic_chunk_parsing_runs_chunks_concurrently(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path, allow_live_pubmed_tools=True)
    active = 0
    peak = 0

    class FakeProvider:
        async def chat(self, **kwargs: object) -> object:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            messages = cast(list[dict[str, str]], kwargs["messages"])
            payload = json.loads(messages[1]["content"])
            entity = {"text": "smoking", "entity_type": "other"}
            claim_frames = [
                {
                    "claim_id": item["claim_id"],
                    "claim_text": item["claim_text"],
                    "subject": entity,
                    "predicate": "causes_or_drives",
                    "object": {"text": "lung cancer", "entity_type": "disease"},
                    "population": "human",
                    "modality": "strong",
                    "polarity": "positive",
                    "claim_strength": "background",
                    "hedging": False,
                }
                for item in payload.get("claims", [])
            ]
            evidence_frames = [
                {
                    "evidence_id": item["evidence_id"],
                    "paper_id": item["paper_id"],
                    "evidence_text": item["evidence_text"],
                    "subject": entity,
                    "predicate": "causes_or_drives",
                    "object": {"text": "lung cancer", "entity_type": "disease"},
                    "population": "human",
                    "modality": "strong",
                    "polarity": "positive",
                    "study_design": "review",
                    "evidence_strength": "review_or_guideline",
                }
                for item in payload.get("evidence_items", [])
            ]
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "claim_frames": claim_frames,
                        "evidence_frames": evidence_frames,
                    }
                )
            )

    service.revision_provider = FakeProvider()
    service.revision_model = "test-model"
    answer = "\n".join(
        f"Smoking causes lung cancer claim {index} [PMID-{index}]."
        for index in range(8)
    )
    evidence = [
        EvidenceItem(
            evidence_id=f"ev-{index}",
            paper_id=f"PMID-{index}",
            claim=f"Smoking causes lung cancer claim {index}.",
            evidence_direction="supports",
            finding="Smoking causes lung cancer.",
            confidence="medium",
            evidence_span="Smoking causes lung cancer.",
            source_scope="abstract",
        )
        for index in range(16)
    ]
    citations = [
        Citation(
            paper_id=f"PMID-{index}",
            title=f"Paper {index}",
            source="mock",
            cited_claim=f"Smoking causes lung cancer claim {index}.",
        )
        for index in range(8)
    ]
    try:
        outcome = await service._llm_claim_logic_frames_or_fallback(
            answer=answer,
            citations=citations,
            evidence_items=evidence,
        )
    finally:
        await service.aclose()

    assert outcome.fallback_reason is None
    assert peak > 1
