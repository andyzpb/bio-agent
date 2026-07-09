from __future__ import annotations

import json
from pathlib import Path

from asv_eval.__main__ import main


def test_probe_provider_writes_failure_when_labels_are_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "trajectory.jsonl"
    output_dir = tmp_path / "gate"
    input_path.write_text(
        json.dumps(
            {
                "trajectory_id": "t1",
                "schema_version": "asv.v1",
                "source_adapter": "test",
                "task": {
                    "task_id": "task-1",
                    "question": "Which answer is supported?",
                    "candidate_space": {
                        "gold_candidate_id": "answer-a",
                        "type": "candidate_set",
                        "candidates": [
                            {"id": "answer-a", "label": "A", "text": "Alpha"},
                            {"id": "answer-b", "label": "B", "text": "Beta"},
                            {"id": "answer-c", "label": "C", "text": "Gamma"},
                            {
                                "id": "none-of-the-above",
                                "label": "D",
                                "text": "Insufficient evidence",
                            },
                        ],
                    },
                },
                "steps": [
                    {
                        "step_id": "s1",
                        "index": 0,
                        "action": {"type": "retrieve"},
                        "state_before": {"evidence": "none"},
                        "state_after": {"evidence": "alpha"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class _MissingEvaluator:
        def score_state(
            self,
            *,
            question,
            evidence_text,
            labels,
            candidate_texts=None,
            rationale_text=None,
        ):
            _ = question, evidence_text, labels, candidate_texts, rationale_text
            return (
                {
                    "answer-a": -20.0,
                    "answer-b": -20.0,
                    "answer-c": -20.0,
                    "none-of-the-above": 0.0,
                },
                [
                    "missing label for candidate answer-a; floor score used",
                    "missing label for candidate answer-b; floor score used",
                    "missing label for candidate answer-c; floor score used",
                ],
            )

    monkeypatch.setattr(
        "asv_eval.__main__._build_deepseek_evaluator",
        lambda config: _MissingEvaluator(),
    )

    code = main(
        [
            "probe-provider",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--evaluator",
            "deepseek-chat-logprob",
            "--fallback-policy",
            "floor",
            "--sample-trajectories",
            "1",
            "--min-all-label-coverage",
            "1.0",
        ]
    )

    summary = json.loads((output_dir / "provider_gate.json").read_text())
    assert code == 2
    assert summary["status"] == "failed"
    assert summary["state_count"] == 2
    assert summary["all_label_coverage_rate"] == 0.0
