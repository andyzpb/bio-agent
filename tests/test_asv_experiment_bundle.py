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


SECRET_MARKERS = (
    "Bearer ",
    "api_key",
    "password",
    "token=",
    "raw_provider_response",
    "sk-live",
    "provider raw secret",
)


def test_biomed_step_value_bundle_contains_no_secret_markers() -> None:
    checked_paths = [
        EXPERIMENT_DIR / "trajectory.jsonl",
        EXPERIMENT_DIR / "beliefs.jsonl",
        EXPERIMENT_DIR / "expected_summary.provided_belief.json",
        EXPERIMENT_DIR / "README.md",
    ]
    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        for marker in SECRET_MARKERS:
            assert marker not in text, f"{marker!r} leaked in {path.name}"


def test_live_deepseek_smoke_docs_are_secret_safe_and_untracked_output_only() -> None:
    readme = (EXPERIMENT_DIR / "README.md").read_text(encoding="utf-8")
    script = (EXPERIMENT_DIR / "run_live_deepseek_smoke.sh").read_text(
        encoding="utf-8"
    )

    assert "zsh -ic" in readme
    assert "--evaluator deepseek-chat-logprob" in readme
    assert "--cache /tmp/asv-biomed-deepseek-cache.jsonl" in readme
    assert (
        "--write-evaluated-trajectories /tmp/asv-biomed-deepseek-evaluated.jsonl"
        in readme
    )
    assert "DEEPSEEK_API_KEY" in readme
    assert "fails automatically" in readme
    assert "live_deepseek_asv_smoke=passed" in readme
    assert "inspect /tmp/asv-biomed-deepseek/summary.json" not in readme
    assert "/tmp/asv-biomed-deepseek" in script
    assert script.count(".venv/bin/python -m asv_eval evaluate") == 2
    assert 'rm -rf "$OUTPUT_DIR" "$EVALUATED" "$CACHE"' in script
    assert (
        'coverage["cache_hit_state_count"] != coverage["evaluated_state_count"]'
        in script
    )
    assert 'Path("/tmp/asv-biomed-deepseek-evaluated.jsonl")' in script
    assert 'Path("/tmp/asv-biomed-deepseek-cache.jsonl")' in script
    assert 'Path("/tmp/asv-biomed-deepseek").rglob("*")' in script
    assert "if path.is_file()" in script
    for marker in (
        "Authorization",
        "client_secret",
        "sk-live",
        "provider_response",
        "raw_provider_response",
        "raw_response",
    ):
        assert f'"{marker}"' in script
    assert "raw provider" not in script.lower()
    assert "Bearer " not in script
