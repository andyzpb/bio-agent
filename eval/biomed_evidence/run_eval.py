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
    parser.add_argument("--source", choices=["mock", "pubmed"], default="mock")
    parser.add_argument(
        "--live-pubmed",
        action="store_true",
        help="Allow real PubMed network retrieval when --source pubmed is selected.",
    )
    parser.add_argument("--max-papers", type=int, default=3)
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
    claim_support_rates: list[float] = []
    citation_precision_rates: list[float] = []
    unsupported_claim_rates: list[float] = []
    overclaim_rates: list[float] = []
    conflict_awareness_checks: list[bool] = []
    uncertainty_calibration_checks: list[bool] = []
    try:
        for case in cases:
            result = await service.answer_with_evidence(
                AnswerWithEvidenceRequest(
                    question=case["question"],
                    source=args.source,
                    max_papers=args.max_papers,
                )
            )
            if not case.get("expected_refusal"):
                manifest_checks.append(_manifest_valid(result.retrieval_manifest))
                audit = service.audit_answer_run(result.run_id)
                if audit is not None:
                    claim_support_rates.append(audit.claim_support_rate)
                    citation_precision_rates.append(audit.citation_precision)
                    unsupported_claim_rates.append(audit.unsupported_claim_rate)
                    overclaim_rates.append(audit.overclaim_rate)
                    conflict_awareness_checks.append(audit.conflict_awareness)
                    uncertainty_calibration_checks.append(audit.uncertainty_calibrated)
            else:
                audit = None
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
                    "audit_id": audit.audit_id if audit is not None else None,
                    "recommended_action": audit.recommended_action if audit is not None else None,
                }
            )

        repeat_runs = []
        for _ in range(3):
            repeat_runs.append(
                await service.search_with_manifest(
                    SearchBiomedicalLiteratureRequest(
                        query="microglial activation Alzheimer's disease",
                        max_results=args.max_papers,
                        source=args.source,
                    )
                )
            )
        repeat_ids = [
            tuple(item.paper_id for item in result.items)
            for result in repeat_runs
        ]
        repeatability_checks.append(all(ids == repeat_ids[0] for ids in repeat_ids))
        count_stability_checks = [
            len(ids) == len(repeat_ids[0])
            for ids in repeat_ids
        ]
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
        watch_result = await service.check_watch(watch.watch_id, source=args.source)
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
            "retrieval_count_stability": rate(count_stability_checks),
            "claim_support_rate": _average(claim_support_rates),
            "citation_precision": _average(citation_precision_rates),
            "unsupported_claim_rate": _average(unsupported_claim_rates),
            "overclaim_rate": _average(overclaim_rates),
            "conflict_awareness_rate": rate(conflict_awareness_checks),
            "uncertainty_calibration_rate": rate(uncertainty_calibration_checks),
            "latency_seconds": round(time.monotonic() - started, 4),
        }
        return {
            "metrics": metrics,
            "source": args.source,
            "answers": answer_results,
            "retrieval_repeat_runs": [
                {
                    "retrieval_id": item.retrieval_manifest.retrieval_id,
                    "paper_ids": [paper.paper_id for paper in item.items],
                    "warnings": item.retrieval_manifest.warnings,
                    "errors": item.retrieval_manifest.errors,
                }
                for item in repeat_runs
            ],
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


def _average(values: list[float]) -> float:
    if not values:
        return 1.0
    return round(sum(values) / len(values), 4)


def main() -> None:
    args = _parser().parse_args()
    if args.source == "pubmed" and not args.live_pubmed:
        raise SystemExit(
            "Real PubMed eval is opt-in. Re-run with --source pubmed --live-pubmed."
        )
    result = asyncio.run(_run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
