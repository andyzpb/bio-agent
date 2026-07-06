from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from asv_eval.adapters import load_standard_jsonl
from asv_eval.reporting import write_report_bundle

ROOT = Path(__file__).resolve().parents[1]


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
                        "raw_scores_before": {"supported": -0.6, "refuted": -0.8},
                        "raw_scores_after": {"supported": -0.1, "refuted": -2.0},
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
    assert (
        (output_dir / "report.md")
        .read_text(encoding="utf-8")
        .startswith("# Agent Step Value Report")
    )
    steps_csv = (output_dir / "tables" / "steps.csv").read_text(encoding="utf-8")
    assert "gold_margin_gain" in steps_csv
    assert "semantic_gold_gain" in steps_csv
    assert "bayesian_surprise_kl" in steps_csv


def test_reporter_writes_medium_tables(tmp_path) -> None:
    input_path = tmp_path / "medium.jsonl"
    output_dir = tmp_path / "out"
    rows = []
    for trajectory_id, after_supported in [("traj-1", 0.82), ("traj-2", 0.35)]:
        rows.append(
            {
                "trajectory_id": trajectory_id,
                "task": {
                    "task_id": f"{trajectory_id}-task",
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
                        "step_id": f"{trajectory_id}-retrieve",
                        "index": 0,
                        "action": {"type": "retrieve"},
                        "belief_before": {"supported": 0.55, "refuted": 0.45},
                        "belief_after": {
                            "supported": after_supported,
                            "refuted": 1 - after_supported,
                        },
                        "raw_scores_before": {"supported": -0.6, "refuted": -0.8},
                        "raw_scores_after": {
                            "supported": -0.1 if after_supported > 0.5 else -1.1,
                            "refuted": -2.0 if after_supported > 0.5 else -0.2,
                        },
                    }
                ],
            }
        )
    input_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    summary = write_report_bundle(load_standard_jsonl(input_path), output_dir)

    assert summary["trajectory_bootstrap"]["trajectory_count"] == 2
    assert summary["trajectory_bootstrap"]["resamples"] == 5000
    assert (output_dir / "tables" / "trajectory_summary.csv").exists()
    assert (output_dir / "tables" / "step_type_summary.csv").exists()
    trajectory_csv = (output_dir / "tables" / "trajectory_summary.csv").read_text(
        encoding="utf-8"
    )
    step_type_csv = (output_dir / "tables" / "step_type_summary.csv").read_text(
        encoding="utf-8"
    )
    assert "mean_gold_margin_gain" in trajectory_csv
    assert "retrieve" in step_type_csv
    assert "pos,zero,neg" in step_type_csv


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


def test_cli_adapt_open_qa_candidate_answer_spec(tmp_path) -> None:
    input_path = tmp_path / "open_qa.jsonl"
    output_path = tmp_path / "trajectory.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "trajectory_id": "open-qa-cli",
                "question": "Which candidate answer best explains the result?",
                "candidate_answers": [
                    {"id": "answer-a", "text": "Alpha explains the result."},
                    {"id": "answer-b", "text": "Beta explains the result."},
                    {
                        "id": "none-of-the-above",
                        "text": "Evidence is insufficient to support any candidate.",
                    },
                ],
                "gold_candidate_id": "answer-b",
                "steps": [
                    {
                        "step_id": "read",
                        "index": 0,
                        "action": {"type": "read"},
                        "observation": {"text": "beta evidence"},
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
            "adapt-open-qa",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "trajectory_count=1" in result.stdout
    [trajectory] = load_standard_jsonl(output_path)
    assert trajectory.task.candidate_space.type == "candidate_set"
    assert trajectory.task.candidate_space.gold_candidate_id == "answer-b"
    assert [
        candidate.label for candidate in trajectory.task.candidate_space.candidates
    ] == [
        "A",
        "B",
        "C",
    ]


def test_cli_audit_permutations_rotates_candidate_labels(tmp_path) -> None:
    input_path = tmp_path / "trajectory.jsonl"
    output_path = tmp_path / "permuted.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "trajectory_id": "traj-permute",
                "task": {
                    "task_id": "task-permute",
                    "question": "Which answer is best?",
                    "candidate_space": {
                        "type": "candidate_set",
                        "candidates": [
                            {"id": "answer-a", "label": "A", "text": "Alpha."},
                            {"id": "answer-b", "label": "B", "text": "Beta."},
                            {"id": "none-of-the-above", "label": "C", "text": "None."},
                        ],
                        "gold_candidate_id": "answer-b",
                    },
                },
                "steps": [
                    {
                        "step_id": "s1",
                        "index": 0,
                        "action": {"type": "retrieve"},
                        "belief_before": {
                            "answer-a": 0.3,
                            "answer-b": 0.4,
                            "none-of-the-above": 0.3,
                        },
                        "belief_after": {
                            "answer-a": 0.2,
                            "answer-b": 0.7,
                            "none-of-the-above": 0.1,
                        },
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
            "audit-permutations",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--b",
            "3",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "trajectory_count=3" in result.stdout
    trajectories = load_standard_jsonl(output_path)
    assert [trajectory.trajectory_id for trajectory in trajectories] == [
        "traj-permute-permutation-0",
        "traj-permute-permutation-1",
        "traj-permute-permutation-2",
    ]
    assert [
        candidate.label
        for candidate in trajectories[1].task.candidate_space.candidates
    ] == ["C", "A", "B"]
    assert [
        candidate.id for candidate in trajectories[1].task.candidate_space.candidates
    ] == ["answer-a", "answer-b", "none-of-the-above"]
    assert trajectories[1].metadata["label_permutation_index"] == 1


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
    monkeypatch.setattr(
        cli, "_build_deepseek_evaluator", lambda config: FakeEvaluator()
    )

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
        json.loads(line)
        for line in evaluated_path.read_text(encoding="utf-8").splitlines()
    ]
    step = evaluated["steps"][0]
    assert step["belief_before"] is not None
    assert step["belief_after"]["supported"] > 0.9
    assert "api_key" not in evaluated_path.read_text(encoding="utf-8")
    [report_step] = [
        json.loads(line)
        for line in (output_dir / "steps.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    quality_flags = report_step["quality_flags"]
    assert quality_flags["evaluator_mode"] == "deepseek_chat_logprob"
    assert quality_flags["provider"] == "deepseek"
    assert quality_flags["model"] == "deepseek-chat"
    assert quality_flags["used_cache"] is False
    assert quality_flags["state_before_hash"].startswith("sha256:")
    assert quality_flags["state_after_hash"].startswith("sha256:")
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["evaluator"]["mode"] == "deepseek-chat-logprob"
    assert summary["evaluator_coverage"]["evaluated_state_count"] == 2
    for path in [output_dir / "summary.json", output_dir / "steps.jsonl"]:
        assert "api_key" not in path.read_text(encoding="utf-8")


def test_cli_evaluate_writes_run_ledger_and_medium_tables(
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
    ledger_path = tmp_path / "run-ledger.jsonl"
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
                        "action": {"type": "retrieve"},
                        "state_before": {"evidence": "baseline beta"},
                        "state_after": {"evidence": "alpha improved beta"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli, "_build_deepseek_evaluator", lambda config: FakeEvaluator()
    )

    exit_code = cli.main(
        [
            "evaluate",
            "--input",
            str(input_path),
            "--evaluator",
            "deepseek-chat-logprob",
            "--run-ledger",
            str(ledger_path),
            "--bootstrap-resamples",
            "10",
            "--bootstrap-seed",
            "3",
            "--max-concurrency",
            "2",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert ledger_path.exists()
    assert len(ledger_path.read_text(encoding="utf-8").splitlines()) == 2
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["trajectory_bootstrap"]["resamples"] == 10
    assert summary["trajectory_bootstrap"]["seed"] == 3
    assert summary["evaluator"]["max_concurrency"] == 2
    assert (output_dir / "tables" / "trajectory_summary.csv").exists()
    assert (output_dir / "tables" / "step_type_summary.csv").exists()


def test_evaluate_accepts_floor_score_runtime_config(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    beliefs_path = tmp_path / "beliefs.jsonl"
    output_dir = tmp_path / "report"
    input_path.write_text(
        json.dumps(
            {
                "trajectory_id": "floor-score-cli",
                "task": {
                    "task_id": "floor-score-cli-task",
                    "question": "Does alpha improve beta?",
                    "candidate_space": {
                        "candidates": [
                            {"id": "supported", "label": "A", "text": "supported"},
                            {"id": "refuted", "label": "B", "text": "refuted"},
                            {
                                "id": "not_enough_information",
                                "label": "C",
                                "text": "not enough information",
                            },
                        ]
                    },
                },
                "steps": [
                    {
                        "step_id": "retrieve",
                        "index": 0,
                        "action": {"type": "retrieve"},
                        "observation": {"summary": "evidence"},
                        "state_before": {"question": "Does alpha improve beta?"},
                        "state_after": {"evidence": "alpha improved beta"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    beliefs_path.write_text(
        json.dumps(
            {
                "trajectory_id": "floor-score-cli",
                "step_id": "retrieve",
                "belief_before": {
                    "supported": 0.34,
                    "refuted": 0.33,
                    "not_enough_information": 0.33,
                },
                "belief_after": {
                    "supported": 0.70,
                    "refuted": 0.15,
                    "not_enough_information": 0.15,
                },
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
            str(beliefs_path),
            "--floor-score",
            "-15",
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
    assert summary["evaluator"]["floor_score"] == -15.0
