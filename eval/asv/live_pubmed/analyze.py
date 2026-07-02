from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_steps(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def aggregate_step_type_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["step_id"])].append(row)
    output: list[dict[str, Any]] = []
    for step_type in sorted(groups):
        items = groups[step_type]
        output.append(
            {
                "step_type": step_type,
                "count": len(items),
                "mean_realized_entropy_reduction": _mean(
                    float(item["asv_components"]["realized_entropy_reduction"]) for item in items
                ),
                "mean_net_asv": _mean(float(item["asv_components"]["net_asv"]) for item in items),
                "mean_cost_scalar": _mean(float(item["asv_components"]["cost_scalar"]) for item in items),
                "mean_gold_log_likelihood_gain": _mean(
                    float((item.get("gold_metrics") or {}).get("gold_log_likelihood_gain") or 0.0)
                    for item in items
                ),
                "floor_score_step_count": sum(
                    (item.get("quality_flags") or {}).get("used_floor_score") is True for item in items
                ),
                "cache_hit_step_count": sum(
                    (item.get("quality_flags") or {}).get("used_cache") is True for item in items
                ),
            }
        )
    return output


def write_analysis_tables(report_dir: Path) -> dict[str, Any]:
    rows = load_steps(report_dir / "steps.jsonl")
    summary = aggregate_step_type_rows(rows)
    tables_dir = report_dir / "tables"
    tables_dir.mkdir(exist_ok=True)
    csv_path = tables_dir / "step_type_summary.csv"
    fields = list(summary[0].keys()) if summary else ["step_type", "count"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary)
    payload = {"step_type_summary": summary}
    (report_dir / "analysis_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def _mean(values: Any) -> float:
    items = [float(value) for value in values]
    if not items:
        return 0.0
    return round(sum(items) / len(items), 6)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build live PubMed ASV analysis tables.")
    parser.add_argument("--report-dir", required=True)
    args = parser.parse_args(argv)
    write_analysis_tables(Path(args.report_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
