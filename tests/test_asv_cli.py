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


def test_cli_evaluate_applies_belief_fixture(tmp_path) -> None:
    input_path = tmp_path / "sample.jsonl"
    output_dir = tmp_path / "out"
    fixture_path = tmp_path / "beliefs.jsonl"
    input_path.write_text(
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
                        ]
                    },
                },
                "steps": [
                    {
                        "step_id": "s1",
                        "index": 0,
                        "action": {"type": "retrieve"},
                        "observation": {"text": "trial found benefit"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    fixture_path.write_text(
        json.dumps(
            {
                "trajectory_id": "traj-1",
                "step_id": "s1",
                "belief_before": {"supported": 0.5, "refuted": 0.5},
                "belief_after": {"supported": 0.8, "refuted": 0.2},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "asv_eval",
            "evaluate",
            "--input",
            str(input_path),
            "--belief-fixture",
            str(fixture_path),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["mean_realized_entropy_reduction"] > 0


def test_cli_evaluate_missing_beliefs_explains_evaluator_options(tmp_path) -> None:
    input_path = tmp_path / "missing-beliefs.jsonl"
    output_dir = tmp_path / "report"
    input_path.write_text(
        json.dumps(
            {
                "trajectory_id": "traj-1",
                "task": {
                    "task_id": "task-1",
                    "question": "Does alpha improve beta?",
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
                        "action": {"type": "read"},
                        "state_before": {"evidence": "baseline beta"},
                        "state_after": {"evidence": "alpha improved beta"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

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

    assert result.returncode != 0
    assert "--belief-fixture" in result.stderr
    assert "--evaluator deepseek-chat-logprob" in result.stderr


def test_cli_evaluate_writes_evaluated_trajectories_with_runtime(
    monkeypatch,
    tmp_path,
) -> None:
    from asv_eval import __main__ as cli

    class FakeEvaluator:
        def score_state(self, *, question, evidence_text, labels):
            _ = question, labels
            if "alpha improved beta" in evidence_text:
                return {"supported": 0.0, "refuted": -5.0}, []
            return {"supported": -1.0, "refuted": -1.0}, []

    input_path = tmp_path / "missing-beliefs.jsonl"
    output_dir = tmp_path / "report"
    evaluated_path = tmp_path / "evaluated" / "trajectories.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "trajectory_id": "traj-1",
                "task": {
                    "task_id": "task-1",
                    "question": "Does alpha improve beta?",
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
                        "action": {"type": "read"},
                        "state_before": {"evidence": "baseline beta"},
                        "state_after": {"evidence": "alpha improved beta"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_build_deepseek_evaluator", lambda config: FakeEvaluator())

    exit_code = cli.main(
        [
            "evaluate",
            "--input",
            str(input_path),
            "--evaluator",
            "deepseek-chat-logprob",
            "--write-evaluated-trajectories",
            str(evaluated_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    [evaluated] = [
        json.loads(line) for line in evaluated_path.read_text(encoding="utf-8").splitlines()
    ]
    step = evaluated["steps"][0]
    assert step["belief_before"] is not None
    assert step["belief_after"]["supported"] > 0.9
    [report_step] = [
        json.loads(line)
        for line in (output_dir / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    quality_flags = report_step["quality_flags"]
    assert quality_flags["evaluator_mode"] == "deepseek_chat_logprob"
    assert quality_flags["provider"] == "deepseek"
    assert quality_flags["model"] == "deepseek-v4-flash"
    assert quality_flags["used_cache"] is False
    assert quality_flags["state_before_hash"].startswith("sha256:")
    assert quality_flags["state_after_hash"].startswith("sha256:")
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["evaluator"]["mode"] == "deepseek-chat-logprob"
