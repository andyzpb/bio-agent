from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from asv_eval.core import (
    Candidate,
    CandidateSpace,
    StepRecord,
    TaskRecord,
    TrajectoryRecord,
)
from eval.asv.open_qa import collect as collect_module
from eval.asv.open_qa import generate as generate_module
from eval.asv.open_qa import run_experiment as run_experiment_module
from eval.asv.open_qa.collect import attach_candidate_set_to_trajectory
from eval.asv.open_qa.generate import (
    OpenQAQuestion,
    build_generation_prompt,
    generate_candidate_specs,
    load_open_qa_questions,
)
from eval.asv.open_qa.run_experiment import ExperimentRun, build_run_commands

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "eval" / "asv" / "open_qa" / "questions.quick.jsonl"


def test_open_qa_question_set_has_expected_mix() -> None:
    questions = load_open_qa_questions(QUESTIONS)

    counts = {
        "intervention": 0,
        "risk": 0,
        "mechanism": 0,
        "diagnostic": 0,
        "insufficient_evidence": 0,
    }
    assert len(questions) == 10
    for row in questions:
        counts[row.category] += 1

    assert counts == {
        "intervention": 3,
        "risk": 2,
        "mechanism": 2,
        "diagnostic": 2,
        "insufficient_evidence": 1,
    }


def test_generation_prompt_requires_four_candidates_and_none_option() -> None:
    question = load_open_qa_questions(QUESTIONS)[0]
    prompt = build_generation_prompt(question)

    assert "four candidate answers" in prompt
    assert "none-of-the-above" in prompt
    assert "gold_candidate_id" in prompt
    assert "Return only JSON" in prompt
    assert "chain-of-thought" not in prompt.lower()


def test_attach_candidate_set_to_trajectory_preserves_steps() -> None:
    base = TrajectoryRecord(
        trajectory_id="bio-agent-run-1",
        task=TaskRecord(
            task_id="run-1",
            question="Which answer is right?",
            candidate_space=CandidateSpace(
                candidates=[
                    Candidate(id="supported", label="A", text="supported"),
                    Candidate(id="refuted", label="B", text="refuted"),
                ]
            ),
        ),
        steps=[
            StepRecord(
                step_id="retrieve",
                index=0,
                action={"type": "retrieve"},
            )
        ],
    )
    reviewed = {
        "trajectory_id": "open-qa-1",
        "question": "Which answer is right?",
        "candidate_answers": [
            {"id": "answer-a", "text": "Alpha."},
            {"id": "answer-b", "text": "Beta."},
            {"id": "answer-c", "text": "Gamma."},
            {"id": "none-of-the-above", "text": "Insufficient evidence."},
        ],
        "gold_candidate_id": "answer-b",
    }

    updated = attach_candidate_set_to_trajectory(base, reviewed)

    assert updated.task.candidate_space.type == "candidate_set"
    assert updated.task.candidate_space.gold_candidate_id == "answer-b"
    assert [candidate.id for candidate in updated.task.candidate_space.candidates] == [
        "answer-a",
        "answer-b",
        "answer-c",
        "none-of-the-above",
    ]
    assert updated.steps == base.steps
    assert updated.metadata["experiment"] == "open_qa_candidate_generation"


def test_run_experiment_builds_preserved_artifact_commands(tmp_path) -> None:
    run = ExperimentRun(
        artifact_root=tmp_path / "artifacts",
        questions_path=Path("questions.jsonl"),
        reviewed_path=None,
        candidate_provider="deepseek",
        candidate_model="deepseek-v4-flash",
        actor_provider="deepseek",
        actor_model="deepseek-v4-flash",
        evaluator_model="deepseek-chat",
        rationale_mode="label-free",
        rationale_max_tokens=256,
        rationale_leakage_policy="warn",
        ack_live=True,
    )

    commands = build_run_commands(run)
    rendered = "\n".join(" ".join(command) for command in commands)

    assert "eval.asv.open_qa.generate" in rendered
    assert "eval.asv.open_qa.collect" in rendered
    assert "asv_eval" in rendered
    assert "audit-permutations" in rendered
    assert str(run.generated_path) in rendered
    assert str(run.reviewed_artifact_path) in rendered
    assert str(run.ledger_path) in rendered
    assert str(run.permutation_ledger_path) in rendered
    assert "--append --resume" in rendered
    assert rendered.count("--max-concurrency 1") == 4
    assert rendered.count("--rationale-mode label-free") == 2
    assert rendered.count("--rationale-max-tokens 256") == 2
    assert rendered.count("--rationale-leakage-policy warn") == 2


def test_run_experiment_runs_adapt_when_reviewed_path_is_provided(
    tmp_path,
    monkeypatch,
) -> None:
    reviewed = tmp_path / "reviewed.jsonl"
    reviewed.write_text(
        json.dumps(_candidate_spec("q1", "Question one?")) + "\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        run_experiment_module,
        "_run",
        lambda command, commands_log: calls.append(command),
    )
    monkeypatch.setattr(
        run_experiment_module,
        "_write_permutation_stability",
        lambda run: None,
    )
    monkeypatch.setattr(run_experiment_module, "_write_results", lambda run: None)

    exit_code = run_experiment_module.run_experiment(
        ExperimentRun(
            artifact_root=tmp_path / "artifacts",
            questions_path=None,
            reviewed_path=reviewed,
            ack_live=True,
        )
    )

    assert exit_code == 0
    assert "adapt-open-qa" in calls[0]
    assert "eval.asv.open_qa.collect" in " ".join(calls[1])


def test_generate_deepseek_provider_defaults_to_deepseek_base_url(
    tmp_path,
    monkeypatch,
) -> None:
    questions = tmp_path / "questions.jsonl"
    output = tmp_path / "generated.jsonl"
    questions.write_text(
        json.dumps(
            {
                "question_id": "q1",
                "category": "intervention",
                "question": "Which answer is right?",
                "source": "pubmed",
                "max_papers": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeProvider:
        kwargs: dict[str, object] = {}

        def __init__(self, **kwargs: object) -> None:
            type(self).kwargs = dict(kwargs)

        async def chat(self, *args, **kwargs):  # noqa: ANN001, ANN202
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "trajectory_id": "q1",
                        "question": "Which answer is right?",
                        "candidate_answers": [
                            {"id": "answer-a", "text": "Alpha."},
                            {"id": "answer-b", "text": "Beta."},
                            {"id": "answer-c", "text": "Gamma."},
                            {
                                "id": "none-of-the-above",
                                "text": "Evidence is insufficient.",
                            },
                        ],
                        "gold_candidate_id": "none-of-the-above",
                    }
                )
            )

    monkeypatch.setenv("FAKE_DEEPSEEK_KEY", "secret")
    monkeypatch.setattr(generate_module, "LLMProvider", FakeProvider)

    exit_code = generate_module.main(
        [
            "--questions",
            str(questions),
            "--output",
            str(output),
            "--provider",
            "deepseek",
            "--api-key-env",
            "FAKE_DEEPSEEK_KEY",
        ]
    )

    assert exit_code == 0
    assert FakeProvider.kwargs["base_url"] == "https://api.deepseek.com/v1"


def test_generate_resume_appends_only_missing_specs(tmp_path, monkeypatch) -> None:
    questions = tmp_path / "questions.jsonl"
    output = tmp_path / "generated.jsonl"
    questions.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question_id": "q1",
                        "category": "intervention",
                        "question": "Question one?",
                        "source": "pubmed",
                        "max_papers": 1,
                    }
                ),
                json.dumps(
                    {
                        "question_id": "q2",
                        "category": "risk",
                        "question": "Question two?",
                        "source": "pubmed",
                        "max_papers": 1,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output.write_text(
        json.dumps(_candidate_spec("q1", "Question one?"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    class FakeProvider:
        prompts: list[str] = []

        def __init__(self, **kwargs: object) -> None:
            pass

        async def chat(self, messages, *args, **kwargs):  # noqa: ANN001, ANN202
            prompt = str(messages[0]["content"])
            type(self).prompts.append(prompt)
            return SimpleNamespace(
                content=json.dumps(_candidate_spec("q2", "Question two?"))
            )

    monkeypatch.setenv("FAKE_DEEPSEEK_KEY", "secret")
    monkeypatch.setattr(generate_module, "LLMProvider", FakeProvider)

    exit_code = generate_module.main(
        [
            "--questions",
            str(questions),
            "--output",
            str(output),
            "--provider",
            "deepseek",
            "--api-key-env",
            "FAKE_DEEPSEEK_KEY",
            "--append",
            "--resume",
        ]
    )

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert exit_code == 0
    assert [row["trajectory_id"] for row in rows] == ["q1", "q2"]
    assert len(FakeProvider.prompts) == 1
    assert "Question two?" in FakeProvider.prompts[0]


def test_generate_candidate_specs_honors_max_concurrency() -> None:
    questions = [
        OpenQAQuestion(
            question_id="q1",
            category="intervention",
            question="Question one?",
        ),
        OpenQAQuestion(
            question_id="q2",
            category="risk",
            question="Question two?",
        ),
        OpenQAQuestion(
            question_id="q3",
            category="mechanism",
            question="Question three?",
        ),
    ]

    class FakeProvider:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def chat(self, messages, *args, **kwargs):  # noqa: ANN001, ANN202
            prompt = str(messages[0]["content"])
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            if "Question two?" in prompt:
                return SimpleNamespace(
                    content=json.dumps(_candidate_spec("q2", "Question two?"))
                )
            if "Question three?" in prompt:
                return SimpleNamespace(
                    content=json.dumps(_candidate_spec("q3", "Question three?"))
                )
            return SimpleNamespace(
                content=json.dumps(_candidate_spec("q1", "Question one?"))
            )

    provider = FakeProvider()
    rows = asyncio.run(
        generate_candidate_specs(
            questions,
            provider=provider,
            model="fake-model",
            max_concurrency=2,
        )
    )

    assert [row["trajectory_id"] for row in rows] == ["q1", "q2", "q3"]
    assert provider.max_active == 2


def test_collect_deepseek_provider_defaults_to_deepseek_base_url(monkeypatch) -> None:
    class FakeProvider:
        kwargs: dict[str, object] = {}

        def __init__(self, **kwargs: object) -> None:
            type(self).kwargs = dict(kwargs)

    monkeypatch.setenv("FAKE_ACTOR_KEY", "secret")
    monkeypatch.setattr(collect_module, "LLMProvider", FakeProvider)

    provider = collect_module._build_actor_provider_from_args(
        SimpleNamespace(
            actor_provider="deepseek",
            actor_model="deepseek-v4-flash",
            actor_api_key_env="FAKE_ACTOR_KEY",
            actor_base_url=None,
        ),
        argparse.ArgumentParser(),
    )

    assert isinstance(provider, FakeProvider)
    assert FakeProvider.kwargs["base_url"] == "https://api.deepseek.com/v1"


def test_collect_open_qa_honors_max_concurrency(tmp_path) -> None:
    specs = [
        _candidate_spec("q1", "Question one?"),
        _candidate_spec("q2", "Question two?"),
        _candidate_spec("q3", "Question three?"),
    ]

    class FakeService:
        active = 0
        max_active = 0
        workspaces: list[Path] = []

        def __init__(self, workspace, **kwargs):  # noqa: ANN001, ANN003
            type(self).workspaces.append(Path(workspace))

        async def answer_with_audit(self, request):  # noqa: ANN001, ANN202
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
            await asyncio.sleep(0.01)
            type(self).active -= 1
            return SimpleNamespace(answer_result=SimpleNamespace(run_id=request.question))

        def export_answer_run_asv_trajectory(self, run_id):  # noqa: ANN001, ANN202
            return TrajectoryRecord(
                trajectory_id=f"source-{run_id}",
                task=TaskRecord(
                    task_id=f"source-{run_id}",
                    question=str(run_id),
                    candidate_space=CandidateSpace(
                        candidates=[
                            Candidate(id="source-a", label="A", text="Alpha."),
                            Candidate(id="source-b", label="B", text="Beta."),
                        ]
                    ),
                ),
                steps=[
                    StepRecord(
                        step_id=f"step-{run_id}",
                        index=0,
                        action={"type": "retrieve"},
                    )
                ],
            )

    rows, trajectories = collect_module.collect_open_qa.run_sync(
        specs,
        config=collect_module.OpenQACollectionConfig(
            reviewed_path=tmp_path / "reviewed.jsonl",
            output_dir=tmp_path / "out",
            workspace=tmp_path / "workspace",
            max_concurrency=2,
        ),
        service_factory=FakeService,
    )

    assert [row.status for row in rows] == ["completed", "completed", "completed"]
    assert [trajectory.trajectory_id for trajectory in trajectories] == ["q1", "q2", "q3"]
    assert FakeService.max_active == 2
    assert len(set(FakeService.workspaces)) == 3


def _candidate_spec(question_id: str, question: str) -> dict[str, object]:
    return {
        "trajectory_id": question_id,
        "question": question,
        "candidate_answers": [
            {"id": "answer-a", "text": "Alpha."},
            {"id": "answer-b", "text": "Beta."},
            {"id": "answer-c", "text": "Gamma."},
            {
                "id": "none-of-the-above",
                "text": "Evidence is insufficient.",
            },
        ],
        "gold_candidate_id": "none-of-the-above",
    }
