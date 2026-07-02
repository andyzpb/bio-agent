from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from asv_eval.adapters import (
    adapt_bio_agent_workspace,
    apply_belief_fixture,
    load_belief_fixture,
    load_standard_jsonl,
    react_transcript_to_trajectory,
)
from asv_eval.core import ASVConfig, CostConfig
from asv_eval.reporting import write_report_bundle


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        return _evaluate(args)
    if args.command == "adapt-react":
        return _adapt_react(args)
    if args.command == "adapt-bio-agent":
        return _adapt_bio_agent(args)
    parser.error(f"unknown command: {args.command}")
    return 2


def _evaluate(args: argparse.Namespace) -> int:
    config = ASVConfig(
        cost=CostConfig(
            prompt_token_weight=args.prompt_token_weight,
            completion_token_weight=args.completion_token_weight,
            tool_call_weight=args.tool_call_weight,
            latency_weight=args.latency_weight,
            risk_weight=args.risk_weight,
        ),
        lambda_cost=args.lambda_cost,
    )
    trajectories = load_standard_jsonl(Path(args.input))
    if args.belief_fixture:
        trajectories = apply_belief_fixture(
            trajectories,
            load_belief_fixture(Path(args.belief_fixture)),
        )
    summary = write_report_bundle(
        trajectories,
        Path(args.output_dir),
        config=config,
    )
    print(
        " ".join(
            [
                f"trajectory_count={summary['trajectory_count']}",
                f"step_count={summary['step_count']}",
                f"mean_net_asv={summary['mean_net_asv']}",
                f"output_dir={args.output_dir}",
            ]
        )
    )
    return 0


def _adapt_react(args: argparse.Namespace) -> int:
    trajectory = react_transcript_to_trajectory(
        Path(args.input).read_text(encoding="utf-8"),
        trajectory_id=args.trajectory_id,
        question=args.question,
        candidates=_parse_candidate_args(args.candidate),
    )
    _write_trajectory_jsonl(Path(args.output), trajectory)
    print(f"trajectory_count=1 output={args.output}")
    return 0


def _adapt_bio_agent(args: argparse.Namespace) -> int:
    trajectory = adapt_bio_agent_workspace(Path(args.workspace), args.run_id)
    _write_trajectory_jsonl(Path(args.output), trajectory)
    print(f"trajectory_count=1 output={args.output}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m asv_eval",
        description="Agent Step Value evaluation utilities.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate = subparsers.add_parser("evaluate", help="score standard ASV JSONL")
    evaluate.add_argument("--input", required=True)
    evaluate.add_argument("--belief-fixture")
    evaluate.add_argument("--output-dir", required=True)
    evaluate.add_argument("--lambda-cost", type=float, default=0.0)
    evaluate.add_argument("--prompt-token-weight", type=float, default=0.0)
    evaluate.add_argument("--completion-token-weight", type=float, default=0.0)
    evaluate.add_argument("--tool-call-weight", type=float, default=0.0)
    evaluate.add_argument("--latency-weight", type=float, default=0.0)
    evaluate.add_argument("--risk-weight", type=float, default=0.0)

    react = subparsers.add_parser("adapt-react", help="convert a ReAct transcript")
    react.add_argument("--input", required=True)
    react.add_argument("--output", required=True)
    react.add_argument("--trajectory-id", required=True)
    react.add_argument("--question", required=True)
    react.add_argument(
        "--candidate",
        action="append",
        required=True,
        help="candidate mapping like A=supported",
    )

    bio_agent = subparsers.add_parser(
        "adapt-bio-agent",
        help="convert one bio-agent run from an existing .akashic-workspace",
    )
    bio_agent.add_argument("--workspace", required=True)
    bio_agent.add_argument("--run-id", required=True)
    bio_agent.add_argument("--output", required=True)
    return parser


def _parse_candidate_args(values: list[str]) -> dict[str, str]:
    candidates: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"candidate must use LABEL=value form: {value}")
        label, candidate = value.split("=", 1)
        candidates[label.strip()] = candidate.strip()
    return candidates


def _write_trajectory_jsonl(path: Path, trajectory) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(trajectory), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
