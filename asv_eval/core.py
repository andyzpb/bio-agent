from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "asv.v1"


@dataclass(frozen=True)
class Candidate:
    id: str
    label: str
    text: str
    prior: float | None = None


@dataclass(frozen=True)
class CandidateSpace:
    candidates: list[Candidate]
    gold_candidate_id: str | None = None
    type: Literal["closed_set", "candidate_set"] = "closed_set"


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    question: str
    candidate_space: CandidateSpace
    task_type: str = "closed_set_qa"
    domain: str | None = None
    difficulty: str | None = None
    gold_visible_to_evaluator: bool = False
    gold_used_only_for_validation: bool = True


@dataclass(frozen=True)
class StepRecord:
    step_id: str
    index: int
    action: dict[str, Any]
    observation: dict[str, Any] = field(default_factory=dict)
    state_before: dict[str, Any] | None = None
    state_after: dict[str, Any] | None = None
    belief_before: dict[str, float] | None = None
    belief_after: dict[str, float] | None = None
    cost: dict[str, float] = field(default_factory=dict)
    label: str | None = None
    label_source: str | None = None
    label_confidence: float | None = None
    quality_flags: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TrajectoryRecord:
    trajectory_id: str
    task: TaskRecord
    steps: list[StepRecord]
    schema_version: str = SCHEMA_VERSION
    source_adapter: str = "standard_jsonl"
    created_at: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    final_score: float | None = None
    success: bool | None = None


@dataclass(frozen=True)
class CostConfig:
    prompt_token_weight: float = 0.0
    completion_token_weight: float = 0.0
    tool_call_weight: float = 0.0
    latency_weight: float = 0.0
    risk_weight: float = 0.0


@dataclass(frozen=True)
class ASVConfig:
    cost: CostConfig = field(default_factory=CostConfig)
    lambda_cost: float = 0.0
    floor_score: float = -20.0


def normalize_log_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    peak = max(scores.values())
    exps = {key: math.exp(value - peak) for key, value in scores.items()}
    total = sum(exps.values())
    return {key: value / total for key, value in exps.items()}


def entropy_nats(probs: dict[str, float]) -> float:
    return -sum(value * math.log(value) for value in probs.values() if value > 0)


def state_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_state(task: TaskRecord, steps: list[StepRecord]) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "question": task.question,
        "observations": [step.observation for step in steps if step.observation],
    }


def scalar_cost(raw: dict[str, float], config: CostConfig) -> float:
    return round(
        config.prompt_token_weight * float(raw.get("prompt_tokens", 0.0)) / 1000.0
        + config.completion_token_weight
        * float(raw.get("completion_tokens", 0.0))
        / 1000.0
        + config.tool_call_weight * float(raw.get("tool_calls", 0.0))
        + config.latency_weight * float(raw.get("latency_ms", 0.0)) / 1000.0
        + config.risk_weight * float(raw.get("risk_score", 0.0)),
        6,
    )


def evaluate_trajectory(
    trajectory: TrajectoryRecord,
    *,
    config: ASVConfig | None = None,
) -> list[dict[str, Any]]:
    active_config = config or ASVConfig()
    rows: list[dict[str, Any]] = []
    candidate_count = len(trajectory.task.candidate_space.candidates)
    max_entropy = math.log(candidate_count) if candidate_count > 1 else 1.0
    for index, step in enumerate(trajectory.steps):
        if step.belief_before is None or step.belief_after is None:
            raise ValueError(
                f"step {step.step_id} is missing belief_before/belief_after"
            )
        state_before = step.state_before or build_state(
            trajectory.task,
            trajectory.steps[:index],
        )
        state_after = step.state_after or build_state(
            trajectory.task,
            trajectory.steps[: index + 1],
        )
        entropy_before = entropy_nats(step.belief_before)
        entropy_after = entropy_nats(step.belief_after)
        reduction = round(entropy_before - entropy_after, 6)
        cost_value = scalar_cost(step.cost, active_config.cost)
        net_asv = round(reduction - active_config.lambda_cost * cost_value, 6)
        gold_id = trajectory.task.candidate_space.gold_candidate_id
        gold_gain = None
        gold_rank_before = None
        gold_rank_after = None
        if gold_id and gold_id in step.belief_before and gold_id in step.belief_after:
            gold_gain = round(
                math.log(step.belief_after[gold_id])
                - math.log(step.belief_before[gold_id]),
                6,
            )
            gold_rank_before = _rank(step.belief_before, gold_id)
            gold_rank_after = _rank(step.belief_after, gold_id)
        rows.append(
            {
                "trajectory_id": trajectory.trajectory_id,
                "step_id": step.step_id,
                "action": step.action,
                "state_before_id": f"state-{trajectory.trajectory_id}-{index}",
                "state_after_id": f"state-{trajectory.trajectory_id}-{index + 1}",
                "state_before_hash": state_hash(state_before),
                "state_after_hash": state_hash(state_after),
                "belief_before": step.belief_before,
                "belief_after": step.belief_after,
                "asv_components": {
                    "entropy_before_nats": round(entropy_before, 6),
                    "entropy_after_nats": round(entropy_after, 6),
                    "entropy_before_normalized": round(
                        entropy_before / max_entropy,
                        6,
                    ),
                    "entropy_after_normalized": round(
                        entropy_after / max_entropy,
                        6,
                    ),
                    "entropy_base": "e",
                    "num_candidates": candidate_count,
                    "realized_entropy_reduction": reduction,
                    "normalized_entropy_reduction": round(reduction / max_entropy, 6),
                    "cost_scalar": cost_value,
                    "lambda": active_config.lambda_cost,
                    "net_asv": net_asv,
                },
                "gold_metrics": {
                    "gold_candidate_id": gold_id,
                    "gold_log_likelihood_gain": gold_gain,
                    "gold_rank_before": gold_rank_before,
                    "gold_rank_after": gold_rank_after,
                },
                "quality_flags": {
                    "evaluator_mode": "provided_belief",
                    "missing_labels": [],
                    "used_floor_score": False,
                    "floor_score": active_config.floor_score,
                    "used_fallback": False,
                    "candidate_count": candidate_count,
                    **step.quality_flags,
                },
                "label": step.label,
                "warnings": [],
            }
        )
    return rows


def _rank(probs: dict[str, float], candidate_id: str) -> int:
    ordered = sorted(probs.items(), key=lambda item: item[1], reverse=True)
    return [key for key, _ in ordered].index(candidate_id) + 1
