from __future__ import annotations

import re

RESEARCH_USE_DISCLAIMER = (
    "This system is intended for biomedical research support only. It does not "
    "provide clinical diagnosis, treatment recommendations, or patient-specific "
    "medical advice. Outputs require expert review."
)

_CLINICAL_PATTERNS = [
    r"\bdiagnos(?:e|is)\b",
    r"\bwhat treatment\b",
    r"\bwhich treatment\b",
    r"\b(?:dose|dosage|dosing)\b",
    r"\bhow much\b.*\b(?:take|use|dose|medication)\b",
    r"\bshould I take\b",
    r"\bshould\s+(?:my|our|the)\b.*\b(?:take|use|receive)\b",
    r"\b(?:my|our)\s+(?:mother|father|parent|wife|husband|child|son|daughter|patient)\b",
    r"\bpatient\b.*\b(?:treat|therapy|diagnos)",
    r"\bmedical record\b",
    r"\bmy symptoms?\b",
    r"\bprescribe\b",
]


def is_clinical_request(text: str) -> bool:
    low = text.lower()
    return any(re.search(pattern, low) for pattern in _CLINICAL_PATTERNS)


def clinical_refusal() -> str:
    return (
        f"{RESEARCH_USE_DISCLAIMER}\n\n"
        "I cannot help diagnose a patient, interpret private medical records, or "
        "recommend treatment. I can help reframe the request as a research literature "
        "question about mechanisms, evidence quality, uncertainty, or study design."
    )
