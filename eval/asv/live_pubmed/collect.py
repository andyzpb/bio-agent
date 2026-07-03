from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from agent.provider import LLMProvider
from asv_eval.adapters import write_standard_jsonl
from asv_eval.core import TrajectoryRecord
from eval.asv.live_pubmed.claims import ClaimRecord, load_claims_jsonl
from plugins.biomed_evidence.schemas import AnswerWithEvidenceRequest
from plugins.biomed_evidence.service import BiomedEvidenceService


@dataclass(frozen=True)
class CollectionConfig:
    claims_path: Path
    output_dir: Path
    workspace: Path
    limit: int | None = None
    actor_provider: Any | None = None
    actor_model: str | None = None
    actor_provider_name: str | None = None


@dataclass(frozen=True)
class CollectionRow:
    claim_id: str
    gold_label: str
    status: str
    run_id: str | None = None
    trajectory_id: str | None = None
    step_count: int = 0
    error: str | None = None

    @classmethod
    def completed(
        cls,
        *,
        claim: ClaimRecord,
        run_id: str,
        trajectory_id: str,
        step_count: int,
    ) -> "CollectionRow":
        return cls(
            claim_id=claim.claim_id,
            gold_label=claim.gold_label,
            status="completed",
            run_id=run_id,
            trajectory_id=trajectory_id,
            step_count=step_count,
        )

    @classmethod
    def failure(
        cls,
        *,
        claim_id: str,
        gold_label: str,
        message: str,
    ) -> "CollectionRow":
        return cls(
            claim_id=claim_id,
            gold_label=gold_label,
            status="failed",
            error=message,
        )


class collect_claims:
    @staticmethod
    def run_sync(
        claims: list[ClaimRecord],
        *,
        config: CollectionConfig,
        service_factory: Callable[..., Any] | None = None,
    ) -> tuple[list[CollectionRow], list[TrajectoryRecord]]:
        return asyncio.run(
            collect_claims.run(
                claims,
                config=config,
                service_factory=service_factory,
            )
        )

    @staticmethod
    async def run(
        claims: list[ClaimRecord],
        *,
        config: CollectionConfig,
        service_factory: Callable[..., Any] | None = None,
    ) -> tuple[list[CollectionRow], list[TrajectoryRecord]]:
        if config.limit is not None and config.limit < 1:
            raise ValueError("limit must be positive when provided")
        active_claims = claims[: config.limit] if config.limit is not None else claims
        factory = service_factory or BiomedEvidenceService
        service = factory(
            config.workspace,
            revision_provider=config.actor_provider,
            revision_model=config.actor_model,
            allow_live_pubmed_tools=True,
        )
        rows: list[CollectionRow] = []
        trajectories: list[TrajectoryRecord] = []
        try:
            for claim in active_claims:
                try:
                    audited = await service.answer_with_audit(
                        AnswerWithEvidenceRequest(**claim.to_answer_request_payload())
                    )
                    run_id = audited.answer_result.run_id
                    trajectory = service.export_answer_run_asv_trajectory(run_id)
                    trajectory = _attach_gold_label(trajectory, claim.gold_label)
                    trajectories.append(trajectory)
                    rows.append(
                        CollectionRow.completed(
                            claim=claim,
                            run_id=run_id,
                            trajectory_id=trajectory.trajectory_id,
                            step_count=len(trajectory.steps),
                        )
                    )
                except Exception as exc:
                    rows.append(
                        CollectionRow.failure(
                            claim_id=claim.claim_id,
                            gold_label=claim.gold_label,
                            message=str(exc),
                        )
                    )
        finally:
            closer = getattr(service, "aclose", None)
            if callable(closer):
                await closer()
        return rows, trajectories


def _attach_gold_label(
    trajectory: TrajectoryRecord,
    gold_label: str,
) -> TrajectoryRecord:
    from dataclasses import replace

    task = trajectory.task
    candidate_space = replace(task.candidate_space, gold_candidate_id=gold_label)
    return replace(
        trajectory,
        task=replace(
            task,
            candidate_space=candidate_space,
            gold_visible_to_evaluator=False,
            gold_used_only_for_validation=True,
        ),
        metadata={
            **trajectory.metadata,
            "experiment": "live_pubmed_step_value",
        },
    )


def write_collection_outputs(
    output_dir: Path,
    rows: list[CollectionRow],
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


def summarize_actor_coverage(
    trajectories: list[TrajectoryRecord],
    *,
    actor_provider_name: str | None = None,
    actor_model: str | None = None,
) -> dict[str, Any]:
    classifier: Counter[str] = Counter()
    planner: Counter[str] = Counter()
    synthesis: Counter[str] = Counter()
    verifier: Counter[str] = Counter()
    revision: Counter[str] = Counter()
    claim_logic: Counter[str] = Counter()
    for trajectory in trajectories:
        for step in trajectory.steps:
            metadata = _step_metadata(step)
            classification = metadata.get("classification")
            if isinstance(classification, dict):
                _count_mode(classifier, classification.get("classifier_mode"))
            query_plan = metadata.get("query_plan")
            if isinstance(query_plan, dict):
                _count_mode(planner, query_plan.get("planner_mode"))
            _count_mode(synthesis, metadata.get("synthesis_mode"))
            _count_mode(verifier, metadata.get("verifier_mode"))
            _count_mode(revision, metadata.get("revision_mode"))
            logic_audit = metadata.get("logic_audit")
            if isinstance(logic_audit, dict):
                parser_counts = logic_audit.get("parser_mode_counts")
                if isinstance(parser_counts, dict):
                    for mode, count in parser_counts.items():
                        if isinstance(count, int | float):
                            claim_logic[str(mode)] += int(count)
    return {
        "provider": actor_provider_name,
        "model": actor_model,
        "configured": bool(actor_provider_name or actor_model),
        "classifier_modes": dict(sorted(classifier.items())),
        "planner_modes": dict(sorted(planner.items())),
        "synthesis_modes": dict(sorted(synthesis.items())),
        "verifier_modes": dict(sorted(verifier.items())),
        "revision_modes": dict(sorted(revision.items())),
        "claim_logic_modes": dict(sorted(claim_logic.items())),
    }


def _step_metadata(step: Any) -> dict[str, Any]:
    observation = getattr(step, "observation", None)
    if not isinstance(observation, dict):
        return {}
    metadata = observation.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _count_mode(counter: Counter[str], mode: Any) -> None:
    if isinstance(mode, str) and mode:
        counter[mode] += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect live PubMed ASV trajectories.")
    parser.add_argument("--claims", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--actor-provider")
    parser.add_argument("--actor-model")
    parser.add_argument("--actor-api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--actor-base-url")
    parser.add_argument("--ack-live", action="store_true")
    args = parser.parse_args(argv)
    if not args.ack_live:
        parser.error("--ack-live is required because this command calls live PubMed and LLM providers")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive when provided")
    actor_provider = _build_actor_provider_from_args(args, parser)
    config = CollectionConfig(
        claims_path=Path(args.claims),
        output_dir=Path(args.output_dir),
        workspace=Path(args.workspace),
        limit=args.limit,
        actor_provider=actor_provider,
        actor_model=args.actor_model,
        actor_provider_name=args.actor_provider,
    )
    rows, trajectories = collect_claims.run_sync(
        load_claims_jsonl(config.claims_path),
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
        base_url=args.actor_base_url,
        provider_name=args.actor_provider,
        force_disable_thinking=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
