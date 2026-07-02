from __future__ import annotations

import math

import pytest

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
from asv_eval.evaluators import (
    DeepSeekLogprobConfig,
    MockBeliefEvaluator,
    candidate_scores_from_top_logprobs,
    ensure_no_gold_leakage,
    normalize_label_token,
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


def test_mock_belief_evaluator_reads_fixture_beliefs() -> None:
    evaluator = MockBeliefEvaluator()
    step = StepRecord(
        step_id="s1",
        index=0,
        action={"type": "search"},
        belief_before={"yes": 0.25, "no": 0.75},
        belief_after={"yes": 0.9, "no": 0.1},
    )

    before, after = evaluator.evaluate_step(step, ["yes", "no"])

    assert before["yes"] == 0.25
    assert after["yes"] == 0.9


def test_logprob_label_mapping_normalizes_variants_and_logsumexp() -> None:
    scores, warnings = candidate_scores_from_top_logprobs(
        [
            {"token": " A", "logprob": -0.2},
            {"token": "A.", "logprob": -1.2},
            {"token": "\nB", "logprob": -2.0},
        ],
        label_to_candidate={"A": "yes", "B": "no"},
        floor_score=-20.0,
    )

    assert normalize_label_token("\nA.") == "A"
    assert scores["yes"] == pytest.approx(-0.2 + math.log1p(math.exp(-1.0)))
    assert scores["no"] == -2.0
    assert warnings == []


def test_logprob_candidate_limit_fails_before_provider_call() -> None:
    config = DeepSeekLogprobConfig(top_logprobs=20, max_logprob_candidates=10)

    with pytest.raises(ValueError, match="candidate_count"):
        config.validate_candidate_count(11)


def test_prompt_leakage_guard_rejects_gold_and_success_fields() -> None:
    with pytest.raises(ValueError, match="gold_candidate_id"):
        ensure_no_gold_leakage("Question plus gold_candidate_id=yes")


def test_step_quality_flags_are_optional_and_preserved() -> None:
    step = StepRecord(
        step_id="s-quality",
        index=0,
        action={"type": "evaluate"},
        quality_flags={"evaluator_mode": "deepseek_chat_logprob"},
    )

    assert step.quality_flags == {"evaluator_mode": "deepseek_chat_logprob"}


def test_evaluate_trajectory_passes_through_quality_flags() -> None:
    task = TaskRecord(
        task_id="task-quality",
        question="Does X help?",
        candidate_space=CandidateSpace(
            candidates=[
                Candidate(id="yes", label="A", text="yes"),
                Candidate(id="no", label="B", text="no"),
            ],
        ),
    )
    trajectory = TrajectoryRecord(
        trajectory_id="traj-quality",
        task=task,
        steps=[
            StepRecord(
                step_id="s1",
                index=0,
                action={"type": "evaluate"},
                belief_before={"yes": 0.5, "no": 0.5},
                belief_after={"yes": 0.9, "no": 0.1},
                quality_flags={
                    "evaluator_mode": "deepseek_chat_logprob",
                    "used_cache": True,
                },
            )
        ],
    )

    [row] = evaluate_trajectory(trajectory)

    assert row["quality_flags"]["evaluator_mode"] == "deepseek_chat_logprob"
    assert row["quality_flags"]["used_cache"] is True
