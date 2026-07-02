from __future__ import annotations

import math

from asv_eval.core import (
    ASVConfig,
    Candidate,
    CandidateSpace,
    CostConfig,
    StepRecord,
    TaskRecord,
    TrajectoryRecord,
    entropy_nats,
    evaluate_trajectory,
    normalize_log_scores,
)


def test_softmax_entropy_and_asv_components() -> None:
    probs = normalize_log_scores({"yes": -0.2, "no": -4.1, "maybe": -2.3})

    assert round(sum(probs.values()), 8) == 1.0
    assert probs["yes"] > probs["maybe"] > probs["no"]
    assert entropy_nats({"a": 0.5, "b": 0.5}) > entropy_nats(
        {"a": 0.99, "b": 0.01}
    )


def test_evaluate_trajectory_computes_realized_entropy_reduction_and_gold_gain() -> None:
    task = TaskRecord(
        task_id="task-1",
        question="Does X help?",
        candidate_space=CandidateSpace(
            candidates=[
                Candidate(id="yes", label="A", text="yes"),
                Candidate(id="no", label="B", text="no"),
                Candidate(id="maybe", label="C", text="maybe"),
            ],
            gold_candidate_id="yes",
        ),
    )
    trajectory = TrajectoryRecord(
        trajectory_id="traj-1",
        task=task,
        steps=[
            StepRecord(
                step_id="s1",
                index=0,
                action={"type": "search", "is_external_observation": True},
                observation={"text": "evidence"},
                belief_before={"yes": 0.34, "no": 0.07, "maybe": 0.59},
                belief_after={"yes": 0.83, "no": 0.02, "maybe": 0.15},
                cost={
                    "prompt_tokens": 1200,
                    "completion_tokens": 80,
                    "tool_calls": 1,
                    "latency_ms": 800,
                },
                label="useful",
            )
        ],
        final_score=1.0,
        success=True,
    )

    rows = evaluate_trajectory(
        trajectory,
        config=ASVConfig(
            cost=CostConfig(
                prompt_token_weight=0.001,
                completion_token_weight=0.001,
                tool_call_weight=0.02,
                latency_weight=0.0001,
            ),
            lambda_cost=1.0,
        ),
    )

    row = rows[0]
    assert row["asv_components"]["realized_entropy_reduction"] > 0
    assert row["asv_components"]["cost_scalar"] == 0.02136
    assert row["asv_components"]["net_asv"] == round(
        row["asv_components"]["realized_entropy_reduction"] - 0.02136,
        6,
    )
    assert row["gold_metrics"]["gold_log_likelihood_gain"] == round(
        math.log(0.83) - math.log(0.34),
        6,
    )
    assert row["state_before_hash"].startswith("sha256:")
    assert row["state_after_hash"].startswith("sha256:")
