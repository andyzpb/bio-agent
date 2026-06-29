from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from plugins.biomed_evidence.schemas import (
    LogicAuditResult,
    LogicVerdict,
    LogicalClaimFrame,
    LogicalEvidenceFrame,
)


@dataclass(frozen=True)
class LogicRuleMetadata:
    rule_id: str
    category: str
    severity: str
    explanation: str


RULE_METADATA: dict[str, LogicRuleMetadata] = {
    "association_does_not_entail_causation": LogicRuleMetadata(
        rule_id="association_does_not_entail_causation",
        category="predicate_mismatch",
        severity="critical",
        explanation=(
            "The claim states a causal relation, but the evidence only reports "
            "association or correlation."
        ),
    ),
    "association_does_not_entail_contribution": LogicRuleMetadata(
        rule_id="association_does_not_entail_contribution",
        category="predicate_mismatch",
        severity="critical",
        explanation=(
            "The claim states a contributing cofactor or risk-factor relation, "
            "but the evidence only reports association or correlation."
        ),
    ),
    "contribution_partially_entails_causation": LogicRuleMetadata(
        rule_id="contribution_partially_entails_causation",
        category="predicate_boundary",
        severity="minor",
        explanation=(
            "Contribution or cofactor evidence supports a weaker causal-boundary "
            "claim, but not definitive independent causation."
        ),
    ),
    "contribution_does_not_entail_sufficient_causation": LogicRuleMetadata(
        rule_id="contribution_does_not_entail_sufficient_causation",
        category="predicate_mismatch",
        severity="critical",
        explanation=(
            "Contribution or cofactor evidence does not establish sufficient, "
            "necessary, independent, or definitive causation."
        ),
    ),
    "trial_no_observed_benefit_partially_entails_no_effect": LogicRuleMetadata(
        rule_id="trial_no_observed_benefit_partially_entails_no_effect",
        category="predicate_boundary",
        severity="minor",
        explanation=(
            "Trial-level no-observed-benefit evidence supports a weaker negative "
            "finding, but not a universal no-effect conclusion."
        ),
    ),
    "animal_evidence_does_not_entail_human_claim": LogicRuleMetadata(
        rule_id="animal_evidence_does_not_entail_human_claim",
        category="population_mismatch",
        severity="critical",
        explanation="Animal evidence does not by itself entail a human claim.",
    ),
    "in_vitro_evidence_does_not_entail_human_claim": LogicRuleMetadata(
        rule_id="in_vitro_evidence_does_not_entail_human_claim",
        category="population_mismatch",
        severity="critical",
        explanation="In-vitro evidence does not by itself entail a human claim.",
    ),
    "mechanism_does_not_entail_treatment": LogicRuleMetadata(
        rule_id="mechanism_does_not_entail_treatment",
        category="claim_strength_mismatch",
        severity="critical",
        explanation=(
            "Mechanistic or associative evidence does not entail treatment "
            "recommendations."
        ),
    ),
    "inconclusive_evidence_does_not_support_positive_claim": LogicRuleMetadata(
        rule_id="inconclusive_evidence_does_not_support_positive_claim",
        category="modality_mismatch",
        severity="major",
        explanation="Inconclusive evidence cannot support an unhedged positive claim.",
    ),
    "weak_evidence_does_not_support_definitive_claim": LogicRuleMetadata(
        rule_id="weak_evidence_does_not_support_definitive_claim",
        category="modality_mismatch",
        severity="major",
        explanation="Suggestive or moderate evidence does not support definitive wording.",
    ),
    "nonclinical_evidence_does_not_entail_clinical_claim": LogicRuleMetadata(
        rule_id="nonclinical_evidence_does_not_entail_clinical_claim",
        category="scope_mismatch",
        severity="critical",
        explanation="Preclinical or abstract-only evidence does not entail a clinical claim.",
    ),
    "biomarker_association_does_not_entail_diagnostic_utility": LogicRuleMetadata(
        rule_id="biomarker_association_does_not_entail_diagnostic_utility",
        category="predicate_mismatch",
        severity="critical",
        explanation="A biomarker association does not establish diagnostic utility.",
    ),
    "nonlongitudinal_evidence_does_not_entail_prognosis": LogicRuleMetadata(
        rule_id="nonlongitudinal_evidence_does_not_entail_prognosis",
        category="study_design_mismatch",
        severity="major",
        explanation="Prognostic claims require longitudinal or prognostic evidence.",
    ),
    "hedging_downgrades_overclaim_severity": LogicRuleMetadata(
        rule_id="hedging_downgrades_overclaim_severity",
        category="hedging",
        severity="minor",
        explanation="Explicit hedging can downgrade some overclaims to partial entailment.",
    ),
}


PREDICATE_NO_ENTAILMENTS: tuple[tuple[str, str, str], ...] = (
    (
        "associated_with",
        "contributes_to",
        "association_does_not_entail_contribution",
    ),
    (
        "correlates_with",
        "contributes_to",
        "association_does_not_entail_contribution",
    ),
    (
        "associated_with",
        "causes_or_drives",
        "association_does_not_entail_causation",
    ),
    (
        "correlates_with",
        "causes_or_drives",
        "association_does_not_entail_causation",
    ),
    (
        "is_marker_of",
        "diagnoses",
        "biomarker_association_does_not_entail_diagnostic_utility",
    ),
)


def audit_logical_support(
    claim_frame: LogicalClaimFrame,
    evidence_frames: list[LogicalEvidenceFrame],
) -> LogicAuditResult:
    if not evidence_frames:
        return LogicAuditResult(
            claim_id=claim_frame.claim_id,
            claim_frame=claim_frame,
            evidence_frames=[],
            logic_verdict="not_assessed",
            entailment_score=0.0,
            reason="Logical audit was not assessed because no aligned evidence frame was available.",
            warnings=[
                "Logical claim audit skipped because no aligned evidence was available."
            ],
        )

    rules: list[str] = []
    predicate_mismatches: list[dict[str, object]] = []
    scope_mismatches: list[dict[str, object]] = []
    modality_mismatches: list[dict[str, object]] = []
    population_mismatches: list[dict[str, object]] = []

    best = evidence_frames[0]
    for evidence in evidence_frames:
        for evidence_predicate, claim_predicate, rule_id in PREDICATE_NO_ENTAILMENTS:
            if (
                evidence.predicate == evidence_predicate
                and claim_frame.predicate == claim_predicate
            ):
                _add_rule(rules, rule_id)
                predicate_mismatches.append(
                    {
                        "axis": "predicate",
                        "claim_value": claim_frame.predicate,
                        "evidence_value": evidence.predicate,
                        "evidence_id": evidence.evidence_id,
                    }
                )
        if (
            evidence.predicate == "contributes_to"
            and claim_frame.predicate == "causes_or_drives"
        ):
            if _claims_sufficient_causation(claim_frame):
                _add_rule(
                    rules,
                    "contribution_does_not_entail_sufficient_causation",
                )
                predicate_mismatches.append(
                    {
                        "axis": "predicate",
                        "claim_value": claim_frame.predicate,
                        "evidence_value": evidence.predicate,
                        "evidence_id": evidence.evidence_id,
                    }
                )
            else:
                _add_rule(rules, "contribution_partially_entails_causation")

        if (
            evidence.predicate == "no_observed_benefit"
            and claim_frame.predicate == "has_no_effect"
        ):
            _add_rule(
                rules,
                "trial_no_observed_benefit_partially_entails_no_effect",
            )

        if claim_frame.population == "human" and evidence.population == "animal":
            _add_rule(rules, "animal_evidence_does_not_entail_human_claim")
            population_mismatches.append(
                _mismatch(
                    "population",
                    claim_frame.population,
                    evidence.population,
                    evidence.evidence_id,
                )
            )
        if claim_frame.population == "human" and evidence.population == "in_vitro":
            _add_rule(rules, "in_vitro_evidence_does_not_entail_human_claim")
            population_mismatches.append(
                _mismatch(
                    "population",
                    claim_frame.population,
                    evidence.population,
                    evidence.evidence_id,
                )
            )

        if (
            claim_frame.claim_strength == "treatment"
            and evidence.evidence_strength
            in {
                "animal_or_in_vitro",
                "observational",
                "not_assessed",
            }
        ):
            _add_rule(rules, "mechanism_does_not_entail_treatment")
            scope_mismatches.append(
                _mismatch(
                    "claim_strength",
                    claim_frame.claim_strength,
                    evidence.evidence_strength,
                    evidence.evidence_id,
                )
            )

        if (
            evidence.modality == "inconclusive"
            and claim_frame.polarity == "positive"
            and not claim_frame.hedging
        ):
            _add_rule(rules, "inconclusive_evidence_does_not_support_positive_claim")
            modality_mismatches.append(
                _mismatch(
                    "modality",
                    claim_frame.modality,
                    evidence.modality,
                    evidence.evidence_id,
                )
            )

        contribution_to_causation = (
            evidence.predicate == "contributes_to"
            and claim_frame.predicate == "causes_or_drives"
            and not _claims_sufficient_causation(claim_frame)
        )
        if (
            not contribution_to_causation
            and claim_frame.modality in {"strong", "definitive"}
            and evidence.modality
            in {
                "possible",
                "suggestive",
                "moderate",
                "inconclusive",
            }
        ):
            _add_rule(rules, "weak_evidence_does_not_support_definitive_claim")
            modality_mismatches.append(
                _mismatch(
                    "modality",
                    claim_frame.modality,
                    evidence.modality,
                    evidence.evidence_id,
                )
            )

        if claim_frame.claim_strength == "clinical" and evidence.study_design in {
            "preclinical",
            "in_vitro",
            "abstract_only",
        }:
            _add_rule(rules, "nonclinical_evidence_does_not_entail_clinical_claim")
            scope_mismatches.append(
                _mismatch(
                    "study_design",
                    claim_frame.claim_strength,
                    evidence.study_design,
                    evidence.evidence_id,
                )
            )

        if (
            claim_frame.claim_strength == "prognostic"
            and evidence.study_design
            not in {
                "longitudinal",
                "cohort",
                "interventional",
                "randomized_trial",
            }
        ):
            _add_rule(rules, "nonlongitudinal_evidence_does_not_entail_prognosis")
            scope_mismatches.append(
                _mismatch(
                    "study_design",
                    claim_frame.claim_strength,
                    evidence.study_design,
                    evidence.evidence_id,
                )
            )

    verdict = _logic_verdict(
        claim_frame=claim_frame,
        rules=rules,
        predicate_mismatches=predicate_mismatches,
        population_mismatches=population_mismatches,
        modality_mismatches=modality_mismatches,
        scope_mismatches=scope_mismatches,
    )
    score = _entailment_score(verdict, rules)
    reason = _logic_reason(claim_frame, best, verdict, rules)
    return LogicAuditResult(
        claim_id=claim_frame.claim_id,
        evidence_ids=[item.evidence_id for item in evidence_frames],
        claim_frame=claim_frame,
        evidence_frames=evidence_frames,
        logic_verdict=cast(LogicVerdict, verdict),
        entailment_score=score,
        rules_triggered=rules,
        predicate_mismatches=predicate_mismatches,
        scope_mismatches=scope_mismatches,
        modality_mismatches=modality_mismatches,
        population_mismatches=population_mismatches,
        reason=reason,
    )


def _logic_verdict(
    *,
    claim_frame: LogicalClaimFrame,
    rules: list[str],
    predicate_mismatches: list[dict[str, object]],
    population_mismatches: list[dict[str, object]],
    modality_mismatches: list[dict[str, object]],
    scope_mismatches: list[dict[str, object]],
) -> str:
    if not rules:
        return "entailed"
    critical_rules = {
        rule
        for rule in rules
        if RULE_METADATA.get(rule) and RULE_METADATA[rule].severity == "critical"
    }
    if claim_frame.hedging and critical_rules <= {
        "animal_evidence_does_not_entail_human_claim",
        "in_vitro_evidence_does_not_entail_human_claim",
    }:
        _add_rule(rules, "hedging_downgrades_overclaim_severity")
        return "partially_entailed"
    if "inconclusive_evidence_does_not_support_positive_claim" in rules:
        return "insufficient_evidence"
    if critical_rules or predicate_mismatches or scope_mismatches:
        return "overclaimed"
    if population_mismatches:
        return "scope_mismatch"
    if modality_mismatches:
        return "modality_mismatch"
    return "partially_entailed"


def _entailment_score(verdict: str, rules: list[str]) -> float:
    if verdict == "entailed":
        return 1.0
    if verdict == "partially_entailed":
        return 0.65
    if verdict == "modality_mismatch":
        return 0.55
    if verdict == "scope_mismatch":
        return 0.45
    if verdict == "insufficient_evidence":
        return 0.2
    if verdict == "overclaimed":
        return 0.35 if len(rules) == 1 else 0.25
    return 0.0


def _logic_reason(
    claim_frame: LogicalClaimFrame,
    evidence_frame: LogicalEvidenceFrame,
    verdict: str,
    rules: list[str],
) -> str:
    if verdict == "entailed":
        return "The parsed claim frame is compatible with the aligned evidence frame."
    explanations = [
        RULE_METADATA[rule].explanation
        for rule in rules
        if rule in RULE_METADATA and rule != "hedging_downgrades_overclaim_severity"
    ]
    if not explanations:
        return "The parsed claim and evidence frames show a support-boundary mismatch."
    return (
        " ".join(explanations)
        + f" Claim predicate/population/modality: {claim_frame.predicate}/"
        + f"{claim_frame.population}/{claim_frame.modality}. Evidence "
        + f"predicate/population/modality: {evidence_frame.predicate}/"
        + f"{evidence_frame.population}/{evidence_frame.modality}."
    )


def _add_rule(rules: list[str], rule: str) -> None:
    if rule not in rules:
        rules.append(rule)


def _mismatch(
    axis: str,
    claim_value: object,
    evidence_value: object,
    evidence_id: str,
) -> dict[str, object]:
    return {
        "axis": axis,
        "claim_value": claim_value,
        "evidence_value": evidence_value,
        "evidence_id": evidence_id,
    }


def _claims_sufficient_causation(claim_frame: LogicalClaimFrame) -> bool:
    text = " ".join(
        [
            claim_frame.claim_text,
            " ".join(claim_frame.qualifiers),
            " ".join(claim_frame.source_spans),
        ]
    ).lower()
    return any(
        marker in text
        for marker in (
            "sufficient cause",
            "sufficient causes",
            "necessary cause",
            "necessary causes",
            "independent cause",
            "independent causes",
            "definitive cause",
            "definitive causes",
            "definitively cause",
        )
    )
