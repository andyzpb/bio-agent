from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from plugins.biomed_evidence.literature_client import LiteratureClientError
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    EvidenceExtractionRequest,
    ExportEvidenceReportRequest,
    FetchBiomedicalPaperRequest,
    SearchBiomedicalLiteratureRequest,
    WatchTopicCreateRequest,
    WatchTopicUpdateRequest,
)
from plugins.biomed_evidence.service import BiomedEvidenceService


def register(app: FastAPI, plugin_dir: Path, workspace: Path) -> list[object]:
    _ = plugin_dir
    service = BiomedEvidenceService(workspace)

    @app.get("/api/biomed/search")
    async def search_biomedical_literature(
        query: str,
        max_results: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
        source: Literal["pubmed", "mock"] = "mock",
    ) -> dict[str, Any]:
        try:
            items = await service.search(
                SearchBiomedicalLiteratureRequest(
                    query=query,
                    max_results=max_results,
                    date_from=date_from,
                    date_to=date_to,
                    source=source,
                )
            )
        except LiteratureClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"items": [item.model_dump(mode="json") for item in items]}

    @app.get("/api/biomed/papers")
    def list_biomed_papers(
        q: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        items, total = service.storage.list_papers(q=q, page=page, page_size=page_size)
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/biomed/papers/{paper_id}")
    async def fetch_biomedical_paper(
        paper_id: str,
        source: Literal["pubmed", "mock"] = "mock",
    ) -> dict[str, Any]:
        try:
            paper = await service.fetch(
                FetchBiomedicalPaperRequest(paper_id=paper_id, source=source)
            )
        except LiteratureClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if paper is None:
            raise HTTPException(status_code=404, detail="paper not found")
        evidence = service.storage.get_evidence_for_paper(paper.paper_id)
        return {
            "paper": paper.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }

    @app.post("/api/biomed/evidence/extract")
    def extract_evidence(payload: EvidenceExtractionRequest) -> dict[str, Any]:
        result = service.extract_evidence(payload)
        return result.model_dump(mode="json")

    @app.get("/api/biomed/evidence")
    def list_evidence(
        q: str = "",
        paper_id: str = "",
        direction: str = "",
        entity: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        items, total = service.list_evidence(
            q=q,
            paper_id=paper_id,
            direction=direction,
            entity=entity,
            page=page,
            page_size=page_size,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.post("/api/biomed/answer")
    async def answer_with_evidence(payload: AnswerWithEvidenceRequest) -> dict[str, Any]:
        try:
            result = await service.answer_with_evidence(payload)
        except LiteratureClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.get("/api/biomed/answer-runs")
    def list_answer_runs(page: int = 1, page_size: int = 25) -> dict[str, Any]:
        items, total = service.storage.list_answer_runs(page=page, page_size=page_size)
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/biomed/graph")
    def get_evidence_graph(
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
    ) -> dict[str, Any]:
        return service.get_graph(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
        ).model_dump(mode="json")

    @app.get("/api/biomed/watch")
    def list_watch_topics(page: int = 1, page_size: int = 100) -> dict[str, Any]:
        items, total = service.list_watches(page=page, page_size=page_size)
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.post("/api/biomed/watch")
    def create_watch_topic(payload: WatchTopicCreateRequest) -> dict[str, Any]:
        return service.create_watch(payload).model_dump(mode="json")

    @app.patch("/api/biomed/watch/{watch_id}")
    def update_watch_topic(
        watch_id: str,
        payload: WatchTopicUpdateRequest,
    ) -> dict[str, Any]:
        watch = service.update_watch(watch_id, payload)
        if watch is None:
            raise HTTPException(status_code=404, detail="watch topic not found")
        return watch.model_dump(mode="json")

    @app.delete("/api/biomed/watch/{watch_id}")
    def delete_watch_topic(watch_id: str) -> dict[str, Any]:
        return {"deleted": service.delete_watch(watch_id), "watch_id": watch_id}

    @app.get("/api/biomed/watch/{watch_id}/events")
    def list_watch_events(
        watch_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        items, total = service.list_watch_decisions(
            watch_id=watch_id,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.post("/api/biomed/watch/{watch_id}/check")
    async def check_watch_topic(
        watch_id: str,
        source: Literal["pubmed", "mock"] = Query(default="mock"),
    ) -> dict[str, Any]:
        try:
            result = await service.check_watch(watch_id, source=source)
        except LiteratureClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="watch topic not found")
        return result.model_dump(mode="json")

    @app.get("/api/biomed/audit/{run_id}")
    def get_audit_run(run_id: str) -> dict[str, Any]:
        result = service.get_answer_run(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="answer run not found")
        return result.model_dump(mode="json")

    @app.get("/api/biomed/export")
    async def export_report(
        run_id: str | None = None,
        question: str | None = None,
        format: Literal["markdown", "json"] = "markdown",
    ) -> Response:
        try:
            report = await service.export_report(
                ExportEvidenceReportRequest(
                    run_id=run_id,
                    question=question,
                    format=format,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        media_type = "application/json" if format == "json" else "text/markdown"
        return Response(content=report, media_type=media_type)

    return [service]
