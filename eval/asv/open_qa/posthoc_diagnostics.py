from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from asv_eval.core import bayesian_surprise_kl, entropy_nats, normalize_log_scores

DEFAULT_ROOT = Path("eval/asv/experiments/asv_medium_openqa_20260705_live_main")


def main() -> None:
    args = _parse_args()
    summary = run(Path(args.root))
    print(json.dumps(summary, indent=2, sort_keys=True))


def run(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    rows = _load_jsonl(root / "report" / "steps.jsonl")
    tables = root / "report" / "tables"
    tables.mkdir(parents=True, exist_ok=True)

    pivot_rows, pivot_summary = _pivot_counts(rows)
    surprise_rows = _surprise_sensitivity(rows)
    floor_rows = _floor_sensitivity(rows)

    _write_csv(tables / "pivot_counts.csv", pivot_rows)
    _write_csv(tables / "surprise_sensitivity.csv", surprise_rows)
    _write_csv(tables / "floor_sensitivity.csv", floor_rows)
    summary = {
        "pivot_counts": pivot_summary,
        "surprise_sensitivity": surprise_rows,
        "floor_sensitivity": floor_rows,
    }
    (root / "report" / "posthoc_diagnostics.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _pivot_counts(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {"overall": rows}
    for row in rows:
        step_type = _step_type(row)
        groups.setdefault(step_type, []).append(row)
    out = [_pivot_row(name, group) for name, group in sorted(groups.items())]
    return out, {row["group"]: row for row in out}


def _pivot_row(group: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    pivot_count = 0
    target_directed = 0
    target_destructive = 0
    for row in rows:
        before = _argmax(row.get("belief_before") or {})
        after = _argmax(row.get("belief_after") or {})
        gold = (row.get("gold_metrics") or {}).get("gold_candidate_id")
        if before is None or after is None or before == after:
            continue
        pivot_count += 1
        if gold and after == gold and before != gold:
            target_directed += 1
        if gold and before == gold and after != gold:
            target_destructive += 1
    n = len(rows)
    return {
        "group": group,
        "step_count": n,
        "pivot_count": pivot_count,
        "pivot_rate": _round(pivot_count / n if n else 0.0),
        "target_directed_pivots": target_directed,
        "target_destructive_pivots": target_destructive,
    }


def _surprise_sensitivity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for epsilon in (1e-4, 1e-6, 1e-8):
        values = [
            bayesian_surprise_kl(
                row.get("belief_before") or {},
                row.get("belief_after") or {},
                epsilon=epsilon,
            )
            for row in rows
        ]
        out.append(
            {
                "setting": f"epsilon={epsilon:g}",
                "mean_bayesian_surprise_kl": _round(_mean(values)),
                "max_bayesian_surprise_kl": _round(max(values) if values else 0.0),
                "nonzero_count": sum(value > 1e-12 for value in values),
            }
        )
    for tau in (1.0, 2.0, 5.0, 10.0):
        before_entropies = []
        after_entropies = []
        nonzero_movements = 0
        for row in rows:
            before = _temperature_scaled_belief(row.get("raw_scores_before") or {}, tau)
            after = _temperature_scaled_belief(row.get("raw_scores_after") or {}, tau)
            before_entropy = entropy_nats(before)
            after_entropy = entropy_nats(after)
            before_entropies.append(before_entropy)
            after_entropies.append(after_entropy)
            if abs(before_entropy - after_entropy) > 1e-12:
                nonzero_movements += 1
        out.append(
            {
                "setting": f"tau={tau:g}",
                "mean_entropy_before": _round(_mean(before_entropies)),
                "mean_entropy_after": _round(_mean(after_entropies)),
                "mean_entropy_movement": _round(
                    _mean([b - a for b, a in zip(before_entropies, after_entropies)])
                ),
                "nonzero_entropy_movement_count": nonzero_movements,
            }
        )
    return out


def _floor_sensitivity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for floor_score in (-10.0, -20.0, -30.0):
        gains = []
        floor_steps = 0
        for row in rows:
            flags = row.get("quality_flags") or {}
            before = dict(row.get("raw_scores_before") or {})
            after = dict(row.get("raw_scores_after") or {})
            if flags.get("used_floor_score"):
                floor_steps += 1
                old_floor = float(flags.get("floor_score", -20.0))
                _replace_floor_values(before, old_floor, floor_score)
                _replace_floor_values(after, old_floor, floor_score)
            gold = (row.get("gold_metrics") or {}).get("gold_candidate_id")
            if gold in before and gold in after:
                gains.append(_margin(after, gold) - _margin(before, gold))
        out.append(
            {
                "floor_score": floor_score,
                "mean_gold_margin_gain": _round(_mean(gains)),
                "floor_step_count": floor_steps,
                "sign": _sign(_mean(gains)),
            }
        )
    return out


def _replace_floor_values(scores: dict[str, float], old: float, new: float) -> None:
    for key, value in list(scores.items()):
        if math.isclose(float(value), old, rel_tol=0.0, abs_tol=1e-9):
            scores[key] = new


def _temperature_scaled_belief(scores: dict[str, float], tau: float) -> dict[str, float]:
    if not scores:
        return {}
    return normalize_log_scores({key: float(value) / tau for key, value in scores.items()})


def _margin(scores: dict[str, float], gold: str) -> float:
    others = [float(value) for key, value in scores.items() if key != gold]
    return float(scores[gold]) - _logsumexp(others)


def _logsumexp(values: list[float]) -> float:
    peak = max(values)
    return peak + math.log(sum(math.exp(value - peak) for value in values))


def _argmax(probs: dict[str, float]) -> str | None:
    if not probs:
        return None
    return max(probs.items(), key=lambda item: float(item[1]))[0]


def _step_type(row: dict[str, Any]) -> str:
    action = row.get("action") if isinstance(row.get("action"), dict) else {}
    return str(action.get("type") or "unknown").replace("_", "-")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _round(value: float) -> float:
    return round(float(value), 6)


def _sign(value: float) -> str:
    if value > 1e-12:
        return "positive"
    if value < -1e-12:
        return "negative"
    return "zero"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    return parser.parse_args()


if __name__ == "__main__":
    main()
