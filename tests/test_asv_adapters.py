from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from asv_eval.adapters import (
    adapt_bio_agent_workspace,
    adapt_bio_agent_run_from_storage,
    load_belief_fixture,
    load_open_qa_candidate_specs,
    load_standard_jsonl,
    react_transcript_to_trajectory,
    write_standard_jsonl,
)
from asv_eval.core import (
    Candidate,
    CandidateSpace,
    StepRecord,
    TaskRecord,
    TrajectoryRecord,
    evaluate_trajectory,
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


def test_standard_jsonl_roundtrip_preserves_step_quality_flags(tmp_path) -> None:
    path = tmp_path / "trajectories.jsonl"
    trajectory = TrajectoryRecord(
        trajectory_id="traj-quality-flags",
        task=TaskRecord(
            task_id="task-quality-flags",
            question="Does X help?",
            candidate_space=CandidateSpace(
                candidates=[
                    Candidate(id="yes", label="A", text="yes"),
                    Candidate(id="no", label="B", text="no"),
                ],
            ),
        ),
        steps=[
            StepRecord(
                step_id="s1",
                index=0,
                action={"type": "evaluate"},
                belief_before={"yes": 0.5, "no": 0.5},
                belief_after={"yes": 0.8, "no": 0.2},
                raw_scores_before={"yes": -0.7, "no": -0.7},
                raw_scores_after={"yes": -0.1, "no": -2.0},
                quality_flags={
                    "evaluator_mode": "deepseek_chat_logprob",
                    "prompt_before_hash": "sha256:before",
                    "used_cache": True,
                },
            )
        ],
    )

    write_standard_jsonl(path, [trajectory])
    [loaded] = load_standard_jsonl(path)

    assert loaded.steps[0].quality_flags == {
        "evaluator_mode": "deepseek_chat_logprob",
        "prompt_before_hash": "sha256:before",
        "used_cache": True,
    }
    assert loaded.steps[0].raw_scores_before == {"yes": -0.7, "no": -0.7}
    assert loaded.steps[0].raw_scores_after == {"yes": -0.1, "no": -2.0}


def test_belief_fixture_loader_reports_malformed_json_with_context(tmp_path) -> None:
    path = tmp_path / "beliefs.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid belief fixture"):
        load_belief_fixture(path)


def test_open_qa_candidate_answer_spec_builds_candidate_set_trajectory(
    tmp_path,
) -> None:
    path = tmp_path / "open_qa.jsonl"
    path.write_text(
        json.dumps(
            {
                "trajectory_id": "open-qa-1",
                "question": "Which mechanism explains the observed response?",
                "candidate_answers": [
                    {
                        "id": "answer-a",
                        "text": "The response is explained by pathway alpha.",
                    },
                    {
                        "id": "answer-b",
                        "text": "The response is explained by pathway beta.",
                    },
                    {
                        "id": "none-of-the-above",
                        "text": "Evidence is insufficient to support any candidate.",
                    },
                ],
                "gold_candidate_id": "answer-a",
                "steps": [
                    {
                        "step_id": "retrieve",
                        "index": 0,
                        "action": {"type": "retrieve"},
                        "state_before": {"evidence": "baseline notes"},
                        "state_after": {"evidence": "alpha pathway evidence"},
                        "belief_before": {
                            "answer-a": 0.3,
                            "answer-b": 0.4,
                            "none-of-the-above": 0.3,
                        },
                        "belief_after": {
                            "answer-a": 0.8,
                            "answer-b": 0.1,
                            "none-of-the-above": 0.1,
                        },
                        "raw_scores_before": {
                            "answer-a": -1.0,
                            "answer-b": -0.4,
                            "none-of-the-above": -0.9,
                        },
                        "raw_scores_after": {
                            "answer-a": -0.1,
                            "answer-b": -2.3,
                            "none-of-the-above": -2.1,
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    [trajectory] = load_open_qa_candidate_specs(path)
    [row] = evaluate_trajectory(trajectory)

    assert trajectory.task.candidate_space.type == "candidate_set"
    assert trajectory.task.candidate_space.candidates[0].label == "A"
    assert trajectory.task.candidate_space.candidates[0].text == (
        "The response is explained by pathway alpha."
    )
    assert trajectory.task.candidate_space.gold_candidate_id == "answer-a"
    assert row["gold_metrics"]["gold_margin_gain"] > 0
    assert row["gold_metrics"]["semantic_gold_gain"] is None


def test_open_qa_candidate_answer_spec_requires_none_of_the_above(tmp_path) -> None:
    path = tmp_path / "open_qa.jsonl"
    path.write_text(
        json.dumps(
            {
                "trajectory_id": "missing-none",
                "question": "Which answer is right?",
                "candidate_answers": [
                    {"id": "answer-a", "text": "Alpha."},
                    {"id": "answer-b", "text": "Beta."},
                ],
                "gold_candidate_id": "answer-a",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="none-of-the-above"):
        load_open_qa_candidate_specs(path)


def test_open_qa_candidate_answer_spec_rejects_duplicate_none_of_the_above(
    tmp_path,
) -> None:
    path = tmp_path / "open_qa.jsonl"
    path.write_text(
        json.dumps(
            {
                "trajectory_id": "duplicate-none",
                "question": "Which answer is right?",
                "candidate_answers": [
                    {"id": "answer-a", "text": "Alpha."},
                    {
                        "id": "none-of-the-above",
                        "text": "Insufficient evidence.",
                    },
                    {"id": "none-of-the-above", "text": "No support."},
                ],
                "gold_candidate_id": "none-of-the-above",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate candidate answer id"):
        load_open_qa_candidate_specs(path)


def test_open_qa_candidate_answer_spec_rejects_unknown_gold_id(tmp_path) -> None:
    path = tmp_path / "open_qa.jsonl"
    path.write_text(
        json.dumps(
            {
                "trajectory_id": "open-qa-bad-gold",
                "question": "Which answer is right?",
                "candidate_answers": [
                    {"id": "answer-a", "text": "Alpha."},
                    {"id": "answer-b", "text": "Beta."},
                    {
                        "id": "none-of-the-above",
                        "text": "Evidence is insufficient.",
                    },
                ],
                "gold_candidate_id": "answer-c",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown gold_candidate_id"):
        load_open_qa_candidate_specs(path)


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


def test_bio_agent_adapter_uses_workflow_asv_projection() -> None:
    storage = SimpleNamespace(
        get_answer_run=lambda run_id: SimpleNamespace(
            run_id=run_id,
            answer="Final answer",
            evidence_summary=[{"evidence_id": "ev-1"}],
            citations=[],
        ),
        get_answer_run_question=lambda run_id: "Does alpha improve beta?",
        list_agent_trace_steps=lambda run_id: [
            SimpleNamespace(
                step_id="classify-1",
                run_id=run_id,
                step="classify",
                status="completed",
                input_summary="question",
                output_summary="research_ok",
                metadata={},
                warnings=[],
                created_at="2026-07-02T12:00:00Z",
            ),
            SimpleNamespace(
                step_id="retrieve-1",
                run_id=run_id,
                step="retrieve",
                status="completed",
                input_summary="question",
                output_summary="papers",
                metadata={
                    "retrieval_id": "retrieval-1",
                    "papers": ["P1"],
                    "observability": {"source_call_count": 1},
                },
                warnings=[],
                created_at="2026-07-02T12:00:01Z",
            ),
            SimpleNamespace(
                step_id="audit-1",
                run_id=run_id,
                step="audit",
                status="completed",
                input_summary="draft",
                output_summary="audit",
                metadata={"claim_support_rate": 1.0},
                warnings=[],
                created_at="2026-07-02T12:00:02Z",
            ),
            SimpleNamespace(
                step_id="final-1",
                run_id=run_id,
                step="finalize",
                status="completed",
                input_summary="revise",
                output_summary="done",
                metadata={},
                warnings=[],
                created_at="2026-07-02T12:00:03Z",
            ),
        ],
    )

    trajectory = adapt_bio_agent_run_from_storage(storage, "run-1")

    assert trajectory.source_adapter == "bio_agent_workflow"
    assert trajectory.task.question == "Does alpha improve beta?"
    assert [step.action["type"] for step in trajectory.steps] == [
        "classify",
        "retrieve",
        "audit",
        "finalize",
    ]
    assert trajectory.steps[1].state_before is not None
    assert trajectory.steps[1].state_after is not None
    assert trajectory.steps[1].cost["source_call_count"] == 1.0


def test_bio_agent_workspace_adapter_requires_existing_db(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        adapt_bio_agent_workspace(tmp_path, "run-1")
