from __future__ import annotations

import re

from plugins.biomed_evidence.guardrails import clinical_refusal, is_clinical_request
from plugins.biomed_evidence.workflow.stateless.types import StepInput, StepOutput

_RESEARCH_INTENT_PATTERNS = (
    r"\bassociat(?:e|ed|ion|ions)\b",
    r"\bbiomarker",
    r"\bcohort\b",
    r"\bevidence\b",
    r"\bfindings?\b",
    r"\blink(?:s|ed)?\b",
    r"\bmechanism",
    r"\bprogression\b",
    r"\bresearch\b",
    r"\bstud(?:y|ies)\b",
    r"\btranscriptom",
    r"\btrial\b",
)

_BIOMEDICAL_ANCHOR_PATTERNS = (
    r"\balzheimer",
    r"\bamyloid\b",
    r"\bcancer\b",
    r"\bdisease\b",
    r"\bdna\b",
    r"\bgene(?:tic|s)?\b",
    r"\bimmune\b",
    r"\binflamm",
    r"\bmicroglia",
    r"\bmutation\b",
    r"\bneuro",
    r"\bpatholog",
    r"\bprotein\b",
    r"\brna\b",
    r"\btherapy\b",
    r"\btranscriptom",
    r"\btumou?r\b",
)

_OUT_OF_DOMAIN_HOMONYM_PATTERNS = (
    r"\bastrolog",
    r"\bcellular data\b",
    r"\bhoroscope\b",
    r"\blucky\b",
    r"\bzodiac\b",
)


def classify_step(step_input: StepInput) -> StepOutput:
    input_state = step_input.to_state()
    is_clinical = is_clinical_request(step_input.question)
    is_supported_research = (not is_clinical) and _is_biomedical_research_question(
        step_input.question
    )
    classification = _classification_for_request(is_clinical, is_supported_research)
    allowed_next_step = "retrieve" if classification == "research" else "stop"
    warnings = _warnings_for_classification(classification)
    output_state = {
        **input_state,
        "completed_steps": _append_unique(step_input.completed_steps, "classify"),
        "available_artifacts": _append_unique(
            step_input.available_artifacts, f"classification:{classification}"
        ),
        "request_type": classification,
        "clinical_boundary": is_clinical,
    }
    observation = {
        "classification": classification,
        "allowed_next_step": allowed_next_step,
        "summary": _summary_for_classification(classification),
    }
    if is_clinical:
        observation["refusal_reason"] = clinical_refusal()

    return StepOutput(
        step_id="classify",
        step_name="classify",
        status="completed" if classification == "research" else "skipped",
        input_state=input_state,
        action={
            "type": "classify",
            "policy": "deterministic_guardrail",
            "source_policy": step_input.source_policy,
        },
        observation=observation,
        output_state=output_state,
        cost={"llm_call_count": 0, "tool_calls": 0},
        warnings=warnings,
        artifact_ids={"classification": classification},
    )


def _append_unique(items: list[str], value: str) -> list[str]:
    result = list(items)
    if value not in result:
        result.append(value)
    return result


def _classification_for_request(
    is_clinical: bool, is_supported_research: bool
) -> str:
    if is_clinical:
        return "clinical_advice_refusal"
    if is_supported_research:
        return "research"
    return "unsupported_request"


def _is_biomedical_research_question(question: str) -> bool:
    low = question.lower()
    if any(re.search(pattern, low) for pattern in _OUT_OF_DOMAIN_HOMONYM_PATTERNS):
        return False
    has_research_intent = any(
        re.search(pattern, low) for pattern in _RESEARCH_INTENT_PATTERNS
    )
    has_biomedical_anchor = any(
        re.search(pattern, low) for pattern in _BIOMEDICAL_ANCHOR_PATTERNS
    )
    return has_research_intent and has_biomedical_anchor


def _summary_for_classification(classification: str) -> str:
    if classification == "clinical_advice_refusal":
        return "Patient-specific clinical advice request refused."
    if classification == "unsupported_request":
        return "The request is outside the biomedical research evidence scope."
    return "The request is a bounded biomedical research question."


def _warnings_for_classification(classification: str) -> list[str]:
    if classification == "clinical_advice_refusal":
        return ["clinical_boundary"]
    if classification == "unsupported_request":
        return ["unsupported_request"]
    return []
