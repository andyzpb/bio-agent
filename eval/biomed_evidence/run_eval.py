from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

from eval.biomed_evidence.metrics import rate
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    EvidenceExtractionRequest,
    SearchBiomedicalLiteratureRequest,
    WatchTopicCreateRequest,
)
from plugins.biomed_evidence.service import BiomedEvidenceService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run biomedical evidence mock eval.")
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path(__file__).with_name("sample_questions.jsonl"),
    )
    parser.add_argument("--output", type=Path, default=Path("biomed_eval_results.json"))
    return parser


async def _run(args: argparse.Namespace) -> dict:
    cases = [
        json.loads(line)
        for line in args.questions.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    service = BiomedEvidenceService(Path(tempfile.mkdtemp(prefix="biomed-eval-")))
    started = time.monotonic()
    answer_results: list[dict] = []
    citation_checks: list[bool] = []
    refusal_checks: list[bool] = []
    schema_checks: list[bool] = []
    forbidden_checks: list[bool] = []
    manifest_checks: list[bool] = []
    repeatability_checks: list[bool] = []
    try:
        for case in cases:
            result = await service.answer_with_evidence(
                AnswerWithEvidenceRequest(question=case["question"], source="mock")
            )
            if not case.get("expected_refusal"):
                manifest_checks.append(_manifest_valid(result.retrieval_manifest))
            text = result.answer.lower()
            if case.get("must_include_citations"):
                citation_checks.append(bool(result.citations))
            if case.get("expected_refusal"):
                refusal_checks.append("cannot help diagnose" in text or "clinical" in text)
            forbidden = [str(item).lower() for item in case.get("forbidden_outputs", [])]
            forbidden_checks.append(not any(item in text for item in forbidden))
            for item in result.evidence_summary:
                try:
                    type(item).model_validate(item.model_dump())
                    schema_checks.append(True)
                except Exception:
                    schema_checks.append(False)
            answer_results.append(
                {
                    "id": case["id"],
                    "run_id": result.run_id,
                    "retrieval_id": result.retrieval_id,
                    "citations": len(result.citations),
                    "uncertainty": result.uncertainty_level,
                    "refused": "cannot help diagnose" in text or "clinical" in text,
                }
            )

        repeat_runs = [
            await service.search_with_manifest(
                SearchBiomedicalLiteratureRequest(
                    query="microglial activation Alzheimer's disease",
                    max_results=3,
                    source="mock",
                )
            )
            for _ in range(3)
        ]
        repeat_ids = [
            tuple(item.paper_id for item in result.items)
            for result in repeat_runs
        ]
        repeatability_checks.append(all(ids == repeat_ids[0] for ids in repeat_ids))
        manifest_checks.extend(
            _manifest_valid(result.retrieval_manifest) for result in repeat_runs
        )

        watch = service.create_watch(
            WatchTopicCreateRequest(
                topic="spatial transcriptomics in tumor microenvironment",
                include_keywords=["spatial transcriptomics", "tumor microenvironment"],
                preferred_methods=["spatial transcriptomics"],
                min_relevance_score=0.7,
            )
        )
        watch_result = await service.check_watch(watch.watch_id)
        decisions = watch_result.decisions if watch_result is not None else []
        push_decisions = [
            item.relevance_score >= watch.min_relevance_score
            for item in decisions
            if item.decision == "push"
        ]
        metrics = {
            "citation_coverage": rate(citation_checks),
            "schema_validity": rate(schema_checks) if schema_checks else 1.0,
            "refusal_success": rate(refusal_checks),
            "forbidden_output_avoidance": rate(forbidden_checks),
            "watch_precision": rate(push_decisions) if push_decisions else 0.0,
            "retrieval_manifest_validity": rate(manifest_checks),
            "retrieval_repeatability": rate(repeatability_checks),
            "latency_seconds": round(time.monotonic() - started, 4),
        }
        return {
            "metrics": metrics,
            "answers": answer_results,
            "watch": {
                "watch_id": watch.watch_id,
                "decisions": [item.model_dump(mode="json") for item in decisions],
            },
        }
    finally:
        await service.aclose()


def _manifest_valid(value: object) -> bool:
    manifest = getattr(value, "retrieval_id", None)
    returned = getattr(value, "returned_paper_ids", None)
    compiled = getattr(value, "compiled_query", None)
    return bool(manifest and isinstance(returned, list) and compiled is not None)


def main() -> None:
    args = _parser().parse_args()
    result = asyncio.run(_run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
