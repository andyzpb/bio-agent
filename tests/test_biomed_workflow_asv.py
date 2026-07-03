from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

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
    assert step.observation["metadata"]["raw_provider_response"] == "[REDACTED]"
    assert "sha256:abc" in rendered


def test_workflow_trace_step_carries_compact_evidence_facts_forward() -> None:
    long_fact = "A" * 650
    retrieve = workflow_step_from_trace(
        AgentTraceStep(
            step_id="trace-retrieve",
            run_id="run-1",
            step="retrieve",
            status="completed",
            input_summary="Does APOE4 increase Alzheimer risk?",
            output_summary="evidence-packet-1",
            metadata={
                "evidence_packet": {
                    "supported_claims": [
                        "APOE epsilon4 is associated with increased Alzheimer risk.",
                        long_fact,
                    ],
                    "conflicting_claims": [
                        {"claim": "Effect differs by ancestry", "pmid": "123"}
                    ],
                    "coverage_gaps": ["No randomized intervention evidence."],
                    "api_key": "secret-should-not-leak",
                }
            },
            created_at="2026-07-02T12:00:00Z",
        ),
        state_before={
            "run_id": "run-1",
            "question": "Does APOE4 increase Alzheimer risk?",
            "completed_steps": [],
            "available_artifacts": [],
        },
    )
    audit = workflow_step_from_trace(
        AgentTraceStep(
            step_id="trace-audit",
            run_id="run-1",
            step="audit",
            status="completed",
            input_summary="draft",
            output_summary="audit-1",
            metadata={
                "claim_support_rate": 1.0,
                "unsupported_claim_rate": 0.0,
                "overclaim_rate": 0.0,
                "recommended_action": "accept",
            },
            created_at="2026-07-02T12:00:01Z",
        ),
        state_before=retrieve.output_state,
    )

    facts = retrieve.output_state["evidence_facts"]
    assert facts["supported_claims"][0] == (
        "APOE epsilon4 is associated with increased Alzheimer risk."
    )
    assert len(facts["supported_claims"][1]) == 500
    assert facts["conflicting_claims"] == [
        '{"claim": "Effect differs by ancestry", "pmid": "123"}'
    ]
    assert facts["coverage_gaps"] == ["No randomized intervention evidence."]
    assert "secret-should-not-leak" not in json.dumps(facts, sort_keys=True)

    assert audit.input_state["evidence_facts"] == retrieve.output_state["evidence_facts"]
    assert audit.output_state["evidence_facts"]["audit"] == {
        "claim_support_rate": 1.0,
        "overclaim_rate": 0.0,
        "recommended_action": "accept",
        "unsupported_claim_rate": 0.0,
    }


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
            "llm_raw_response": {"content": "plain llm body"},
            "synthesis_prompt_hash": "sha256:abc",
            "observability": {"prompt_tokens": 321},
        }
    )

    rendered = json.dumps(redacted, sort_keys=True)
    assert "sk-test-secret" not in rendered
    assert "plain llm body" not in rendered
    assert "Authorization: Bearer [REDACTED]" in rendered
    assert redacted["raw_provider_response"] == "[REDACTED]"
    assert redacted["llm_raw_response"] == "[REDACTED]"
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
                                "content": "plain provider body",
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
    assert "plain provider body" not in rendered
    assert "agenttracestep" not in rendered
    assert "raw_provider_response" not in rendered or "[redacted]" in rendered


@pytest.mark.asyncio
async def test_service_export_asv_revised_high_score_run_counts_as_success(
    tmp_path: Path,
) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links neuroinflammation to memory decline?",
                source="mock",
                max_papers=5,
            )
        )
        run_id = audited.answer_result.run_id
        audit = service.storage.get_latest_citation_audit_for_run(run_id)
        revision = service.storage.get_answer_revision(run_id)
        assert audit is not None
        assert revision is not None
        service.storage.save_citation_audit(
            audit.model_copy(
                update={
                    "claim_support_rate": 1.0,
                    "citation_precision": 1.0,
                    "overclaim_rate": 0.0,
                }
            )
        )
        service.storage.save_answer_revision(
            revision.model_copy(update={"revision_action": "revise"})
        )

        trajectory = service.export_answer_run_asv_trajectory(run_id)
    finally:
        await service.aclose()

    assert trajectory.final_score is not None
    assert trajectory.final_score >= 0.8
    assert trajectory.success is True


def test_service_export_asv_trajectory_reports_missing_run(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        with pytest.raises(ValueError, match="answer_run_not_found"):
            service.export_answer_run_asv_trajectory("missing-run")
    finally:
        service.storage.close()


@pytest.mark.asyncio
async def test_exported_biomed_asv_trajectory_can_be_evaluated_with_fixture(
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

    input_path = tmp_path / "biomed-asv.jsonl"
    fixture_path = tmp_path / "beliefs.jsonl"
    output_dir = tmp_path / "asv-report"
    input_path.write_text(
        json.dumps(asdict(trajectory), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    fixture_rows = []
    for step in trajectory.steps:
        fixture_rows.append(
            {
                "trajectory_id": trajectory.trajectory_id,
                "step_id": step.step_id,
                "belief_before": {
                    "supported": 0.34,
                    "refuted": 0.33,
                    "not_enough_information": 0.33,
                },
                "belief_after": {
                    "supported": 0.70,
                    "refuted": 0.15,
                    "not_enough_information": 0.15,
                },
            }
        )
    fixture_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in fixture_rows),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "asv_eval",
            "evaluate",
            "--input",
            str(input_path),
            "--belief-fixture",
            str(fixture_path),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["trajectory_count"] == 1
    assert summary["step_count"] == len(trajectory.steps)
    assert summary["mean_realized_entropy_reduction"] > 0
