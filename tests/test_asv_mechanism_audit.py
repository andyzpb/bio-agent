from __future__ import annotations

import json
from pathlib import Path

from eval.asv.open_qa.mechanism_audit import (
    load_step_rows,
    paired_protocol_rows,
    write_mechanism_audit,
)


def test_mechanism_audit_counts_damage_repair_and_groups(tmp_path: Path) -> None:
    rationale = tmp_path / "rationale_steps.jsonl"
    direct = tmp_path / "direct_steps.jsonl"
    output_dir = tmp_path / "audit"
    _write_steps(
        rationale,
        [
            _step("t1", "s1", "extract", 3.0, -1.0, surprise=4.0),
            _step("t1", "s2", "audit", -2.0, 2.0, surprise=2.0),
            _step("t1", "s3", "retrieve", -1.0, -0.5, surprise=0.5),
        ],
    )
    _write_steps(
        direct,
        [
            _step("t1", "s1", "extract", 3.0, 4.0, surprise=0.2),
            _step("t1", "s2", "audit", -2.0, 3.0, surprise=1.0),
            _step("t1", "s3", "retrieve", -1.0, 2.0, surprise=1.5),
        ],
    )

    summary = write_mechanism_audit(
        rationale_steps=rationale,
        direct_steps=direct,
        output_dir=output_dir,
    )

    assert summary["rationale_step_count"] == 3
    assert summary["direct_step_count"] == 3
    damage_table = (output_dir / "damage_repair_by_step_type.csv").read_text(
        encoding="utf-8"
    )
    assert "extract,1,-4.0,-4.0,1,1.0,0,0.0" in damage_table
    assert "audit,1,4.0,4.0,0,0.0,1,1.0" in damage_table
    group_table = (output_dir / "external_internal_split.csv").read_text(
        encoding="utf-8"
    )
    assert "internal_transformation,2,0.0,0.0,1,0.5,1,0.5" in group_table
    paired_table = (output_dir / "direct_vs_rationale_paired.csv").read_text(
        encoding="utf-8"
    )
    assert "extract,1,1.0,-4.0,-5.0,0.0,1.0" in paired_table


def test_load_step_rows_skips_missing_gold_margin(tmp_path: Path) -> None:
    path = tmp_path / "steps.jsonl"
    path.write_text(
        json.dumps({"trajectory_id": "t1", "step_id": "s1", "gold_metrics": {}})
        + "\n",
        encoding="utf-8",
    )

    assert load_step_rows(path) == []


def test_paired_protocol_rows_uses_stable_step_keys(tmp_path: Path) -> None:
    rationale = tmp_path / "rationale_steps.jsonl"
    direct = tmp_path / "direct_steps.jsonl"
    _write_steps(
        rationale,
        [
            _step("t1", "shared", "audit", 1.0, -1.0, surprise=1.0),
            _step("t1", "rationale-only", "audit", 1.0, -1.0, surprise=1.0),
        ],
    )
    _write_steps(
        direct,
        [
            _step("t1", "shared", "audit", 1.0, 2.0, surprise=1.0),
            _step("t1", "direct-only", "audit", 1.0, 2.0, surprise=1.0),
        ],
    )

    rows = paired_protocol_rows(
        direct_rows=load_step_rows(direct),
        rationale_rows=load_step_rows(rationale),
    )

    audit = next(row for row in rows if row.get("step_type") == "audit")
    assert audit["n_paired"] == 1
    assert audit["protocol_damage_count"] == 1


def _write_steps(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _step(
    trajectory_id: str,
    step_id: str,
    step_type: str,
    before: float,
    after: float,
    *,
    surprise: float,
) -> dict[str, object]:
    return {
        "trajectory_id": trajectory_id,
        "step_id": step_id,
        "action": {"type": step_type},
        "asv_components": {"bayesian_surprise_kl": surprise},
        "gold_metrics": {
            "gold_margin_before": before,
            "gold_margin_after": after,
            "gold_margin_gain": after - before,
        },
        "quality_flags": {"used_floor_score": False},
    }

