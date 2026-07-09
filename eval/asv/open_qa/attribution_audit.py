from __future__ import annotations

import argparse
import json
import math
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

from asv_eval.adapters import load_standard_jsonl
from asv_eval.core import StepRecord, TaskRecord, normalize_log_scores
from asv_eval.evaluators import (
    DeepSeekLogprobBeliefEvaluator,
    DeepSeekLogprobConfig,
)
from asv_eval.runtime import EvaluatorRuntimeConfig, render_state_for_evaluator


QUALITY_FLAG_KEYS = (
    "used_floor_score",
    "used_fallback",
    "rationale_gold_leakage",
    "rationale_label_leakage",
)
EVIDENCE_KEYS = (
    "evidence",
    "evidence_facts",
    "supported_claims",
    "contradicted_claims",
    "retrieval",
    "retrieval_id",
    "citation",
    "citations",
    "pubmed",
    "pmid",
    "snippet",
    "abstract",
    "artifact",
    "available_artifacts",
)
STRUCTURE_KEYS = ("question", "completed_steps", "last_step", "last_status")


def main() -> None:
    args = _parse_args()
    root = Path(args.root)
    out_dir = root / "attribution_audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    trajectories = load_standard_jsonl(root / "collection/trajectory.jsonl")
    by_key = {
        (trajectory.trajectory_id, step.step_id): (trajectory.task, step)
        for trajectory in trajectories
        for step in trajectory.steps
    }
    rationale_rows = _load_step_rows(root / "report/steps.jsonl")
    direct_rows = _load_step_rows(root / "direct-report/steps.jsonl")
    samples = _sample_transitions(
        rationale_rows=rationale_rows,
        direct_rows=direct_rows,
        by_key=by_key,
        n=args.sample_size,
        seed=args.seed,
    )
    _write_jsonl(out_dir / "sampled_transitions.jsonl", samples)
    _write_cue_todo(out_dir / "cue_retention_labels.todo.jsonl", samples, by_key)

    protocol_rows = _run_protocol_ablation(
        samples=samples,
        by_key=by_key,
        root=root,
        out_dir=out_dir,
        args=args,
    )
    slice_rows = _run_state_slice_ablation(
        samples=samples,
        by_key=by_key,
        root=root,
        out_dir=out_dir,
        args=args,
    )
    summary = _summarize(samples, protocol_rows, slice_rows)
    (out_dir / "attribution_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "attribution_report.md").write_text(
        _render_report(summary),
        encoding="utf-8",
    )
    print(json.dumps(summary["headline"], indent=2, sort_keys=True))
    print(f"WROTE {out_dir / 'attribution_report.md'}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default="eval/asv/experiments/asv_medium_openqa_20260705_live_main",
    )
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--max-concurrency", type=int, default=8)
    parser.add_argument("--top-logprobs", type=int, default=20)
    parser.add_argument("--floor-score", type=float, default=-20.0)
    parser.add_argument(
        "--protocols",
        nargs="+",
        default=[
            "direct",
            "generated-rationale-128",
            "swapped-rationale-128",
            "generated-rationale-512",
            "extractive-buffer",
            "candidate-only-rationale",
        ],
    )
    parser.add_argument(
        "--state-slices",
        nargs="+",
        default=["full", "evidence-only", "agent-output-only"],
    )
    return parser.parse_args()


def _load_step_rows(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows[(str(row["trajectory_id"]), str(row["step_id"]))] = row
    return rows


def _sample_transitions(
    *,
    rationale_rows: dict[tuple[str, str], dict[str, Any]],
    direct_rows: dict[tuple[str, str], dict[str, Any]],
    by_key: dict[tuple[str, str], tuple[TaskRecord, StepRecord]],
    n: int,
    seed: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key, rationale in rationale_rows.items():
        direct = direct_rows.get(key)
        if direct is None or key not in by_key:
            continue
        if _bad_quality(rationale) or _bad_quality(direct):
            continue
        rgain = _gain(rationale)
        dgain = _gain(direct)
        if rgain is None or dgain is None:
            continue
        task, step = by_key[key]
        candidates.append(
            {
                "trajectory_id": key[0],
                "step_id": key[1],
                "step_type": step.action.get("type") or "unknown",
                "gold_candidate_id": task.candidate_space.gold_candidate_id,
                "direct_gain": dgain,
                "rationale_gain": rgain,
                "protocol_gap": rgain - dgain,
                "abs_protocol_gap": abs(rgain - dgain),
            }
        )
    candidates.sort(key=lambda row: row["abs_protocol_gap"], reverse=True)
    rng = random.Random(seed)
    chosen: list[dict[str, Any]] = []
    per_trajectory: dict[str, int] = {}
    for row in candidates:
        if per_trajectory.get(row["trajectory_id"], 0) >= 3:
            continue
        chosen.append(row)
        per_trajectory[row["trajectory_id"]] = per_trajectory.get(
            row["trajectory_id"], 0
        ) + 1
        if len(chosen) >= n:
            break
    if len(chosen) < n:
        remaining = [row for row in candidates if row not in chosen]
        rng.shuffle(remaining)
        chosen.extend(remaining[: n - len(chosen)])
    return chosen[:n]


def _bad_quality(row: dict[str, Any]) -> bool:
    flags = dict(row.get("quality_flags") or {})
    if any(bool(flags.get(key)) for key in QUALITY_FLAG_KEYS):
        return True
    return int(flags.get("missing_label_count") or 0) > 0


def _gain(row: dict[str, Any]) -> float | None:
    value = (row.get("gold_metrics") or {}).get("gold_margin_gain")
    return None if value is None else float(value)


def _run_protocol_ablation(
    *,
    samples: list[dict[str, Any]],
    by_key: dict[tuple[str, str], tuple[TaskRecord, StepRecord]],
    root: Path,
    out_dir: Path,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    output = out_dir / "protocol_ablation.jsonl"
    existing = _load_existing(output, ("trajectory_id", "step_id", "protocol"))
    rows = list(existing.values())
    direct_rows = _load_step_rows(root / "direct-report/steps.jsonl")
    rationale_rows = _load_step_rows(root / "report/steps.jsonl")
    tasks: list[tuple[dict[str, Any], str]] = []
    for sample in samples:
        key = (sample["trajectory_id"], sample["step_id"])
        for protocol in args.protocols:
            row_key = (sample["trajectory_id"], sample["step_id"], protocol)
            if row_key in existing:
                continue
            if protocol == "direct":
                rows.append(
                    _row_from_existing(sample, protocol, direct_rows[key], "full")
                )
            elif protocol == "generated-rationale-128":
                rows.append(
                    _row_from_existing(sample, protocol, rationale_rows[key], "full")
                )
            else:
                tasks.append((sample, protocol))
    if tasks:
        rationale_pool = None
        if any(protocol == "swapped-rationale-128" for _, protocol in tasks):
            rationale_pool = _build_swapped_rationale_pool(
                samples=[sample for sample, protocol in tasks if protocol == "swapped-rationale-128"],
                by_key=by_key,
                args=args,
            )
        rows.extend(
            _score_tasks(
                tasks=tasks,
                by_key=by_key,
                args=args,
                state_slice="full",
                output=output,
                rationale_pool=rationale_pool,
            )
        )
    _write_jsonl(output, _dedupe_rows(rows, ("trajectory_id", "step_id", "protocol")))
    return _load_jsonl(output)


def _run_state_slice_ablation(
    *,
    samples: list[dict[str, Any]],
    by_key: dict[tuple[str, str], tuple[TaskRecord, StepRecord]],
    root: Path,
    out_dir: Path,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    output = out_dir / "state_slice_ablation.jsonl"
    existing = _load_existing(output, ("trajectory_id", "step_id", "state_slice", "protocol"))
    rows = list(existing.values())
    direct_rows = _load_step_rows(root / "direct-report/steps.jsonl")
    rationale_rows = _load_step_rows(root / "report/steps.jsonl")
    tasks_by_slice: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for sample in samples:
        key = (sample["trajectory_id"], sample["step_id"])
        for state_slice in args.state_slices:
            for protocol in ("direct", "generated-rationale-128"):
                row_key = (
                    sample["trajectory_id"],
                    sample["step_id"],
                    state_slice,
                    protocol,
                )
                if row_key in existing:
                    continue
                if state_slice == "full" and protocol == "direct":
                    rows.append(
                        _row_from_existing(
                            sample, protocol, direct_rows[key], state_slice
                        )
                    )
                elif state_slice == "full" and protocol == "generated-rationale-128":
                    rows.append(
                        _row_from_existing(
                            sample, protocol, rationale_rows[key], state_slice
                        )
                    )
                else:
                    tasks_by_slice.setdefault(state_slice, []).append((sample, protocol))
    for active_slice, tasks in tasks_by_slice.items():
        if tasks:
            rows.extend(
                _score_tasks(
                    tasks=tasks,
                    by_key=by_key,
                    args=args,
                    state_slice=active_slice,
                    output=output,
                )
            )
    _write_jsonl(
        output,
        _dedupe_rows(rows, ("trajectory_id", "step_id", "state_slice", "protocol")),
    )
    return _load_jsonl(output)


def _score_tasks(
    *,
    tasks: list[tuple[dict[str, Any], str]],
    by_key: dict[tuple[str, str], tuple[TaskRecord, StepRecord]],
    args: argparse.Namespace,
    output: Path,
    state_slice: str | None = None,
    rationale_pool: dict[tuple[str, str, str], str] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    thread_local = threading.local()

    def evaluator() -> DeepSeekLogprobBeliefEvaluator:
        current = getattr(thread_local, "evaluator", None)
        if current is None:
            current = DeepSeekLogprobBeliefEvaluator(
                DeepSeekLogprobConfig(
                    model=args.model,
                    base_url=args.base_url,
                    api_key_env=args.api_key_env,
                    top_logprobs=args.top_logprobs,
                    floor_score=args.floor_score,
                )
            )
            thread_local.evaluator = current
        return current

    def run_one(sample: dict[str, Any], protocol: str) -> dict[str, Any]:
        task, step = by_key[(sample["trajectory_id"], sample["step_id"])]
        active_slice = state_slice or "full"
        before = _render(task, step, "before", active_slice)
        after = _render(task, step, "after", active_slice)
        before_scores, before_flags, before_warnings = _score_state(
            evaluator(),
            task,
            before,
            protocol,
            args,
            sample=sample,
            rationale_pool=rationale_pool,
        )
        after_scores, after_flags, after_warnings = _score_state(
            evaluator(),
            task,
            after,
            protocol,
            args,
            sample=sample,
            rationale_pool=rationale_pool,
        )
        row = _scored_row(
            sample=sample,
            protocol=protocol,
            state_slice=active_slice,
            before_scores=before_scores,
            after_scores=after_scores,
            before_flags=before_flags,
            after_flags=after_flags,
            before_warnings=before_warnings,
            after_warnings=after_warnings,
        )
        with lock:
            with output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        return row

    with ThreadPoolExecutor(max_workers=max(1, args.max_concurrency)) as pool:
        futures = [pool.submit(run_one, sample, protocol) for sample, protocol in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def _render(
    task: TaskRecord,
    step: StepRecord,
    position: str,
    state_slice: str,
) -> dict[str, Any]:
    raw = step.state_before if position == "before" else step.state_after
    raw = raw or {}
    if state_slice == "full":
        state = raw
    elif state_slice == "evidence-only":
        state = _filter_state(raw, keep_evidence=True)
    elif state_slice == "agent-output-only":
        state = _filter_state(raw, keep_evidence=False)
    else:
        raise ValueError(f"unknown state slice: {state_slice}")
    rendered = render_state_for_evaluator(
        task,
        StepRecord(
            step_id=step.step_id,
            index=step.index,
            action=step.action,
            state_before=state,
            state_after=state,
        ),
        position="before",
        config=EvaluatorRuntimeConfig(state_text_max_chars=6000),
    )
    return {
        "position": position,
        "evidence_text": rendered.state_text,
        "labels": rendered.labels,
        "candidate_texts": rendered.candidate_texts,
    }


def _build_swapped_rationale_pool(
    *,
    samples: list[dict[str, Any]],
    by_key: dict[tuple[str, str], tuple[TaskRecord, StepRecord]],
    args: argparse.Namespace,
) -> dict[tuple[str, str, str], str]:
    generated: dict[tuple[str, str, str], str] = {}
    thread_local = threading.local()

    def evaluator() -> DeepSeekLogprobBeliefEvaluator:
        current = getattr(thread_local, "evaluator", None)
        if current is None:
            current = DeepSeekLogprobBeliefEvaluator(
                DeepSeekLogprobConfig(
                    model=args.model,
                    base_url=args.base_url,
                    api_key_env=args.api_key_env,
                    top_logprobs=args.top_logprobs,
                    floor_score=args.floor_score,
                )
            )
            thread_local.evaluator = current
        return current

    def make_one(sample: dict[str, Any], position: str) -> tuple[tuple[str, str, str], str]:
        task, step = by_key[(sample["trajectory_id"], sample["step_id"])]
        rendered = _render(task, step, position, "full")
        text = _generated_rationale(
            evaluator(),
            task.question,
            rendered["evidence_text"],
            rendered["candidate_texts"],
            128,
        )
        return (sample["trajectory_id"], sample["step_id"], position), text

    with ThreadPoolExecutor(max_workers=max(1, args.max_concurrency)) as pool:
        futures = [
            pool.submit(make_one, sample, position)
            for sample in samples
            for position in ("before", "after")
        ]
        for future in as_completed(futures):
            key, text = future.result()
            generated[key] = text
    return _swap_rationales(samples, generated, seed=args.seed)


def _swap_rationales(
    samples: list[dict[str, Any]],
    generated: dict[tuple[str, str, str], str],
    *,
    seed: int,
) -> dict[tuple[str, str, str], str]:
    rng = random.Random(seed)
    swapped: dict[tuple[str, str, str], str] = {}
    for sample in samples:
        for position in ("before", "after"):
            key = (sample["trajectory_id"], sample["step_id"], position)
            donors = [
                other
                for other in samples
                if other["trajectory_id"] != sample["trajectory_id"]
                and (other["trajectory_id"], other["step_id"], position) in generated
            ]
            if not donors:
                raise ValueError("cannot swap rationales without another trajectory")
            donor = rng.choice(donors)
            swapped[key] = generated[(donor["trajectory_id"], donor["step_id"], position)]
    return swapped


def _filter_state(value: Any, *, keep_evidence: bool) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lower = str(key).lower()
            is_evidence = any(token in lower for token in EVIDENCE_KEYS)
            is_structure = lower in STRUCTURE_KEYS
            if keep_evidence and (is_evidence or is_structure):
                out[key] = _filter_state(item, keep_evidence=keep_evidence)
            elif not keep_evidence and (not is_evidence or is_structure):
                out[key] = _filter_state(item, keep_evidence=keep_evidence)
        return out
    if isinstance(value, list):
        return [_filter_state(item, keep_evidence=keep_evidence) for item in value]
    return value


def _score_state(
    evaluator: DeepSeekLogprobBeliefEvaluator,
    task: TaskRecord,
    rendered: dict[str, Any],
    protocol: str,
    args: argparse.Namespace,
    *,
    sample: dict[str, Any] | None = None,
    rationale_pool: dict[tuple[str, str, str], str] | None = None,
) -> tuple[dict[str, float], dict[str, Any], list[str]]:
    candidate_texts = rendered["candidate_texts"]
    evidence_text = rendered["evidence_text"]
    rationale_text = None
    rationale_flags: dict[str, Any] = {"rationale_mode": "off"}
    warnings: list[str] = []
    if protocol == "generated-rationale-512":
        rationale_text = _generated_rationale(
            evaluator, task.question, evidence_text, candidate_texts, 512
        )
        rationale_flags = _rationale_flags(rationale_text, candidate_texts, protocol)
    elif protocol == "generated-rationale-128":
        rationale_text = _generated_rationale(
            evaluator, task.question, evidence_text, candidate_texts, 128
        )
        rationale_flags = _rationale_flags(rationale_text, candidate_texts, protocol)
    elif protocol == "swapped-rationale-128":
        if sample is None or rationale_pool is None:
            raise ValueError("swapped-rationale-128 requires a rationale pool")
        rationale_text = rationale_pool[
            (sample["trajectory_id"], sample["step_id"], rendered["position"])
        ]
        rationale_flags = _rationale_flags(rationale_text, candidate_texts, protocol)
    elif protocol == "extractive-buffer":
        rationale_text = _extractive_buffer(evidence_text)
        rationale_flags = _rationale_flags(rationale_text, candidate_texts, protocol)
    elif protocol == "candidate-only-rationale":
        candidate_only = "No evidence state is provided for this ablation."
        rationale_text = _generated_rationale(
            evaluator, task.question, candidate_only, candidate_texts, 128
        )
        evidence_text = candidate_only
        rationale_flags = _rationale_flags(rationale_text, candidate_texts, protocol)
    elif protocol != "direct":
        raise ValueError(f"unknown protocol: {protocol}")
    scores, score_warnings = evaluator.score_state(
        question=task.question,
        evidence_text=evidence_text,
        labels=rendered["labels"],
        candidate_texts=candidate_texts if rationale_text else None,
        rationale_text=rationale_text,
    )
    warnings.extend(score_warnings)
    return scores, rationale_flags, warnings


def _generated_rationale(
    evaluator: DeepSeekLogprobBeliefEvaluator,
    question: str,
    evidence_text: str,
    candidate_texts: dict[str, str],
    max_tokens: int,
) -> str:
    original = evaluator.config.rationale_max_tokens
    object.__setattr__(evaluator.config, "rationale_max_tokens", max_tokens)
    try:
        text, _ = evaluator.rationale_for_state(
            question=question,
            evidence_text=evidence_text,
            candidate_texts=candidate_texts,
        )
    finally:
        object.__setattr__(evaluator.config, "rationale_max_tokens", original)
    return text


def _extractive_buffer(evidence_text: str, max_lines: int = 24) -> str:
    lines = [line.strip() for line in evidence_text.splitlines() if line.strip()]
    keep = [
        line
        for line in lines
        if any(token in line.lower() for token in EVIDENCE_KEYS)
        or line.startswith('"')
    ]
    if not keep:
        keep = lines
    return "\n".join(keep[:max_lines])


def _rationale_flags(
    rationale_text: str,
    candidate_texts: dict[str, str],
    protocol: str,
) -> dict[str, Any]:
    covered = [candidate_id for candidate_id in candidate_texts if candidate_id in rationale_text]
    return {
        "rationale_mode": protocol,
        "rationale_tokens_approx": len(rationale_text.split()),
        "rationale_candidate_coverage": round(len(covered) / max(len(candidate_texts), 1), 6),
        "rationale_covered_candidate_ids": covered,
    }


def _row_from_existing(
    sample: dict[str, Any],
    protocol: str,
    source: dict[str, Any],
    state_slice: str,
) -> dict[str, Any]:
    return _scored_row(
        sample=sample,
        protocol=protocol,
        state_slice=state_slice,
        before_scores={k: float(v) for k, v in source["raw_scores_before"].items()},
        after_scores={k: float(v) for k, v in source["raw_scores_after"].items()},
        before_flags={},
        after_flags={},
        before_warnings=[],
        after_warnings=[],
        source="existing",
    )


def _scored_row(
    *,
    sample: dict[str, Any],
    protocol: str,
    state_slice: str,
    before_scores: dict[str, float],
    after_scores: dict[str, float],
    before_flags: dict[str, Any],
    after_flags: dict[str, Any],
    before_warnings: list[str],
    after_warnings: list[str],
    source: str = "deepseek",
) -> dict[str, Any]:
    gold = sample["gold_candidate_id"]
    before_margin = _margin(before_scores, gold)
    after_margin = _margin(after_scores, gold)
    gain = after_margin - before_margin
    return {
        **sample,
        "protocol": protocol,
        "state_slice": state_slice,
        "source": source,
        "raw_scores_before": before_scores,
        "raw_scores_after": after_scores,
        "belief_before": normalize_log_scores(before_scores),
        "belief_after": normalize_log_scores(after_scores),
        "gold_margin_before": round(before_margin, 6),
        "gold_margin_after": round(after_margin, 6),
        "gold_margin_gain": round(gain, 6),
        "damage": before_margin > 0 and after_margin <= 0,
        "repair": before_margin <= 0 and after_margin > 0,
        "before_warnings": before_warnings,
        "after_warnings": after_warnings,
        "quality_flags": {
            "before": before_flags,
            "after": after_flags,
            "missing_label_count": len(before_warnings) + len(after_warnings),
            "used_floor_score": any("floor score" in w.lower() for w in before_warnings + after_warnings),
        },
    }


def _margin(scores: dict[str, float], gold: str) -> float:
    others = [value for key, value in scores.items() if key != gold]
    return float(scores[gold]) - _logsumexp(others)


def _logsumexp(values: list[float]) -> float:
    peak = max(values)
    return peak + math.log(sum(math.exp(value - peak) for value in values))


def _write_cue_todo(
    path: Path,
    samples: list[dict[str, Any]],
    by_key: dict[tuple[str, str], tuple[TaskRecord, StepRecord]],
) -> None:
    rows = []
    for sample in samples:
        task, step = by_key[(sample["trajectory_id"], sample["step_id"])]
        rows.append(
            {
                "trajectory_id": sample["trajectory_id"],
                "step_id": sample["step_id"],
                "step_type": sample["step_type"],
                "question": task.question,
                "gold_candidate_id": task.candidate_space.gold_candidate_id,
                "candidates": [asdict(candidate) for candidate in task.candidate_space.candidates],
                "state_before": step.state_before,
                "state_after": step.state_after,
                "gold_support_cue_in_state_before": None,
                "gold_support_cue_in_state_after": None,
                "gold_support_cue_in_rationale_before": None,
                "gold_support_cue_in_rationale_after": None,
                "competitor_support_cue_introduced": None,
                "unsupported_claim_in_rationale": None,
                "rationale_overstates_absence_of_evidence": None,
                "cue_retention_label": None,
                "attribution_label": None,
            }
        )
    _write_jsonl(path, rows)


def _summarize(
    samples: list[dict[str, Any]],
    protocol_rows: list[dict[str, Any]],
    slice_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    direct = {
        (row["trajectory_id"], row["step_id"]): row
        for row in protocol_rows
        if row["protocol"] == "direct"
    }
    protocol_summary = [
        _summary_row(rows, direct)
        for _, rows in _group(protocol_rows, "protocol").items()
    ]
    slice_summary = [
        _summary_row(rows, direct, group_keys=("state_slice", "protocol"))
        for _, rows in _group(slice_rows, "state_slice", "protocol").items()
    ]
    return {
        "headline": {
            "sampled_transitions": len(samples),
            "protocol_rows": len(protocol_rows),
            "state_slice_rows": len(slice_rows),
        },
        "protocol_summary": sorted(protocol_summary, key=lambda row: row["protocol"]),
        "state_slice_summary": sorted(
            slice_summary, key=lambda row: (row["state_slice"], row["protocol"])
        ),
    }


def _summary_row(
    rows: list[dict[str, Any]],
    direct: dict[tuple[str, str], dict[str, Any]],
    group_keys: tuple[str, ...] = ("protocol",),
) -> dict[str, Any]:
    gaps = []
    disagreements = []
    for row in rows:
        base = direct.get((row["trajectory_id"], row["step_id"]))
        if not base:
            continue
        gap = row["gold_margin_gain"] - base["gold_margin_gain"]
        gaps.append(gap)
        if _sign(row["gold_margin_gain"]) and _sign(base["gold_margin_gain"]):
            disagreements.append(_sign(row["gold_margin_gain"]) != _sign(base["gold_margin_gain"]))
    out = {key: rows[0][key] for key in group_keys}
    out.update(
        {
            "n": len(rows),
            "mean_gold_margin_gain": _round(_mean([row["gold_margin_gain"] for row in rows])),
            "mean_gap_vs_direct": _round(_mean(gaps)),
            "mean_abs_gap_vs_direct": _round(_mean([abs(value) for value in gaps])),
            "sign_disagreement_rate_nonzero": _round(_mean(disagreements)) if disagreements else None,
            "damage_rate": _round(_mean([row["damage"] for row in rows])),
            "repair_rate": _round(_mean([row["repair"] for row in rows])),
            "floor_or_missing_rows": sum(
                1 for row in rows if (row.get("quality_flags") or {}).get("used_floor_score")
            ),
        }
    )
    return out


def _group(rows: list[dict[str, Any]], *keys: str) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(tuple(row[key] for key in keys), []).append(row)
    return grouped


def _sign(value: float) -> int:
    if value > 1e-9:
        return 1
    if value < -1e-9:
        return -1
    return 0


def _mean(values: list[Any]) -> float | None:
    numeric = [float(value) for value in values]
    return sum(numeric) / len(numeric) if numeric else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# ASV protocol attribution audit",
        "",
        "## Protocol ablation",
        "",
        "| Protocol | n | Mean gain | Gap vs direct | Abs gap | Sign disagreement | Damage | Repair | Floor/missing |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["protocol_summary"]:
        lines.append(
            f"| {row['protocol']} | {row['n']} | {row['mean_gold_margin_gain']} | "
            f"{row['mean_gap_vs_direct']} | {row['mean_abs_gap_vs_direct']} | "
            f"{row['sign_disagreement_rate_nonzero']} | {row['damage_rate']} | "
            f"{row['repair_rate']} | {row['floor_or_missing_rows']} |"
        )
    lines.extend(
        [
            "",
            "## State-slice ablation",
            "",
            "| Slice | Protocol | n | Mean gain | Gap vs direct | Abs gap | Sign disagreement | Damage | Repair | Floor/missing |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary["state_slice_summary"]:
        lines.append(
            f"| {row['state_slice']} | {row['protocol']} | {row['n']} | "
            f"{row['mean_gold_margin_gain']} | {row['mean_gap_vs_direct']} | "
            f"{row['mean_abs_gap_vs_direct']} | {row['sign_disagreement_rate_nonzero']} | "
            f"{row['damage_rate']} | {row['repair_rate']} | {row['floor_or_missing_rows']} |"
        )
    return "\n".join(lines) + "\n"


def _load_existing(path: Path, keys: tuple[str, ...]) -> dict[tuple[Any, ...], dict[str, Any]]:
    if not path.exists():
        return {}
    rows = _load_jsonl(path)
    return {tuple(row[key] for key in keys): row for row in rows}


def _dedupe_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    by_key = {tuple(row[key] for key in keys): row for row in rows}
    return list(by_key.values())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
