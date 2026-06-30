from __future__ import annotations

import re

from plugins.biomed_evidence.schemas import EvidenceItem, EvidenceMaturity


def derive_evidence_maturity(
    *,
    question: str,
    evidence: list[EvidenceItem],
) -> EvidenceMaturity:
    question_text = question.lower()
    evidence_text = " ".join(
        [
            *[
                " ".join(
                    [
                        item.claim,
                        item.finding,
                        item.evidence_span or "",
                        " ".join(item.methods),
                        " ".join(item.limitations),
                    ]
                )
                for item in evidence
            ],
        ]
    ).lower()
    if _has_clinical_intervention_language(question_text):
        return "clinical_intervention_claim"
    if _has_authority_language(evidence_text) and any(
        _is_positive_causal_evidence(item) for item in evidence
    ):
        return "established_causal_risk_factor"
    if _has_association_language(evidence_text) and _has_authority_language(evidence_text):
        return "established_association"
    return "emerging_claim"


def _is_positive_causal_evidence(item: EvidenceItem) -> bool:
    if item.evidence_direction != "supports":
        return False
    text = _evidence_text(item)
    return _has_causal_risk_language(text) and not _has_negated_causal_language(text)


def _evidence_text(item: EvidenceItem) -> str:
    return " ".join(
        [
            item.claim,
            item.finding,
            item.evidence_span or "",
            " ".join(item.methods),
            " ".join(item.limitations),
        ]
    ).lower()


def _has_causal_risk_language(text: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"established causal risk factor|causal risk factor|major risk factor|"
            r"primary cause|aetiological factor|etiological factor|carcinogen|"
            r"causes?|attributable to|dose[- ]response|cessation reduces risk"
            r")\b",
            text,
        )
    )


def _has_negated_causal_language(text: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"no evidence|no convincing evidence|insufficient evidence|"
            r"does not|did not|cannot|fails? to|not clearly|not establish(?:ed)?"
            r").{0,100}\b(caus|causal|link|associated|association)",
            text,
        )
    )


def _has_authority_language(text: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"guidelines?|clinical guidelines?|consensus|monograph|iarc|who|cdc|nci|"
            r"surgeon general|public health|systematic review|meta[- ]analysis"
            r")\b",
            text,
        )
    )


def _has_association_language(text: str) -> bool:
    return bool(re.search(r"\b(associated|association|linked|risk factor)\b", text))


def _has_clinical_intervention_language(text: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"treat(?:s|ment)?|therapy|therapeutic|placebo|"
            r"usual care|standard of care|clinical outcomes?|improve[sd]? outcomes?"
            r")\b",
            text,
        )
    )
