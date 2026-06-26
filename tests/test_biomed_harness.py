from __future__ import annotations

import json
from pathlib import Path

from eval.biomed_evidence.run_harness import _build_gates, main
from plugins.biomed_evidence.schemas import (
    HarnessScenario,
    HarnessScenarioResult,
    PilotReport,
    PilotReportObservability,
    PilotReportRoi,
    RunLiteratureSetSummary,
)


def test_biomed_harness_writes_bundle_and_markdown(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.jsonl"
    output = tmp_path / "harness.json"
    markdown = tmp_path / "harness.md"
    scenario.write_text(
        json.dumps(
            {
                "id": "microglia-harness",
                "question": "What evidence links microglia to Alzheimer's disease?",
                "source": "mock",
                "max_papers": 3,
                "enable_full_text_enhance": False,
                "manual_baseline_minutes": 120,
                "reviewer_minutes": 45,
                "require_literature_set": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--scenario",
            str(scenario),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    metrics = payload["results"][0]["metrics"]
    assert exit_code == 0
    assert payload["schema_version"] == "biomed-harness-v1"
    assert payload["results"][0]["scenario_id"] == "microglia-harness"
    assert payload["results"][0]["run_id"]
    assert payload["results"][0]["literature_set_summary"]["total_papers"] == 3
    assert metrics["citation_count"] > 0
    assert metrics["review_available"] is True
    assert metrics["review_validation_ok"] is True
    assert metrics["review_completion"] is False
    assert metrics["pilot_report_roi_present"] is True
    assert "latency_seconds" in metrics
    assert "source_call_count" in metrics
    assert "estimated_cost_usd" in metrics
    assert metrics["full_text_enhancement_success"] is None
    assert "literature_set_saved_count" in metrics
    assert markdown.read_text(encoding="utf-8").startswith(
        "# Biomedical Evidence Harness"
    )


def test_harness_failed_gate_returns_nonzero_and_marks_full_text_unsuccessful(
    tmp_path: Path,
) -> None:
    scenario = tmp_path / "scenario.jsonl"
    output = tmp_path / "harness.json"
    markdown = tmp_path / "harness.md"
    scenario.write_text(
        json.dumps(
            {
                "id": "microglia-review-gate",
                "question": "What evidence links microglia to Alzheimer's disease?",
                "source": "mock",
                "max_papers": 3,
                "enable_full_text_enhance": True,
                "require_review_completion": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--scenario",
            str(scenario),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    metrics = payload["results"][0]["metrics"]
    gates = payload["results"][0]["gates"]

    assert exit_code == 1
    assert payload["summary"]["failed_count"] == 1
    assert metrics["full_text_enhancement_success"] is False
    assert metrics["review_completion"] is False
    assert gates["require_review_completion"]["passed"] is False


def test_must_include_citations_gate_uses_actual_citation_count() -> None:
    scenario = HarnessScenario(
        id="citation-gate",
        question="What evidence links microglia to Alzheimer's disease?",
        must_include_citations=True,
    )
    result = HarnessScenarioResult(
        scenario_id="citation-gate",
        run_id="run-1",
        source="mock",
        question=scenario.question,
        final_answer="Microglia are linked to Alzheimer's disease.",
        literature_set_summary=RunLiteratureSetSummary(total_papers=1),
        pilot_report=PilotReport(
            run_id="run-1",
            question=scenario.question,
            source="mock",
            generated_at="2026-06-26T00:00:00+00:00",
            roi=PilotReportRoi(),
            observability=PilotReportObservability(),
            audit_summary={"claim_count": 2},
        ),
        metrics={
            "citation_count": 0,
            "unsupported_claim_rate": 0.0,
            "overclaim_rate": 0.0,
            "review_completion": False,
        },
    )

    gates = _build_gates(scenario=scenario, result=result)

    assert gates["must_include_citations"]["passed"] is False
