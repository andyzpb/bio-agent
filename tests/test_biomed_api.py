from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.biomed_evidence.dashboard import register


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    register(app, Path(__file__).parents[1] / "plugins" / "biomed_evidence", tmp_path)
    return TestClient(app)


def test_biomed_api_answer_extract_graph_and_audit(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        search = client.get(
            "/api/biomed/search",
            params={"query": "microglia", "source": "mock"},
        )
        assert search.status_code == 200
        search_payload = search.json()
        assert search_payload["items"]
        retrieval_id = search_payload["retrieval_manifest"]["retrieval_id"]
        retrieval = client.get(f"/api/biomed/retrievals/{retrieval_id}")
        assert retrieval.status_code == 200
        assert retrieval.json()["returned_paper_ids"]

        plan = client.post(
            "/api/biomed/plan",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_results": 5,
            },
        )
        assert plan.status_code == 200
        plan_payload = plan.json()
        assert plan_payload["classification"]["intent"] == "research_question"
        assert plan_payload["query_plan"]["support_queries"]
        assert plan_payload["query_plan"]["refute_queries"]
        assert plan_payload["validation"]["valid"] is True
        assert plan_payload["search_request"]["source"] == "mock"

        answer = client.post(
            "/api/biomed/answer",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_papers": 5,
            },
        )
        assert answer.status_code == 200
        payload = answer.json()
        assert payload["citations"]
        assert payload["evidence_summary"]
        assert payload["retrieval_id"]
        assert payload["retrieval_manifest"]["compiled_query"]

        evidence = client.get("/api/biomed/evidence", params={"direction": "supports"})
        assert evidence.status_code == 200
        assert evidence.json()["total"] >= 1

        graph = client.get("/api/biomed/graph", params={"topic": "microglial activation"})
        assert graph.status_code == 200
        assert graph.json()["nodes"]
        assert graph.json()["edges"]

        audit = client.get(f"/api/biomed/audit/{payload['run_id']}")
        assert audit.status_code == 200
        assert audit.json()["run_id"] == payload["run_id"]
        assert audit.json()["retrieval_id"] == payload["retrieval_id"]
        assert audit.json()["latest_citation_audit"] is None

        created_audit = client.post(f"/api/biomed/answer-runs/{payload['run_id']}/audit")
        assert created_audit.status_code == 200
        audit_payload = created_audit.json()
        assert audit_payload["run_id"] == payload["run_id"]
        assert audit_payload["claim_support_rate"] >= 0.8
        assert audit_payload["citation_precision"] >= 0.8
        assert audit_payload["recommended_action"] in {
            "pass",
            "pass_with_limitations",
            "revise",
            "refuse_or_abstain",
        }

        audit_detail = client.get(f"/api/biomed/audits/{audit_payload['audit_id']}")
        assert audit_detail.status_code == 200
        assert audit_detail.json()["audit_id"] == audit_payload["audit_id"]

        audit_list = client.get("/api/biomed/audits", params={"run_id": payload["run_id"]})
        assert audit_list.status_code == 200
        assert audit_list.json()["total"] == 1

        audit = client.get(f"/api/biomed/audit/{payload['run_id']}")
        assert audit.status_code == 200
        assert audit.json()["latest_citation_audit"]["audit_id"] == audit_payload["audit_id"]

        conflict = client.post(
            "/api/biomed/conflicts",
            json={
                "claim": "Microglial activation is associated with Alzheimer's disease progression.",
                "topic": "microglial activation Alzheimer's disease progression",
                "source": "mock",
            },
        )
        assert conflict.status_code == 200
        assert conflict.json()["verdict"] in {
            "no_conflict_found",
            "mixed_evidence",
            "contradicted",
            "insufficient_search",
        }

        report = client.get("/api/biomed/export", params={"run_id": payload["run_id"]})
        assert report.status_code == 200
        assert "Biomedical Evidence Report" in report.text
        assert "Retrieval Provenance" in report.text

        audited = client.post(
            "/api/biomed/answer/audited",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_papers": 5,
                "use_llm_planner": True,
                "execute_support_refute": True,
                "use_llm_verifier": True,
            },
        )
        assert audited.status_code == 200
        audited_payload = audited.json()
        audited_run_id = audited_payload["answer_result"]["run_id"]
        assert audited_payload["audit"]["audit_id"]
        assert audited_payload["advisory_verifier"]["verifier_mode"] == "fallback"
        assert audited_payload["revision"]["revision_id"]
        assert audited_payload["final_action"] in {"pass", "revise", "refuse", "abstain"}
        assert audited_payload["answer_result"]["retrieval_bundle"]["executed_multi_query"] is True
        assert len(audited_payload["answer_result"]["retrieval_bundle"]["records"]) >= 3
        assert len(audited_payload["trace"]) == 11

        trace = client.get(f"/api/biomed/answer-runs/{audited_run_id}/trace")
        assert trace.status_code == 200
        trace_payload = trace.json()
        assert trace_payload["run_id"] == audited_run_id
        assert trace_payload["revision"]["revision_id"] == audited_payload["revision"]["revision_id"]
        assert trace_payload["latest_advisory_verifier"]["verifier_mode"] == "fallback"
        assert {step["step"] for step in trace_payload["trace"]} == {
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
        retrieve_step = next(step for step in trace_payload["trace"] if step["step"] == "retrieve")
        assert retrieve_step["metadata"]["retrieval_bundle"]["executed_multi_query"] is True


def test_biomed_api_watch_crud_check_events(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        created = client.post(
            "/api/biomed/watch",
            json={
                "topic": "spatial transcriptomics in tumor microenvironment",
                "include_keywords": ["spatial transcriptomics", "tumor microenvironment"],
                "preferred_methods": ["spatial transcriptomics"],
                "min_relevance_score": 0.7,
                "schedule": "daily",
            },
        )
        assert created.status_code == 200
        watch_id = created.json()["watch_id"]

        checked = client.post(f"/api/biomed/watch/{watch_id}/check")
        assert checked.status_code == 200
        checked_payload = checked.json()
        assert checked_payload["decisions"]
        assert checked_payload["retrieval_manifest"]["retrieval_id"]
        assert checked_payload["snapshot"]["new_paper_ids"]

        events = client.get(f"/api/biomed/watch/{watch_id}/events")
        assert events.status_code == 200
        assert events.json()["total"] >= 1
        assert events.json()["items"][0]["retrieval_id"]

        patched = client.patch(
            f"/api/biomed/watch/{watch_id}",
            json={"enabled": False, "schedule": "manual"},
        )
        assert patched.status_code == 200
        assert patched.json()["enabled"] is False

        deleted = client.delete(f"/api/biomed/watch/{watch_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True


def test_biomed_api_validation_error(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/biomed/answer", json={"source": "mock"})
        assert response.status_code == 422
