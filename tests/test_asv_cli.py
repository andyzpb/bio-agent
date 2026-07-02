from __future__ import annotations

import json
import subprocess
import sys

from asv_eval.adapters import load_standard_jsonl
from asv_eval.reporting import write_report_bundle


def _write_sample(path) -> None:
    path.write_text(
        json.dumps(
            {
                "trajectory_id": "traj-1",
                "task": {
                    "task_id": "task-1",
                    "question": "Does the evidence support alpha?",
                    "candidate_space": {
                        "candidates": [
                            {"id": "supported", "label": "A", "text": "supported"},
                            {"id": "refuted", "label": "B", "text": "refuted"},
                        ],
                        "gold_candidate_id": "supported",
                    },
                },
                "steps": [
                    {
                        "step_id": "s1",
                        "index": 0,
                        "action": {"type": "search"},
                        "observation": {"text": "trial found benefit"},
                        "belief_before": {"supported": 0.55, "refuted": 0.45},
                        "belief_after": {"supported": 0.82, "refuted": 0.18},
                        "cost": {"prompt_tokens": 1000, "tool_calls": 1},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_reporter_writes_expected_bundle(tmp_path) -> None:
    input_path = tmp_path / "sample.jsonl"
    output_dir = tmp_path / "out"
    _write_sample(input_path)

    summary = write_report_bundle(load_standard_jsonl(input_path), output_dir)

    assert summary["trajectory_count"] == 1
    assert summary["step_count"] == 1
    assert (output_dir / "steps.jsonl").exists()
    assert (output_dir / "states.jsonl").exists()
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "tables" / "steps.csv").exists()
    assert (output_dir / "interventions.json").exists()
    assert (output_dir / "report.md").read_text(encoding="utf-8").startswith(
        "# Agent Step Value Report"
    )


def test_cli_evaluate_smoke(tmp_path) -> None:
    input_path = tmp_path / "sample.jsonl"
    output_dir = tmp_path / "out"
    _write_sample(input_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "asv_eval",
            "evaluate",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "trajectory_count=1" in result.stdout
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["mean_realized_entropy_reduction"] > 0
