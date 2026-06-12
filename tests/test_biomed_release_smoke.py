from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from eval.biomed_evidence.run_release_smoke import (
    ReleaseSmokeRunner,
    SmokeConfig,
    redact,
)


def test_release_smoke_runner_writes_artifact_bundle(tmp_path: Path) -> None:
    dashboard_client = httpx.Client(
        base_url="http://dashboard.test",
        transport=httpx.MockTransport(_dashboard_handler),
    )
    ollama_client = httpx.Client(
        base_url="http://ollama.test/v1",
        transport=httpx.MockTransport(_ollama_handler),
    )
    runner = ReleaseSmokeRunner(
        SmokeConfig(output_dir=tmp_path, source="pubmed"),
        dashboard_client=dashboard_client,
        ollama_client=ollama_client,
    )

    try:
        summary = runner.run()
    finally:
        runner.close()

    assert summary["status"] == "passed"
    assert summary["ids"]["run_id"] == "biomed-run-smoke"
    assert summary["ids"]["retrieval_id"] == "retrieval-smoke"
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "pubmed_audited_answer.json").exists()

    persisted_summary = json.loads((tmp_path / "summary.json").read_text())
    assert persisted_summary["schema_version"] == "biomed-release-smoke-v1"
    assert all(item["passed"] for item in persisted_summary["checks"])


def test_release_smoke_redacts_secret_keys_and_query_values() -> None:
    payload = {
        "headers": {"Authorization": "Bearer secret", "x-api-key": "abc"},
        "url": "https://example.test/search?api_key=abc&query=microglia",
        "nested": [{"token": "secret-token"}],
    }

    redacted = redact(payload)

    assert redacted["headers"]["Authorization"] == "<redacted>"
    assert redacted["headers"]["x-api-key"] == "<redacted>"
    assert "api_key=<redacted>" in redacted["url"]
    assert redacted["nested"][0]["token"] == "<redacted>"


def _ollama_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "gpt-oss:120b-cloud"}]})
    if request.url.path == "/v1/chat/completions":
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"ok":true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )
    return httpx.Response(404, json={"error": request.url.path})


def _dashboard_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/dashboard/plugins":
        return _json([{"id": "biomed_evidence", "panels": []}])
    if path == "/api/biomed/release/tool-contracts":
        return _json({"schema_version": "release-tool-envelope-v1", "tool_count": 3})
    if path == "/api/biomed/literature/check":
        return _json(
            {
                "ok": True,
                "ready": True,
                "live": True,
                "item_count": 2,
                "abstract_count": 2,
                "warnings": [],
                "errors": [],
                "retrieval_manifest": {
                    "retrieval_id": "retrieval-ready",
                    "source": "pubmed",
                },
            }
        )
    if path == "/api/biomed/literature/search":
        return _json(
            {
                "source": "pubmed",
                "live": True,
                "query_used": "microglia Alzheimer disease progression",
                "items": [{"paper_id": "pmid:1", "source_rank": 1}],
                "coverage": {
                    "item_count": 2,
                    "abstract_count": 2,
                    "stored_paper_count": 2,
                },
                "retrieval_manifest": {
                    "retrieval_id": "retrieval-smoke",
                    "source": "pubmed",
                    "returned_paper_ids": ["pmid:1", "pmid:2"],
                    "errors": [],
                },
                "source_trace": {"stored_paper_ids": ["pmid:1", "pmid:2"]},
            }
        )
    if path == "/api/biomed/answer/audited":
        body = _json_body(request)
        question = str(body.get("question") or "")
        if "dose" in question.lower():
            return _json(
                {
                    "final_action": "refuse",
                    "final_answer": "I cannot provide dosing advice.",
                    "answer_result": {
                        "run_id": "biomed-run-clinical",
                        "citations": [],
                        "evidence_summary": [],
                    },
                    "trace": [
                        {"step": "classify", "status": "completed"},
                        {"step": "finalize", "status": "completed"},
                    ],
                }
            )
        return _json(_audited_answer_payload())
    if path == "/api/biomed/answer-runs/biomed-run-smoke/trace":
        return _json(
            {
                "run_id": "biomed-run-smoke",
                "trace": [
                    {"step": step, "status": "completed"}
                    for step in (
                        "classify",
                        "plan",
                        "retrieve",
                        "extract",
                        "audit",
                        "revise",
                        "finalize",
                    )
                ],
            }
        )
    if path == "/api/biomed/answer-runs/biomed-run-smoke/evidence-packet":
        return _json(
            {
                "ok": True,
                "result": {"evidence_packet": {"evidence_ids": ["ev-1"]}},
                "ids": {"packet_id": "packet-smoke"},
            }
        )
    if path == "/api/biomed/answer-runs/biomed-run-smoke/provenance":
        return _json(
            {
                "ok": True,
                "result": {
                    "schema_version": "biomed-provenance-v1",
                    "entities": [{"id": "answer:biomed-run-smoke"}],
                    "activities": [{"id": "activity:retrieve"}],
                },
                "ids": {"graph_id": "graph-smoke"},
            }
        )
    if path == "/api/biomed/retrievals/retrieval-smoke":
        return _json(
            {
                "retrieval_id": "retrieval-smoke",
                "source": "pubmed",
                "returned_paper_ids": ["pmid:1", "pmid:2"],
                "errors": [],
            }
        )
    return httpx.Response(404, json={"error": path})


def _audited_answer_payload() -> dict[str, Any]:
    return {
        "final_action": "revise",
        "answer_result": {
            "run_id": "biomed-run-smoke",
            "citations": [{"paper_id": "pmid:1"}],
            "evidence_summary": [{"evidence_id": "ev-1"}],
            "retrieval_manifest": {
                "retrieval_id": "retrieval-smoke",
                "source": "pubmed",
                "returned_paper_ids": ["pmid:1", "pmid:2"],
            },
            "retrieval_bundle": {"records": [{"retrieval_id": "retrieval-smoke"}]},
            "query_plan": {
                "planner_mode": "llm",
                "llm_model": "gpt-oss:120b-cloud",
            },
            "synthesis_mode": "llm",
            "synthesis_model": "gpt-oss:120b-cloud",
        },
        "advisory_verifier": {
            "verifier_mode": "llm",
            "llm_model": "gpt-oss:120b-cloud",
        },
        "revision": {
            "revision_mode": "llm",
            "llm_model": "gpt-oss:120b-cloud",
        },
        "trace": [{"step": "audit", "status": "completed"}],
    }


def _json(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _json_body(request: httpx.Request) -> dict[str, Any]:
    if not request.content:
        return {}
    payload = json.loads(request.content.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}
