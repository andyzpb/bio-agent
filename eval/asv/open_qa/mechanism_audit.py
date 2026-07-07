from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


MECHANISM_GROUPS = {
    "external_evidence": {"retrieve"},
    "task_framing": {"classify", "plan", "validate_plan"},
    "internal_transformation": {
        "extract",
        "draft",
        "audit",
        "revise",
        "advisory_verify",
        "post_audit",
        "finalize",
    },
    "self_verification": {
        "audit",
        "revise",
        "advisory_verify",
        "post_audit",
        "finalize",
    },
}


@dataclass(frozen=True)
class StepAuditRow:
    trajectory_id: str
    step_id: str
    step_type: str
    gold_margin_before: float
    gold_margin_after: float
    gold_margin_gain: float
    bayesian_surprise_kl: float
    used_floor_score: bool

    @property
    def before_correct(self) -> bool:
        return self.gold_margin_before > 0

    @property
    def after_correct(self) -> bool:
        return self.gold_margin_after > 0

    @property
    def damage(self) -> bool:
        return self.before_correct and not self.after_correct

    @property
    def repair(self) -> bool:
        return not self.before_correct and self.after_correct


def load_step_rows(path: Path) -> list[StepAuditRow]:
    rows: list[StepAuditRow] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            gold = raw.get("gold_metrics") or {}
            before = _float(gold.get("gold_margin_before"))
            after = _float(gold.get("gold_margin_after"))
            gain = _float(gold.get("gold_margin_gain"))
            if before is None or after is None or gain is None:
                continue
            action = raw.get("action") if isinstance(raw.get("action"), dict) else {}
            flags = raw.get("quality_flags") if isinstance(raw.get("quality_flags"), dict) else {}
            rows.append(
                StepAuditRow(
                    trajectory_id=str(raw["trajectory_id"]),
                    step_id=str(raw["step_id"]),
                    step_type=_normalize_step_type(str(action.get("type") or "unknown")),
                    gold_margin_before=before,
                    gold_margin_after=after,
                    gold_margin_gain=gain,
                    bayesian_surprise_kl=float(
                        (raw.get("asv_components") or {}).get("bayesian_surprise_kl")
                        or 0.0
                    ),
                    used_floor_score=bool(flags.get("used_floor_score")),
                )
            )
    return rows


def summarize_rows(
    rows: Iterable[StepAuditRow],
    key_fn: Callable[[StepAuditRow], str | None],
    *,
    key_name: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[StepAuditRow]] = {}
    for row in rows:
        key = key_fn(row)
        if key is not None:
            grouped.setdefault(key, []).append(row)
    return [_summary_row(key_name, key, grouped[key]) for key in sorted(grouped)]


def mechanism_group_rows(rows: Iterable[StepAuditRow]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    rows = list(rows)
    for group, step_types in MECHANISM_GROUPS.items():
        members = [row for row in rows if row.step_type in step_types]
        if members:
            output.append(_summary_row("group", group, members))
    return output


def paired_protocol_rows(
    *,
    direct_rows: list[StepAuditRow],
    rationale_rows: list[StepAuditRow],
) -> list[dict[str, Any]]:
    direct_by_key = {(row.trajectory_id, row.step_id): row for row in direct_rows}
    pairs = [
        (direct_by_key[(row.trajectory_id, row.step_id)], row)
        for row in rationale_rows
        if (row.trajectory_id, row.step_id) in direct_by_key
    ]
    output: list[dict[str, Any]] = []
    for step_type in sorted({rationale.step_type for _, rationale in pairs}):
        output.append(
            _paired_summary_row(
                "step_type",
                step_type,
                [
                    (direct, rationale)
                    for direct, rationale in pairs
                    if rationale.step_type == step_type
                ],
            )
        )
    for group, step_types in MECHANISM_GROUPS.items():
        members = [
            (direct, rationale)
            for direct, rationale in pairs
            if rationale.step_type in step_types
        ]
        if members:
            output.append(_paired_summary_row("group", group, members))
    return output


def write_mechanism_audit(
    *,
    rationale_steps: Path,
    output_dir: Path,
    direct_steps: Path | None = None,
) -> dict[str, Any]:
    rationale_rows = load_step_rows(rationale_steps)
    output_dir.mkdir(parents=True, exist_ok=True)

    by_step_type = summarize_rows(
        rationale_rows, lambda row: row.step_type, key_name="step_type"
    )
    by_group = mechanism_group_rows(rationale_rows)
    _write_csv(output_dir / "damage_repair_by_step_type.csv", by_step_type)
    _write_csv(output_dir / "external_internal_split.csv", by_group)

    paired: list[dict[str, Any]] = []
    direct_rows: list[StepAuditRow] = []
    if direct_steps is not None and direct_steps.exists():
        direct_rows = load_step_rows(direct_steps)
        paired = paired_protocol_rows(
            direct_rows=direct_rows,
            rationale_rows=rationale_rows,
        )
    _write_csv(output_dir / "direct_vs_rationale_paired.csv", paired)

    summary = {
        "rationale_steps": str(rationale_steps),
        "rationale_steps_sha256": _sha256(rationale_steps),
        "rationale_step_count": len(rationale_rows),
        "direct_steps": str(direct_steps) if direct_steps else None,
        "direct_steps_sha256": _sha256(direct_steps) if direct_steps else None,
        "direct_step_count": len(direct_rows),
        "paired_summary_row_count": len(paired),
        "top_negative_step_types": sorted(
            by_step_type,
            key=lambda row: float(row["mean_gold_margin_gain"]),
        )[:5],
    }
    (output_dir / "mechanism_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_dir / "mechanism_report.md").write_text(
        _render_report(by_step_type, by_group, paired, summary), encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ASV open-QA mechanism audit.")
    parser.add_argument("--rationale-steps", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--direct-steps")
    args = parser.parse_args(argv)
    write_mechanism_audit(
        rationale_steps=Path(args.rationale_steps),
        direct_steps=Path(args.direct_steps) if args.direct_steps else None,
        output_dir=Path(args.output_dir),
    )
    return 0


def _summary_row(key_name: str, key: str, rows: list[StepAuditRow]) -> dict[str, Any]:
    gains = [row.gold_margin_gain for row in rows]
    damage_rows = [row for row in rows if row.damage]
    return {
        key_name: key,
        "n": len(rows),
        "mean_gold_margin_gain": _round(_mean(gains)),
        "median_gold_margin_gain": _round(statistics.median(gains)),
        "damage_count": len(damage_rows),
        "damage_rate": _round(len(damage_rows) / len(rows)),
        "repair_count": sum(row.repair for row in rows),
        "repair_rate": _round(sum(row.repair for row in rows) / len(rows)),
        "unchanged_correct_count": sum(
            row.before_correct and row.after_correct for row in rows
        ),
        "unchanged_wrong_count": sum(
            (not row.before_correct) and (not row.after_correct) for row in rows
        ),
        "mean_bayesian_surprise_kl": _round(
            _mean([row.bayesian_surprise_kl for row in rows])
        ),
        "mean_surprise_on_damage": _round(
            _mean([row.bayesian_surprise_kl for row in damage_rows])
        ),
        "floor_score_step_count": sum(row.used_floor_score for row in rows),
    }


def _paired_summary_row(
    key_name: str,
    key: str,
    pairs: list[tuple[StepAuditRow, StepAuditRow]],
) -> dict[str, Any]:
    return {
        key_name: key,
        "n_paired": len(pairs),
        "mean_direct_gold_margin_gain": _round(
            _mean([direct.gold_margin_gain for direct, _ in pairs])
        ),
        "mean_rationale_gold_margin_gain": _round(
            _mean([rationale.gold_margin_gain for _, rationale in pairs])
        ),
        "mean_delta_protocol_gain": _round(
            _mean(
                [
                    rationale.gold_margin_gain - direct.gold_margin_gain
                    for direct, rationale in pairs
                ]
            )
        ),
        "direct_damage_rate": _round(
            sum(direct.damage for direct, _ in pairs) / len(pairs)
        ),
        "rationale_damage_rate": _round(
            sum(rationale.damage for _, rationale in pairs) / len(pairs)
        ),
        "direct_repair_rate": _round(
            sum(direct.repair for direct, _ in pairs) / len(pairs)
        ),
        "rationale_repair_rate": _round(
            sum(rationale.repair for _, rationale in pairs) / len(pairs)
        ),
        "protocol_damage_count": sum(
            rationale.damage and not direct.damage for direct, rationale in pairs
        ),
        "protocol_repair_loss_count": sum(
            direct.repair and not rationale.repair for direct, rationale in pairs
        ),
    }


def _render_report(
    by_step_type: list[dict[str, Any]],
    by_group: list[dict[str, Any]],
    paired: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    lines = [
        "# ASV Self-Correction Mechanism Audit",
        "",
        f"- rationale steps: {summary['rationale_step_count']}",
        f"- direct steps: {summary['direct_step_count']}",
        f"- paired summary rows: {summary['paired_summary_row_count']}",
        "",
        "## Most Negative Step Types",
        "",
        _markdown_table(
            sorted(
                by_step_type,
                key=lambda row: float(row["mean_gold_margin_gain"]),
            )[:5],
            [
                "step_type",
                "n",
                "mean_gold_margin_gain",
                "damage_rate",
                "repair_rate",
                "mean_surprise_on_damage",
            ],
        ),
        "",
        "## Mechanism Groups",
        "",
        _markdown_table(
            by_group,
            [
                "group",
                "n",
                "mean_gold_margin_gain",
                "damage_rate",
                "repair_rate",
                "mean_surprise_on_damage",
            ],
        ),
    ]
    if paired:
        lines.extend(
            [
                "",
                "## Direct vs Rationale",
                "",
                _markdown_table(
                    paired,
                    [
                        "step_type",
                        "group",
                        "n_paired",
                        "mean_direct_gold_margin_gain",
                        "mean_rationale_gold_margin_gain",
                        "mean_delta_protocol_gain",
                        "direct_damage_rate",
                        "rationale_damage_rate",
                    ],
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    visible = [column for column in columns if any(column in row for row in rows)]
    if not rows or not visible:
        return "_No rows._"
    lines = [
        "| " + " | ".join(visible) + " |",
        "| " + " | ".join("---" for _ in visible) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in visible) + " |")
    return "\n".join(lines)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _round(value: float) -> float:
    return round(float(value), 6)


def _normalize_step_type(value: str) -> str:
    return value.strip().replace("-", "_") or "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
