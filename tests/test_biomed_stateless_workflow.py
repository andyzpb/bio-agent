from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from plugins.biomed_evidence.workflow.asv import trajectory_from_workflow_steps
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
