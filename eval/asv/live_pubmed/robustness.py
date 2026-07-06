from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from asv_eval.adapters import (
    build_label_permuted_trajectories,
    load_standard_jsonl,
    write_standard_jsonl,
)
from asv_eval.core import bayesian_surprise_kl


def summarize_permutation_stability(report_dir: Path) -> dict[str, float | int]:
    rows = _read_jsonl(report_dir / "steps.jsonl")
    values = [float(row["asv_components"]["net_asv"]) for row in rows]
    if not values:
        return {
            "step_count": 0,
            "permutation_group_count": 0,
            "mean_net_asv": 0.0,
            "min_net_asv": 0.0,
            "max_net_asv": 0.0,
            "mean_group_range_net_asv": 0.0,
            "max_group_range_net_asv": 0.0,
            "mean_group_range_bayesian_surprise_kl": 0.0,
            "max_group_range_bayesian_surprise_kl": 0.0,
            "mean_permutation_averaged_gold_margin_gain": 0.0,
            "mean_group_range_gold_margin_gain": 0.0,
            "max_group_range_gold_margin_gain": 0.0,
            "mean_channel_anisotropy_before": 0.0,
            "mean_channel_anisotropy_after": 0.0,
            "mean_channel_anisotropy_delta": 0.0,
        }

    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_permutation_group_key(row)].append(row)
    ranges = [
        _range(_component_values(group_rows, "net_asv"))
        for group_rows in groups.values()
    ]
    surprise_ranges = [
        _range(_component_values(group_rows, "bayesian_surprise_kl"))
        for group_rows in groups.values()
    ]
    margin_ranges = [
        _range(_gold_metric_values(group_rows, "gold_margin_gain"))
        for group_rows in groups.values()
    ]
    mean_margins = [
        _mean(_gold_metric_values(group_rows, "gold_margin_gain"))
        for group_rows in groups.values()
    ]
    before_anisotropy: list[float] = []
    after_anisotropy: list[float] = []
    anisotropy_deltas: list[float] = []
    for group_rows in groups.values():
        before = _channel_anisotropy(group_rows, "belief_before")
        after = _channel_anisotropy(group_rows, "belief_after")
        if before is not None:
            before_anisotropy.append(before)
        if after is not None:
            after_anisotropy.append(after)
        if before is not None and after is not None:
            anisotropy_deltas.append(after - before)
    min_value = min(values)
    max_value = max(values)
    return {
        "step_count": len(values),
        "permutation_group_count": len(groups),
        "mean_net_asv": round(sum(values) / len(values), 6),
        "min_net_asv": min_value,
        "max_net_asv": max_value,
        "mean_group_range_net_asv": round(sum(ranges) / len(ranges), 6),
        "max_group_range_net_asv": round(max(ranges), 6),
        "mean_group_range_bayesian_surprise_kl": _mean(surprise_ranges),
        "max_group_range_bayesian_surprise_kl": _max_or_zero(surprise_ranges),
        "mean_permutation_averaged_gold_margin_gain": _mean(mean_margins),
        "mean_group_range_gold_margin_gain": _mean(margin_ranges),
        "max_group_range_gold_margin_gain": _max_or_zero(margin_ranges),
        "mean_channel_anisotropy_before": _mean(before_anisotropy),
        "mean_channel_anisotropy_after": _mean(after_anisotropy),
        "mean_channel_anisotropy_delta": _mean(anisotropy_deltas),
    }


def _permutation_group_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    trajectory_id = str(row.get("trajectory_id") or "")
    base_trajectory_id = trajectory_id.split("-permutation-", 1)[0]
    return (
        base_trajectory_id,
        str(row.get("step_id") or ""),
        str(row.get("state_before_hash") or ""),
        str(row.get("state_after_hash") or ""),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build label-permuted live PubMed ASV trajectories."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--permutations", type=int, default=3)
    args = parser.parse_args(argv)

    trajectories = load_standard_jsonl(Path(args.input))
    permuted = build_label_permuted_trajectories(
        trajectories,
        permutation_count=max(1, int(args.permutations)),
    )
    write_standard_jsonl(Path(args.output), permuted)
    print(f"trajectory_count={len(permuted)} output={args.output}")
    return 0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _component_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        components = row.get("asv_components")
        if not isinstance(components, dict):
            continue
        value = components.get(key)
        if isinstance(value, int | float):
            values.append(float(value))
    return values


def _gold_metric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        metrics = row.get("gold_metrics")
        if not isinstance(metrics, dict):
            continue
        value = metrics.get(key)
        if isinstance(value, int | float):
            values.append(float(value))
    return values


def _range(values: list[float]) -> float:
    return max(values) - min(values) if values else 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _max_or_zero(values: list[float]) -> float:
    return round(max(values), 6) if values else 0.0


def _channel_anisotropy(rows: list[dict[str, Any]], key: str) -> float | None:
    beliefs = [row.get(key) for row in rows if isinstance(row.get(key), dict)]
    if len(beliefs) < 2:
        return None
    candidate_ids = sorted(
        {candidate_id for belief in beliefs for candidate_id in belief}
    )
    if not candidate_ids:
        return None
    marginal = {
        candidate_id: sum(float(belief.get(candidate_id, 0.0)) for belief in beliefs)
        / len(beliefs)
        for candidate_id in candidate_ids
    }
    return round(
        sum(bayesian_surprise_kl(marginal, belief) for belief in beliefs)
        / len(beliefs),
        6,
    )


if __name__ == "__main__":
    raise SystemExit(main())
