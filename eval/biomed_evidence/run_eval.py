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
    BiomedProjectCreateRequest,
    EvidenceExtractionRequest,
    GenerateProjectEvidenceBriefRequest,
    LiteratureAccessCheckRequest,
    LiteratureSearchRequest,
    ProjectClaimRecordRequest,
    ProjectPaperDecisionRequest,
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
    literature_check = await service.check_literature_access(
        LiteratureAccessCheckRequest(
            source=args.source,
            query="microglia Alzheimer disease",
            max_results=min(max(1, args.max_papers), 3),
        )
    )
    literature_search = await service.search_literature(
        LiteratureSearchRequest(
            source=args.source,
            query="microglia Alzheimer disease",
            max_results=min(max(1, args.max_papers), 3),
            retrieval_intent="primary",
            require_abstract=True,
            store=True,
        )
    )
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
    extraction_mode_checks: list[bool] = []
    span_grounding_checks: list[bool] = []
    synthesis_mode_checks: list[bool] = []
    synthesis_audit_gate_checks: list[bool] = []
    advisory_schema_checks: list[bool] = []
    audit_verifier_agreement_checks: list[bool] = []
    high_risk_disagreement_rates: list[float] = []
    advisory_false_pass_blocked_checks: list[bool] = []
    verifier_trace_checks: list[bool] = []
    project_context_application_checks: list[bool] = []
    rejected_paper_exclusion_checks: list[bool] = []
    saved_paper_prioritization_checks: list[bool] = []
    memory_not_used_as_evidence_checks: list[bool] = []
    review_queue_capture_checks: list[bool] = []
    project_brief_audit_checks: list[bool] = []
    project_trace_checks: list[bool] = []
    clinical_boundary_before_memory_checks: list[bool] = []
    logic_trace_checks: list[bool] = []
    logic_fact_export_checks: list[bool] = []
    logic_parser_fallback_rates: list[float] = []
    clinical_boundary_before_logic_checks: list[bool] = []
    try:
        for case in cases:
            audited = await service.answer_with_audit(
                AnswerWithEvidenceRequest(
                    question=case["question"],
                    source=args.source,
                    max_papers=args.max_papers,
                    use_llm_planner=True,
                    execute_support_refute=True,
                    use_llm_extractor=True,
                    use_llm_synthesis=True,
                    use_llm_verifier=True,
                    use_llm_claim_logic=True,
                    export_logic_facts=True,
                )
            )
            result = audited.answer_result
            audit = audited.audit
            advisory = audited.advisory_verifier
            revision = audited.revision
            trace_completeness_checks.append(_trace_complete(audited.trace))
            plan_trace_checks.append(_plan_trace_complete(audited.trace))
            router_schema_checks.append(result.question_classification is not None)
            planner_schema_checks.append(
                bool(case.get("expected_refusal")) or result.query_plan is not None
            )
            query_plan_checks.append(
                bool(case.get("expected_refusal"))
                or bool(
                    result.query_plan_validation and result.query_plan_validation.valid
                )
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
            revision_success_checks.append(
                _revision_success(audited, bool(case.get("expected_refusal")))
            )
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
                if item.verdict
                in {
                    "not_cited",
                    "irrelevant_citation",
                    "insufficient_evidence",
                }
            ]
            if unsupported_claims:
                unsupported_revision_checks.append(
                    revision.revision_action in {"revise", "abstain", "refuse"}
                    and bool(
                        revision.removed_claims
                        or "insufficient" in result.answer.lower()
                    )
                )
            if case.get("expected_refusal"):
                clinical_revision_checks.append(audited.final_action == "refuse")
                logic_trace = _logic_trace(audited.trace)
                clinical_boundary_before_logic_checks.append(
                    not bool(logic_trace.get("enabled"))
                    and logic_trace.get("claim_count") == 0
                    and logic_trace.get("fact_export_count") == 0
                )
            if not case.get("expected_refusal"):
                logic_trace = _logic_trace(audited.trace)
                parser_mode_counts = logic_trace.get("parser_mode_counts")
                fallback_count = (
                    int(parser_mode_counts.get("fallback", 0))
                    if isinstance(parser_mode_counts, dict)
                    else 0
                )
                parser_count = (
                    sum(int(value) for value in parser_mode_counts.values())
                    if isinstance(parser_mode_counts, dict)
                    else 0
                )
                logic_trace_checks.append(
                    bool(logic_trace.get("enabled"))
                    and int(logic_trace.get("claim_count") or 0) >= 1
                )
                logic_fact_export_checks.append(
                    int(logic_trace.get("fact_export_count") or 0) >= 1
                    and int(logic_trace.get("fact_count") or 0) >= 1
                )
                logic_parser_fallback_rates.append(
                    fallback_count / parser_count if parser_count else 0.0
                )
                manifest_checks.append(_manifest_valid(result.retrieval_manifest))
                retrieval_bundle_checks.append(
                    _retrieval_bundle_valid(result.retrieval_bundle)
                )
                support_refute_execution_checks.append(
                    _support_refute_executed(result.retrieval_bundle)
                )
                evidence_intent_checks.append(
                    _evidence_intents_labeled(result.evidence_summary)
                )
                retrieval_bundle_trace_checks.append(
                    _retrieval_bundle_trace_complete(audited.trace)
                )
                extraction_mode_checks.append(
                    _extraction_modes_recorded(result.evidence_summary)
                )
                span_grounding_checks.append(
                    _spans_grounded(
                        service, result.evidence_summary, source=args.source
                    )
                )
                synthesis_mode_checks.append(
                    result.synthesis_mode in {"deterministic", "llm", "fallback"}
                )
                synthesis_audit_gate_checks.append(
                    result.synthesis_mode != "llm"
                    or audit.recommended_action not in {"revise", "refuse_or_abstain"}
                )
                advisory_schema_checks.append(
                    advisory is not None
                    and advisory.verifier_mode in {"llm", "fallback"}
                    and advisory.deterministic_action == audit.recommended_action
                )
                audit_verifier_agreement_checks.append(
                    advisory is not None
                    and advisory.advisory_action
                    in {
                        audit.recommended_action,
                        "needs_expert_review",
                        "pass_with_limitations",
                    }
                )
                high_risk_disagreement_rates.append(
                    1.0 if advisory and advisory.high_risk_disagreement_count else 0.0
                )
                advisory_false_pass_blocked_checks.append(
                    advisory is None
                    or audit.recommended_action in {"pass", "pass_with_limitations"}
                    or advisory.advisory_action not in {"pass", "pass_with_limitations"}
                )
                verifier_trace_checks.append(_verifier_trace_complete(audited.trace))
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
                refusal_checks.append(
                    "cannot help diagnose" in text or "clinical" in text
                )
            forbidden = [
                str(item).lower() for item in case.get("forbidden_outputs", [])
            ]
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
                    "planner_mode": (
                        result.query_plan.planner_mode if result.query_plan else None
                    ),
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
                    "synthesis_mode": result.synthesis_mode,
                    "advisory_verifier_mode": (
                        advisory.verifier_mode if advisory is not None else None
                    ),
                    "advisory_action": (
                        advisory.advisory_action if advisory is not None else None
                    ),
                    "advisory_high_risk_disagreements": (
                        advisory.high_risk_disagreement_count
                        if advisory is not None
                        else 0
                    ),
                    "extraction_modes": sorted(
                        {item.extraction_mode for item in result.evidence_summary}
                    ),
                    "logic_trace": _logic_trace(audited.trace),
                }
            )

        project = service.create_project(
            BiomedProjectCreateRequest(
                name="Microglia AD progression",
                research_question=(
                    "Evidence linking microglial activation to Alzheimer's disease progression"
                ),
                include_keywords=["microglial activation", "Alzheimer's disease"],
                exclude_keywords=["dosage", "patient-specific treatment"],
                preferred_methods=["single-cell RNA-seq", "longitudinal cohort"],
            )
        )
        seed = await service.search_with_manifest(
            SearchBiomedicalLiteratureRequest(
                query="microglial activation Alzheimer's disease progression",
                max_results=max(2, args.max_papers),
                source=args.source,
            )
        )
        saved_paper_id = seed.items[0].paper_id if seed.items else ""
        rejected_paper_id = seed.items[1].paper_id if len(seed.items) > 1 else ""
        if saved_paper_id:
            service.save_project_paper_decision(
                project.project_id,
                ProjectPaperDecisionRequest(
                    paper_id=saved_paper_id,
                    source=args.source,
                    decision="saved",
                    reason="Relevant seed paper for the project.",
                    retrieval_id=seed.retrieval_manifest.retrieval_id,
                ),
            )
        if rejected_paper_id:
            service.save_project_paper_decision(
                project.project_id,
                ProjectPaperDecisionRequest(
                    paper_id=rejected_paper_id,
                    source=args.source,
                    decision="rejected",
                    reason="Project reviewer excluded this paper.",
                    retrieval_id=seed.retrieval_manifest.retrieval_id,
                ),
            )
        project_audited = await service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                project_id=project.project_id,
                source=args.source,
                max_papers=max(2, args.max_papers),
                use_llm_planner=True,
                execute_support_refute=True,
                use_llm_extractor=True,
                use_llm_synthesis=True,
                use_llm_verifier=True,
                use_llm_claim_logic=True,
                export_logic_facts=True,
            )
        )
        project_result = project_audited.answer_result
        project_trace = project_result.project_context_trace
        returned_project_ids = (
            project_result.retrieval_manifest.returned_paper_ids
            if project_result.retrieval_manifest is not None
            else []
        )
        project_context_application_checks.append(
            project_result.project_id == project.project_id
            and bool(project_trace.get("memory_used"))
        )
        rejected_paper_exclusion_checks.append(
            not rejected_paper_id or rejected_paper_id not in returned_project_ids
        )
        saved_paper_prioritization_checks.append(
            not saved_paper_id
            or saved_paper_id not in returned_project_ids
            or returned_project_ids[0] == saved_paper_id
        )
        memory_not_used_as_evidence_checks.append(
            all(item.paper_id != project.project_id for item in project_result.evidence_summary)
        )
        queue_items, _ = service.list_project_review_queue(project.project_id)
        review_queue_capture_checks.append(
            bool(queue_items)
            or not project_audited.audit.failed_claims
            and not project_result.conflicting_evidence
        )
        if project_result.evidence_summary:
            first_evidence = project_result.evidence_summary[0]
            service.save_project_claim_record(
                project.project_id,
                ProjectClaimRecordRequest(
                    claim=first_evidence.claim,
                    status="supported",
                    evidence_ids=[first_evidence.evidence_id],
                    audit_ids=[project_audited.audit.audit_id],
                    verifier_ids=(
                        [project_audited.advisory_verifier.verifier_id]
                        if project_audited.advisory_verifier is not None
                        else []
                    ),
                ),
            )
        brief = service.generate_project_evidence_brief(
            GenerateProjectEvidenceBriefRequest(project_id=project.project_id)
        )
        project_brief_audit_checks.append(
            bool(brief.audit_ids)
            and "Project memory is context only" in brief.content
        )
        project_trace_checks.append(
            bool(project_trace.get("original_paper_ids"))
            and isinstance(project_trace.get("returned_paper_ids"), list)
        )
        clinical_project_answer = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What dose should my mother take for Alzheimer disease?",
                project_id=project.project_id,
                source=args.source,
            )
        )
        clinical_boundary_before_memory_checks.append(
            clinical_project_answer.project_id is None
            and not bool(clinical_project_answer.project_context_trace.get("memory_used"))
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
            tuple(item.paper_id for item in result.items) for result in repeat_runs
        ]
        repeatability_checks.append(all(ids == repeat_ids[0] for ids in repeat_ids))
        count_stability_checks = [len(ids) == len(repeat_ids[0]) for ids in repeat_ids]
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
            "literature_access_ready": 1.0 if literature_check.ready else 0.0,
            "literature_access_item_count": literature_check.item_count,
            "literature_access_abstract_coverage": literature_check.abstract_coverage,
            "literature_access_live": literature_check.live,
            "literature_search_manifest_validity": (
                1.0
                if _manifest_valid(literature_search.retrieval_manifest)
                else 0.0
            ),
            "literature_search_item_count": literature_search.coverage.item_count,
            "literature_search_stored_paper_count": (
                literature_search.coverage.stored_paper_count
            ),
            "literature_search_abstract_coverage": (
                literature_search.coverage.abstract_coverage
            ),
            "literature_search_warning_count": len(literature_search.warnings),
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
                rate(unsupported_revision_checks)
                if unsupported_revision_checks
                else 1.0
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
            "extraction_mode_record_rate": rate(extraction_mode_checks),
            "span_grounding_rate": rate(span_grounding_checks),
            "synthesis_mode_record_rate": rate(synthesis_mode_checks),
            "synthesis_audit_gate_success": rate(synthesis_audit_gate_checks),
            "advisory_schema_validity": rate(advisory_schema_checks),
            "audit_verifier_agreement_rate": rate(audit_verifier_agreement_checks),
            "high_risk_disagreement_rate": _average(high_risk_disagreement_rates),
            "advisory_false_pass_blocked_rate": rate(
                advisory_false_pass_blocked_checks
            ),
            "verifier_trace_completeness": rate(verifier_trace_checks),
            "project_context_application_rate": rate(
                project_context_application_checks
            ),
            "rejected_paper_exclusion_rate": rate(rejected_paper_exclusion_checks),
            "saved_paper_prioritization_rate": rate(
                saved_paper_prioritization_checks
            ),
            "memory_not_used_as_evidence_rate": rate(
                memory_not_used_as_evidence_checks
            ),
            "review_queue_capture_rate": rate(review_queue_capture_checks),
            "project_brief_audit_pass_rate": rate(project_brief_audit_checks),
            "project_trace_completeness": rate(project_trace_checks),
            "clinical_boundary_before_memory_rate": rate(
                clinical_boundary_before_memory_checks
            ),
            "logic_trace_completeness": rate(logic_trace_checks),
            "logic_fact_export_success_rate": rate(logic_fact_export_checks),
            "logic_parser_fallback_rate": _average(logic_parser_fallback_rates),
            "clinical_boundary_before_logic_rate": rate(
                clinical_boundary_before_logic_checks
            ),
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
            "literature_search": {
                "retrieval_id": (
                    literature_search.retrieval_manifest.retrieval_id
                ),
                "paper_ids": [paper.paper_id for paper in literature_search.items],
                "coverage": literature_search.coverage.model_dump(mode="json"),
                "warnings": literature_search.warnings,
                "errors": literature_search.errors,
            },
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
        "advisory_verify",
        "revise",
        "post_audit",
        "finalize",
    }
    observed = {str(getattr(item, "step", "")) for item in trace}
    return expected <= observed


def _plan_trace_complete(trace: list[object]) -> bool:
    expected = {"classify", "plan", "validate_plan"}
    observed = {str(getattr(item, "step", "")) for item in trace}
    return expected <= observed


def _verifier_trace_complete(trace: list[object]) -> bool:
    return any(str(getattr(item, "step", "")) == "advisory_verify" for item in trace)


def _logic_trace(trace: list[object]) -> dict[str, object]:
    for item in trace:
        if str(getattr(item, "step", "")) != "audit":
            continue
        metadata = getattr(item, "metadata", {})
        if not isinstance(metadata, dict):
            return {}
        logic = metadata.get("logic_audit")
        if isinstance(logic, dict):
            return logic
    return {}


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
    intents = {
        str(getattr(record, "intent", "")) for record in getattr(bundle, "records", [])
    }
    return {"primary", "support", "refute"} <= intents


def _evidence_intents_labeled(evidence: list[object]) -> bool:
    if not evidence:
        return False
    valid = {"primary", "support", "refute"}
    return all(str(getattr(item, "retrieval_intent", "")) in valid for item in evidence)


def _extraction_modes_recorded(evidence: list[object]) -> bool:
    if not evidence:
        return False
    valid = {"deterministic", "llm", "fallback"}
    return all(str(getattr(item, "extraction_mode", "")) in valid for item in evidence)


def _spans_grounded(
    service: BiomedEvidenceService, evidence: list[object], *, source: str
) -> bool:
    if not evidence:
        return False
    for item in evidence:
        span = _norm(str(getattr(item, "evidence_span", "") or ""))
        paper_id = str(getattr(item, "paper_id", "") or "")
        if not span or not paper_id:
            return False
        paper = service.storage.get_paper(paper_id, source=source)
        if paper is None:
            return False
        haystack = _norm(f"{paper.title} {paper.abstract or ''}")
        if span.lower() not in haystack.lower():
            return False
    return True


def _norm(value: str) -> str:
    return " ".join(value.split())


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
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
