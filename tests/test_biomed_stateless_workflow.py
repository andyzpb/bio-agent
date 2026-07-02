from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from plugins.biomed_evidence.workflow.asv import trajectory_from_workflow_steps
from plugins.biomed_evidence.workflow.stateless.classify import classify_step
from plugins.biomed_evidence.workflow.stateless.types import (
    MockRetrievalArtifact,
    StepInput,
    StepOutput,
    step_output_to_workflow_step,
)


def test_stateless_step_output_projects_to_biomed_workflow_step() -> None:
    step_input = StepInput(
        run_id="stateless-run-1",
        question="Does microglial activation track Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:research"],
    )
    step_output = StepOutput(
        step_id="retrieve",
        step_name="retrieve",
        status="completed",
        input_state=step_input.to_state(),
        action={"type": "retrieve", "source_mode": "mock"},
        observation={"summary": "retrieved one mocked paper"},
        output_state={
            **step_input.to_state(),
            "completed_steps": ["classify", "retrieve"],
            "available_artifacts": [
                "classification:research",
                "retrieval_id:retrieval-1",
            ],
        },
        cost={"source_call_count": 1, "tool_calls": 1},
        warnings=["mock source"],
        artifact_ids={"retrieval_id": "retrieval-1"},
    )

    workflow_step = step_output_to_workflow_step("stateless-run-1", step_output)

    assert workflow_step.step_name == "retrieve"
    assert workflow_step.run_id == "stateless-run-1"
    assert workflow_step.action["source_mode"] == "mock"
    assert workflow_step.output_state["completed_steps"] == ["classify", "retrieve"]
    assert workflow_step.cost["source_call_count"] == 1
    assert workflow_step.warnings == ["mock source"]
    assert workflow_step.artifact_ids == {"retrieval_id": "retrieval-1"}


def test_stateless_classify_step_marks_research_question() -> None:
    step_input = StepInput(
        run_id="stateless-run-2",
        question="What evidence links microglial activation to Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
    )

    output = classify_step(step_input)

    assert output.step_id == "classify"
    assert output.step_name == "classify"
    assert output.status == "completed"
    assert output.input_state == step_input.to_state()
    assert output.action == {
        "type": "classify",
        "policy": "deterministic_guardrail",
        "source_policy": "mock_only",
    }
    assert output.observation["classification"] == "research"
    assert output.observation["allowed_next_step"] == "retrieve"
    assert output.output_state["completed_steps"] == ["classify"]
    assert output.output_state["available_artifacts"] == ["classification:research"]
    assert output.cost == {"llm_call_count": 0, "tool_calls": 0}
    assert output.warnings == []
    assert output.errors == []
    assert output.artifact_ids == {"classification": "research"}


def test_stateless_classify_step_refuses_clinical_request() -> None:
    step_input = StepInput(
        run_id="stateless-run-3",
        question="My father has symptoms, what dose of medication should he take?",
        source_policy="mock_only",
        source="mock",
    )

    output = classify_step(step_input)

    assert output.step_id == "classify"
    assert output.step_name == "classify"
    assert output.status == "skipped"
    assert output.input_state == step_input.to_state()
    assert output.action == {
        "type": "classify",
        "policy": "deterministic_guardrail",
        "source_policy": "mock_only",
    }
    assert output.observation["classification"] == "clinical_advice_refusal"
    assert output.observation["allowed_next_step"] == "stop"
    assert "research support only" in output.observation["refusal_reason"]
    assert output.output_state["completed_steps"] == ["classify"]
    assert output.output_state["available_artifacts"] == [
        "classification:clinical_advice_refusal"
    ]
    assert output.output_state["clinical_boundary"] is True
    assert output.cost == {"llm_call_count": 0, "tool_calls": 0}
    assert output.warnings == ["clinical_boundary"]
    assert output.errors == []
    assert output.artifact_ids == {"classification": "clinical_advice_refusal"}


def test_stateless_classify_step_skips_unsupported_request() -> None:
    step_input = StepInput(
        run_id="stateless-run-unsupported",
        question="What evidence supports that my laptop battery drains quickly?",
        source_policy="mock_only",
        source="mock",
    )

    output = classify_step(step_input)

    assert output.status == "skipped"
    assert output.observation["classification"] == "unsupported_request"
    assert output.observation["allowed_next_step"] == "stop"
    assert output.output_state["available_artifacts"] == [
        "classification:unsupported_request"
    ]
    assert output.warnings == ["unsupported_request"]
    assert output.artifact_ids == {"classification": "unsupported_request"}


def test_stateless_classify_step_skips_biomedical_homonyms_out_of_domain() -> None:
    for question in [
        "What evidence supports that my cellular data drains quickly?",
        "What evidence supports that Cancer will be lucky this week?",
    ]:
        output = classify_step(
            StepInput(
                run_id="stateless-run-homonym",
                question=question,
                source_policy="mock_only",
                source="mock",
            )
        )

        assert output.status == "skipped"
        assert output.observation["classification"] == "unsupported_request"
        assert output.observation["allowed_next_step"] == "stop"


def test_stateless_classify_step_deduplicates_existing_state_markers() -> None:
    step_input = StepInput(
        run_id="stateless-run-idempotent",
        question="What evidence links microglial activation to Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:research"],
    )

    output = classify_step(step_input)

    assert output.output_state["completed_steps"] == ["classify"]
    assert output.output_state["available_artifacts"] == ["classification:research"]
