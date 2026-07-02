from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from asv_eval.adapters import load_standard_jsonl, write_standard_jsonl
from asv_eval.core import TrajectoryRecord


def build_label_permuted_trajectories(
    trajectories: Sequence[TrajectoryRecord],
    permutation_count: int,
) -> list[TrajectoryRecord]:
    if permutation_count < 0:
        raise ValueError("permutation_count must be non-negative")

    permuted: list[TrajectoryRecord] = []
    for trajectory in trajectories:
        candidates = trajectory.task.candidate_space.candidates
        labels = [candidate.label for candidate in candidates]
        for index in range(permutation_count):
            rotated_labels = _rotate_labels(labels, index)
            candidate_space = replace(
                trajectory.task.candidate_space,
                candidates=[
                    replace(candidate, label=rotated_label)
                    for candidate, rotated_label in zip(
                        candidates,
                        rotated_labels,
                        strict=True,
                    )
                ],
            )
            permuted.append(
                replace(
                    trajectory,
                    trajectory_id=f"{trajectory.trajectory_id}-permutation-{index}",
                    task=replace(trajectory.task, candidate_space=candidate_space),
                    metadata={
                        **trajectory.metadata,
                        "label_permutation_index": index,
                    },
                )
            )
    return permuted


def summarize_permutation_stability(report_dir: Path) -> dict[str, float | int]:
    values = [
        float(row["asv_components"]["net_asv"])
        for row in _read_jsonl(report_dir / "steps.jsonl")
    ]
    if not values:
        return {
            "step_count": 0,
            "mean_net_asv": 0.0,
            "min_net_asv": 0.0,
            "max_net_asv": 0.0,
            "range_net_asv": 0.0,
        }

    min_value = min(values)
    max_value = max(values)
    return {
        "step_count": len(values),
        "mean_net_asv": round(sum(values) / len(values), 6),
        "min_net_asv": min_value,
        "max_net_asv": max_value,
        "range_net_asv": round(max_value - min_value, 6),
    }


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


def _rotate_labels(labels: list[str], offset: int) -> list[str]:
    if not labels:
        return []
    offset %= len(labels)
    return labels[-offset:] + labels[:-offset] if offset else labels


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
