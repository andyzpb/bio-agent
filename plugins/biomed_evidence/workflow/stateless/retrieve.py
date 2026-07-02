from __future__ import annotations

from typing import Any

from plugins.biomed_evidence.workflow.stateless.types import StepInput, StepOutput


def retrieve_step(step_input: StepInput) -> StepOutput:
    input_state = step_input.to_state()
    if "classification:clinical_advice_refusal" in step_input.available_artifacts:
        return _stopped_output(
            step_input=step_input,
            input_state=input_state,
            warning="clinical_boundary",
            summary="clinical boundary stopped retrieval",
        )

    if "classification:unsupported_request" in step_input.available_artifacts:
        return _stopped_output(
            step_input=step_input,
            input_state=input_state,
            warning="unsupported_request",
            summary="unsupported request stopped retrieval",
        )

    if "classification:research" not in step_input.available_artifacts:
        output_state = {
            **input_state,
            "last_step": "retrieve",
            "last_status": "failed",
        }
        return StepOutput(
            step_id="retrieve",
            step_name="retrieve",
            status="failed",
            input_state=input_state,
            action=_retrieve_action(step_input),
            observation={"summary": "research classification is required"},
            output_state=output_state,
            cost=_zero_cost(),
            errors=["missing_research_classification"],
        )

    if step_input.source_policy != "mock_only" or step_input.source != "mock":
        output_state = {
            **input_state,
            "last_step": "retrieve",
            "last_status": "failed",
        }
        return StepOutput(
            step_id="retrieve",
            step_name="retrieve",
            status="failed",
            input_state=input_state,
            action=_retrieve_action(step_input),
            observation={"summary": "stateless retrieve supports mock source only"},
            output_state=output_state,
            cost=_zero_cost(),
            errors=["unsupported_source_policy"],
        )

    retrieval_id = f"{step_input.run_id}-retrieval-mock"
    papers = [artifact.summary() for artifact in step_input.artifact_payloads]
    output_state = {
        **input_state,
        "completed_steps": _append_unique(step_input.completed_steps, "retrieve"),
        "available_artifacts": _append_unique(
            step_input.available_artifacts, f"retrieval_id:{retrieval_id}"
        ),
        "retrieval_id": retrieval_id,
        "retrieved_paper_ids": [paper["paper_id"] for paper in papers],
        "retrieved_papers": papers,
        "last_step": "retrieve",
        "last_status": "completed",
    }
    source_call_count = 1 if papers else 0
    return StepOutput(
        step_id="retrieve",
        step_name="retrieve",
        status="completed",
        input_state=input_state,
        action={
            "type": "retrieve",
            "source_mode": "mock",
            "query": step_input.question,
        },
        observation={
            "retrieval_id": retrieval_id,
            "summary": f"retrieved {len(papers)} mocked paper(s)",
            "paper_count": len(papers),
            "papers": papers,
        },
        output_state=output_state,
        cost={
            "source_call_count": source_call_count,
            "artifact_cache_hit_count": 0,
            "tool_calls": source_call_count,
        },
        warnings=[] if papers else ["empty_mock_retrieval"],
        artifact_ids={"retrieval_id": retrieval_id},
    )


def _stopped_output(
    *,
    step_input: StepInput,
    input_state: dict[str, Any],
    warning: str,
    summary: str,
) -> StepOutput:
    output_state = {
        **input_state,
        "last_step": "retrieve",
        "last_status": "skipped",
    }
    return StepOutput(
        step_id="retrieve",
        step_name="retrieve",
        status="skipped",
        input_state=input_state,
        action=_retrieve_action(step_input),
        observation={"summary": summary, "paper_count": 0},
        output_state=output_state,
        cost=_zero_cost(),
        warnings=[warning],
    )


def _retrieve_action(step_input: StepInput) -> dict[str, str]:
    return {
        "type": "retrieve",
        "source_mode": step_input.source,
        "query": step_input.question,
    }


def _zero_cost() -> dict[str, float]:
    return {
        "source_call_count": 0,
        "artifact_cache_hit_count": 0,
        "tool_calls": 0,
    }


def _append_unique(items: list[str], value: str) -> list[str]:
    result = list(items)
    if value not in result:
        result.append(value)
    return result
