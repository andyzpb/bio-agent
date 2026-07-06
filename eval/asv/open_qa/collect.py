from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable

from agent.provider import LLMProvider
from asv_eval.adapters import open_qa_candidate_spec_to_trajectory, write_standard_jsonl
from asv_eval.core import TrajectoryRecord
from eval.asv.live_pubmed.collect import summarize_actor_coverage
from eval.asv.open_qa.generate import DEEPSEEK_BASE_URL
from plugins.biomed_evidence.schemas import AnswerWithEvidenceRequest
from plugins.biomed_evidence.service import BiomedEvidenceService


@dataclass(frozen=True)
class OpenQACollectionConfig:
    reviewed_path: Path
    output_dir: Path
    workspace: Path
    limit: int | None = None
    actor_provider: Any | None = None
    actor_model: str | None = None
    actor_provider_name: str | None = None
    max_concurrency: int = 1


@dataclass(frozen=True)
class OpenQACollectionRow:
    trajectory_id: str
    status: str
    run_id: str | None = None
    collected_trajectory_id: str | None = None
    step_count: int = 0
    error: str | None = None


def load_reviewed_specs(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: reviewed spec must be an object")
        open_qa_candidate_spec_to_trajectory(payload)
        rows.append(payload)
    return rows


def attach_candidate_set_to_trajectory(
    base: TrajectoryRecord,
    reviewed: dict[str, Any],
) -> TrajectoryRecord:
    reviewed_trajectory = open_qa_candidate_spec_to_trajectory(reviewed)
    reviewed_task = reviewed_trajectory.task
    task = replace(
        base.task,
        task_id=reviewed_task.task_id,
        question=reviewed_task.question,
        candidate_space=reviewed_task.candidate_space,
        task_type=reviewed_task.task_type,
        domain=reviewed_task.domain or base.task.domain,
        difficulty=reviewed_task.difficulty or base.task.difficulty,
        gold_visible_to_evaluator=False,
        gold_used_only_for_validation=True,
    )
    return replace(
        base,
        trajectory_id=reviewed_trajectory.trajectory_id,
        task=task,
        metadata={
            **base.metadata,
            **reviewed_trajectory.metadata,
            "experiment": "open_qa_candidate_generation",
            "source_trajectory_id": base.trajectory_id,
        },
        source_adapter="open_qa_live_pubmed",
    )


class collect_open_qa:
    @staticmethod
    def run_sync(
        reviewed_specs: list[dict[str, Any]],
        *,
        config: OpenQACollectionConfig,
        service_factory: Callable[..., Any] | None = None,
    ) -> tuple[list[OpenQACollectionRow], list[TrajectoryRecord]]:
        return asyncio.run(
            collect_open_qa.run(
                reviewed_specs,
                config=config,
                service_factory=service_factory,
            )
        )

    @staticmethod
    async def run(
        reviewed_specs: list[dict[str, Any]],
        *,
        config: OpenQACollectionConfig,
        service_factory: Callable[..., Any] | None = None,
    ) -> tuple[list[OpenQACollectionRow], list[TrajectoryRecord]]:
        if config.limit is not None and config.limit < 1:
            raise ValueError("limit must be positive when provided")
        active_specs = (
            reviewed_specs[: config.limit]
            if config.limit is not None
            else reviewed_specs
        )
        factory = service_factory or BiomedEvidenceService
        if config.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if config.max_concurrency > 1:
            semaphore = asyncio.Semaphore(config.max_concurrency)

            async def run_one(reviewed: dict[str, Any]):
                async with semaphore:
                    workspace = _workspace_for_trajectory(
                        config.workspace,
                        str(reviewed["trajectory_id"]),
                    )
                    service = _build_service(factory, workspace, config)
                    try:
                        return await _collect_one(reviewed, service)
                    finally:
                        closer = getattr(service, "aclose", None)
                        if callable(closer):
                            await closer()

            results = await asyncio.gather(
                *(run_one(reviewed) for reviewed in active_specs)
            )
            rows = [row for row, _trajectory in results]
            trajectories = [
                trajectory for _row, trajectory in results if trajectory is not None
            ]
            return rows, trajectories

        service = factory(
            config.workspace,
            revision_provider=config.actor_provider,
            revision_model=config.actor_model,
            allow_live_pubmed_tools=True,
        )
        rows: list[OpenQACollectionRow] = []
        trajectories: list[TrajectoryRecord] = []
        try:
            for reviewed in active_specs:
                row, trajectory = await _collect_one(reviewed, service)
                rows.append(row)
                if trajectory is not None:
                    trajectories.append(trajectory)
        finally:
            closer = getattr(service, "aclose", None)
            if callable(closer):
                await closer()
        return rows, trajectories


def write_collection_outputs(
    output_dir: Path,
    rows: list[OpenQACollectionRow],
    trajectories: list[TrajectoryRecord],
    *,
    actor_provider_name: str | None = None,
    actor_model: str | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "collection.jsonl").write_text(
        "".join(json.dumps(asdict(row), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    write_standard_jsonl(output_dir / "trajectory.jsonl", trajectories)
    (output_dir / "collection_summary.json").write_text(
        json.dumps(
            {
                "collection": {
                    "count": len(rows),
                    "completed": sum(row.status == "completed" for row in rows),
                    "failed": sum(row.status == "failed" for row in rows),
                    "trajectory_count": len(trajectories),
                },
                "actor": summarize_actor_coverage(
                    trajectories,
                    actor_provider_name=actor_provider_name,
                    actor_model=actor_model,
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _max_papers(reviewed: dict[str, Any]) -> int:
    metadata = reviewed.get("metadata")
    if isinstance(metadata, dict) and metadata.get("max_papers") is not None:
        return max(1, int(metadata["max_papers"]))
    return max(1, int(reviewed.get("max_papers", 5)))


def _build_service(
    factory: Callable[..., Any],
    workspace: Path,
    config: OpenQACollectionConfig,
) -> Any:
    return factory(
        workspace,
        revision_provider=config.actor_provider,
        revision_model=config.actor_model,
        allow_live_pubmed_tools=True,
    )


async def _collect_one(
    reviewed: dict[str, Any],
    service: Any,
) -> tuple[OpenQACollectionRow, TrajectoryRecord | None]:
    trajectory_id = str(reviewed["trajectory_id"])
    try:
        audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question=str(reviewed["question"]),
                source="pubmed",
                max_papers=_max_papers(reviewed),
                use_llm_planner=True,
                execute_support_refute=True,
                use_llm_extractor=True,
                use_llm_synthesis=True,
                use_llm_verifier=True,
                use_llm_revision=True,
                use_llm_claim_logic=True,
                export_logic_facts=True,
            )
        )
        run_id = audited.answer_result.run_id
        base = service.export_answer_run_asv_trajectory(run_id)
        trajectory = attach_candidate_set_to_trajectory(base, reviewed)
        return (
            OpenQACollectionRow(
                trajectory_id=trajectory_id,
                status="completed",
                run_id=run_id,
                collected_trajectory_id=trajectory.trajectory_id,
                step_count=len(trajectory.steps),
            ),
            trajectory,
        )
    except Exception as exc:
        return (
            OpenQACollectionRow(
                trajectory_id=trajectory_id,
                status="failed",
                error=str(exc),
            ),
            None,
        )


def _workspace_for_trajectory(root: Path, trajectory_id: str) -> Path:
    safe = "".join(
        ch if ch.isalnum() or ch in "._-" else "_" for ch in trajectory_id
    ).strip("._")
    return root / "tasks" / (safe or "trajectory")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect live PubMed trajectories for reviewed open QA specs."
    )
    parser.add_argument("--reviewed", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--actor-provider")
    parser.add_argument("--actor-model")
    parser.add_argument("--actor-api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--actor-base-url")
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--ack-live", action="store_true")
    args = parser.parse_args(argv)

    if not args.ack_live:
        parser.error("--ack-live is required because this command calls live PubMed")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive when provided")
    if args.max_concurrency < 1:
        parser.error("--max-concurrency must be positive")

    actor_provider = _build_actor_provider_from_args(args, parser)
    config = OpenQACollectionConfig(
        reviewed_path=Path(args.reviewed),
        output_dir=Path(args.output_dir),
        workspace=Path(args.workspace),
        limit=args.limit,
        actor_provider=actor_provider,
        actor_model=args.actor_model,
        actor_provider_name=args.actor_provider,
        max_concurrency=args.max_concurrency,
    )
    rows, trajectories = collect_open_qa.run_sync(
        load_reviewed_specs(config.reviewed_path),
        config=config,
    )
    write_collection_outputs(
        config.output_dir,
        rows,
        trajectories,
        actor_provider_name=config.actor_provider_name,
        actor_model=config.actor_model,
    )
    completed = sum(row.status == "completed" for row in rows)
    print(
        f"collection_count={len(rows)} completed={completed} "
        f"trajectory_count={len(trajectories)} output_dir={config.output_dir}"
    )
    return 0 if completed == len(rows) and trajectories else 1


def _build_actor_provider_from_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> Any | None:
    if not args.actor_provider:
        return None
    if not args.actor_model:
        parser.error("--actor-model is required when --actor-provider is set")
    api_key = os.getenv(str(args.actor_api_key_env or ""))
    if not api_key:
        parser.error(f"{args.actor_api_key_env} is required for --actor-provider")
    return LLMProvider(
        api_key=api_key,
        base_url=args.actor_base_url or DEEPSEEK_BASE_URL,
        provider_name=args.actor_provider,
        force_disable_thinking=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
