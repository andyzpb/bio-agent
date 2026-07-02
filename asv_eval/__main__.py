from __future__ import annotations

import argparse
import sys
from pathlib import Path

from asv_eval.adapters import (
    adapt_bio_agent_workspace,
    apply_belief_fixture,
    load_belief_fixture,
    load_standard_jsonl,
    react_transcript_to_trajectory,
    write_standard_jsonl,
)
from asv_eval.core import ASVConfig, CostConfig
from asv_eval.evaluators import DeepSeekLogprobBeliefEvaluator, DeepSeekLogprobConfig
from asv_eval.reporting import write_report_bundle
from asv_eval.runtime import (
    EvaluatorRuntimeConfig,
    StateScoreCache,
    fill_missing_beliefs,
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        try:
            return _evaluate(args)
        except ValueError as exc:
            message = str(exc)
            if "missing belief_before/belief_after" in message:
                message = (
                    f"{message}. Provide beliefs with --belief-fixture or evaluate "
                    "states with --evaluator deepseek-chat-logprob."
                )
            print(message, file=sys.stderr)
            return 1
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
    evaluator_mode = args.evaluator or "provided-belief"
    runtime_config = EvaluatorRuntimeConfig(
        mode=evaluator_mode,
        model=args.model,
        api_key_env=args.api_key_env,
        fallback_policy=args.fallback_policy,
        floor_score=args.floor_score,
        state_text_max_chars=args.state_text_max_chars,
    )
    runtime_evaluator = (
        _build_deepseek_evaluator(runtime_config)
        if evaluator_mode == "deepseek-chat-logprob"
        else None
    )
    trajectories = fill_missing_beliefs(
        trajectories,
        config=runtime_config,
        evaluator=runtime_evaluator,
        cache=StateScoreCache(Path(args.cache)) if args.cache else None,
    )
    if args.write_evaluated_trajectories:
        write_standard_jsonl(Path(args.write_evaluated_trajectories), trajectories)
    summary = write_report_bundle(
        trajectories,
        Path(args.output_dir),
        config=config,
        evaluator_config=runtime_config.cache_identity(),
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
    evaluate.add_argument(
        "--evaluator",
        choices=["provided-belief", "deepseek-chat-logprob"],
    )
    evaluate.add_argument("--model", default="deepseek-v4-flash")
    evaluate.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    evaluate.add_argument("--cache")
    evaluate.add_argument("--fallback-policy", choices=["error", "floor"], default="error")
    evaluate.add_argument("--floor-score", type=float, default=-20.0)
    evaluate.add_argument("--state-text-max-chars", type=int, default=6000)
    evaluate.add_argument("--write-evaluated-trajectories")
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
    write_standard_jsonl(path, [trajectory])


def _build_deepseek_evaluator(
    config: EvaluatorRuntimeConfig,
) -> DeepSeekLogprobBeliefEvaluator:
    return DeepSeekLogprobBeliefEvaluator(
        DeepSeekLogprobConfig(
            model=config.model,
            api_key_env=config.api_key_env,
            top_logprobs=config.top_logprobs,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            max_logprob_candidates=config.max_logprob_candidates,
            floor_score=config.floor_score,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
