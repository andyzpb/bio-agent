from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from eval.asv.live_pubmed.robustness import summarize_permutation_stability


@dataclass(frozen=True)
class ExperimentRun:
    artifact_root: Path
    questions_path: Path | None
    reviewed_path: Path | None
    candidate_provider: str | None = None
    candidate_model: str = "deepseek-v4-flash"
    actor_provider: str | None = None
    actor_model: str | None = None
    evaluator_model: str = "deepseek-chat"
    rationale_mode: str = "off"
    rationale_max_tokens: int = 128
    rationale_leakage_policy: str = "error"
    max_concurrency: int = 1
    workspace: Path | None = None
    ack_live: bool = False
    python_executable: str = sys.executable

    @property
    def generated_path(self) -> Path:
        return self.artifact_root / "generated.candidate_answers.jsonl"

    @property
    def reviewed_artifact_path(self) -> Path:
        return self.artifact_root / "reviewed.candidate_answers.jsonl"

    @property
    def adapted_path(self) -> Path:
        return self.artifact_root / "reviewed.asv.jsonl"

    @property
    def collection_dir(self) -> Path:
        return self.artifact_root / "collection"

    @property
    def collection_workspace(self) -> Path:
        return self.workspace or (self.artifact_root / "workspace")

    @property
    def collected_trajectory_path(self) -> Path:
        return self.collection_dir / "trajectory.jsonl"

    @property
    def report_dir(self) -> Path:
        return self.artifact_root / "report"

    @property
    def cache_path(self) -> Path:
        return self.artifact_root / "evaluator-cache.jsonl"

    @property
    def evaluated_path(self) -> Path:
        return self.artifact_root / "evaluated.trajectory.jsonl"

    @property
    def ledger_path(self) -> Path:
        return self.artifact_root / "run-ledger.jsonl"

    @property
    def permutations_path(self) -> Path:
        return self.artifact_root / "label-permutations.trajectory.jsonl"

    @property
    def permutation_ledger_path(self) -> Path:
        return self.artifact_root / "permutation-run-ledger.jsonl"

    @property
    def permutation_report_dir(self) -> Path:
        return self.artifact_root / "permutation-report"


def build_run_commands(run: ExperimentRun) -> list[list[str]]:
    commands: list[list[str]] = []
    reviewed_input = run.reviewed_artifact_path
    if run.reviewed_path is None:
        if run.questions_path is None:
            raise ValueError("questions_path is required when reviewed_path is absent")
        generate = [
            run.python_executable,
            "-m",
            "eval.asv.open_qa.generate",
            "--questions",
            str(run.questions_path),
            "--output",
            str(run.generated_path),
            "--append",
            "--resume",
            "--max-concurrency",
            str(run.max_concurrency),
        ]
        if run.candidate_provider:
            generate.extend(
                [
                    "--provider",
                    run.candidate_provider,
                    "--model",
                    run.candidate_model,
                ]
            )
        commands.append(generate)
    commands.append(
        [
            run.python_executable,
            "-m",
            "asv_eval",
            "adapt-open-qa",
            "--input",
            str(reviewed_input),
            "--output",
            str(run.adapted_path),
        ]
    )
    collect = [
        run.python_executable,
        "-m",
        "eval.asv.open_qa.collect",
        "--reviewed",
        str(reviewed_input),
        "--output-dir",
        str(run.collection_dir),
        "--workspace",
        str(run.collection_workspace),
        "--max-concurrency",
        str(run.max_concurrency),
    ]
    if run.actor_provider:
        collect.extend(["--actor-provider", run.actor_provider])
    if run.actor_model:
        collect.extend(["--actor-model", run.actor_model])
    if run.ack_live:
        collect.append("--ack-live")
    commands.append(collect)
    evaluate = [
        run.python_executable,
        "-m",
        "asv_eval",
        "evaluate",
        "--input",
        str(run.collected_trajectory_path),
        "--evaluator",
        "deepseek-chat-logprob",
        "--model",
        run.evaluator_model,
        "--fallback-policy",
        "floor",
        "--cache",
        str(run.cache_path),
        "--run-ledger",
        str(run.ledger_path),
        "--max-concurrency",
        str(run.max_concurrency),
        "--write-evaluated-trajectories",
        str(run.evaluated_path),
        "--output-dir",
        str(run.report_dir),
    ]
    _append_rationale_args(evaluate, run)
    commands.append(evaluate)
    commands.append(
        [
            run.python_executable,
            "-m",
            "eval.asv.live_pubmed.analyze",
            "--report-dir",
            str(run.report_dir),
        ]
    )
    commands.append(
        [
            run.python_executable,
            "-m",
            "asv_eval",
            "audit-permutations",
            "--input",
            str(run.evaluated_path),
            "--output",
            str(run.permutations_path),
            "--b",
            "4",
        ]
    )
    permutation_evaluate = [
        run.python_executable,
        "-m",
        "asv_eval",
        "evaluate",
        "--input",
        str(run.permutations_path),
        "--evaluator",
        "deepseek-chat-logprob",
        "--model",
        run.evaluator_model,
        "--fallback-policy",
        "floor",
        "--cache",
        str(run.cache_path),
        "--run-ledger",
        str(run.permutation_ledger_path),
        "--max-concurrency",
        str(run.max_concurrency),
        "--output-dir",
        str(run.permutation_report_dir),
    ]
    _append_rationale_args(permutation_evaluate, run)
    commands.append(permutation_evaluate)
    return commands


def _append_rationale_args(command: list[str], run: ExperimentRun) -> None:
    if run.rationale_mode == "off":
        return
    command.extend(
        [
            "--rationale-mode",
            run.rationale_mode,
            "--rationale-max-tokens",
            str(run.rationale_max_tokens),
            "--rationale-leakage-policy",
            run.rationale_leakage_policy,
        ]
    )


def run_experiment(run: ExperimentRun) -> int:
    if not run.ack_live:
        raise ValueError("--ack-live is required for live collection/evaluation")
    run.artifact_root.mkdir(parents=True, exist_ok=True)
    commands_log = run.artifact_root / "commands.log"
    _write_manifest(run)
    commands = build_run_commands(run)
    if run.reviewed_path is None:
        for command in commands[:1]:
            _run(command, commands_log)
        shutil.copyfile(run.generated_path, run.reviewed_artifact_path)
        remaining_commands = commands[1:]
    else:
        shutil.copyfile(run.reviewed_path, run.reviewed_artifact_path)
        remaining_commands = commands
    for command in remaining_commands:
        _run(command, commands_log)
    _write_permutation_stability(run)
    _write_results(run)
    return 0


def _run(command: list[str], commands_log: Path) -> None:
    commands_log.parent.mkdir(parents=True, exist_ok=True)
    with commands_log.open("a", encoding="utf-8") as handle:
        handle.write(" ".join(command) + "\n")
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {result.returncode}: {' '.join(command)}"
        )


def _write_manifest(run: ExperimentRun) -> None:
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact_root": str(run.artifact_root),
        "questions_path": str(run.questions_path) if run.questions_path else None,
        "reviewed_path": str(run.reviewed_path) if run.reviewed_path else None,
        "candidate_provider": run.candidate_provider,
        "candidate_model": run.candidate_model,
        "actor_provider": run.actor_provider,
        "actor_model": run.actor_model,
        "evaluator_model": run.evaluator_model,
        "rationale_mode": run.rationale_mode,
        "rationale_max_tokens": run.rationale_max_tokens,
        "rationale_leakage_policy": run.rationale_leakage_policy,
        "max_concurrency": run.max_concurrency,
    }
    (run.artifact_root / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_results(run: ExperimentRun) -> None:
    summary = _read_json(run.report_dir / "summary.json")
    analysis = _read_json(run.report_dir / "analysis_summary.json")
    permutation_summary = _read_json(run.permutation_report_dir / "summary.json")
    permutation_stability = _read_json(run.artifact_root / "permutation_stability.json")
    lines = [
        "# Open QA Candidate Generation ASV Results",
        "",
        f"- artifact_root: `{run.artifact_root}`",
        f"- trajectory_count: {summary.get('trajectory_count')}",
        f"- step_count: {summary.get('step_count')}",
        f"- mean_net_asv: {summary.get('mean_net_asv')}",
        f"- mean_gold_margin_gain: {_mean_step_type_metric(analysis, 'mean_gold_margin_gain')}",
        f"- permutation_step_count: {permutation_summary.get('step_count')}",
        f"- mean_group_range_net_asv: {permutation_stability.get('mean_group_range_net_asv')}",
        f"- max_group_range_net_asv: {permutation_stability.get('max_group_range_net_asv')}",
        "",
        "Raw generated/reviewed specs, collection outputs, evaluator cache, "
        "evaluated trajectories, and reports are preserved under this artifact root.",
    ]
    (run.artifact_root / "results.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _write_permutation_stability(run: ExperimentRun) -> None:
    stability = summarize_permutation_stability(run.permutation_report_dir)
    (run.artifact_root / "permutation_stability.json").write_text(
        json.dumps(stability, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _mean_step_type_metric(analysis: dict, metric: str) -> float | None:
    rows = analysis.get("step_type_summary")
    if not isinstance(rows, list):
        return None
    values = [
        float(row[metric])
        for row in rows
        if isinstance(row, dict) and isinstance(row.get(metric), int | float)
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the open QA candidate-generation ASV experiment."
    )
    parser.add_argument("--questions")
    parser.add_argument("--reviewed")
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--candidate-provider", choices=["deepseek"])
    parser.add_argument("--candidate-model", default="deepseek-v4-flash")
    parser.add_argument("--actor-provider")
    parser.add_argument("--actor-model")
    parser.add_argument("--evaluator-model", default="deepseek-chat")
    parser.add_argument(
        "--rationale-mode", choices=["off", "label-free"], default="off"
    )
    parser.add_argument("--rationale-max-tokens", type=int, default=128)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument(
        "--rationale-leakage-policy",
        choices=["error", "warn"],
        default="error",
    )
    parser.add_argument("--workspace")
    parser.add_argument("--ack-live", action="store_true")
    args = parser.parse_args(argv)

    if not args.reviewed and not args.questions:
        parser.error("--questions or --reviewed is required")
    run = ExperimentRun(
        artifact_root=Path(args.artifact_root),
        questions_path=Path(args.questions) if args.questions else None,
        reviewed_path=Path(args.reviewed) if args.reviewed else None,
        candidate_provider=args.candidate_provider,
        candidate_model=args.candidate_model,
        actor_provider=args.actor_provider,
        actor_model=args.actor_model,
        evaluator_model=args.evaluator_model,
        rationale_mode=args.rationale_mode,
        rationale_max_tokens=args.rationale_max_tokens,
        rationale_leakage_policy=args.rationale_leakage_policy,
        max_concurrency=args.max_concurrency,
        workspace=Path(args.workspace) if args.workspace else None,
        ack_live=args.ack_live,
    )
    try:
        return run_experiment(run)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
