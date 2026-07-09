from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from asv_eval.adapters import (
    adapt_bio_agent_workspace,
    apply_belief_fixture,
    build_label_permuted_trajectories,
    load_belief_fixture,
    load_open_qa_candidate_specs,
    load_standard_jsonl,
    react_transcript_to_trajectory,
    write_standard_jsonl,
)
from asv_eval.core import ASVConfig, CostConfig
from asv_eval.evaluators import DeepSeekLogprobBeliefEvaluator, DeepSeekLogprobConfig
from asv_eval.reporting import write_report_bundle
from asv_eval.runtime import (
    EvaluatorRuntimeConfig,
    RationaleTextCache,
    RunLedger,
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
    if args.command == "adapt-open-qa":
        return _adapt_open_qa(args)
    if args.command == "audit-permutations":
        return _audit_permutations(args)
    if args.command == "adapt-bio-agent":
        return _adapt_bio_agent(args)
    if args.command == "probe-provider":
        return _probe_provider(args)
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
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        top_logprobs=args.top_logprobs,
        max_logprob_candidates=args.max_logprob_candidates,
        fallback_policy=args.fallback_policy,
        floor_score=args.floor_score,
        state_text_max_chars=args.state_text_max_chars,
        option_label_scheme=args.option_label_scheme,
        disable_thinking=args.disable_thinking,
        rationale_mode=args.rationale_mode,
        rationale_max_tokens=args.rationale_max_tokens,
        rationale_leakage_policy=args.rationale_leakage_policy,
        max_concurrency=args.max_concurrency,
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
        persistent_rationale_cache=(
            RationaleTextCache(Path(args.rationale_cache))
            if args.rationale_cache
            else (
                RationaleTextCache(Path(f"{args.cache}.rationale.jsonl"))
                if args.cache and args.rationale_mode != "off"
                else None
            )
        ),
        ledger=RunLedger(Path(args.run_ledger)) if args.run_ledger else None,
    )
    if args.write_evaluated_trajectories:
        write_standard_jsonl(Path(args.write_evaluated_trajectories), trajectories)
    summary = write_report_bundle(
        trajectories,
        Path(args.output_dir),
        config=config,
        evaluator_config={
            **runtime_config.cache_identity(),
            "max_concurrency": runtime_config.max_concurrency,
        },
        bootstrap_resamples=args.bootstrap_resamples,
        bootstrap_seed=args.bootstrap_seed,
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


def _adapt_open_qa(args: argparse.Namespace) -> int:
    trajectories = load_open_qa_candidate_specs(Path(args.input))
    write_standard_jsonl(Path(args.output), trajectories)
    print(f"trajectory_count={len(trajectories)} output={args.output}")
    return 0


def _audit_permutations(args: argparse.Namespace) -> int:
    trajectories = load_standard_jsonl(Path(args.input))
    permuted = build_label_permuted_trajectories(
        trajectories,
        permutation_count=max(1, int(args.b)),
    )
    write_standard_jsonl(Path(args.output), permuted)
    print(f"trajectory_count={len(permuted)} output={args.output}")
    return 0


def _adapt_bio_agent(args: argparse.Namespace) -> int:
    trajectory = adapt_bio_agent_workspace(Path(args.workspace), args.run_id)
    _write_trajectory_jsonl(Path(args.output), trajectory)
    print(f"trajectory_count=1 output={args.output}")
    return 0


def _probe_provider(args: argparse.Namespace) -> int:
    trajectories = load_standard_jsonl(Path(args.input))
    sampled = [
        replace(trajectory, steps=trajectory.steps[: max(0, args.sample_steps)])
        for trajectory in trajectories[: max(0, args.sample_trajectories)]
    ]
    runtime_config = EvaluatorRuntimeConfig(
        mode=args.evaluator,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        top_logprobs=args.top_logprobs,
        max_logprob_candidates=args.max_logprob_candidates,
        fallback_policy=args.fallback_policy,
        floor_score=args.floor_score,
        state_text_max_chars=args.state_text_max_chars,
        option_label_scheme=args.option_label_scheme,
        disable_thinking=args.disable_thinking,
        max_concurrency=args.max_concurrency,
    )
    filled = fill_missing_beliefs(
        sampled,
        config=runtime_config,
        evaluator=_build_deepseek_evaluator(runtime_config),
        cache=StateScoreCache(),
    )
    rows = [
        {
            "trajectory_id": trajectory.trajectory_id,
            "step_id": step.step_id,
            "missing_label_count": int(
                (step.quality_flags or {}).get("missing_label_count") or 0
            ),
            "used_floor_score": bool(
                (step.quality_flags or {}).get("used_floor_score")
            ),
            "before_warnings": (step.quality_flags or {}).get("before_warnings") or [],
            "after_warnings": (step.quality_flags or {}).get("after_warnings") or [],
        }
        for trajectory in filled
        for step in trajectory.steps
    ]
    covered_steps = sum(row["missing_label_count"] == 0 for row in rows)
    coverage_rate = covered_steps / len(rows) if rows else 0.0
    status = "passed" if coverage_rate >= args.min_all_label_coverage else "failed"
    summary = {
        "status": status,
        "provider": runtime_config.provider,
        "model": runtime_config.model,
        "option_label_scheme": runtime_config.option_label_scheme,
        "disable_thinking": runtime_config.disable_thinking,
        "top_logprobs": runtime_config.top_logprobs,
        "step_count": len(rows),
        "state_count": len(rows) * 2,
        "all_label_coverage_rate": round(coverage_rate, 6),
        "floor_score_step_count": sum(row["used_floor_score"] for row in rows),
        "missing_label_step_count": sum(row["missing_label_count"] > 0 for row in rows),
        "min_all_label_coverage": args.min_all_label_coverage,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "provider_gate.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "provider_gate_states.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if status == "passed" else 2


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
    _add_provider_runtime_args(evaluate)
    evaluate.add_argument("--cache")
    evaluate.add_argument("--rationale-cache")
    evaluate.add_argument("--run-ledger")
    evaluate.add_argument(
        "--rationale-mode", choices=["off", "label-free", "quote"], default="off"
    )
    evaluate.add_argument("--rationale-max-tokens", type=int, default=128)
    evaluate.add_argument(
        "--rationale-leakage-policy",
        choices=["error", "warn"],
        default="error",
    )
    evaluate.add_argument("--write-evaluated-trajectories")
    evaluate.add_argument("--output-dir", required=True)
    evaluate.add_argument("--bootstrap-resamples", type=int, default=5000)
    evaluate.add_argument("--bootstrap-seed", type=int, default=7)
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

    open_qa = subparsers.add_parser(
        "adapt-open-qa",
        help="convert open QA candidate answer specs",
    )
    open_qa.add_argument("--input", required=True)
    open_qa.add_argument("--output", required=True)

    permutations = subparsers.add_parser(
        "audit-permutations",
        help="write label-permuted standard ASV trajectories",
    )
    permutations.add_argument("--input", required=True)
    permutations.add_argument("--output", required=True)
    permutations.add_argument("--b", type=int, default=4)

    bio_agent = subparsers.add_parser(
        "adapt-bio-agent",
        help="convert one bio-agent run from an existing .akashic-workspace",
    )
    bio_agent.add_argument("--workspace", required=True)
    bio_agent.add_argument("--run-id", required=True)
    bio_agent.add_argument("--output", required=True)

    probe = subparsers.add_parser(
        "probe-provider",
        help="check whether a logprob provider covers all option labels on real ASV states",
    )
    probe.add_argument("--input", required=True)
    probe.add_argument("--output-dir", required=True)
    probe.add_argument(
        "--evaluator",
        choices=["deepseek-chat-logprob"],
        default="deepseek-chat-logprob",
    )
    probe.add_argument("--sample-trajectories", type=int, default=2)
    probe.add_argument("--sample-steps", type=int, default=5)
    probe.add_argument("--min-all-label-coverage", type=float, default=1.0)
    _add_provider_runtime_args(probe)
    return parser


def _add_provider_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--top-logprobs", type=int, default=20)
    parser.add_argument("--max-logprob-candidates", type=int, default=10)
    parser.add_argument(
        "--fallback-policy", choices=["error", "floor"], default="error"
    )
    parser.add_argument("--floor-score", type=float, default=-20.0)
    parser.add_argument("--state-text-max-chars", type=int, default=6000)
    parser.add_argument(
        "--option-label-scheme", choices=["source", "numeric"], default="source"
    )
    parser.add_argument("--disable-thinking", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=1)


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
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            top_logprobs=config.top_logprobs,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            max_logprob_candidates=config.max_logprob_candidates,
            floor_score=config.floor_score,
            rationale_max_tokens=config.rationale_max_tokens,
            disable_thinking=config.disable_thinking,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
