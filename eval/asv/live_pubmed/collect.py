from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

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
    require_ack_live: bool = True


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
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "collection.jsonl").write_text(
        "".join(json.dumps(asdict(row), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    write_standard_jsonl(output_dir / "trajectory.jsonl", trajectories)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect live PubMed ASV trajectories.")
    parser.add_argument("--claims", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ack-live", action="store_true")
    args = parser.parse_args(argv)
    if not args.ack_live:
        parser.error("--ack-live is required because this command calls live PubMed and LLM providers")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive when provided")
    config = CollectionConfig(
        claims_path=Path(args.claims),
        output_dir=Path(args.output_dir),
        workspace=Path(args.workspace),
        limit=args.limit,
    )
    rows, trajectories = collect_claims.run_sync(
        load_claims_jsonl(config.claims_path),
        config=config,
    )
    write_collection_outputs(config.output_dir, rows, trajectories)
    completed = sum(row.status == "completed" for row in rows)
    print(
        f"collection_count={len(rows)} completed={completed} "
        f"trajectory_count={len(trajectories)} output_dir={config.output_dir}"
    )
    return 0 if completed == len(rows) and trajectories else 1


if __name__ == "__main__":
    raise SystemExit(main())
