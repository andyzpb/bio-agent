from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from asv_eval.core import ASVConfig, TrajectoryRecord, evaluate_trajectory


def write_report_bundle(
    trajectories: list[TrajectoryRecord],
    output_dir: Path,
    *,
    config: ASVConfig | None = None,
    evaluator_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = output_dir / "tables"
    tables_dir.mkdir(exist_ok=True)

    rows: list[dict[str, Any]] = []
    for trajectory in trajectories:
        rows.extend(evaluate_trajectory(trajectory, config=config))

    summary = build_summary(trajectories, rows, evaluator_config=evaluator_config)
    _write_jsonl(output_dir / "steps.jsonl", rows)
    _write_jsonl(output_dir / "states.jsonl", _state_rows(rows))
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "interventions.json", build_interventions(rows))
    _write_steps_csv(tables_dir / "steps.csv", rows)
    (output_dir / "report.md").write_text(render_markdown_report(summary), encoding="utf-8")
    return summary


def build_summary(
    trajectories: list[TrajectoryRecord],
    rows: list[dict[str, Any]],
    *,
    evaluator_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reductions = [
        float(row["asv_components"]["realized_entropy_reduction"]) for row in rows
    ]
    net_values = [float(row["asv_components"]["net_asv"]) for row in rows]
    cost_values = [float(row["asv_components"]["cost_scalar"]) for row in rows]
    adapters = sorted({trajectory.source_adapter for trajectory in trajectories})
    return {
        "trajectory_count": len(trajectories),
        "step_count": len(rows),
        "source_adapters": adapters,
        "mean_realized_entropy_reduction": _mean(reductions),
        "mean_net_asv": _mean(net_values),
        "mean_cost_scalar": _mean(cost_values),
        "positive_net_asv_steps": sum(value > 0 for value in net_values),
        "negative_net_asv_steps": sum(value < 0 for value in net_values),
        "zero_net_asv_steps": sum(value == 0 for value in net_values),
        "evaluator": evaluator_config or {"mode": "provided-belief"},
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
    return "\n".join(
        [
            "# Agent Step Value Report",
            "",
            f"- trajectories: {summary['trajectory_count']}",
            f"- evaluated steps: {summary['step_count']}",
            f"- mean realized entropy reduction: {summary['mean_realized_entropy_reduction']}",
            f"- mean net ASV: {summary['mean_net_asv']}",
            f"- mean cost scalar: {summary['mean_cost_scalar']}",
            f"- positive net ASV steps: {summary['positive_net_asv_steps']}",
            f"- negative net ASV steps: {summary['negative_net_asv_steps']}",
            "",
        ]
    )


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
        "cost_scalar",
        "gold_log_likelihood_gain",
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
                    "cost_scalar": row["asv_components"]["cost_scalar"],
                    "gold_log_likelihood_gain": row["gold_metrics"][
                        "gold_log_likelihood_gain"
                    ],
                    "label": row.get("label") or "",
                }
            )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)
