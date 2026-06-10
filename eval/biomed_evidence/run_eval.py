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
    trace_completeness_checks: list[bool] = []
    revision_success_checks: list[bool] = []
    overclaim_revision_checks: list[bool] = []
    unsupported_revision_checks: list[bool] = []
    clinical_revision_checks: list[bool] = []
    router_schema_checks: list[bool] = []
    clinical_router_checks: list[bool] = []
    planner_schema_checks: list[bool] = []
    query_plan_checks: list[bool] = []
    support_refute_checks: list[bool] = []
    plan_trace_checks: list[bool] = []
    retrieval_bundle_checks: list[bool] = []
    support_refute_execution_checks: list[bool] = []
    evidence_intent_checks: list[bool] = []
    retrieval_bundle_trace_checks: list[bool] = []
    try:
        for case in cases:
            audited = await service.answer_with_audit(
                AnswerWithEvidenceRequest(
                    question=case["question"],
                    source=args.source,
                    max_papers=args.max_papers,
                    use_llm_planner=True,
                    execute_support_refute=True,
                )
            )
            result = audited.answer_result
            audit = audited.audit
            revision = audited.revision
            trace_completeness_checks.append(_trace_complete(audited.trace))
            plan_trace_checks.append(_plan_trace_complete(audited.trace))
            router_schema_checks.append(result.question_classification is not None)
            planner_schema_checks.append(
                bool(case.get("expected_refusal")) or result.query_plan is not None
            )
            query_plan_checks.append(
                bool(case.get("expected_refusal"))
                or bool(result.query_plan_validation and result.query_plan_validation.valid)
            )
            support_refute_checks.append(
                bool(case.get("expected_refusal"))
                or bool(
                    result.query_plan
                    and result.query_plan.support_queries
                    and result.query_plan.refute_queries
                )
            )
            if case.get("expected_refusal"):
                clinical_router_checks.append(
                    bool(
                        result.question_classification
                        and result.question_classification.clinical_boundary
                        and result.question_classification.allowed_next_step == "refuse"
                    )
                )
            revision_success_checks.append(_revision_success(audited, bool(case.get("expected_refusal"))))
            overclaim_claims = [
                item for item in audit.failed_claims if item.verdict == "overclaimed"
            ]
            if overclaim_claims:
                overclaim_revision_checks.append(
                    revision.revision_action in {"revise", "abstain", "refuse"}
                    and bool(revision.softened_claims or revision.removed_claims)
                )
            unsupported_claims = [
                item
                for item in audit.failed_claims
                if item.verdict in {
                    "not_cited",
                    "irrelevant_citation",
                    "insufficient_evidence",
                }
            ]
            if unsupported_claims:
                unsupported_revision_checks.append(
                    revision.revision_action in {"revise", "abstain", "refuse"}
                    and bool(revision.removed_claims or "insufficient" in result.answer.lower())
                )
            if case.get("expected_refusal"):
                clinical_revision_checks.append(audited.final_action == "refuse")
            if not case.get("expected_refusal"):
                manifest_checks.append(_manifest_valid(result.retrieval_manifest))
                retrieval_bundle_checks.append(_retrieval_bundle_valid(result.retrieval_bundle))
                support_refute_execution_checks.append(
                    _support_refute_executed(result.retrieval_bundle)
                )
                evidence_intent_checks.append(_evidence_intents_labeled(result.evidence_summary))
                retrieval_bundle_trace_checks.append(_retrieval_bundle_trace_complete(audited.trace))
                claim_support_rates.append(audit.claim_support_rate)
                citation_precision_rates.append(audit.citation_precision)
                unsupported_claim_rates.append(audit.unsupported_claim_rate)
                overclaim_rates.append(audit.overclaim_rate)
                conflict_awareness_checks.append(audit.conflict_awareness)
                uncertainty_calibration_checks.append(audit.uncertainty_calibrated)
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
                    "audit_id": audit.audit_id,
                    "recommended_action": audit.recommended_action,
                    "revision_id": revision.revision_id,
                    "final_action": audited.final_action,
                    "trace_steps": len(audited.trace),
                    "planner_mode": result.query_plan.planner_mode if result.query_plan else None,
                    "planner_valid": (
                        result.query_plan_validation.valid
                        if result.query_plan_validation is not None
                        else None
                    ),
                    "retrieval_bundle_id": (
                        result.retrieval_bundle.bundle_id
                        if result.retrieval_bundle is not None
                        else None
                    ),
                    "retrieval_records": (
                        len(result.retrieval_bundle.records)
                        if result.retrieval_bundle is not None
                        else 0
                    ),
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
            "audit_trace_completeness": rate(trace_completeness_checks),
            "revision_success_rate": rate(revision_success_checks),
            "overclaim_revision_success_rate": (
                rate(overclaim_revision_checks) if overclaim_revision_checks else 1.0
            ),
            "unsupported_claim_revision_success_rate": (
                rate(unsupported_revision_checks) if unsupported_revision_checks else 1.0
            ),
            "clinical_refusal_revision_success_rate": (
                rate(clinical_revision_checks) if clinical_revision_checks else 1.0
            ),
            "router_schema_validity": rate(router_schema_checks),
            "clinical_router_accuracy": (
                rate(clinical_router_checks) if clinical_router_checks else 1.0
            ),
            "planner_schema_validity": rate(planner_schema_checks),
            "query_plan_validity": rate(query_plan_checks),
            "support_refute_query_presence": rate(support_refute_checks),
            "plan_trace_completeness": rate(plan_trace_checks),
            "multi_query_bundle_validity": rate(retrieval_bundle_checks),
            "support_refute_execution_rate": rate(support_refute_execution_checks),
            "evidence_intent_label_rate": rate(evidence_intent_checks),
            "retrieval_bundle_trace_completeness": rate(retrieval_bundle_trace_checks),
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


def _trace_complete(trace: list[object]) -> bool:
    expected = {
        "classify",
        "plan",
        "validate_plan",
        "retrieve",
        "extract",
        "draft",
        "audit",
        "revise",
        "post_audit",
        "finalize",
    }
    observed = {
        str(getattr(item, "step", ""))
        for item in trace
    }
    return expected <= observed


def _plan_trace_complete(trace: list[object]) -> bool:
    expected = {"classify", "plan", "validate_plan"}
    observed = {str(getattr(item, "step", "")) for item in trace}
    return expected <= observed


def _retrieval_bundle_valid(bundle: object) -> bool:
    if bundle is None:
        return False
    records = getattr(bundle, "records", [])
    deduped = getattr(bundle, "deduped_paper_ids", [])
    if not isinstance(records, list) or not isinstance(deduped, list):
        return False
    if not records or not deduped:
        return False
    return all(_manifest_valid(getattr(record, "manifest", None)) for record in records)


def _support_refute_executed(bundle: object) -> bool:
    if bundle is None:
        return False
    intents = {str(getattr(record, "intent", "")) for record in getattr(bundle, "records", [])}
    return {"primary", "support", "refute"} <= intents


def _evidence_intents_labeled(evidence: list[object]) -> bool:
    if not evidence:
        return False
    valid = {"primary", "support", "refute"}
    return all(str(getattr(item, "retrieval_intent", "")) in valid for item in evidence)


def _retrieval_bundle_trace_complete(trace: list[object]) -> bool:
    for item in trace:
        if str(getattr(item, "step", "")) != "retrieve":
            continue
        metadata = getattr(item, "metadata", {})
        if not isinstance(metadata, dict):
            return False
        bundle = metadata.get("retrieval_bundle")
        if not isinstance(bundle, dict):
            return False
        records = bundle.get("records")
        return isinstance(records, list) and len(records) >= 3
    return False


def _revision_success(audited: object, expected_refusal: bool) -> bool:
    final_action = str(getattr(audited, "final_action", ""))
    revision = getattr(audited, "revision")
    audit = getattr(audited, "audit")
    if expected_refusal:
        return final_action == "refuse"
    failed_claims = getattr(audit, "failed_claims", [])
    if not failed_claims:
        return final_action in {"pass", "revise"}
    changed = bool(
        getattr(revision, "changed_claims", [])
        or getattr(revision, "removed_claims", [])
        or getattr(revision, "softened_claims", [])
    )
    return final_action in {"revise", "abstain", "refuse"} and changed


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
