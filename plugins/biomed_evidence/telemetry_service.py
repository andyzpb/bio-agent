from __future__ import annotations

from collections import Counter, defaultdict
from typing import cast

from plugins.biomed_evidence.schemas import (
    AgentTraceStep,
    CoverageMatrixRow,
    StepTelemetrySummary,
    StepTransitionRecord,
    WorkflowState,
)

_STEP_TO_STATE: dict[str, WorkflowState] = {
    "classify": "classified",
    "plan": "planned",
    "validate_plan": "planned",
    "retrieve": "searched",
    "extract": "extracted",
    "coverage_gap_analysis": "gap_analyzed",
    "build_packet": "packet_built",
    "draft": "synthesized",
    "audit": "audited",
    "advisory_verify": "audited",
    "revise": "revised",
    "post_audit": "audited",
    "finalize": "revised",
}


def build_step_telemetry(
    trace: list[AgentTraceStep],
    *,
    run_id: str | None = None,
    coverage_matrix: list[CoverageMatrixRow] | None = None,
    stop_reason: str | None = None,
) -> StepTelemetrySummary:
    states: list[WorkflowState] = []
    for step in trace:
        if step.status == "failed":
            states.append("failed")
            continue
        if step.step == "finalize" and step.output_summary in {"refuse", "abstain"}:
            states.append("refused")
            continue
        states.append(_STEP_TO_STATE.get(step.step, "failed"))

    coverage_counts = Counter(row.coverage_status for row in (coverage_matrix or []))
    coverage_summary = dict(coverage_counts)
    transitions: list[StepTransitionRecord] = []
    for index in range(max(0, len(states) - 1)):
        next_state = states[index + 1]
        transitions.append(
            StepTransitionRecord(
                from_state=states[index],
                to_state=next_state,
                tool_or_route="answer_trace",
                run_id=run_id,
                coverage_status_summary=coverage_summary,
                step_index=index + 1,
                stop_reason=stop_reason,
                success_category=(
                    "failed" if next_state == "failed" else "completed"
                ),
            )
        )

    matrix: dict[str, dict[str, int]] = defaultdict(dict)
    for record in transitions:
        row = matrix[record.from_state]
        row[record.to_state] = row.get(record.to_state, 0) + 1

    step_count = float(len(trace))
    warnings: list[str] = []
    if len(trace) > 12:
        warnings.append("Trace has more steps than the current release baseline.")
    if any(state == "failed" for state in states):
        warnings.append("Trace includes a failed workflow state.")

    return StepTelemetrySummary(
        run_id=run_id,
        transition_records=transitions,
        transition_matrix={key: dict(value) for key, value in matrix.items()},
        mean_tool_step_count=step_count,
        p95_tool_step_count=step_count,
        expected_remaining_steps=0.0 if trace else 1.0,
        unusual_path_warnings=warnings,
        advisory_only=True,
    )


def workflow_state_for_step(step: str) -> WorkflowState:
    return cast(WorkflowState, _STEP_TO_STATE.get(step, "failed"))
