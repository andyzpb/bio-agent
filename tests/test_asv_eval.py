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
    bayesian_surprise_kl,
    entropy_nats,
    evaluate_trajectory,
    js_pivot_score,
    normalize_log_scores,
)
from asv_eval.evaluators import (
    DeepSeekLogprobBeliefEvaluator,
    DeepSeekLogprobConfig,
    MockBeliefEvaluator,
    candidate_scores_from_top_logprobs,
    ensure_no_gold_leakage,
    normalize_label_token,
    render_forced_choice_prompt,
    render_label_free_rationale_prompt,
)
from asv_eval.reporting import build_summary


def test_softmax_entropy_and_asv_components() -> None:
    probs = normalize_log_scores({"yes": -0.2, "no": -4.1, "maybe": -2.3})

    assert round(sum(probs.values()), 8) == 1.0
    assert probs["yes"] > probs["maybe"] > probs["no"]
    assert entropy_nats({"a": 0.5, "b": 0.5}) > entropy_nats({"a": 0.99, "b": 0.01})
    assert bayesian_surprise_kl({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) == 0.0
    assert js_pivot_score({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) == 0.0


def test_evaluate_trajectory_computes_realized_entropy_reduction_and_gold_gain() -> (
    None
):
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
    assert (
        row["gold_metrics"]["oracle_gold_log_likelihood_gain"]
        == row["gold_metrics"]["gold_log_likelihood_gain"]
    )
    assert row["action"] == {"type": "search", "is_external_observation": True}
    assert row["state_before_hash"].startswith("sha256:")
    assert row["state_after_hash"].startswith("sha256:")


def test_evaluate_trajectory_skips_gold_gain_for_zero_probability_gold() -> None:
    task = TaskRecord(
        task_id="task-zero-gold",
        question="Does X help?",
        candidate_space=CandidateSpace(
            candidates=[
                Candidate(id="supported", label="A", text="supported"),
                Candidate(id="not_enough_information", label="C", text="not enough"),
            ],
            gold_candidate_id="supported",
        ),
    )
    trajectory = TrajectoryRecord(
        trajectory_id="traj-zero-gold",
        task=task,
        steps=[
            StepRecord(
                step_id="s1",
                index=0,
                action={"type": "classify"},
                belief_before={"supported": 0.0, "not_enough_information": 1.0},
                belief_after={"supported": 1.0, "not_enough_information": 0.0},
            )
        ],
    )

    [row] = evaluate_trajectory(trajectory)

    assert row["gold_metrics"]["gold_log_likelihood_gain"] is None
    assert row["gold_metrics"]["oracle_gold_log_likelihood_gain"] == round(
        math.log(1.0) - math.log(1e-12),
        6,
    )
    assert row["gold_metrics"]["gold_rank_before"] == 2
    assert row["gold_metrics"]["gold_rank_after"] == 1


def test_evaluate_trajectory_reports_margin_and_semantic_gain_for_one_hot_move() -> (
    None
):
    task = TaskRecord(
        task_id="task-one-hot",
        question="Does the evidence support APOE risk?",
        candidate_space=CandidateSpace(
            candidates=[
                Candidate(id="supported", label="A", text="supported"),
                Candidate(id="refuted", label="B", text="refuted"),
                Candidate(
                    id="not_enough_information",
                    label="C",
                    text="not enough information",
                ),
            ],
            gold_candidate_id="supported",
        ),
    )
    trajectory = TrajectoryRecord(
        trajectory_id="traj-one-hot",
        task=task,
        steps=[
            StepRecord(
                step_id="retrieve",
                index=0,
                action={"type": "retrieve"},
                belief_before={
                    "supported": 0.0,
                    "refuted": 0.0,
                    "not_enough_information": 1.0,
                },
                belief_after={
                    "supported": 1.0,
                    "refuted": 0.0,
                    "not_enough_information": 0.0,
                },
                raw_scores_before={
                    "supported": -4.0,
                    "refuted": -5.0,
                    "not_enough_information": 0.0,
                },
                raw_scores_after={
                    "supported": 0.0,
                    "refuted": -6.0,
                    "not_enough_information": -7.0,
                },
            )
        ],
    )

    [row] = evaluate_trajectory(trajectory)
    metrics = row["gold_metrics"]

    before_margin = -4.0 - math.log(math.exp(-5.0) + math.exp(0.0))
    after_margin = 0.0 - math.log(math.exp(-6.0) + math.exp(-7.0))
    assert row["asv_components"]["realized_entropy_reduction"] == 0.0
    assert row["asv_components"]["bayesian_surprise_kl"] > 14.0
    assert 0.0 < row["asv_components"]["js_pivot_score"] < math.log(2)
    assert metrics["gold_margin_before"] == pytest.approx(round(before_margin, 6))
    assert metrics["gold_margin_after"] == pytest.approx(round(after_margin, 6))
    assert metrics["gold_margin_gain"] == pytest.approx(
        round(after_margin - before_margin, 6)
    )
    assert metrics["semantic_gold_distance_before"] == pytest.approx(
        round(math.sqrt(2.0), 6)
    )
    assert metrics["semantic_gold_distance_after"] == 0.0
    assert metrics["semantic_gold_gain"] == pytest.approx(round(math.sqrt(2.0), 6))


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


def test_label_free_rationale_prompt_uses_candidate_ids_without_option_mapping() -> (
    None
):
    prompt = render_label_free_rationale_prompt(
        question="Which answer is supported?",
        evidence_text='{"evidence": "alpha"}',
        candidate_texts={
            "supported": "Supported by evidence",
            "none": "Evidence is insufficient",
        },
    )

    assert "candidate_id: supported" in prompt
    assert "candidate_id: none" in prompt
    assert "A: supported" not in prompt
    assert "A = candidate_id" not in prompt
    assert "Do not output a final option label" in prompt


def test_rationale_conditioned_scoring_puts_physical_mapping_at_tail() -> None:
    prompt = render_forced_choice_prompt(
        question="Which answer is supported?",
        evidence_text='{"evidence": "alpha"}',
        labels={"A": "supported", "B": "none"},
        candidate_texts={
            "supported": "Supported by evidence",
            "none": "Evidence is insufficient",
        },
        rationale_text='{"supported_evidence":[{"candidate_id":"supported"}]}',
    )

    assert "Candidate manifest:" in prompt
    assert "A: supported" not in prompt
    assert "<RATIONALE_BUFFER>" in prompt
    mapping_index = prompt.index("Current physical option mapping:")
    rationale_index = prompt.index("</RATIONALE_BUFFER>")
    assert mapping_index > rationale_index
    assert prompt.rstrip().endswith("Output exactly one uppercase option label.")


def test_logprob_label_mapping_clamps_provider_sentinel_scores() -> None:
    scores, warnings = candidate_scores_from_top_logprobs(
        [
            {"token": "A", "logprob": -9999.0},
            {"token": "B", "logprob": -0.1},
        ],
        label_to_candidate={"A": "supported", "B": "not_enough_information"},
        floor_score=-20.0,
    )

    assert scores["supported"] == -20.0
    assert scores["not_enough_information"] == -0.1
    assert warnings == []


def test_logprob_candidate_limit_fails_before_provider_call() -> None:
    config = DeepSeekLogprobConfig(top_logprobs=20, max_logprob_candidates=10)

    with pytest.raises(ValueError, match="candidate_count"):
        config.validate_candidate_count(11)


class _CaptureClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def post(self, path: str, json: dict[str, object]):
        self.payloads.append(json)

        class _Response:
            status_code = 200
            headers: dict[str, str] = {}

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "logprobs": {
                                "content": [
                                    {
                                        "top_logprobs": [
                                            {"token": "1", "logprob": -0.1},
                                            {"token": "2", "logprob": -2.0},
                                        ]
                                    }
                                ]
                            }
                        }
                    ]
                }

        return _Response()


def test_disable_thinking_adds_dashscope_payload_flag() -> None:
    client = _CaptureClient()
    evaluator = DeepSeekLogprobBeliefEvaluator(
        DeepSeekLogprobConfig(
            model="qwen3.7-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key_env="DASHSCOPE_API_KEY",
            top_logprobs=5,
            max_logprob_candidates=5,
            disable_thinking=True,
        ),
        client=client,
    )

    evaluator.score_state(
        question="Which option is supported?",
        evidence_text='{"evidence": "alpha"}',
        labels={"1": "answer-a", "2": "answer-b"},
    )

    assert client.payloads[0]["enable_thinking"] is False


def test_prompt_leakage_guard_rejects_gold_and_success_fields() -> None:
    with pytest.raises(ValueError, match="gold_candidate_id"):
        ensure_no_gold_leakage("Question plus gold_candidate_id=yes")
    with pytest.raises(ValueError, match="success"):
        ensure_no_gold_leakage('{"success": true}')


def test_prompt_leakage_guard_allows_success_in_evidence_text() -> None:
    ensure_no_gold_leakage('{"evidence": "The trial success rate improved."}')


def test_forced_choice_prompt_is_state_grounded() -> None:
    prompt = render_forced_choice_prompt(
        question="Does APOE e4 increase Alzheimer's disease risk?",
        evidence_text='{"completed_steps":[]}',
        labels={
            "A": "supported",
            "B": "refuted",
            "C": "not_enough_information",
        },
    )

    assert "Use only information inside the evidence block" in prompt
    assert "Do not use outside biomedical knowledge" in prompt
    assert "choose the not_enough_information option" in prompt


def test_forced_choice_prompt_includes_candidate_answer_text_without_cot() -> None:
    prompt = render_forced_choice_prompt(
        question="Which answer best explains the response?",
        evidence_text='{"evidence":"alpha pathway evidence"}',
        labels={"A": "answer-a", "B": "answer-b"},
        candidate_texts={
            "answer-a": "Alpha pathway activation explains the response.",
            "answer-b": "Beta pathway inhibition explains the response.",
        },
    )

    assert "A: answer-a - Alpha pathway activation explains the response." in prompt
    assert "B: answer-b - Beta pathway inhibition explains the response." in prompt
    assert "compare the evidence against every candidate" in prompt
    assert "chain-of-thought" not in prompt.lower()
    assert "Output exactly one option label." in prompt


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


def test_build_summary_reports_evaluator_coverage_from_quality_flags() -> None:
    task = TaskRecord(
        task_id="task-coverage",
        question="Does X help?",
        candidate_space=CandidateSpace(
            candidates=[
                Candidate(id="yes", label="A", text="yes"),
                Candidate(id="no", label="B", text="no"),
            ],
        ),
    )
    trajectory = TrajectoryRecord(
        trajectory_id="traj-coverage",
        task=task,
        steps=[
            StepRecord(
                step_id="s1",
                index=0,
                action={"type": "evaluate"},
                belief_before={"yes": 0.5, "no": 0.5},
                belief_after={"yes": 0.8, "no": 0.2},
            ),
            StepRecord(
                step_id="s2",
                index=1,
                action={"type": "evaluate"},
                belief_before={"yes": 0.8, "no": 0.2},
                belief_after={"yes": 0.6, "no": 0.4},
            ),
        ],
    )
    rows = evaluate_trajectory(trajectory)
    rows[0]["quality_flags"].update(
        {
            "used_cache": True,
            "before_used_cache": True,
            "after_used_cache": True,
            "used_floor_score": True,
            "missing_labels": ["B"],
        }
    )
    rows[1]["quality_flags"].update(
        {
            "before_used_cache": True,
            "after_used_cache": False,
            "used_cache": False,
            "used_fallback": True,
            "missing_labels": [],
        }
    )

    summary = build_summary([trajectory], rows)

    assert summary["evaluator_coverage"]["evaluated_state_count"] == len(rows) * 2
    assert summary["evaluator_coverage"]["cache_hit_state_count"] == 3
    assert summary["evaluator_coverage"]["cache_hit_step_count"] == 1
    assert summary["evaluator_coverage"]["floor_score_step_count"] == 1
    assert summary["evaluator_coverage"]["fallback_step_count"] == 1
    assert summary["evaluator_coverage"]["missing_label_step_count"] == 1
