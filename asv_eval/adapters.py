from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from asv_eval.core import (
    Candidate,
    CandidateSpace,
    StepRecord,
    TaskRecord,
    TrajectoryRecord,
)


def load_standard_jsonl(path: Path) -> list[TrajectoryRecord]:
    trajectories: list[TrajectoryRecord] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            trajectories.append(trajectory_from_dict(payload))
        except Exception as exc:
            raise ValueError(f"{path}:{line_no}: invalid ASV trajectory: {exc}") from exc
    return trajectories


def trajectory_from_dict(payload: dict[str, Any]) -> TrajectoryRecord:
    task_payload = payload["task"]
    space_payload = task_payload["candidate_space"]
    candidates = [
        Candidate(
            id=str(item["id"]),
            label=str(item.get("label") or chr(ord("A") + idx)),
            text=str(item.get("text") or item["id"]),
            prior=item.get("prior"),
        )
        for idx, item in enumerate(space_payload["candidates"])
    ]
    task = TaskRecord(
        task_id=str(task_payload.get("task_id") or payload.get("trajectory_id")),
        question=str(task_payload["question"]),
        candidate_space=CandidateSpace(
            candidates=candidates,
            gold_candidate_id=space_payload.get("gold_candidate_id"),
            type=cast(Any, space_payload.get("type", "closed_set")),
        ),
        task_type=str(task_payload.get("task_type", "closed_set_qa")),
        domain=task_payload.get("domain"),
        difficulty=task_payload.get("difficulty"),
        gold_visible_to_evaluator=bool(
            task_payload.get("gold_visible_to_evaluator", False)
        ),
        gold_used_only_for_validation=bool(
            task_payload.get("gold_used_only_for_validation", True)
        ),
    )
    steps = [
        StepRecord(
            step_id=str(item["step_id"]),
            index=int(item.get("index", idx)),
            action=dict(item.get("action") or {}),
            observation=dict(item.get("observation") or {}),
            state_before=item.get("state_before"),
            state_after=item.get("state_after"),
            belief_before=item.get("belief_before"),
            belief_after=item.get("belief_after"),
            cost=dict(item.get("cost") or {}),
            label=item.get("label"),
            label_source=item.get("label_source"),
            label_confidence=item.get("label_confidence"),
        )
        for idx, item in enumerate(payload.get("steps") or [])
    ]
    return TrajectoryRecord(
        trajectory_id=str(payload["trajectory_id"]),
        task=task,
        steps=steps,
        schema_version=str(payload.get("schema_version", "asv.v1")),
        source_adapter=str(payload.get("source_adapter", "standard_jsonl")),
        created_at=payload.get("created_at"),
        run_id=payload.get("run_id"),
        metadata=dict(payload.get("metadata") or {}),
        final_score=payload.get("final_score"),
        success=payload.get("success"),
    )


def react_transcript_to_trajectory(
    transcript: str,
    *,
    trajectory_id: str,
    question: str,
    candidates: dict[str, str],
) -> TrajectoryRecord:
    candidate_items = [
        Candidate(id=value, label=label, text=value) for label, value in candidates.items()
    ]
    task = TaskRecord(
        task_id=trajectory_id,
        question=question,
        candidate_space=CandidateSpace(candidates=candidate_items),
    )
    steps: list[StepRecord] = []
    action_type = "tool"
    action_text = ""
    for raw in transcript.splitlines():
        line = raw.strip()
        if line.startswith("Action:"):
            action_text = line.removeprefix("Action:").strip()
            action_type = action_text.split("[", 1)[0].strip() or "tool"
        elif line.startswith("Observation:") and action_text:
            steps.append(
                StepRecord(
                    step_id=f"{trajectory_id}-step-{len(steps) + 1}",
                    index=len(steps),
                    action={
                        "type": action_type,
                        "raw": action_text,
                        "is_external_observation": True,
                    },
                    observation={"text": line.removeprefix("Observation:").strip()},
                )
            )
            action_text = ""
    return TrajectoryRecord(
        trajectory_id=trajectory_id,
        source_adapter="react",
        task=task,
        steps=steps,
    )


def adapt_bio_agent_run_from_storage(storage: Any, run_id: str) -> TrajectoryRecord:
    run = storage.get_answer_run(run_id)
    if run is None:
        raise ValueError(f"bio-agent run not found: {run_id}")
    candidates = [
        Candidate(id="supported", label="A", text="supported"),
        Candidate(id="refuted", label="B", text="refuted"),
        Candidate(
            id="not_enough_information",
            label="C",
            text="not enough information",
        ),
    ]
    task = TaskRecord(
        task_id=run_id,
        question=getattr(run, "answer", "")[:240] or run_id,
        candidate_space=CandidateSpace(candidates=candidates),
        domain="biomedical",
    )
    steps: list[StepRecord] = []
    for trace in storage.list_agent_trace_steps(run_id):
        step_name = str(getattr(trace, "step", ""))
        if step_name not in {"retrieve", "extract", "audit"}:
            continue
        metadata = dict(getattr(trace, "metadata", {}) or {})
        steps.append(
            StepRecord(
                step_id=str(getattr(trace, "step_id", f"{run_id}-{len(steps)}")),
                index=len(steps),
                action={"type": step_name, "is_external_observation": True},
                observation={
                    "summary": getattr(trace, "output_summary", ""),
                    "metadata": metadata,
                },
            )
        )
    return TrajectoryRecord(
        trajectory_id=f"bio-agent-{run_id}",
        source_adapter="bio_agent",
        run_id=run_id,
        task=task,
        steps=steps,
    )


def adapt_bio_agent_workspace(workspace: Path, run_id: str) -> TrajectoryRecord:
    from plugins.biomed_evidence.storage import BiomedStorage

    db_path = workspace / "biomed_evidence" / "biomed.db"
    if not db_path.exists():
        raise FileNotFoundError(f"bio-agent db not found: {db_path}")

    storage = BiomedStorage(db_path)
    try:
        return adapt_bio_agent_run_from_storage(storage, run_id)
    finally:
        storage.close()
