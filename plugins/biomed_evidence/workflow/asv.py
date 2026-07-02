from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

from asv_eval.core import (
    Candidate,
    CandidateSpace,
    StepRecord,
    TaskRecord,
    TrajectoryRecord,
)
from plugins.biomed_evidence.schemas import AgentTraceStep
from plugins.biomed_evidence.workflow.types import (
    BIOMED_ASV_CANDIDATE_IDS,
    BiomedWorkflowStep,
)

_SECRET_REDACTION = "[REDACTED]"
_SECRET_STRING_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;&]+)"),
    re.compile(r"(?i)(api[_-]?key\s*=\s*)([^&\s,;]+)"),
)
_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
_SAFE_SECRET_KEY_EXCEPTIONS = (
    "prompt_hash",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
)
_ARTIFACT_ID_KEYS = (
    "audit_id",
    "evidence_graph_id",
    "evidence_packet_id",
    "literature_set_id",
    "project_id",
    "provenance_graph_id",
    "retrieval_bundle_id",
    "retrieval_id",
    "revision_id",
    "run_id",
)
_COST_KEYS = (
    "artifact_cache_hit_count",
    "artifact_cache_miss_count",
    "artifact_cache_write_count",
    "completion_tokens",
    "latency_ms",
    "llm_call_count",
    "prompt_tokens",
    "source_call_count",
    "tool_call_count",
    "tool_calls",
    "total_tokens",
)


def workflow_step_from_trace(
    trace: AgentTraceStep,
    *,
    state_before: dict[str, Any],
) -> BiomedWorkflowStep:
    metadata = dict(trace.metadata or {})
    artifact_ids = _artifact_ids_from_metadata(metadata)
    completed_steps = list(state_before.get("completed_steps") or [])
    if trace.step not in completed_steps:
        completed_steps.append(trace.step)
    available_artifacts = list(state_before.get("available_artifacts") or [])
    for key, value in artifact_ids.items():
        artifact_ref = f"{key}:{value}"
        if artifact_ref not in available_artifacts:
            available_artifacts.append(artifact_ref)
    output_state = {
        **state_before,
        "run_id": trace.run_id,
        "completed_steps": completed_steps,
        "available_artifacts": available_artifacts,
        "last_step": trace.step,
        "last_status": trace.status,
    }
    return BiomedWorkflowStep(
        step_id=trace.step_id,
        run_id=trace.run_id,
        step_name=trace.step,
        status=trace.status,
        input_state=redact_for_asv(state_before),
        action={
            "type": trace.step,
            "status": trace.status,
            "input_summary": trace.input_summary,
        },
        observation={
            "summary": trace.output_summary,
            "metadata": redact_for_asv(metadata),
            "warnings": list(trace.warnings),
        },
        output_state=redact_for_asv(output_state),
        cost=_cost_from_metadata(metadata),
        warnings=list(trace.warnings),
        errors=list(_metadata_errors(metadata)),
        artifact_ids=artifact_ids,
        created_at=trace.created_at,
    )


def trajectory_from_answer_run(run: Any) -> TrajectoryRecord:
    answer_result = getattr(run, "answer_result", None)
    run_id = str(
        getattr(run, "run_id", None)
        or getattr(answer_result, "run_id", None)
        or _value_from_mapping(run, "run_id")
        or "unknown"
    )
    question = str(
        getattr(run, "question", None)
        or getattr(answer_result, "question", None)
        or _value_from_mapping(run, "question")
        or getattr(answer_result, "answer", None)
        or run_id
    )
    trace = list(getattr(run, "trace", None) or _value_from_mapping(run, "trace") or [])
    state: dict[str, Any] = {
        "run_id": run_id,
        "question": question,
        "completed_steps": [],
        "available_artifacts": [],
    }
    workflow_steps: list[BiomedWorkflowStep] = []
    for item in trace:
        step = workflow_step_from_trace(item, state_before=state)
        workflow_steps.append(step)
        state = step.output_state
    return trajectory_from_workflow_steps(
        run_id=run_id,
        question=question,
        steps=workflow_steps,
        created_at=getattr(run, "created_at", None),
        final_score=_final_score_from_run(run),
        success=_success_from_run(run),
        metadata={"source_run": redact_for_asv(_object_to_mapping(run))},
    )


def trajectory_from_workflow_steps(
    *,
    run_id: str,
    question: str,
    steps: list[BiomedWorkflowStep],
    created_at: str | None = None,
    final_score: float | None = None,
    success: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> TrajectoryRecord:
    candidates = [
        Candidate(
            id=candidate_id,
            label=chr(ord("A") + index),
            text=candidate_id.replace("_", " "),
        )
        for index, candidate_id in enumerate(BIOMED_ASV_CANDIDATE_IDS)
    ]
    task = TaskRecord(
        task_id=run_id,
        question=question,
        candidate_space=CandidateSpace(candidates=candidates),
        domain="biomedical",
    )
    return TrajectoryRecord(
        trajectory_id=f"bio-agent-{run_id}",
        source_adapter="bio_agent_workflow",
        run_id=run_id,
        task=task,
        steps=[
            StepRecord(
                step_id=step.step_id,
                index=index,
                action=dict(step.action),
                observation=dict(step.observation),
                state_before=dict(step.input_state),
                state_after=dict(step.output_state),
                cost=dict(step.cost),
            )
            for index, step in enumerate(steps)
        ],
        created_at=created_at or (steps[0].created_at if steps else None),
        metadata=metadata or {},
        final_score=final_score,
        success=success,
    )


def redact_for_asv(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                redacted[key_text] = _SECRET_REDACTION
            else:
                redacted[key_text] = redact_for_asv(item)
        return redacted
    if isinstance(value, list):
        return [redact_for_asv(item) for item in value]
    if isinstance(value, tuple):
        return [redact_for_asv(item) for item in value]
    if isinstance(value, str):
        return _redact_secret_strings(value)
    return value


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if any(part in normalized for part in _SAFE_SECRET_KEY_EXCEPTIONS):
        return False
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _artifact_ids_from_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    artifact_ids: dict[str, str] = {}
    for key in _ARTIFACT_ID_KEYS:
        value = metadata.get(key)
        if value is not None and not isinstance(value, (dict, list, tuple)):
            artifact_ids[key] = str(value)
    return artifact_ids


def _cost_from_metadata(metadata: dict[str, Any]) -> dict[str, float]:
    cost: dict[str, float] = {}
    observability = metadata.get("observability")
    if isinstance(observability, dict):
        for key, value in observability.items():
            if key in _COST_KEYS and isinstance(value, (int, float)):
                cost[str(key)] = value
    for key in _COST_KEYS:
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            cost[key] = value
    if "tool_calls" not in cost:
        llm_calls = cost.get("llm_call_count")
        source_calls = cost.get("source_call_count")
        if isinstance(llm_calls, (int, float)) and isinstance(source_calls, (int, float)):
            cost["tool_calls"] = llm_calls + source_calls
    return cost


def _redact_secret_strings(value: str) -> str:
    redacted = value
    for pattern in _SECRET_STRING_PATTERNS:
        redacted = pattern.sub(rf"\1{_SECRET_REDACTION}", redacted)
    return redacted


def _final_score_from_run(run: Any) -> float | None:
    audit = _attribute_or_mapping(run, "audit")
    if audit is None:
        return None
    support_rate = _attribute_or_mapping(audit, "claim_support_rate")
    precision = _attribute_or_mapping(audit, "citation_precision")
    overclaim_rate = _attribute_or_mapping(audit, "overclaim_rate")
    if not isinstance(support_rate, (int, float)):
        return None
    score = float(support_rate)
    if isinstance(precision, (int, float)):
        score = (score + float(precision)) / 2.0
    if isinstance(overclaim_rate, (int, float)):
        score -= float(overclaim_rate)
    return max(0.0, min(1.0, round(score, 6)))


def _success_from_run(run: Any) -> bool | None:
    final_action = _attribute_or_mapping(run, "final_action")
    if final_action is not None:
        return str(final_action) in {"accept", "pass", "pass_with_limitations"}
    score = _final_score_from_run(run)
    if score is None:
        return None
    return score >= 0.8


def _metadata_errors(metadata: dict[str, Any]) -> list[str]:
    errors = metadata.get("errors")
    if isinstance(errors, list):
        return [str(item) for item in errors]
    if isinstance(errors, str):
        return [errors]
    return []


def _value_from_mapping(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _attribute_or_mapping(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _object_to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}
