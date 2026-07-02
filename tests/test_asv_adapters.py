from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from asv_eval.adapters import (
    adapt_bio_agent_workspace,
    adapt_bio_agent_run_from_storage,
    load_standard_jsonl,
    react_transcript_to_trajectory,
)


def test_standard_jsonl_loader_builds_trajectory(tmp_path) -> None:
    path = tmp_path / "trajectories.jsonl"
    path.write_text(
        json.dumps(
            {
                "trajectory_id": "traj-1",
                "task": {
                    "task_id": "task-1",
                    "question": "Q?",
                    "candidate_space": {
                        "candidates": [
                            {"id": "yes", "label": "A", "text": "yes"},
                            {"id": "no", "label": "B", "text": "no"},
                        ],
                        "gold_candidate_id": "yes",
                    },
                },
                "steps": [
                    {
                        "step_id": "s1",
                        "index": 0,
                        "action": {"type": "search"},
                        "belief_before": {"yes": 0.5, "no": 0.5},
                        "belief_after": {"yes": 0.8, "no": 0.2},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    trajectories = load_standard_jsonl(path)

    assert trajectories[0].trajectory_id == "traj-1"
    assert trajectories[0].task.candidate_space.candidates[0].label == "A"


def test_react_adapter_scores_only_observation_steps() -> None:
    transcript = """Thought: I should search.
Action: search[alpha]
Observation: found alpha evidence
Thought: I now think A is right.
Final: A
"""

    trajectory = react_transcript_to_trajectory(
        transcript,
        trajectory_id="react-1",
        question="Which answer is right?",
        candidates={"A": "alpha", "B": "beta"},
    )

    assert [step.action["type"] for step in trajectory.steps] == ["search"]
    assert trajectory.steps[0].observation["text"] == "found alpha evidence"


def test_bio_agent_adapter_maps_trace_steps_conservatively() -> None:
    storage = SimpleNamespace(
        get_answer_run=lambda run_id: SimpleNamespace(
            run_id=run_id,
            answer="Final answer",
            evidence_summary=[],
            citations=[],
        ),
        list_agent_trace_steps=lambda run_id: [
            SimpleNamespace(
                step_id="plan-1",
                step="plan",
                output_summary="plan",
                metadata={},
                warnings=[],
            ),
            SimpleNamespace(
                step_id="retrieve-1",
                step="retrieve",
                output_summary="papers",
                metadata={"papers": ["P1"]},
                warnings=[],
            ),
            SimpleNamespace(
                step_id="audit-1",
                step="audit",
                output_summary="audit",
                metadata={"claim_support_rate": 1.0},
                warnings=[],
            ),
            SimpleNamespace(
                step_id="final-1",
                step="finalize",
                output_summary="done",
                metadata={},
                warnings=[],
            ),
        ],
    )

    trajectory = adapt_bio_agent_run_from_storage(storage, "run-1")

    assert [step.step_id for step in trajectory.steps] == ["retrieve-1", "audit-1"]
    assert trajectory.steps[0].action["type"] == "retrieve"
    assert trajectory.steps[1].action["type"] == "audit"


def test_bio_agent_workspace_adapter_requires_existing_db(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        adapt_bio_agent_workspace(tmp_path, "run-1")
