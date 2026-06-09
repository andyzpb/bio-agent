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

        report = client.get("/api/biomed/export", params={"run_id": payload["run_id"]})
        assert report.status_code == 200
        assert "Biomedical Evidence Report" in report.text


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
        assert checked.json()["decisions"]

        events = client.get(f"/api/biomed/watch/{watch_id}/events")
        assert events.status_code == 200
        assert events.json()["total"] >= 1

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
