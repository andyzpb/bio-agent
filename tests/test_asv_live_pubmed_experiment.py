from __future__ import annotations

import json
from pathlib import Path

import pytest

from asv_eval.core import Candidate, CandidateSpace, StepRecord, TaskRecord, TrajectoryRecord
from eval.asv.live_pubmed.collect import (
    CollectionConfig,
    CollectionRow,
    collect_claims,
    write_collection_outputs,
)
from eval.asv.live_pubmed.evaluate import (
    EvaluationRun,
    build_evaluate_command,
    scan_for_secret_markers,
)
from eval.asv.live_pubmed.claims import (
    CLAIM_LABELS,
    ClaimRecord,
    load_claims_jsonl,
    validate_claim_set,
)


ROOT = Path(__file__).resolve().parents[1]
CLAIMS_PATH = (
    ROOT
    / "eval"
    / "asv"
    / "experiments"
    / "live_pubmed_step_value"
    / "claims.pilot.jsonl"
)


def test_live_pubmed_claim_loader_reads_pilot_set() -> None:
    claims = load_claims_jsonl(CLAIMS_PATH)

    assert len(claims) == 30
    assert {claim.gold_label for claim in claims} == set(CLAIM_LABELS)
    assert all(claim.source == "pubmed" for claim in claims)
    assert all(claim.max_papers >= 3 for claim in claims)
    assert all(claim.question.endswith("?") for claim in claims)


def test_live_pubmed_claim_set_is_balanced_and_has_unique_ids() -> None:
    claims = load_claims_jsonl(CLAIMS_PATH)

    summary = validate_claim_set(claims, min_per_label=8)

    assert summary["total"] == 30
    assert summary["labels"] == {
        "supported": 10,
        "refuted": 10,
        "not_enough_information": 10,
    }
    assert summary["duplicate_ids"] == []


def test_live_pubmed_claim_loader_rejects_invalid_label(tmp_path: Path) -> None:
    path = tmp_path / "claims.jsonl"
    path.write_text(
        json.dumps(
            {
                "claim_id": "bad-1",
                "question": "Does alpha improve beta?",
                "gold_label": "yes",
                "source": "pubmed",
                "max_papers": 3,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid gold_label"):
        load_claims_jsonl(path)


def test_live_pubmed_claim_loader_rejects_non_positive_max_papers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "claims.jsonl"
    path.write_text(
        json.dumps(
            {
                "claim_id": "bad-max-papers",
                "question": "Does alpha improve beta?",
                "gold_label": "supported",
                "source": "pubmed",
                "max_papers": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="max_papers must be positive"):
        load_claims_jsonl(path)


def test_live_pubmed_claim_loader_reports_non_object_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "claims.jsonl"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="claim row must be a JSON object"):
        load_claims_jsonl(path)


def test_claim_record_to_answer_request_payload_uses_live_flags() -> None:
    claim = ClaimRecord(
        claim_id="claim-test",
        question="Does APOE e4 increase Alzheimer's disease risk?",
        gold_label="supported",
        source="pubmed",
        max_papers=4,
    )

    payload = claim.to_answer_request_payload()

    assert payload == {
        "question": "Does APOE e4 increase Alzheimer's disease risk?",
        "source": "pubmed",
        "max_papers": 4,
        "use_llm_planner": True,
        "execute_support_refute": True,
        "use_llm_extractor": True,
        "use_llm_synthesis": True,
        "use_llm_verifier": True,
        "use_llm_revision": True,
        "use_llm_claim_logic": True,
        "export_logic_facts": True,
    }


class FakeLiveCollectorService:
    def __init__(self, workspace: Path, **kwargs) -> None:
        self.workspace = Path(workspace)
        self.closed = False

    async def answer_with_audit(self, request):
        run_id = f"run-{request.question.split()[1].lower()}"
        return type(
            "Audited",
            (),
            {
                "answer_result": type("AnswerResult", (), {"run_id": run_id})(),
                "trace": [],
                "model_dump": lambda self, mode="json": {
                    "answer_result": {"run_id": run_id},
                    "trace": [],
                },
            },
        )()

    def export_answer_run_asv_trajectory(self, run_id: str) -> TrajectoryRecord:
        return TrajectoryRecord(
            trajectory_id=f"bio-agent-{run_id}",
            run_id=run_id,
            source_adapter="bio_agent_workflow",
            task=TaskRecord(
                task_id=run_id,
                question=f"Question for {run_id}",
                domain="biomedical",
                candidate_space=CandidateSpace(
                    candidates=[
                        Candidate(id="supported", label="A", text="supported"),
                        Candidate(id="refuted", label="B", text="refuted"),
                        Candidate(
                            id="not_enough_information",
                            label="C",
                            text="not enough information",
                        ),
                    ],
                    gold_candidate_id=None,
                ),
            ),
            steps=[
                StepRecord(
                    step_id="retrieve",
                    index=0,
                    action={"type": "retrieve"},
                    observation={"summary": "retrieved fake papers"},
                    state_before={"question": f"Question for {run_id}"},
                    state_after={
                        "question": f"Question for {run_id}",
                        "evidence": ["fake evidence"],
                    },
                    cost={"source_call_count": 1, "tool_calls": 1},
                )
            ],
        )

    async def aclose(self) -> None:
        self.closed = True


class FailingLiveCollectorService(FakeLiveCollectorService):
    async def answer_with_audit(self, request):
        raise TimeoutError("provider timeout")


def test_collect_claims_dry_run_writes_frozen_trajectories(tmp_path: Path) -> None:
    claim = ClaimRecord(
        claim_id="supported-test",
        question="Does APOE e4 increase Alzheimer's disease risk?",
        gold_label="supported",
        source="pubmed",
        max_papers=3,
    )
    config = CollectionConfig(
        claims_path=tmp_path / "claims.jsonl",
        output_dir=tmp_path / "out",
        workspace=tmp_path / "workspace",
        limit=1,
    )

    rows, trajectories = collect_claims.run_sync(
        [claim],
        config=config,
        service_factory=FakeLiveCollectorService,
    )

    assert [row.status for row in rows] == ["completed"]
    assert rows[0].claim_id == "supported-test"
    assert rows[0].gold_label == "supported"
    assert len(trajectories) == 1
    assert trajectories[0].task.candidate_space.gold_candidate_id == "supported"

    write_collection_outputs(config.output_dir, rows, trajectories)

    assert (config.output_dir / "collection.jsonl").exists()
    assert (config.output_dir / "trajectory.jsonl").exists()
    payload = json.loads(
        (config.output_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert payload["task"]["candidate_space"]["gold_candidate_id"] == "supported"
    assert payload["task"]["gold_visible_to_evaluator"] is False
    assert payload["task"]["gold_used_only_for_validation"] is True


def test_collection_row_records_failures_without_throwing() -> None:
    row = CollectionRow.failure(
        claim_id="claim-failed",
        gold_label="refuted",
        message="provider timeout",
    )

    assert row.status == "failed"
    assert row.error == "provider timeout"
    assert row.run_id is None


def test_collect_claims_records_service_failures_without_throwing(
    tmp_path: Path,
) -> None:
    claim = ClaimRecord(
        claim_id="refuted-test",
        question="Does beta carotene reduce lung cancer incidence in smokers?",
        gold_label="refuted",
        source="pubmed",
        max_papers=3,
    )
    config = CollectionConfig(
        claims_path=tmp_path / "claims.jsonl",
        output_dir=tmp_path / "out",
        workspace=tmp_path / "workspace",
        limit=1,
    )

    rows, trajectories = collect_claims.run_sync(
        [claim],
        config=config,
        service_factory=FailingLiveCollectorService,
    )

    assert trajectories == []
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].claim_id == "refuted-test"
    assert rows[0].error == "provider timeout"


def test_collect_claims_rejects_non_positive_limit(tmp_path: Path) -> None:
    config = CollectionConfig(
        claims_path=tmp_path / "claims.jsonl",
        output_dir=tmp_path / "out",
        workspace=tmp_path / "workspace",
        limit=0,
    )

    with pytest.raises(ValueError, match="limit must be positive"):
        collect_claims.run_sync(
            [],
            config=config,
            service_factory=FakeLiveCollectorService,
        )


def test_collect_main_returns_nonzero_on_partial_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from eval.asv.live_pubmed import collect as collect_module

    claims_path = tmp_path / "claims.jsonl"
    output_dir = tmp_path / "out"
    claims_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "claim_id": "supported-test",
                        "question": "Does APOE e4 increase Alzheimer's disease risk?",
                        "gold_label": "supported",
                        "source": "pubmed",
                        "max_papers": 3,
                    }
                ),
                json.dumps(
                    {
                        "claim_id": "refuted-test",
                        "question": "Does beta carotene reduce lung cancer incidence in smokers?",
                        "gold_label": "refuted",
                        "source": "pubmed",
                        "max_papers": 3,
                    }
                ),
                json.dumps(
                    {
                        "claim_id": "nei-test",
                        "question": "Does taurine supplementation slow human brain aging?",
                        "gold_label": "not_enough_information",
                        "source": "pubmed",
                        "max_papers": 3,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class PartiallyFailingService(FakeLiveCollectorService):
        async def answer_with_audit(self, request):
            if "beta carotene" in request.question:
                raise TimeoutError("provider timeout")
            return await super().answer_with_audit(request)

    monkeypatch.setattr(collect_module, "BiomedEvidenceService", PartiallyFailingService)

    exit_code = collect_module.main(
        [
            "--claims",
            str(claims_path),
            "--workspace",
            str(tmp_path / "workspace"),
            "--output-dir",
            str(output_dir),
            "--ack-live",
        ]
    )

    assert exit_code == 1
    rows = [
        json.loads(line)
        for line in (output_dir / "collection.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["status"] for row in rows] == ["completed", "failed", "completed"]


def test_build_evaluate_command_uses_deepseek_cache_and_frozen_input(
    tmp_path: Path,
) -> None:
    run = EvaluationRun(
        input_path=tmp_path / "trajectory.jsonl",
        output_dir=tmp_path / "report",
        cache_path=tmp_path / "cache.jsonl",
        evaluated_path=tmp_path / "evaluated.jsonl",
        fallback_policy="floor",
        floor_score=-20.0,
    )

    command = build_evaluate_command(run)

    assert command[:4] == [".venv/bin/python", "-m", "asv_eval", "evaluate"]
    assert "--evaluator" in command
    assert "deepseek-chat-logprob" in command
    assert "--cache" in command
    assert str(run.cache_path) in command
    assert "--write-evaluated-trajectories" in command
    assert str(run.evaluated_path) in command
    assert "--fallback-policy" in command
    assert "floor" in command
    assert "--floor-score" in command
    assert "-20.0" in command


def test_secret_scan_allows_safe_env_var_name(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_text('{"credential_env": "DEEPSEEK_API_KEY"}', encoding="utf-8")

    assert scan_for_secret_markers([path]) == []


def test_secret_scan_flags_raw_provider_payload(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        '{"raw_provider_response": {"Authorization": "Bearer abc"}}',
        encoding="utf-8",
    )

    assert scan_for_secret_markers([path]) == [
        f"raw_provider_response found in {path}",
        f"Authorization found in {path}",
        f"Bearer  found in {path}",
    ]
