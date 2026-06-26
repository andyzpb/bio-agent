from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.biomed_evidence.metrics import rate
from plugins.biomed_evidence.schemas import (
    ExportEvidenceReportRequest,
    FullTextEnhancementRequest,
    HarnessScenario,
    HarnessScenarioResult,
    PilotReport,
    RunLiteratureSetSummary,
)
from plugins.biomed_evidence.service import BiomedEvidenceService

SCHEMA_VERSION = "biomed-harness-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run biomedical evidence harness.")
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    return parser


def _load_scenarios(path: Path) -> list[HarnessScenario]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = [
            json.loads(line) for line in stripped.splitlines() if line.strip()
        ]
    if isinstance(payload, dict):
        items = payload.get("scenarios") if isinstance(payload.get("scenarios"), list) else [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("Scenario file must contain JSON object, array, or JSONL.")
    return [HarnessScenario.model_validate(item) for item in items]


def _metric_bool(value: Any) -> bool:
    return bool(value)


def _full_text_enhancement_success(
    *,
    scenario: HarnessScenario,
    result: HarnessScenarioResult,
) -> bool | None:
    if not scenario.enable_full_text_enhance:
        return None
    enhancement = result.full_text_enhancement
    processed = len(enhancement.get("processed_paper_ids") or [])
    unavailable = len(enhancement.get("unavailable_paper_ids") or [])
    used_full_text = bool(
        enhancement.get("document_ids") or enhancement.get("extracted_evidence_ids")
    )
    return used_full_text and unavailable < processed


def _review_completion_metrics(review: dict[str, Any]) -> tuple[bool, bool, bool]:
    review_available = bool(review.get("available"))
    review_validation_ok = review_available and _metric_bool(review.get("validation_ok"))
    total_claims = int(review.get("total_claims") or 0)
    latest_decision_count = int(review.get("latest_decision_count") or 0)
    review_completion = (
        review_available
        and total_claims > 0
        and latest_decision_count >= total_claims
    )
    return review_available, review_validation_ok, review_completion


def _build_metrics(
    *,
    scenario: HarnessScenario,
    result: HarnessScenarioResult,
) -> dict[str, Any]:
    audit = result.pilot_report.audit_summary
    review = result.pilot_report.review_summary
    roi = result.pilot_report.roi
    observability = result.pilot_report.observability
    literature = result.literature_set_summary
    review_available, review_validation_ok, review_completion = (
        _review_completion_metrics(review)
    )
    return {
        "citation_count": int(result.metrics.get("citation_count") or 0),
        "citation_precision": float(audit.get("citation_precision") or 0.0),
        "unsupported_claim_rate": float(audit.get("unsupported_claim_rate") or 0.0),
        "overclaim_rate": float(audit.get("overclaim_rate") or 0.0),
        "review_available": review_available,
        "review_validation_ok": review_validation_ok,
        "review_completion": review_completion,
        "pilot_report_roi_present": (
            roi.manual_baseline_minutes is not None
            and roi.reviewer_minutes is not None
            and roi.time_saved_minutes is not None
        ),
        "full_text_enhancement_requested": scenario.enable_full_text_enhance,
        "full_text_enhancement_success": _full_text_enhancement_success(
            scenario=scenario,
            result=result,
        ),
        "latency_seconds": observability.latency_seconds,
        "prompt_tokens": observability.prompt_tokens,
        "cache_hit_tokens": observability.cache_hit_tokens,
        "cache_hit_rate": observability.cache_hit_rate,
        "llm_call_count": observability.llm_call_count,
        "source_call_count": observability.source_call_count,
        "estimated_cost_usd": observability.estimated_cost_usd,
        "artifact_cache_hit_count": observability.artifact_cache_hit_count,
        "artifact_cache_miss_count": observability.artifact_cache_miss_count,
        "artifact_cache_write_count": observability.artifact_cache_write_count,
        "literature_set_total_papers": result.literature_set_summary.total_papers,
        "literature_set_saved_count": literature.saved_count,
        "literature_set_rejected_count": literature.rejected_count,
        "literature_set_needs_review_count": literature.needs_review_count,
        "literature_set_full_text_count": literature.full_text_count,
        "literature_set_packet_included_count": literature.packet_included_count,
    }


def _build_gates(
    *,
    scenario: HarnessScenario,
    result: HarnessScenarioResult,
) -> dict[str, Any]:
    answer_text = result.final_answer.lower()
    forbidden_hits = [
        item for item in scenario.forbidden_outputs if item.lower() in answer_text
    ]
    gates: dict[str, Any] = {
        "must_include_citations": {
            "required": scenario.must_include_citations,
            "passed": (
                (not scenario.must_include_citations)
                or int(result.metrics.get("citation_count") or 0) > 0
            ),
        },
        "forbidden_outputs": {
            "forbidden_outputs": list(scenario.forbidden_outputs),
            "matches": forbidden_hits,
            "passed": not forbidden_hits,
        },
        "max_unsupported_rate": {
            "limit": scenario.max_unsupported_rate,
            "actual": result.metrics["unsupported_claim_rate"],
            "passed": (
                scenario.max_unsupported_rate is None
                or result.metrics["unsupported_claim_rate"]
                <= scenario.max_unsupported_rate
            ),
        },
        "max_overclaim_rate": {
            "limit": scenario.max_overclaim_rate,
            "actual": result.metrics["overclaim_rate"],
            "passed": (
                scenario.max_overclaim_rate is None
                or result.metrics["overclaim_rate"] <= scenario.max_overclaim_rate
            ),
        },
        "require_review_completion": {
            "required": scenario.require_review_completion,
            "passed": (
                (not scenario.require_review_completion)
                or bool(result.metrics["review_completion"])
            ),
        },
        "require_literature_set": {
            "required": scenario.require_literature_set,
            "passed": (
                (not scenario.require_literature_set)
                or result.literature_set_summary.total_papers > 0
            ),
        },
    }
    gates["passed"] = all(
        item["passed"] for item in gates.values() if isinstance(item, dict)
    )
    return gates


async def _run_scenario(
    service: BiomedEvidenceService,
    scenario: HarnessScenario,
) -> HarnessScenarioResult:
    audited = await service.run_harness_scenario(scenario)
    enhancement: dict[str, Any] = {}
    warnings: list[str] = []
    if scenario.enable_full_text_enhance:
        envelope = await service.enhance_run_with_full_text(
            FullTextEnhancementRequest(
                run_id=audited.answer_result.run_id,
                source=scenario.source,
                max_papers=scenario.max_papers,
                use_open_provider=False,
            )
        )
        enhancement = {"ok": envelope.ok, **envelope.result}
        warnings.extend(envelope.warnings)
        if envelope.message:
            warnings.append(envelope.message)
        if envelope.errors:
            warnings.extend(error.message for error in envelope.errors)
    literature_set = service.get_run_literature_set(
        audited.answer_result.run_id,
        project_id=scenario.project_id or "",
    )
    pilot_report = PilotReport.model_validate_json(
        await service.export_report(
            ExportEvidenceReportRequest(
                run_id=audited.answer_result.run_id,
                report_type="pilot",
                format="json",
                manual_baseline_minutes=scenario.manual_baseline_minutes,
                reviewer_minutes=scenario.reviewer_minutes,
            )
        )
    )
    result = HarnessScenarioResult(
        scenario_id=scenario.id,
        run_id=audited.answer_result.run_id,
        retrieval_id=audited.answer_result.retrieval_id,
        source=scenario.source,
        question=scenario.question,
        final_answer=audited.final_answer,
        literature_set_summary=(
            literature_set.summary
            if literature_set is not None
            else RunLiteratureSetSummary()
        ),
        pilot_report=pilot_report,
        metrics={"citation_count": len(audited.answer_result.citations)},
        full_text_enhancement=enhancement,
        warnings=warnings,
    )
    result.metrics = _build_metrics(scenario=scenario, result=result)
    result.gates = _build_gates(scenario=scenario, result=result)
    result.passed = bool(result.gates.get("passed"))
    return result


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _bundle_summary(results: list[HarnessScenarioResult]) -> dict[str, Any]:
    return {
        "scenario_count": len(results),
        "passed_count": sum(1 for item in results if item.passed),
        "failed_count": sum(1 for item in results if not item.passed),
        "pass_rate": rate([item.passed for item in results]),
        "average_citation_precision": _average(
            [float(item.metrics["citation_precision"]) for item in results]
        ),
    }


def _render_markdown(
    results: list[HarnessScenarioResult],
    summary: dict[str, Any],
) -> str:
    lines = [
        "# Biomedical Evidence Harness",
        "",
        "## Summary",
        "",
        f"- Scenarios: `{summary['scenario_count']}`",
        f"- Passed: `{summary['passed_count']}`",
        f"- Failed: `{summary['failed_count']}`",
        f"- Pass rate: `{summary['pass_rate']}`",
        "",
        "## Results",
        "",
    ]
    for item in results:
        lines.extend(
            [
                f"### {item.scenario_id}",
                f"- Run ID: `{item.run_id}`",
                f"- Source: `{item.source}`",
                f"- Papers: `{item.literature_set_summary.total_papers}`",
                f"- Review completion: `{item.metrics['review_completion']}`",
                f"- ROI present: `{item.metrics['pilot_report_roi_present']}`",
                f"- Gates passed: `{item.passed}`",
                "",
            ]
        )
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = _load_scenarios(args.scenario)
    workspace = Path(tempfile.mkdtemp(prefix="biomed-harness-"))
    service = BiomedEvidenceService(workspace)
    try:
        results = [await _run_scenario(service, scenario) for scenario in scenarios]
    finally:
        await service.aclose()
        shutil.rmtree(workspace, ignore_errors=True)
    summary = _bundle_summary(results)
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "results": [item.model_dump(mode="json") for item in results],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    args.markdown.write_text(_render_markdown(results, summary), encoding="utf-8")
    return bundle


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bundle = asyncio.run(_run(args))
    return 1 if int(bundle["summary"].get("failed_count") or 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
