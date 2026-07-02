from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = ROOT / "eval" / "asv" / "experiments" / "biomed_step_value_smoke"
TRAJECTORY_PATH = EXPERIMENT_DIR / "trajectory.jsonl"
BELIEFS_PATH = EXPERIMENT_DIR / "beliefs.jsonl"
EXPECTED_SUMMARY_PATH = EXPERIMENT_DIR / "expected_summary.provided_belief.json"


def test_biomed_step_value_bundle_runs_with_provided_beliefs(tmp_path) -> None:
    output_dir = tmp_path / "provided-report"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "asv_eval",
            "evaluate",
            "--input",
            str(TRAJECTORY_PATH),
            "--belief-fixture",
            str(BELIEFS_PATH),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    expected = json.loads(EXPECTED_SUMMARY_PATH.read_text(encoding="utf-8"))
    for key, value in expected.items():
        assert summary[key] == value
    assert summary["evaluator"]["mode"] == "provided-belief"
    assert summary["evaluator_coverage"]["evaluated_state_count"] == 6

    steps = [
        json.loads(line)
        for line in (output_dir / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["step_id"] for row in steps] == [
        "classify",
        "retrieve",
        "synthesize",
    ]
    assert steps[1]["asv_components"]["realized_entropy_reduction"] > 0
