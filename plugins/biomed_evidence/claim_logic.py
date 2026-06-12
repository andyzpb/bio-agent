from __future__ import annotations

import hashlib
import re
from plugins.biomed_evidence.claim_logic_export import export_logic_facts
from plugins.biomed_evidence.claim_logic_rules import audit_logical_support
from plugins.biomed_evidence.schemas import (
    AtomicClaim,
    BiomedicalEntity,
    EvidenceItem,
    EvidenceStrength,
    LogicAuditResult,
    LogicClaimStrength,
    LogicModality,
    LogicParserMode,
    LogicPolarity,
    LogicPopulation,
    LogicPredicate,
    LogicStudyDesign,
    LogicalClaimFrame,
    LogicalEntity,
    LogicalEvidenceFrame,
)


def parse_logical_claim(
    claim: AtomicClaim,
    *,
    parser_mode: LogicParserMode = "deterministic",
    parser_model: str | None = None,
    parser_prompt_hash: str | None = None,
) -> LogicalClaimFrame:
    text = claim.text
    predicate = _predicate(text)
    return LogicalClaimFrame(
        claim_id=claim.claim_id,
        claim_text=text,
        subject=_logical_subject(text),
        predicate=predicate,
        object=_logical_object(text),
        polarity=_polarity(text),
        modality=_claim_modality(text, predicate),
        population=_population(text),
        claim_strength=_claim_strength(text, predicate, claim.claim_type),
        scope=_scope_terms(text),
        qualifiers=_qualifiers(text),
        hedging=_is_hedged(text),
        source_spans=_source_spans(text),
        parser_mode=parser_mode,
        parser_model=parser_model,
        parser_prompt_hash=parser_prompt_hash,
        parser_warnings=(
            []
            if parser_mode != "fallback"
            else ["LLM claim parser unavailable; deterministic fallback used."]
        ),
    )


def parse_logical_evidence(
    evidence: EvidenceItem,
    *,
    parser_mode: LogicParserMode = "deterministic",
    parser_model: str | None = None,
    parser_prompt_hash: str | None = None,
) -> LogicalEvidenceFrame:
    text = _evidence_text(evidence)
    predicate = _predicate(text)
    strength = _evidence_strength(evidence)
    return LogicalEvidenceFrame(
        evidence_id=evidence.evidence_id,
        paper_id=evidence.paper_id,
        evidence_text=text,
        subject=_entity_from_evidence(
            evidence, fallback_text=text, prefer_subject=True
        ),
        predicate=predicate,
        object=_entity_from_evidence(
            evidence, fallback_text=text, prefer_subject=False
        ),
        polarity=_evidence_polarity(evidence, text),
        modality=_evidence_modality(evidence, text),
        population=_evidence_population(evidence, text),
        model_system=_model_system(evidence, text),
        study_design=_study_design(evidence, text, strength),
        evidence_strength=strength,
        limitations=evidence.limitations,
        source_spans=_source_spans(text),
        parser_mode=parser_mode,
        parser_model=parser_model,
        parser_prompt_hash=parser_prompt_hash,
        parser_warnings=(
            []
            if parser_mode != "fallback"
            else ["LLM evidence parser unavailable; deterministic fallback used."]
        ),
    )


def audit_claim_logic(
    claim: AtomicClaim,
    evidence_items: list[EvidenceItem],
    *,
    parser_mode: LogicParserMode = "deterministic",
    export_facts: bool = False,
) -> LogicAuditResult:
    claim_frame = parse_logical_claim(claim, parser_mode=parser_mode)
    evidence_frames = [
        parse_logical_evidence(item, parser_mode=parser_mode) for item in evidence_items
    ]
    result = audit_logical_support(claim_frame, evidence_frames)
    if export_facts:
        result = result.model_copy(
            update={
                "logic_fact_export": export_logic_facts(
                    claim_frame,
                    evidence_frames,
                    result,
                    format="text",
                )
            }
        )
    return result


def prompt_hash(payload: object) -> str:
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()[:16]


def _predicate(text: str) -> LogicPredicate:
    lowered = text.lower()
    if re.search(r"\b(no effect|not associated|does not affect|reduced)\b", lowered):
        return "has_no_effect"
    if re.search(r"\b(caus\w*|driv\w*|lead(?:s)? to|result(?:s)? in)\b", lowered):
        return "causes_or_drives"
    if re.search(r"\b(predict|prognos)\w*\b", lowered):
        return "predicts"
    if re.search(r"\b(treat|therapy|therapeutic|dose|dosing)\w*\b", lowered):
        return "treats"
    if re.search(r"\b(diagnos|diagnostic)\w*\b", lowered):
        return "diagnoses"
    if re.search(r"\b(marker|biomarker)\b", lowered):
        return "is_marker_of"
    if re.search(r"\b(mechanism|mechanistic|pathway|mediates?)\b", lowered):
        return "is_mechanistically_linked_to"
    if re.search(r"\b(correlat|correlation)\w*\b", lowered):
        return "correlates_with"
    if re.search(r"\b(associated|association|linked|links|relat(?:ed|ion))\b", lowered):
        return "associated_with"
    if re.search(r"\b(increase|elevat|enrich)\w*\b", lowered):
        return "increases"
    if re.search(r"\b(decrease|reduce|lower)\w*\b", lowered):
        return "decreases"
    if re.search(r"\b(inconclusive|uncertain|mixed)\b", lowered):
        return "uncertain_or_inconclusive"
    return "unspecified"


def _claim_strength(
    text: str,
    predicate: LogicPredicate,
    claim_type: str,
) -> LogicClaimStrength:
    lowered = text.lower()
    if (
        predicate in {"causes_or_drives", "is_required_for", "is_sufficient_for"}
        or claim_type == "causal"
    ):
        return "causal"
    if predicate == "treats" or claim_type == "treatment_recommendation":
        return "treatment"
    if predicate == "diagnoses":
        return "diagnostic"
    if predicate == "predicts":
        return "prognostic"
    if "clinical" in lowered or claim_type == "clinical_implication":
        return "clinical"
    if (
        predicate == "is_mechanistically_linked_to"
        or claim_type == "mechanistic_hypothesis"
    ):
        return "mechanistic"
    if (
        predicate in {"associated_with", "correlates_with", "is_marker_of"}
        or claim_type == "association"
    ):
        return "association"
    if claim_type == "uncertainty":
        return "uncertainty"
    if claim_type == "background":
        return "background"
    return "unspecified"


def _claim_modality(text: str, predicate: LogicPredicate) -> LogicModality:
    lowered = text.lower()
    if re.search(r"\b(proves?|establish(?:es|ed)?|definitive|conclusive)\b", lowered):
        return "definitive"
    if predicate in {"causes_or_drives", "treats", "diagnoses", "predicts"}:
        return "strong"
    if _is_hedged(text):
        return "suggestive"
    if re.search(r"\b(associated|correlated|linked)\b", lowered):
        return "moderate"
    return "unspecified"


def _evidence_modality(evidence: EvidenceItem, text: str) -> LogicModality:
    lowered = " ".join([text, " ".join(evidence.limitations)]).lower()
    if evidence.evidence_direction == "inconclusive" or re.search(
        r"\b(inconclusive|not significant|mixed)\b", lowered
    ):
        return "inconclusive"
    if evidence.confidence == "low" or re.search(
        r"\b(may|might|suggest|limited|small)\b", lowered
    ):
        return "suggestive"
    if evidence.confidence == "high":
        return "strong"
    return "moderate"


def _polarity(text: str) -> LogicPolarity:
    lowered = text.lower()
    if re.search(r"\b(no|not|neither|failed to|did not)\b", lowered):
        return "negative"
    if re.search(r"\b(mixed|inconclusive|uncertain)\b", lowered):
        return "uncertain"
    return "positive"


def _evidence_polarity(evidence: EvidenceItem, text: str) -> LogicPolarity:
    if evidence.evidence_direction == "contradicts":
        return "negative"
    if evidence.evidence_direction == "inconclusive":
        return "uncertain"
    return _polarity(text)


def _population(text: str) -> LogicPopulation:
    lowered = text.lower()
    if re.search(r"\b(mouse|mice|rat|zebrafish|animal|murine)\b", lowered):
        return "animal"
    if re.search(r"\b(in vitro|cell culture|organoid|cell line)\b", lowered):
        return "in_vitro"
    if re.search(
        r"\b(humans?|patients?|cohort|clinical|post-?mortem|csf|donors?)\b", lowered
    ):
        return "human"
    return "unspecified"


def _evidence_population(evidence: EvidenceItem, text: str) -> LogicPopulation:
    joined = " ".join(
        [text, " ".join(evidence.methods), " ".join(evidence.limitations)]
    )
    population = _population(joined)
    if population != "unspecified":
        return population
    if _evidence_strength(evidence) == "animal_or_in_vitro":
        return "animal"
    if _evidence_strength(evidence) in {
        "observational",
        "longitudinal",
        "interventional",
    }:
        return "human"
    return "unspecified"


def _study_design(
    evidence: EvidenceItem,
    text: str,
    strength: EvidenceStrength,
) -> LogicStudyDesign:
    lowered = " ".join(
        [text, " ".join(evidence.methods), " ".join(evidence.limitations)]
    ).lower()
    if "random" in lowered:
        return "randomized_trial"
    if "intervention" in lowered or "trial" in lowered:
        return "interventional"
    if "longitudinal" in lowered:
        return "longitudinal"
    if "case-control" in lowered or "case control" in lowered:
        return "case_control"
    if "cohort" in lowered:
        return "cohort"
    if "cross-sectional" in lowered or "cross sectional" in lowered:
        return "cross_sectional"
    if "meta-analysis" in lowered or "meta analysis" in lowered:
        return "meta_analysis"
    if "review" in lowered:
        return "review"
    if (
        "in vitro" in lowered
        or "cell culture" in lowered
        or strength == "animal_or_in_vitro"
    ):
        return "in_vitro" if "in vitro" in lowered else "preclinical"
    if strength == "abstract_only":
        return "abstract_only"
    if strength == "observational":
        return "observational"
    if strength == "longitudinal":
        return "longitudinal"
    if strength == "interventional":
        return "interventional"
    return "unspecified"


def _evidence_strength(evidence: EvidenceItem) -> EvidenceStrength:
    text = _evidence_text(evidence).lower()
    methods = " ".join(evidence.methods).lower()
    limitations = " ".join(evidence.limitations).lower()
    combined = " ".join([text, methods, limitations])
    if "abstract" in limitations:
        return "abstract_only"
    if re.search(
        r"\b(mouse|mice|murine|rat|animal|in vitro|cell culture|organoid)\b", combined
    ):
        return "animal_or_in_vitro"
    if re.search(r"\b(randomized|trial|intervention)\b", combined):
        return "interventional"
    if "longitudinal" in combined:
        return "longitudinal"
    if re.search(
        r"\b(cohort|observational|cross-sectional|case-control|post-mortem)\b", combined
    ):
        return "observational"
    if re.search(r"\b(review|guideline|meta-analysis)\b", combined):
        return "review_or_guideline"
    return "not_assessed"


def _logical_subject(text: str) -> LogicalEntity:
    subject = _split_relation(text)[0]
    return LogicalEntity(
        text=subject or "unspecified",
        entity_type=_entity_type(subject),
        source_span=subject or None,
    )


def _logical_object(text: str) -> LogicalEntity:
    obj = _split_relation(text)[1]
    return LogicalEntity(
        text=obj or "unspecified",
        entity_type=_entity_type(obj),
        source_span=obj or None,
    )


def _entity_from_evidence(
    evidence: EvidenceItem,
    *,
    fallback_text: str,
    prefer_subject: bool,
) -> LogicalEntity:
    if evidence.entities:
        index = 0 if prefer_subject else min(1, len(evidence.entities) - 1)
        entity = evidence.entities[index]
        return _entity_from_biomedical_entity(entity)
    return (
        _logical_subject(fallback_text)
        if prefer_subject
        else _logical_object(fallback_text)
    )


def _entity_from_biomedical_entity(entity: BiomedicalEntity) -> LogicalEntity:
    return LogicalEntity(
        text=entity.name,
        entity_type=entity.entity_type,
        normalized_id=entity.normalized_id,
        source_span=entity.name,
    )


def _split_relation(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"\[[^\]]+\]", "", text).strip(" .")
    patterns = [
        r"\bcaus\w*\b",
        r"\bdriv\w*\b",
        r"\bassociated with\b",
        r"\bcorrelat\w* with\b",
        r"\blink\w* to\b",
        r"\bpredict\w*\b",
        r"\btreat\w*\b",
        r"\bdiagnos\w*\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            return (
                cleaned[: match.start()].strip(" ,;:-") or "unspecified",
                cleaned[match.end() :].strip(" ,;:-") or "unspecified",
            )
    words = cleaned.split()
    if len(words) <= 6:
        return cleaned or "unspecified", "unspecified"
    return " ".join(words[: max(2, len(words) // 2)]), " ".join(
        words[max(2, len(words) // 2) :]
    )


def _entity_type(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(alzheimer|disease|pathology|progression)\b", lowered):
        return "disease_process"
    if re.search(r"\b(microglia|astrocyte|neuron|cell)\b", lowered):
        return "cell_type"
    if re.search(r"\b(activation|inflammation|pathway|process)\b", lowered):
        return "biological_process"
    if re.search(r"\b(marker|biomarker|protein)\b", lowered):
        return "biomarker"
    return "unspecified"


def _model_system(evidence: EvidenceItem, text: str) -> str | None:
    lowered = " ".join(
        [text, " ".join(evidence.methods), " ".join(evidence.limitations)]
    ).lower()
    if "mouse" in lowered or "mice" in lowered or "murine" in lowered:
        return "mouse"
    if "rat" in lowered:
        return "rat"
    if "organoid" in lowered:
        return "organoid"
    if "cell culture" in lowered:
        return "cell_culture"
    return None


def _scope_terms(text: str) -> list[str]:
    terms: list[str] = []
    lowered = text.lower()
    for label, pattern in {
        "human": r"\b(human|patients?|clinical)\b",
        "animal": r"\b(mouse|mice|animal|murine|rat)\b",
        "in_vitro": r"\b(in vitro|cell culture|organoid)\b",
        "disease_progression": r"\bprogression\b",
        "treatment": r"\b(treat|therapy|dose)\w*\b",
        "diagnostic": r"\b(diagnos|diagnostic)\w*\b",
    }.items():
        if re.search(pattern, lowered):
            terms.append(label)
    return terms


def _qualifiers(text: str) -> list[str]:
    qualifiers: list[str] = []
    lowered = text.lower()
    if _is_hedged(text):
        qualifiers.append("hedged")
    if "limited" in lowered:
        qualifiers.append("limited")
    if "adjust" in lowered:
        qualifiers.append("adjusted")
    return qualifiers


def _is_hedged(text: str) -> bool:
    return bool(
        re.search(
            r"\b(may|might|could|suggests?|consistent with|associated with|linked to|possible|potential)\b",
            text.lower(),
        )
    )


def _source_spans(text: str) -> list[str]:
    spans = [
        span.strip(" .,:;")
        for span in re.split(r"\b(?:and|but|however)\b", text)
        if span.strip(" .,:;")
    ]
    return spans[:4] or [text]


def _evidence_text(evidence: EvidenceItem) -> str:
    return evidence.evidence_span or evidence.finding or evidence.claim
