from __future__ import annotations

import csv
import json
import random
import statistics
from pathlib import Path
from typing import Any

from asv_eval.core import ASVConfig, TrajectoryRecord, evaluate_trajectory


def write_report_bundle(
    trajectories: list[TrajectoryRecord],
    output_dir: Path,
    *,
    config: ASVConfig | None = None,
    evaluator_config: dict[str, Any] | None = None,
    bootstrap_resamples: int = 5000,
    bootstrap_seed: int = 7,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(exist_ok=True)

    rows: list[dict[str, Any]] = []
    for trajectory in trajectories:
        rows.extend(evaluate_trajectory(trajectory, config=config))

    trajectory_rows = build_trajectory_summary_rows(rows)
    step_type_rows = build_step_type_summary_rows(rows)
    summary = build_summary(
        trajectories,
        rows,
        evaluator_config=evaluator_config,
        bootstrap_resamples=bootstrap_resamples,
        bootstrap_seed=bootstrap_seed,
    )
    _write_jsonl(output_dir / "steps.jsonl", rows)
    _write_jsonl(output_dir / "states.jsonl", _state_rows(rows))
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "interventions.json", build_interventions(rows))
    _write_steps_csv(tables_dir / "steps.csv", rows)
    _write_csv(tables_dir / "trajectory_summary.csv", trajectory_rows)
    _write_csv(tables_dir / "step_type_summary.csv", step_type_rows)
    (output_dir / "report.md").write_text(
        render_markdown_report(summary), encoding="utf-8"
    )
    return summary


def build_summary(
    trajectories: list[TrajectoryRecord],
    rows: list[dict[str, Any]],
    *,
    evaluator_config: dict[str, Any] | None = None,
    bootstrap_resamples: int = 5000,
    bootstrap_seed: int = 7,
) -> dict[str, Any]:
    reductions = [
        float(row["asv_components"]["realized_entropy_reduction"]) for row in rows
    ]
    net_values = [float(row["asv_components"]["net_asv"]) for row in rows]
    cost_values = [float(row["asv_components"]["cost_scalar"]) for row in rows]
    surprise_values = [
        float(row["asv_components"]["bayesian_surprise_kl"]) for row in rows
    ]
    js_values = [float(row["asv_components"]["js_pivot_score"]) for row in rows]
    gold_margin_values = _gold_metric_values(rows, "gold_margin_gain")
    semantic_gold_values = _gold_metric_values(rows, "semantic_gold_gain")
    adapters = sorted({trajectory.source_adapter for trajectory in trajectories})
    return {
        "trajectory_count": len(trajectories),
        "step_count": len(rows),
        "source_adapters": adapters,
        "mean_realized_entropy_reduction": _mean(reductions),
        "mean_net_asv": _mean(net_values),
        "mean_bayesian_surprise_kl": _mean(surprise_values),
        "max_bayesian_surprise_kl": (
            round(max(surprise_values), 6) if surprise_values else 0.0
        ),
        "mean_js_pivot_score": _mean(js_values),
        "mean_gold_margin_gain": (
            _mean(gold_margin_values) if gold_margin_values else None
        ),
        "mean_semantic_gold_gain": (
            _mean(semantic_gold_values) if semantic_gold_values else None
        ),
        "mean_cost_scalar": _mean(cost_values),
        "positive_net_asv_steps": sum(value > 0 for value in net_values),
        "negative_net_asv_steps": sum(value < 0 for value in net_values),
        "zero_net_asv_steps": sum(value == 0 for value in net_values),
        "evaluator": evaluator_config or {"mode": "provided-belief"},
        "evaluator_coverage": _evaluator_coverage(rows),
        "trajectory_bootstrap": trajectory_bootstrap_summary(
            rows,
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        ),
    }


def build_interventions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    low_value_steps = [
        {
            "trajectory_id": row["trajectory_id"],
            "step_id": row["step_id"],
            "net_asv": row["asv_components"]["net_asv"],
            "realized_entropy_reduction": row["asv_components"][
                "realized_entropy_reduction"
            ],
            "cost_scalar": row["asv_components"]["cost_scalar"],
            "label": row.get("label"),
        }
        for row in rows
        if float(row["asv_components"]["net_asv"]) <= 0
    ]
    return {
        "low_value_steps": low_value_steps,
        "recommendations": [
            "Inspect low_value_steps for actions that add cost without reducing uncertainty.",
            "Compare repeated action types before changing agent policy.",
        ],
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    bootstrap = summary.get("trajectory_bootstrap") or {}
    return "\n".join(
        [
            "# Agent Step Value Report",
            "",
            f"- trajectories: {summary['trajectory_count']}",
            f"- evaluated steps: {summary['step_count']}",
            f"- mean realized entropy reduction: {summary['mean_realized_entropy_reduction']}",
            f"- mean entropy net ASV: {summary['mean_net_asv']}",
            f"- mean Bayesian surprise KL: {summary['mean_bayesian_surprise_kl']}",
            f"- max Bayesian surprise KL: {summary['max_bayesian_surprise_kl']}",
            f"- mean JS pivot score: {summary['mean_js_pivot_score']}",
            f"- mean gold margin gain: {summary['mean_gold_margin_gain']}",
            f"- trajectory-bootstrap gold margin CI: [{bootstrap.get('ci_low')}, {bootstrap.get('ci_high')}]",
            f"- LOTO gold margin range: [{bootstrap.get('loto_min')}, {bootstrap.get('loto_max')}]",
            f"- mean semantic gold gain: {summary['mean_semantic_gold_gain']}",
            f"- mean cost scalar: {summary['mean_cost_scalar']}",
            f"- positive net ASV steps: {summary['positive_net_asv_steps']}",
            f"- negative net ASV steps: {summary['negative_net_asv_steps']}",
            "",
        ]
    )


def build_trajectory_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["trajectory_id"]), []).append(row)
    output = []
    for trajectory_id in sorted(grouped):
        values = _gold_metric_values(grouped[trajectory_id], "gold_margin_gain")
        output.append(
            {
                "trajectory_id": trajectory_id,
                "step_count": len(grouped[trajectory_id]),
                "gold_margin_step_count": len(values),
                "mean_gold_margin_gain": _mean(values) if values else "",
                "positive_steps": sum(value > 0 for value in values),
                "zero_steps": sum(value == 0 for value in values),
                "negative_steps": sum(value < 0 for value in values),
            }
        )
    return output


def build_step_type_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        value = _gold_metric_value(row, "gold_margin_gain")
        if value is None:
            continue
        action = row.get("action") if isinstance(row.get("action"), dict) else {}
        step_type = str(action.get("type") or "unknown").replace("_", "-")
        grouped.setdefault(step_type, []).append(value)
    output = []
    for step_type in sorted(grouped):
        values = grouped[step_type]
        output.append(
            {
                "step_type": step_type,
                "n": len(values),
                "mean": _mean(values),
                "sd": round(statistics.stdev(values), 6) if len(values) > 1 else "",
                "median": round(statistics.median(values), 6),
                "min": round(min(values), 6),
                "max": round(max(values), 6),
                "pos": sum(value > 0 for value in values),
                "zero": sum(value == 0 for value in values),
                "neg": sum(value < 0 for value in values),
            }
        )
    return output


def trajectory_bootstrap_summary(
    rows: list[dict[str, Any]],
    *,
    resamples: int = 5000,
    seed: int = 7,
) -> dict[str, Any]:
    trajectory_rows = build_trajectory_summary_rows(rows)
    values = [
        float(row["mean_gold_margin_gain"])
        for row in trajectory_rows
        if isinstance(row["mean_gold_margin_gain"], int | float)
    ]
    if not values:
        return {
            "metric": "gold_margin_gain",
            "unit": "trajectory",
            "trajectory_count": 0,
            "mean": None,
            "ci_low": None,
            "ci_high": None,
            "loto_min": None,
            "loto_max": None,
            "sign_stable": None,
            "resamples": resamples,
            "seed": seed,
        }
    observed = _mean(values)
    rng = random.Random(seed)
    boot = [
        _mean([rng.choice(values) for _ in values])
        for _ in range(max(0, resamples))
    ]
    loto = (
        [_mean(values[:index] + values[index + 1 :]) for index in range(len(values))]
        if len(values) > 1
        else values
    )
    ci_low = _quantile(boot, 0.025) if boot else observed
    ci_high = _quantile(boot, 0.975) if boot else observed
    return {
        "metric": "gold_margin_gain",
        "unit": "trajectory",
        "trajectory_count": len(values),
        "mean": observed,
        "ci_low": round(ci_low, 6),
        "ci_high": round(ci_high, 6),
        "loto_min": round(min(loto), 6),
        "loto_max": round(max(loto), 6),
        "sign_stable": _sign_stable(observed, loto),
        "resamples": resamples,
        "seed": seed,
    }


def _evaluator_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    quality_flags = [row.get("quality_flags") or {} for row in rows]
    return {
        "evaluated_state_count": len(rows) * 2,
        "cache_hit_state_count": sum(
            _cache_hit_state_count(flags) for flags in quality_flags
        ),
        "cache_hit_step_count": sum(
            flags.get("used_cache") is True for flags in quality_flags
        ),
        "floor_score_step_count": sum(
            flags.get("used_floor_score") is True for flags in quality_flags
        ),
        "fallback_step_count": sum(
            flags.get("used_fallback") is True for flags in quality_flags
        ),
        "missing_label_step_count": sum(
            bool(flags.get("missing_labels")) for flags in quality_flags
        ),
    }


def _cache_hit_state_count(flags: dict[str, Any]) -> int:
    if "before_used_cache" in flags or "after_used_cache" in flags:
        return int(flags.get("before_used_cache") is True) + int(
            flags.get("after_used_cache") is True
        )
    return 2 if flags.get("used_cache") is True else 0


def _state_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for row in rows:
        states.append(
            {
                "trajectory_id": row["trajectory_id"],
                "step_id": row["step_id"],
                "state_id": row["state_before_id"],
                "position": "before",
                "state_hash": row["state_before_hash"],
                "belief": row["belief_before"],
            }
        )
        states.append(
            {
                "trajectory_id": row["trajectory_id"],
                "step_id": row["step_id"],
                "state_id": row["state_after_id"],
                "position": "after",
                "state_hash": row["state_after_hash"],
                "belief": row["belief_after"],
            }
        )
    return states


def _write_steps_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "trajectory_id",
        "step_id",
        "net_asv",
        "realized_entropy_reduction",
        "bayesian_surprise_kl",
        "js_pivot_score",
        "cost_scalar",
        "gold_log_likelihood_gain",
        "oracle_gold_log_likelihood_gain",
        "gold_margin_before",
        "gold_margin_after",
        "gold_margin_gain",
        "semantic_gold_distance_before",
        "semantic_gold_distance_after",
        "semantic_gold_gain",
        "label",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "trajectory_id": row["trajectory_id"],
                    "step_id": row["step_id"],
                    "net_asv": row["asv_components"]["net_asv"],
                    "realized_entropy_reduction": row["asv_components"][
                        "realized_entropy_reduction"
                    ],
                    "bayesian_surprise_kl": row["asv_components"][
                        "bayesian_surprise_kl"
                    ],
                    "js_pivot_score": row["asv_components"]["js_pivot_score"],
                    "cost_scalar": row["asv_components"]["cost_scalar"],
                    "gold_log_likelihood_gain": row["gold_metrics"][
                        "gold_log_likelihood_gain"
                    ],
                    "oracle_gold_log_likelihood_gain": row["gold_metrics"].get(
                        "oracle_gold_log_likelihood_gain"
                    ),
                    "gold_margin_before": row["gold_metrics"].get("gold_margin_before"),
                    "gold_margin_after": row["gold_metrics"].get("gold_margin_after"),
                    "gold_margin_gain": row["gold_metrics"].get("gold_margin_gain"),
                    "semantic_gold_distance_before": row["gold_metrics"].get(
                        "semantic_gold_distance_before"
                    ),
                    "semantic_gold_distance_after": row["gold_metrics"].get(
                        "semantic_gold_distance_after"
                    ),
                    "semantic_gold_gain": row["gold_metrics"].get("semantic_gold_gain"),
                    "label": row.get("label") or "",
                }
            )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def _gold_metric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _gold_metric_value(row, key)
        if value is not None:
            values.append(float(value))
    return values


def _gold_metric_value(row: dict[str, Any], key: str) -> float | None:
    metrics = row.get("gold_metrics")
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(key)
    return float(value) if isinstance(value, int | float) else None


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _sign_stable(observed: float, values: list[float]) -> bool:
    if observed > 0:
        return min(values) > 0
    if observed < 0:
        return max(values) < 0
    return False
