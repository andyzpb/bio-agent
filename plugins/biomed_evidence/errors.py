from __future__ import annotations

from typing import Any

from plugins.biomed_evidence.schemas import (
    ReleaseToolEnvelope,
    ReleaseToolError,
    ReleaseToolErrorCode,
    ReleaseToolMetadata,
)

_DEFAULT_NEXT_ACTIONS: dict[ReleaseToolErrorCode, list[str]] = {
    "clinical_boundary": [
        "reframe_as_research_question",
        "consult_qualified_clinician_for_patient_specific_advice",
    ],
    "source_policy_blocked": ["use_mock", "enable_live_source_policy"],
    "invalid_input": ["correct_request_payload"],
    "unknown_run_id": ["list_answer_runs", "rerun_answer_workflow"],
    "unknown_retrieval_id": ["rerun_literature_search"],
    "unknown_paper_id": ["search_literature"],
    "missing_retrieval_manifest": ["rerun_literature_search"],
    "empty_evidence": ["extract_evidence_batch", "broaden_query"],
    "llm_schema_invalid": ["retry_without_llm", "inspect_fallback_reason"],
    "external_source_unavailable": ["retry_later", "use_mock"],
    "rate_limited": ["retry_later", "reduce_max_results"],
    "timeout": ["reduce_limits", "retry_later"],
    "budget_exceeded": ["reduce_limits", "continue_from_partial_trace"],
    "export_path_blocked": ["configure_export_path"],
    "packet_unavailable": ["build_evidence_packet"],
    "provenance_unavailable": ["inspect_answer_trace"],
}

_NON_RECOVERABLE: set[ReleaseToolErrorCode] = {"clinical_boundary"}


def release_ok(
    *,
    tool_name: str,
    result: dict[str, Any],
    ids: dict[str, str] | None = None,
    warnings: list[str] | None = None,
    trace: dict[str, Any] | None = None,
    metadata: ReleaseToolMetadata | None = None,
) -> ReleaseToolEnvelope:
    return ReleaseToolEnvelope(
        ok=True,
        result=result,
        warnings=warnings or [],
        errors=[],
        trace=trace or {},
        ids=ids or {},
        metadata=metadata
        or ReleaseToolMetadata(tool_name=tool_name, side_effects=["read_storage"]),
    )


def release_error(
    *,
    tool_name: str,
    code: ReleaseToolErrorCode,
    message: str,
    detail: dict[str, Any] | None = None,
    recoverable: bool | None = None,
    next_allowed_actions: list[str] | None = None,
    warnings: list[str] | None = None,
    trace: dict[str, Any] | None = None,
    ids: dict[str, str] | None = None,
    metadata: ReleaseToolMetadata | None = None,
) -> ReleaseToolEnvelope:
    is_recoverable = (
        recoverable if recoverable is not None else code not in _NON_RECOVERABLE
    )
    actions = next_allowed_actions or list(_DEFAULT_NEXT_ACTIONS.get(code, []))
    error = ReleaseToolError(
        code=code,
        message=message,
        recoverable=is_recoverable,
        next_allowed_actions=actions,
        detail=detail or {},
    )
    return ReleaseToolEnvelope(
        ok=False,
        result={},
        warnings=warnings or [],
        errors=[error],
        error_code=code,
        message=message,
        recoverable=is_recoverable,
        next_allowed_actions=actions,
        trace=trace or {},
        ids=ids or {},
        metadata=metadata or ReleaseToolMetadata(tool_name=tool_name),
    )
