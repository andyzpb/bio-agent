from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from plugins.biomed_evidence.graph import (
    EDGE_TYPES,
    NODE_TYPES,
    SCHEMA_VERSION,
    BiomedEvidenceGraph,
    build_evidence_card,
    graph_to_json_dict,
    shortest_path,
    validate_evidence_graph,
)
from plugins.biomed_evidence.literature_client import LiteratureClientError
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    BiomedProjectCreateRequest,
    BiomedProjectUpdateRequest,
    CitationAuditRequest,
    ConflictAuditRequest,
    CoverageGapAnalysisRequest,
    EvidenceBatchExtractionRequest,
    EvidenceExtractionRequest,
    EvidencePacketBuildRequest,
    ExportEvidenceReportRequest,
    FetchBiomedicalPaperRequest,
    GenerateProjectEvidenceBriefRequest,
    LiteratureAccessCheckRequest,
    LiteratureSearchRequest,
    MultiPassLiteratureSearchRequest,
    ObsidianExportRequest,
    PlanBiomedicalSearchRequest,
    ProjectClaimRecordRequest,
    ProjectPaperDecisionRequest,
    RunReviewDecisionRequest,
    SavedToolChainTemplateRunRequest,
    SavedToolChainTemplateSaveRequest,
    SearchBiomedicalLiteratureRequest,
    WatchTopicCreateRequest,
    WatchTopicUpdateRequest,
)
from plugins.biomed_evidence.service import BiomedEvidenceService
from plugins.biomed_evidence.tool_contracts import list_release_tool_contracts


def register(app: FastAPI, plugin_dir: Path, workspace: Path) -> list[object]:
    _ = plugin_dir
    service = BiomedEvidenceService(
        workspace,
        revision_provider=getattr(app.state, "biomed_revision_provider", None),
        revision_model=str(getattr(app.state, "biomed_revision_model", "") or ""),
    )

    @app.get("/api/biomed/search")
    async def search_biomedical_literature(
        query: str,
        max_results: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
        source: Literal["pubmed", "mock"] = "mock",
    ) -> dict[str, Any]:
        try:
            result = await service.search_with_manifest(
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
        return {
            "items": [item.model_dump(mode="json") for item in result.items],
            "retrieval_manifest": result.retrieval_manifest.model_dump(mode="json"),
        }

    @app.post("/api/biomed/literature/check")
    async def check_literature_access(
        payload: LiteratureAccessCheckRequest,
    ) -> dict[str, Any]:
        result = await service.check_literature_access(payload)
        return result.model_dump(mode="json")

    @app.get("/api/biomed/release/tool-contracts")
    def get_release_tool_contracts() -> dict[str, Any]:
        contracts = list_release_tool_contracts()
        return {
            "schema_version": "release-tool-envelope-v1",
            "tools": [item.model_dump(mode="json") for item in contracts],
            "tool_count": len(contracts),
        }

    @app.get("/api/biomed/workflow/templates")
    def list_workflow_templates() -> dict[str, Any]:
        return service.list_workflow_templates().model_dump(mode="json")

    @app.get("/api/biomed/workflow/templates/{template_id}")
    def get_workflow_template(template_id: str) -> dict[str, Any]:
        template = service.get_workflow_template(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="workflow template not found")
        return template.model_dump(mode="json")

    @app.post("/api/biomed/workflow/templates")
    def save_workflow_template(
        payload: SavedToolChainTemplateSaveRequest,
    ) -> dict[str, Any]:
        try:
            template = service.save_workflow_template(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return template.model_dump(mode="json")

    @app.delete("/api/biomed/workflow/templates/{template_id}")
    def delete_workflow_template(template_id: str) -> dict[str, Any]:
        return {
            "deleted": service.delete_workflow_template(template_id),
            "template_id": template_id,
        }

    @app.post("/api/biomed/workflow/templates/{template_id}/run")
    async def run_workflow_template(
        template_id: str,
        payload: SavedToolChainTemplateRunRequest,
    ) -> dict[str, Any]:
        result = await service.run_workflow_template(template_id, payload)
        return result.model_dump(mode="json")

    @app.post("/api/biomed/retrieval/multi-pass")
    async def run_multi_pass_literature_search(
        payload: MultiPassLiteratureSearchRequest,
    ) -> dict[str, Any]:
        try:
            result = await service.run_multi_pass_literature_search(payload)
        except LiteratureClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.post("/api/biomed/evidence/extract-batch")
    async def extract_evidence_batch(
        payload: EvidenceBatchExtractionRequest,
    ) -> dict[str, Any]:
        try:
            result = await service.extract_evidence_batch(payload)
        except LiteratureClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.post("/api/biomed/evidence/coverage-gaps")
    def analyze_coverage_gaps(payload: CoverageGapAnalysisRequest) -> dict[str, Any]:
        return service.analyze_coverage_gaps(payload).model_dump(mode="json")

    @app.post("/api/biomed/evidence/packet")
    def build_evidence_packet(payload: EvidencePacketBuildRequest) -> dict[str, Any]:
        return service.build_evidence_packet(payload).model_dump(mode="json")

    @app.get("/api/biomed/answer-runs/{run_id}/evidence-packet")
    def get_evidence_packet(run_id: str) -> dict[str, Any]:
        return service.get_evidence_packet(run_id).model_dump(mode="json")

    @app.get("/api/biomed/answer-runs/{run_id}/provenance")
    def export_provenance_graph(run_id: str) -> dict[str, Any]:
        return service.export_provenance_graph(run_id).model_dump(mode="json")

    @app.post("/api/biomed/export/obsidian/evidence-packet")
    def export_evidence_packet_to_obsidian(
        payload: ObsidianExportRequest,
    ) -> dict[str, Any]:
        return service.export_evidence_packet_to_obsidian(payload).model_dump(mode="json")

    @app.post("/api/biomed/export/obsidian/project")
    def export_project_to_obsidian(payload: ObsidianExportRequest) -> dict[str, Any]:
        return service.export_project_to_obsidian(payload).model_dump(mode="json")

    @app.post("/api/biomed/export/obsidian/watch")
    def export_research_watch_to_obsidian(
        payload: ObsidianExportRequest,
    ) -> dict[str, Any]:
        return service.export_research_watch_to_obsidian(payload).model_dump(
            mode="json"
        )

    @app.post("/api/biomed/literature/search")
    async def search_literature(payload: LiteratureSearchRequest) -> dict[str, Any]:
        try:
            result = await service.search_literature(payload)
        except LiteratureClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.get("/api/biomed/retrievals/{retrieval_id}")
    def get_retrieval_manifest(retrieval_id: str) -> dict[str, Any]:
        manifest = service.get_retrieval_manifest(retrieval_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="retrieval manifest not found")
        return manifest.model_dump(mode="json")

    @app.post("/api/biomed/plan")
    async def plan_biomedical_search(payload: PlanBiomedicalSearchRequest) -> dict[str, Any]:
        result = await service.plan_biomedical_search(payload)
        return result.model_dump(mode="json")

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

    @app.post("/api/biomed/projects")
    def create_project(payload: BiomedProjectCreateRequest) -> dict[str, Any]:
        return service.create_project(payload).model_dump(mode="json")

    @app.get("/api/biomed/projects")
    def list_projects(page: int = 1, page_size: int = 50) -> dict[str, Any]:
        items, total = service.list_projects(page=page, page_size=page_size)
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/biomed/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        project = service.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return project.model_dump(mode="json")

    @app.patch("/api/biomed/projects/{project_id}")
    def update_project(
        project_id: str,
        payload: BiomedProjectUpdateRequest,
    ) -> dict[str, Any]:
        project = service.update_project(project_id, payload)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return project.model_dump(mode="json")

    @app.post("/api/biomed/projects/{project_id}/papers")
    def save_project_paper_decision(
        project_id: str,
        payload: ProjectPaperDecisionRequest,
    ) -> dict[str, Any]:
        try:
            decision = service.save_project_paper_decision(project_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return decision.model_dump(mode="json")

    @app.get("/api/biomed/projects/{project_id}/papers")
    def list_project_paper_decisions(
        project_id: str,
        decision: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        try:
            items, total = service.list_project_paper_decisions(
                project_id,
                decision=decision,
                page=page,
                page_size=page_size,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.post("/api/biomed/projects/{project_id}/claims")
    def save_project_claim_record(
        project_id: str,
        payload: ProjectClaimRecordRequest,
    ) -> dict[str, Any]:
        try:
            claim = service.save_project_claim_record(project_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return claim.model_dump(mode="json")

    @app.get("/api/biomed/projects/{project_id}/claims")
    def list_project_claim_records(
        project_id: str,
        status: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        try:
            items, total = service.list_project_claim_records(
                project_id,
                status=status,
                page=page,
                page_size=page_size,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/biomed/projects/{project_id}/review-queue")
    def list_project_review_queue(
        project_id: str,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        try:
            items, total = service.list_project_review_queue(
                project_id,
                page=page,
                page_size=page_size,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.post("/api/biomed/projects/{project_id}/briefs")
    def generate_project_evidence_brief(
        project_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            request_payload = GenerateProjectEvidenceBriefRequest.model_validate(
                {**payload, "project_id": project_id}
            )
            brief = service.generate_project_evidence_brief(
                request_payload
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return brief.model_dump(mode="json")

    @app.get("/api/biomed/projects/{project_id}/briefs")
    def list_project_briefs(
        project_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        try:
            items, total = service.list_project_briefs(
                project_id,
                page=page,
                page_size=page_size,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "items": [item.model_dump(mode="json") for item in items],
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
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.post("/api/biomed/answer/audited")
    async def answer_with_audit(payload: AnswerWithEvidenceRequest) -> dict[str, Any]:
        try:
            result = await service.answer_with_audit(payload)
        except LiteratureClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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

    @app.post("/api/biomed/audit/citations")
    def validate_citation_support(payload: CitationAuditRequest) -> dict[str, Any]:
        result = service.audit_answer(payload)
        return result.model_dump(mode="json")

    @app.post("/api/biomed/answer-runs/{run_id}/audit")
    def audit_answer_run(run_id: str) -> dict[str, Any]:
        result = service.audit_answer_run(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="answer run not found")
        return result.model_dump(mode="json")

    @app.get("/api/biomed/answer-runs/{run_id}/trace")
    def get_answer_trace(run_id: str) -> dict[str, Any]:
        result = service.get_answer_trace(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="answer run not found")
        return result

    @app.get("/api/biomed/answer-runs/{run_id}/argument-graph")
    def get_answer_argument_graph(run_id: str) -> dict[str, Any]:
        result = service.get_answer_argument_graph(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="answer run not found")
        return result.model_dump(mode="json")

    @app.get("/api/biomed/answer-runs/{run_id}/evidence-graph")
    def get_answer_evidence_graph(
        run_id: str,
        validate: bool = False,
    ) -> dict[str, Any]:
        result = service.get_graph_v1(run_id=run_id, validate=validate)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        return result.model_dump(mode="json")

    @app.get("/api/biomed/answer-runs/{run_id}/evidence-review")
    def get_answer_evidence_review(
        run_id: str,
        include_graph: bool = False,
    ) -> dict[str, Any]:
        result = service.get_run_evidence_review(
            run_id,
            include_graph=include_graph,
        )
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        return result.model_dump(mode="json")

    @app.post("/api/biomed/answer-runs/{run_id}/evidence-review/snapshot")
    def create_answer_evidence_review_snapshot(
        run_id: str,
        force: bool = False,
    ) -> dict[str, Any]:
        snapshot = service.create_evidence_graph_snapshot(run_id, force=force)
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        return {
            "snapshot": snapshot.model_dump(
                mode="json",
                exclude={"graph", "validation"},
            ),
            "validation": snapshot.validation,
        }

    @app.post("/api/biomed/evidence-graph/snapshots/backfill")
    def backfill_evidence_graph_snapshots(limit: int = 100) -> dict[str, Any]:
        return service.backfill_evidence_graph_snapshots(limit=limit)

    @app.get("/api/biomed/answer-runs/{run_id}/evidence-review/snapshot-diff")
    def get_answer_evidence_review_snapshot_diff(
        run_id: str,
        base_snapshot_id: str = "",
        compare_snapshot_id: str = "",
    ) -> dict[str, Any]:
        result = service.get_evidence_graph_snapshot_diff(
            run_id,
            base_snapshot_id=base_snapshot_id,
            compare_snapshot_id=compare_snapshot_id,
        )
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        return result

    @app.get("/api/biomed/answer-runs/{run_id}/evidence-review/decisions")
    def list_answer_evidence_review_decisions(
        run_id: str,
        claim_id: str = "",
    ) -> dict[str, Any]:
        decisions = service.list_run_review_decisions(run_id, claim_id=claim_id)
        if decisions is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        return {
            "items": [item.model_dump(mode="json") for item in decisions],
            "total": len(decisions),
            "run_id": run_id,
        }

    @app.post("/api/biomed/answer-runs/{run_id}/evidence-review/decisions")
    def create_answer_evidence_review_decision(
        run_id: str,
        payload: RunReviewDecisionRequest,
    ) -> dict[str, Any]:
        try:
            decision = service.record_run_review_decision(run_id, payload)
        except ValueError as exc:
            detail = {
                "error_code": "invalid_review_decision",
                "message": str(exc),
                "run_id": run_id,
            }
            if "clinical refusal" in str(exc):
                detail["error_code"] = "clinical_boundary"
            raise HTTPException(status_code=400, detail=detail) from exc
        if decision is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        return decision.model_dump(mode="json")

    @app.get("/api/biomed/answer-runs/{run_id}/evidence-review/packet")
    def export_answer_evidence_review_packet(
        run_id: str,
        include_graph: bool = False,
    ) -> dict[str, Any]:
        packet = service.export_run_review_packet(
            run_id,
            include_graph=include_graph,
        )
        if packet is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        return packet.model_dump(mode="json")

    @app.get("/api/biomed/answer-runs/{run_id}/math-signals")
    def get_answer_math_signals(run_id: str) -> dict[str, Any]:
        result = service.get_answer_math_signals(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="answer run not found")
        return result.model_dump(mode="json")

    @app.get("/api/biomed/audits")
    def list_answer_audits(
        run_id: str = "",
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        items, total = service.list_answer_audits(
            run_id=run_id,
            page=page,
            page_size=page_size,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/biomed/audits/{audit_id}")
    def get_answer_audit(audit_id: str) -> dict[str, Any]:
        result = service.get_citation_audit(audit_id)
        if result is None:
            raise HTTPException(status_code=404, detail="audit not found")
        return result.model_dump(mode="json")

    @app.post("/api/biomed/conflicts")
    def find_conflicting_evidence(payload: ConflictAuditRequest) -> dict[str, Any]:
        return service.find_conflicting_evidence(payload).model_dump(mode="json")

    @app.get("/api/biomed/graph/schema")
    def get_evidence_graph_schema() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "node_types": list(NODE_TYPES),
            "edge_types": list(EDGE_TYPES),
        }

    @app.get("/api/biomed/graph/v1")
    def get_evidence_graph_v1(
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
        run_id: str = "",
        validate: bool = False,
    ) -> dict[str, Any]:
        result = service.get_graph_v1(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
            run_id=run_id,
            validate=validate,
        )
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        return result.model_dump(mode="json")

    @app.post("/api/biomed/graph/v1/validate")
    def validate_evidence_graph_v1(payload: dict[str, Any]) -> dict[str, Any]:
        raw_graph = payload.get("graph")
        if isinstance(raw_graph, dict):
            graph = BiomedEvidenceGraph.model_validate(raw_graph)
        else:
            graph = service.get_graph_v1(
                topic=str(payload.get("topic") or ""),
                entity=str(payload.get("entity") or ""),
                paper_id=str(payload.get("paper_id") or ""),
                direction=str(payload.get("direction") or ""),
                run_id=str(payload.get("run_id") or ""),
            )
            if graph is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "error_code": "unknown_run_id",
                        "run_id": str(payload.get("run_id") or ""),
                    },
                )
        return validate_evidence_graph(graph).model_dump(mode="json")

    @app.get("/api/biomed/graph/v1/evidence-card/{claim_id}")
    def get_evidence_graph_card(
        claim_id: str,
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
        run_id: str = "",
    ) -> dict[str, Any]:
        graph = service.get_graph_v1(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
            run_id=run_id,
        )
        if graph is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        node_id = claim_id if claim_id.startswith("claim:") else f"claim:{claim_id}"
        try:
            return build_evidence_card(graph, node_id).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_claim_id", "claim_id": claim_id},
            ) from exc

    @app.get("/api/biomed/graph/v1/path")
    def get_evidence_graph_path(
        source: str,
        target: str,
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
        run_id: str = "",
        directed: bool = False,
        max_depth: int = 6,
    ) -> dict[str, Any]:
        graph = service.get_graph_v1(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
            run_id=run_id,
        )
        if graph is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        path = shortest_path(
            graph,
            source,
            target,
            directed=directed,
            max_depth=max(1, min(max_depth, 20)),
        )
        if not path:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "graph_path_not_found",
                    "source": source,
                    "target": target,
                },
            )
        nodes_by_id = {node.id: node for node in graph.nodes}
        path_edges = []
        for left, right in zip(path, path[1:]):
            edge = next(
                (
                    item
                    for item in graph.edges
                    if (item.source == left and item.target == right)
                    or (
                        not directed
                        and item.source == right
                        and item.target == left
                    )
                ),
                None,
            )
            if edge is not None:
                path_edges.append(edge.model_dump(mode="json"))
        return {
            "schema_version": graph.schema_version,
            "path_mode": "directed" if directed else "related_undirected",
            "path": path,
            "nodes": [
                nodes_by_id[node_id].model_dump(mode="json")
                for node_id in path
                if node_id in nodes_by_id
            ],
            "edges": path_edges,
        }

    @app.get("/api/biomed/graph/v1/export/json")
    def export_evidence_graph_json(
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
        run_id: str = "",
        validate: bool = False,
    ) -> dict[str, Any]:
        graph = service.get_graph_v1(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
            run_id=run_id,
            validate=validate,
        )
        if graph is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "unknown_run_id", "run_id": run_id},
            )
        return graph_to_json_dict(graph)

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
        payload = result.model_dump(mode="json")
        latest_audit = service.get_latest_citation_audit_for_run(run_id)
        payload["latest_citation_audit"] = (
            latest_audit.model_dump(mode="json") if latest_audit is not None else None
        )
        latest_advisory = service.storage.get_latest_advisory_verifier_for_run(run_id)
        payload["latest_advisory_verifier"] = (
            latest_advisory.model_dump(mode="json")
            if latest_advisory is not None
            else None
        )
        trace = service.get_answer_trace(run_id)
        if trace is not None:
            payload["latest_revision"] = trace.get("revision")
            payload["trace"] = trace.get("trace")
        return payload

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
