from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from plugins.biomed_evidence.schemas import AnswerWithEvidenceRequest
from plugins.biomed_evidence.schemas import AgentTraceStep
from plugins.biomed_evidence.service import BiomedEvidenceService
from plugins.biomed_evidence.workflow.asv import (
    redact_for_asv,
    trajectory_from_workflow_steps,
    workflow_step_from_trace,
)
from plugins.biomed_evidence.workflow.types import BIOMED_ASV_CANDIDATE_IDS


def test_workflow_trace_step_projects_state_action_observation_and_cost() -> None:
    trace = AgentTraceStep(
        step_id="trace-retrieve",
        run_id="run-1",
        step="retrieve",
        status="completed",
        input_summary="Does alpha improve beta?",
        output_summary="retrieval-1",
        warnings=["source warning"],
        metadata={
            "retrieval_id": "retrieval-1",
            "papers": ["PMID:1"],
            "observability": {
                "llm_call_count": 1,
                "source_call_count": 2,
                "prompt_tokens": 321,
                "latency_ms": 140,
                "artifact_cache_hit_count": 1,
            },
            "raw_provider_response": {"authorization": "Bearer secret"},
            "synthesis_prompt_hash": "sha256:abc",
        },
        created_at="2026-07-02T12:00:00Z",
    )

    step = workflow_step_from_trace(
        trace,
        state_before={
            "run_id": "run-1",
            "question": "Does alpha improve beta?",
            "completed_steps": [],
            "available_artifacts": [],
        },
    )

    assert step.step_name == "retrieve"
    assert step.action["type"] == "retrieve"
    assert step.action["status"] == "completed"
    assert step.artifact_ids["retrieval_id"] == "retrieval-1"
    assert step.cost["llm_call_count"] == 1
    assert step.cost["source_call_count"] == 2
    assert step.cost["prompt_tokens"] == 321
    assert step.cost["latency_ms"] == 140
    assert step.output_state["completed_steps"] == ["retrieve"]
    assert step.output_state["available_artifacts"] == ["retrieval_id:retrieval-1"]

    rendered = json.dumps(step.observation, sort_keys=True)
    assert "Bearer secret" not in rendered
    assert "raw_provider_response" in rendered
    assert "sha256:abc" in rendered


def test_workflow_steps_convert_to_standard_asv_trajectory() -> None:
    first = workflow_step_from_trace(
        AgentTraceStep(
            step_id="trace-classify",
            run_id="run-1",
            step="classify",
            status="completed",
            input_summary="Does alpha improve beta?",
            output_summary="research_ok",
            metadata={},
            created_at="2026-07-02T12:00:00Z",
        ),
        state_before={
            "run_id": "run-1",
            "question": "Does alpha improve beta?",
            "completed_steps": [],
            "available_artifacts": [],
        },
    )
    second = workflow_step_from_trace(
        AgentTraceStep(
            step_id="trace-audit",
            run_id="run-1",
            step="audit",
            status="completed",
            input_summary="draft",
            output_summary="audit-1",
            metadata={
                "claim_support_rate": 1.0,
                "citation_precision": 1.0,
                "unsupported_claim_rate": 0.0,
                "overclaim_rate": 0.0,
                "observability": {"prompt_tokens": 222},
            },
            created_at="2026-07-02T12:00:01Z",
        ),
        state_before=first.output_state,
    )

    trajectory = trajectory_from_workflow_steps(
        run_id="run-1",
        question="Does alpha improve beta?",
        steps=[first, second],
    )

    assert trajectory.trajectory_id == "bio-agent-run-1"
    assert trajectory.source_adapter == "bio_agent_workflow"
    assert trajectory.run_id == "run-1"
    assert [item.id for item in trajectory.task.candidate_space.candidates] == list(
        BIOMED_ASV_CANDIDATE_IDS
    )
    assert [step.action["type"] for step in trajectory.steps] == [
        "classify",
        "audit",
    ]
    assert trajectory.steps[0].state_before is not None
    assert trajectory.steps[0].state_after is not None
    assert trajectory.steps[1].cost["prompt_tokens"] == 222
    assert trajectory.steps[1].belief_before is None
    assert trajectory.steps[1].belief_after is None


def test_redact_for_asv_masks_secret_bearing_strings_without_hiding_prompt_metrics() -> None:
    redacted = redact_for_asv(
        {
            "debug_log": "POST /v1 Authorization: Bearer sk-test-secret",
            "request_url": "https://example.test?api_key=sk-test-secret&mode=test",
            "raw_provider_response": "api_key=sk-test-secret",
            "synthesis_prompt_hash": "sha256:abc",
            "observability": {"prompt_tokens": 321},
        }
    )

    rendered = json.dumps(redacted, sort_keys=True)
    assert "sk-test-secret" not in rendered
    assert "Authorization: Bearer [REDACTED]" in rendered
    assert "api_key=[REDACTED]" in rendered
    assert "raw_provider_response" in rendered
    assert "sha256:abc" in rendered
    assert redacted["observability"]["prompt_tokens"] == 321


def test_workflow_trace_cost_derives_tool_calls_from_llm_and_source_calls() -> None:
    step = workflow_step_from_trace(
        AgentTraceStep(
            step_id="trace-retrieve",
            run_id="run-1",
            step="retrieve",
            status="completed",
            input_summary="Does alpha improve beta?",
            output_summary="retrieval-1",
            metadata={
                "observability": {
                    "llm_call_count": 1,
                    "source_call_count": 2,
                    "prompt_tokens": 321,
                },
            },
            created_at="2026-07-02T12:00:00Z",
        ),
        state_before={
            "run_id": "run-1",
            "question": "Does alpha improve beta?",
            "completed_steps": [],
            "available_artifacts": [],
        },
    )

    assert step.cost["llm_call_count"] == 1
    assert step.cost["source_call_count"] == 2
    assert step.cost["tool_calls"] == 3


@pytest.mark.asyncio
async def test_service_exports_saved_audited_run_as_asv_trajectory(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question=(
                    "What recent evidence links microglial activation to "
                    "Alzheimer's disease progression?"
                ),
                source="mock",
                max_papers=5,
            )
        )

        trajectory = service.export_answer_run_asv_trajectory(
            audited.answer_result.run_id
        )
    finally:
        await service.aclose()

    assert trajectory.run_id == audited.answer_result.run_id
    assert trajectory.task.question.startswith("What recent evidence")
    assert trajectory.final_score is not None
    assert trajectory.success is not None
    step_types = [step.action["type"] for step in trajectory.steps]
    assert {"classify", "retrieve", "extract", "audit", "revise", "finalize"} <= set(
        step_types
    )
    assert all(step.state_before is not None for step in trajectory.steps)
    assert all(step.state_after is not None for step in trajectory.steps)
    assert any(step.cost for step in trajectory.steps)
    rendered = json.dumps(
        [step.observation for step in trajectory.steps],
        sort_keys=True,
    ).lower()
    assert "authorization" not in rendered
    assert "bearer secret" not in rendered
    assert "raw_provider_response" not in rendered or "[redacted]" in rendered


@pytest.mark.asyncio
async def test_service_export_asv_trajectory_redacts_full_serialized_payload(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links tau pathology to synaptic loss?",
                source="mock",
                max_papers=3,
            )
        )
        extract_step = next(
            step
            for step in service.storage.list_agent_trace_steps(
                audited.answer_result.run_id
            )
            if step.step == "extract"
        )
        service.storage.save_agent_trace_steps(
            [
                extract_step.model_copy(
                    update={
                        "metadata": {
                            "debug_log": "Authorization: Bearer secret-token",
                            "raw_provider_response": {
                                "authorization": "Bearer secret-token",
                            },
                        },
                    }
                )
            ]
        )

        trajectory = service.export_answer_run_asv_trajectory(
            audited.answer_result.run_id
        )
    finally:
        await service.aclose()

    rendered = json.dumps(asdict(trajectory), default=str, sort_keys=True).lower()
    assert "secret-token" not in rendered
    assert "bearer secret" not in rendered
    assert "agenttracestep" not in rendered
    assert "raw_provider_response" not in rendered or "[redacted]" in rendered


def test_service_export_asv_trajectory_reports_missing_run(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        with pytest.raises(ValueError, match="answer_run_not_found"):
            service.export_answer_run_asv_trajectory("missing-run")
    finally:
        service.storage.close()
