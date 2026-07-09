from __future__ import annotations

import csv
import json
from pathlib import Path

from eval.asv.open_qa import posthoc_diagnostics


def _write_steps(path: Path) -> None:
    rows = [
        {
            "trajectory_id": "t1",
            "step_id": "s1",
            "action": {"type": "retrieve"},
            "belief_before": {"gold": 0.99, "other": 0.01},
            "belief_after": {"gold": 0.01, "other": 0.99},
            "raw_scores_before": {"gold": 0.0, "other": -20.0},
            "raw_scores_after": {"gold": -20.0, "other": 0.0},
            "gold_metrics": {
                "gold_candidate_id": "gold",
                "gold_margin_gain": -40.0,
            },
            "quality_flags": {
                "used_floor_score": True,
                "floor_score": -20.0,
                "missing_labels": ["gold"],
            },
            "asv_components": {"bayesian_surprise_kl": 1.0},
        },
        {
            "trajectory_id": "t1",
            "step_id": "s2",
            "action": {"type": "finalize"},
            "belief_before": {"gold": 0.4, "other": 0.6},
            "belief_after": {"gold": 0.7, "other": 0.3},
            "raw_scores_before": {"gold": -1.0, "other": 0.0},
            "raw_scores_after": {"gold": 0.0, "other": -1.0},
            "gold_metrics": {
                "gold_candidate_id": "gold",
                "gold_margin_gain": 2.0,
            },
            "quality_flags": {"used_floor_score": False, "floor_score": -20.0},
            "asv_components": {"bayesian_surprise_kl": 0.2},
        },
    ]
    path.parent.mkdir(parents=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_posthoc_diagnostics_writes_pivot_surprise_and_floor_tables(tmp_path: Path) -> None:
    root = tmp_path / "run"
    steps = root / "report" / "steps.jsonl"
    _write_steps(steps)

    summary = posthoc_diagnostics.run(root)

    assert summary["pivot_counts"]["overall"]["pivot_count"] == 2
    assert summary["pivot_counts"]["overall"]["target_destructive_pivots"] == 1
    assert summary["pivot_counts"]["overall"]["target_directed_pivots"] == 1
    assert summary["floor_sensitivity"][0]["floor_score"] == -10.0
    assert (root / "report" / "tables" / "pivot_counts.csv").exists()
    assert (root / "report" / "tables" / "surprise_sensitivity.csv").exists()
    assert (root / "report" / "tables" / "floor_sensitivity.csv").exists()
    with (root / "report" / "tables" / "floor_sensitivity.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["floor_score"] == "-10.0"
    assert rows[0]["floor_step_count"] == "1"
