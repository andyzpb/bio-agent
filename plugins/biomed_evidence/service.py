from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, cast

import httpx

from plugins.biomed_evidence.citation_auditor import (
    extract_atomic_claims,
    find_conflicting_evidence as audit_conflicts,
    validate_citation_support,
)
from plugins.biomed_evidence.evidence_extractor import EvidenceExtractor
from plugins.biomed_evidence.errors import release_error, release_ok
from plugins.biomed_evidence.guardrails import (
    RESEARCH_USE_DISCLAIMER,
    clinical_refusal,
    is_clinical_request,
)
from plugins.biomed_evidence.literature_client import (
    LiteratureClientError,
    MockLiteratureClient,
    PubMedLiteratureClient,
)
from plugins.biomed_evidence.math_signals import (
    build_argument_graph,
    build_math_signals,
)
from plugins.biomed_evidence.obsidian_export import (
    ensure_obsidian_export_dir,
    export_packet_note,
    export_project_note,
    export_watch_note,
)
from plugins.biomed_evidence.graph import (
    BiomedEvidenceGraph,
    GraphScope,
    build_graph_from_evidence,
    build_run_graph,
    validate_evidence_graph,
)
from plugins.biomed_evidence.provenance_service import build_provenance_graph
from plugins.biomed_evidence.schemas import (
    AdvisoryClaimReview,
    AdvisoryVerifierDisagreement,
    AdvisoryVerifierResult,
    AgentTraceStep,
    AnswerWithEvidenceRequest,
    AnswerWithEvidenceResult,
    AnswerRevision,
    ArgumentGraphResult,
    AtomicClaim,
    AuditedAnswerResult,
    BanditAdvisoryResult,
    BiomedProject,
    BiomedProjectCreateRequest,
    BiomedProjectUpdateRequest,
    BiomedicalEntity,
    BiomedicalPaper,
    BiomedicalQuestionClassification,
    BiomedicalQueryPlan,
    Citation,
    CitationAuditRequest,
    CitationAuditResult,
    ClaimAuditItem,
    ConfidenceLevel,
    ConflictAuditRequest,
    ConflictAuditResult,
    CoverageGapAnalysisRequest,
    CoverageGapAnalysisResult,
    CoverageStatus,
    EvidenceBatchExtractionRequest,
    EvidenceBatchExtractionResult,
    EvidenceExtractionRequest,
    EvidenceExtractionResult,
    EvidencePacketBuildRequest,
    EvidencePacketBuildResult,
    EvidencePacketGetResult,
    EvidenceSelectionItem,
    EvidencePacketSelectionResult,
    EvidencePacketSelectionStrategy,
    EvidencePacketSummary,
    ExtractionMode,
    EvidenceGraph,
    EvidenceItem,
    ExportEvidenceReportRequest,
    FetchBiomedicalPaperRequest,
    GapSearchDecision,
    GenerateProjectEvidenceBriefRequest,
    GraphEdge,
    GraphNode,
    LiteratureAccessCheckRequest,
    LiteratureAccessCheckResult,
    LiteraturePaperRecord,
    LiteratureSearchCoverage,
    LiteratureSearchRequest,
    LiteratureSearchResult,
    LiteratureSourceTrace,
    LogicalClaimFrame,
    LogicalEvidenceFrame,
    MathSignalsResult,
    MultiPassLiteratureSearchRequest,
    MultiPassLiteratureSearchResult,
    ObsidianExportRequest,
    ObsidianExportResult,
    PaperMetadata,
    PlanBiomedicalSearchRequest,
    PlanBiomedicalSearchResult,
    ProjectClaimRecord,
    ProjectClaimRecordRequest,
    ProjectEvidenceBrief,
    ProjectPaperDecision,
    ProjectPaperDecisionRequest,
    ProjectReviewQueueItem,
    ProvenanceGraphResult,
    QueryPlanValidation,
    CoverageMatrixRow,
    ReleaseToolEnvelope,
    ReleaseToolSourcePolicy,
    RetrievalBundle,
    RetrievalBundleRecord,
    RetrievalIntent,
    RetrievalManifest,
    RetrievalSubquestion,
    SavedToolChainTemplate,
    SavedToolChainTemplateListResult,
    SavedToolChainTemplateRunRequest,
    SavedToolChainTemplateSaveRequest,
    SearchBiomedicalLiteratureRequest,
    SearchBiomedicalLiteratureResult,
    WatchCheckResult,
    WatchDecisionDetail,
    WatchSnapshot,
    WatchTopic,
    WatchTopicCreateRequest,
    WatchTopicUpdateRequest,
)
from plugins.biomed_evidence.storage import BiomedStorage
from plugins.biomed_evidence.telemetry_service import build_step_telemetry
from plugins.biomed_evidence.tool_contracts import get_release_tool_metadata


@dataclass(frozen=True)
class _SynthesisOutcome:
    answer: str
    mode: str
    model: str | None
    prompt_hash: str | None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class _LogicParserOutcome:
    claim_frames: dict[str, LogicalClaimFrame]
    evidence_frames: dict[str, LogicalEvidenceFrame]
    prompt_hash: str | None
    model: str | None
    fallback_reason: str | None = None


class BiomedEvidenceService:
    def __init__(
        self,
        workspace: Path,
        *,
        http_client: httpx.AsyncClient | None = None,
        revision_provider: Any | None = None,
        revision_model: str | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.storage = BiomedStorage(self.workspace / "biomed_evidence" / "biomed.db")
        self.revision_provider = revision_provider
        self.revision_model = revision_model or ""
        self.mock_client = MockLiteratureClient()
        self.pubmed_client = PubMedLiteratureClient(
            client=http_client,
            email=os.getenv("NCBI_EMAIL") or None,
            api_key=os.getenv("NCBI_API_KEY") or None,
        )
        self.extractor = EvidenceExtractor()

    def close(self) -> None:
        self.storage.close()

    async def aclose(self) -> None:
        self.storage.close()
        await self.pubmed_client.close()

    def list_workflow_templates(self) -> SavedToolChainTemplateListResult:
        custom, _ = self.storage.list_workflow_templates(page=1, page_size=500)
        items = [*default_workflow_templates(), *custom]
        return SavedToolChainTemplateListResult(items=items, total=len(items))

    def get_workflow_template(self, template_id: str) -> SavedToolChainTemplate | None:
        defaults = {item.template_id: item for item in default_workflow_templates()}
        if template_id in defaults:
            return defaults[template_id]
        return self.storage.get_workflow_template(template_id)

    def save_workflow_template(
        self,
        request: SavedToolChainTemplateSaveRequest,
    ) -> SavedToolChainTemplate:
        template_id = _clean_template_id(request.template_id or request.name)
        if template_id in {item.template_id for item in default_workflow_templates()}:
            raise ValueError("built-in workflow templates are immutable")
        now = _now_iso()
        existing = self.storage.get_workflow_template(template_id)
        template = SavedToolChainTemplate(
            template_id=template_id,
            name=request.name.strip() or "Untitled workflow template",
            description=request.description,
            workflow=request.workflow,
            builtin=False,
            source=request.source,
            source_policy=_template_source_policy(request.source),
            max_papers=max(1, min(int(request.max_papers), 50)),
            max_queries=max(1, min(int(request.max_queries), 20)),
            max_followups=max(0, min(int(request.max_followups), 10)),
            max_tool_steps=max(1, min(int(request.max_tool_steps), 100)),
            max_wall_clock_seconds=max(
                1,
                min(int(request.max_wall_clock_seconds), 900),
            ),
            include_rejected_papers=request.include_rejected_papers,
            require_citations=request.require_citations,
            execute_support_refute=request.execute_support_refute,
            use_llm_planner=request.use_llm_planner,
            use_llm_extractor=request.use_llm_extractor,
            use_llm_synthesis=request.use_llm_synthesis,
            use_llm_verifier=request.use_llm_verifier,
            use_llm_revision=request.use_llm_revision,
            use_llm_claim_logic=request.use_llm_claim_logic,
            export_logic_facts=request.export_logic_facts,
            build_evidence_packet=request.build_evidence_packet,
            export_provenance=request.export_provenance,
            clinical_guard_required=request.clinical_guard_required,
            required_skills=_clean_list(request.required_skills),
            stop_conditions=_clean_list(request.stop_conditions),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        self.storage.save_workflow_template(template)
        return template

    def delete_workflow_template(self, template_id: str) -> bool:
        if template_id in {item.template_id for item in default_workflow_templates()}:
            return False
        return self.storage.delete_workflow_template(template_id)

    async def run_workflow_template(
        self,
        template_id: str,
        request: SavedToolChainTemplateRunRequest,
    ) -> ReleaseToolEnvelope:
        tool_name = "run_saved_tool_chain_template"
        metadata = get_release_tool_metadata(tool_name)
        template = self.get_workflow_template(template_id)
        if template is None:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="workflow template not found",
                detail={"template_id": template_id},
                metadata=metadata,
            )
        question = request.question.strip()
        if not question:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="question is required to run a workflow template",
                detail={"template_id": template_id},
                metadata=metadata,
            )
        if template.clinical_guard_required and is_clinical_request(question):
            return release_error(
                tool_name=tool_name,
                code="clinical_boundary",
                message=(
                    "Clinical or patient-specific request blocked before template "
                    "retrieval, extraction, LLM, audit, or export steps."
                ),
                detail={
                    "template_id": template_id,
                    "clinical_guard_required": True,
                    "memory_used": False,
                    "retrieval_executed": False,
                },
                trace={"template_id": template_id, "step": "clinical_precheck"},
                metadata=metadata,
            )
        source = request.source_override or template.source
        if source == "pubmed" and not request.allow_live_pubmed:
            return release_error(
                tool_name=tool_name,
                code="source_policy_blocked",
                message=(
                    "This template would use live PubMed; rerun with "
                    "allow_live_pubmed=true to opt in."
                ),
                detail={
                    "template_id": template_id,
                    "source": source,
                    "source_policy": "live_opt_in",
                },
                metadata=metadata,
            )
        active_template = template.model_copy(
            update={
                "source": source,
                "source_policy": _template_source_policy(source),
                "max_papers": max(
                    1,
                    min(
                        int(request.max_papers_override)
                        if request.max_papers_override is not None
                        else template.max_papers,
                        50,
                    ),
                ),
            }
        )
        try:
            audited = await self.answer_with_audit(
                AnswerWithEvidenceRequest(
                    question=question,
                    max_papers=active_template.max_papers,
                    project_id=request.project_id,
                    project_context=request.project_context,
                    require_citations=active_template.require_citations,
                    source=active_template.source,
                    include_rejected_papers=active_template.include_rejected_papers,
                    use_llm_revision=active_template.use_llm_revision,
                    use_llm_planner=active_template.use_llm_planner,
                    execute_support_refute=active_template.execute_support_refute,
                    use_llm_extractor=active_template.use_llm_extractor,
                    use_llm_synthesis=active_template.use_llm_synthesis,
                    use_llm_verifier=active_template.use_llm_verifier,
                    use_llm_claim_logic=active_template.use_llm_claim_logic,
                    export_logic_facts=active_template.export_logic_facts,
                )
            )
        except LiteratureClientError as exc:
            return release_error(
                tool_name=tool_name,
                code="external_source_unavailable",
                message=str(exc),
                detail={"template_id": template_id, "source": active_template.source},
                metadata=metadata,
            )
        except ValueError as exc:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message=str(exc),
                detail={
                    "template_id": template_id,
                    "project_id": request.project_id,
                },
                metadata=metadata,
            )
        provenance: dict[str, Any] | None = None
        if active_template.export_provenance:
            provenance = self.export_provenance_graph(
                audited.answer_result.run_id
            ).model_dump(mode="json")
        ids = {
            "template_id": active_template.template_id,
            "run_id": audited.answer_result.run_id,
        }
        if audited.answer_result.retrieval_id:
            ids["retrieval_id"] = audited.answer_result.retrieval_id
        if audited.answer_result.evidence_packet:
            ids["packet_id"] = audited.answer_result.evidence_packet.packet_id
        return release_ok(
            tool_name=tool_name,
            result={
                "template": active_template.model_dump(mode="json"),
                "audited_answer": audited.model_dump(mode="json"),
                "provenance": provenance,
            },
            ids=ids,
            trace={
                "template_id": active_template.template_id,
                "workflow": active_template.workflow,
                "source": active_template.source,
                "required_skills": active_template.required_skills,
                "stop_conditions": active_template.stop_conditions,
            },
            metadata=metadata,
        )

    def create_project(self, request: BiomedProjectCreateRequest) -> BiomedProject:
        now = _now_iso()
        project = BiomedProject(
            project_id=f"biomed-project-{uuid.uuid4().hex[:12]}",
            name=request.name.strip() or "Untitled biomedical project",
            description=request.description,
            research_question=request.research_question.strip(),
            include_keywords=_clean_list(request.include_keywords),
            exclude_keywords=_clean_list(request.exclude_keywords),
            preferred_methods=_clean_list(request.preferred_methods),
            preferred_species=_clean_list(request.preferred_species),
            preferred_study_types=_clean_list(request.preferred_study_types),
            created_at=now,
            updated_at=now,
        )
        self.storage.save_project(project)
        return project

    def update_project(
        self,
        project_id: str,
        request: BiomedProjectUpdateRequest,
    ) -> BiomedProject | None:
        current = self.storage.get_project(project_id)
        if current is None:
            return None
        update: dict[str, object] = {"updated_at": _now_iso()}
        for field in (
            "name",
            "description",
            "research_question",
            "include_keywords",
            "exclude_keywords",
            "preferred_methods",
            "preferred_species",
            "preferred_study_types",
        ):
            value = getattr(request, field)
            if value is None:
                continue
            if isinstance(value, list):
                update[field] = _clean_list(value)
            elif isinstance(value, str):
                update[field] = value.strip()
            else:
                update[field] = value
        updated = current.model_copy(update=update)
        self.storage.save_project(updated)
        return updated

    def get_project(self, project_id: str) -> BiomedProject | None:
        return self.storage.get_project(project_id)

    def list_projects(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[BiomedProject], int]:
        return self.storage.list_projects(page=page, page_size=page_size)

    def save_project_paper_decision(
        self,
        project_id: str,
        request: ProjectPaperDecisionRequest,
    ) -> ProjectPaperDecision:
        project = self.storage.get_project(project_id)
        if project is None:
            raise ValueError("project not found")
        now = _now_iso()
        decision = ProjectPaperDecision(
            decision_id=f"biomed-proj-paper-{uuid.uuid4().hex[:12]}",
            project_id=project.project_id,
            paper_id=request.paper_id,
            source=request.source,
            decision=request.decision,
            reason=request.reason,
            tags=_clean_list(request.tags),
            notes=request.notes,
            run_id=request.run_id,
            retrieval_id=request.retrieval_id,
            created_at=now,
            updated_at=now,
        )
        return self.storage.save_project_paper_decision(decision)

    def list_project_paper_decisions(
        self,
        project_id: str,
        *,
        decision: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[ProjectPaperDecision], int]:
        if self.storage.get_project(project_id) is None:
            raise ValueError("project not found")
        return self.storage.list_project_paper_decisions(
            project_id,
            decision=decision,
            page=page,
            page_size=page_size,
        )

    def save_project_claim_record(
        self,
        project_id: str,
        request: ProjectClaimRecordRequest,
    ) -> ProjectClaimRecord:
        project = self.storage.get_project(project_id)
        if project is None:
            raise ValueError("project not found")
        now = _now_iso()
        claim = ProjectClaimRecord(
            claim_id=f"biomed-proj-claim-{uuid.uuid4().hex[:12]}",
            project_id=project.project_id,
            claim=request.claim,
            status=request.status,
            evidence_ids=_clean_list(request.evidence_ids),
            audit_ids=_clean_list(request.audit_ids),
            verifier_ids=_clean_list(request.verifier_ids),
            notes=request.notes,
            created_at=now,
            updated_at=now,
        )
        return self.storage.save_project_claim_record(claim)

    def list_project_claim_records(
        self,
        project_id: str,
        *,
        status: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[ProjectClaimRecord], int]:
        if self.storage.get_project(project_id) is None:
            raise ValueError("project not found")
        return self.storage.list_project_claim_records(
            project_id,
            status=status,
            page=page,
            page_size=page_size,
        )

    def list_project_review_queue(
        self,
        project_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[ProjectReviewQueueItem], int]:
        if self.storage.get_project(project_id) is None:
            raise ValueError("project not found")
        return self.storage.list_project_review_queue(
            project_id,
            page=page,
            page_size=page_size,
        )

    def generate_project_evidence_brief(
        self,
        request: GenerateProjectEvidenceBriefRequest,
    ) -> ProjectEvidenceBrief:
        project = self.storage.get_project(request.project_id)
        if project is None:
            raise ValueError("project not found")
        claims, _ = self.storage.list_project_claim_records(
            project.project_id,
            page=1,
            page_size=500,
        )
        decisions, _ = self.storage.list_project_paper_decisions(
            project.project_id,
            page=1,
            page_size=500,
        )
        review_queue, _ = self.storage.list_project_review_queue(
            project.project_id,
            page=1,
            page_size=200,
        )
        saved_decisions = [item for item in decisions if item.decision == "saved"]
        audited_claims = [item for item in claims if item.audit_ids]
        included_evidence_ids = sorted(
            {
                evidence_id
                for claim in audited_claims
                for evidence_id in claim.evidence_ids
            }
        )
        audit_ids = sorted(
            {audit_id for claim in audited_claims for audit_id in claim.audit_ids}
        )
        verifier_ids = sorted(
            {
                verifier_id
                for claim in audited_claims
                for verifier_id in claim.verifier_ids
            }
        )
        title = request.title or f"{project.name} evidence brief"
        if request.format == "json":
            content = json.dumps(
                {
                    "project": project.model_dump(mode="json"),
                    "saved_papers": [
                        item.model_dump(mode="json") for item in saved_decisions
                    ],
                    "audited_claims": [
                        item.model_dump(mode="json") for item in audited_claims
                    ],
                    "review_queue": [
                        item.model_dump(mode="json") for item in review_queue
                    ],
                    "policy": (
                        "Project memory is context only; brief claims are promoted "
                        "only when linked to audit IDs."
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        else:
            content = _project_brief_markdown(
                project=project,
                title=title,
                saved_decisions=saved_decisions,
                audited_claims=audited_claims,
                review_queue=review_queue,
                storage=self.storage,
            )
        brief = ProjectEvidenceBrief(
            brief_id=f"biomed-proj-brief-{uuid.uuid4().hex[:12]}",
            project_id=project.project_id,
            title=title,
            format=request.format,
            content=content,
            included_claim_ids=[item.claim_id for item in audited_claims],
            included_evidence_ids=included_evidence_ids,
            audit_ids=audit_ids,
            verifier_ids=verifier_ids,
            created_at=_now_iso(),
        )
        return self.storage.save_project_brief(brief)

    def list_project_briefs(
        self,
        project_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ProjectEvidenceBrief], int]:
        if self.storage.get_project(project_id) is None:
            raise ValueError("project not found")
        return self.storage.list_project_briefs(
            project_id,
            page=page,
            page_size=page_size,
        )

    async def search(
        self,
        request: SearchBiomedicalLiteratureRequest,
    ) -> list[PaperMetadata]:
        return (await self.search_with_manifest(request)).items

    async def search_literature(
        self,
        request: LiteratureSearchRequest,
    ) -> LiteratureSearchResult:
        if request.project_id and self.storage.get_project(request.project_id) is None:
            raise ValueError("project not found")
        publication_types = _clean_list(
            [*request.publication_types, *request.article_types]
        )
        search_request = SearchBiomedicalLiteratureRequest(
            query=request.query,
            max_results=request.max_results,
            date_from=request.date_from,
            date_to=request.date_to,
            source=request.source,
            publication_types=publication_types,
            study_types=_clean_list(request.study_types),
            mesh_terms=_clean_list(request.mesh_terms),
            species_terms=_clean_list(request.species_terms),
            exclude_terms=_clean_list(request.exclude_terms),
            store=request.store,
        )
        result = await self.search_with_manifest(search_request)
        manifest = result.retrieval_manifest
        records: list[LiteraturePaperRecord] = []
        stored_paper_ids: list[str] = []
        abstract_count = 0
        skipped_no_abstract_count = 0
        for index, item in enumerate(result.items, start=1):
            stored = self.storage.get_paper(item.paper_id, source=item.source)
            if stored is not None:
                stored_paper_ids.append(stored.paper_id)
            abstract = stored.abstract if stored is not None else None
            mesh_terms = stored.mesh_terms if stored is not None else []
            keywords = stored.keywords if stored is not None else []
            abstract_available = bool((abstract or "").strip())
            if abstract_available:
                abstract_count += 1
            elif request.require_abstract:
                skipped_no_abstract_count += 1
            records.append(
                LiteraturePaperRecord(
                    paper_id=item.paper_id,
                    source=item.source,
                    title=item.title,
                    abstract=abstract,
                    authors=item.authors,
                    journal=item.journal,
                    publication_date=item.publication_date,
                    doi=item.doi,
                    url=item.url,
                    source_rank=index,
                    abstract_available=abstract_available,
                    mesh_terms=mesh_terms,
                    keywords=keywords,
                )
            )
        warnings = [*manifest.warnings]
        if (
            request.require_abstract
            and result.items
            and skipped_no_abstract_count == len(result.items)
        ):
            warnings.append(
                "Literature search returned papers but no stored abstracts; evidence "
                "extraction will be limited."
            )
        query_used = manifest.compiled_query or request.query
        coverage = LiteratureSearchCoverage(
            item_count=len(records),
            abstract_count=abstract_count,
            abstract_coverage=_safe_ratio(abstract_count, len(records)),
            stored_paper_count=len(stored_paper_ids),
            skipped_no_abstract_count=skipped_no_abstract_count,
        )
        source_trace = LiteratureSourceTrace(
            source=request.source,
            live=request.source == "pubmed",
            query_used=query_used,
            compiled_query=manifest.compiled_query,
            retrieval_intent=request.retrieval_intent,
            project_id=request.project_id,
            store_requested=request.store,
            require_abstract=request.require_abstract,
            stored_paper_ids=stored_paper_ids,
            unsupported_filters=manifest.unsupported_filters,
            warnings=warnings,
            errors=manifest.errors,
        )
        return LiteratureSearchResult(
            source=request.source,
            query=request.query,
            query_used=query_used,
            retrieval_intent=request.retrieval_intent,
            live=request.source == "pubmed",
            items=records,
            retrieval_manifest=manifest,
            coverage=coverage,
            source_trace=source_trace,
            warnings=warnings,
            errors=manifest.errors,
        )

    async def check_literature_access(
        self,
        request: LiteratureAccessCheckRequest,
    ) -> LiteratureAccessCheckResult:
        checked_at = _now_iso()
        warnings: list[str] = []
        errors: list[str] = []
        search_request = SearchBiomedicalLiteratureRequest(
            query=request.query,
            max_results=max(1, min(request.max_results, 10)),
            date_from=request.date_from,
            date_to=request.date_to,
            source=request.source,
        )
        if request.source == "pubmed":
            if not self.pubmed_client.email:
                warnings.append(
                    "NCBI_EMAIL is not configured; PubMed allows requests but "
                    "tool/contact identity is recommended for live use."
                )
            if not self.pubmed_client.api_key:
                warnings.append(
                    "NCBI_API_KEY is not configured; PubMed rate limits may be lower."
                )
        try:
            result = await self.search_with_manifest(search_request)
        except LiteratureClientError as exc:
            errors.append(str(exc))
            return LiteratureAccessCheckResult(
                source=request.source,
                query=request.query,
                live=request.source == "pubmed",
                ok=False,
                ready=False,
                checked_at=checked_at,
                ncbi_email_configured=bool(self.pubmed_client.email),
                ncbi_api_key_configured=bool(self.pubmed_client.api_key),
                warnings=warnings,
                errors=errors,
            )

        items = result.items
        stored_paper_count = 0
        abstract_count = 0
        for item in items:
            stored = self.storage.get_paper(item.paper_id, source=item.source)
            if stored is None:
                stored = await self.fetch(
                    FetchBiomedicalPaperRequest(
                        paper_id=item.paper_id,
                        source=item.source,
                    )
                )
            if stored is None:
                continue
            stored_paper_count += 1
            if (stored.abstract or "").strip():
                abstract_count += 1
        item_count = len(items)
        if item_count == 0:
            warnings.append("Literature source returned zero papers for the smoke query.")
        if request.require_abstract and item_count > 0 and abstract_count == 0:
            warnings.append(
                "Literature source returned papers but no abstracts; evidence extraction "
                "will be limited."
            )
        manifest = result.retrieval_manifest
        warnings.extend(manifest.warnings)
        errors.extend(manifest.errors)
        ready = (
            item_count > 0
            and stored_paper_count > 0
            and not errors
            and (not request.require_abstract or abstract_count > 0)
        )
        return LiteratureAccessCheckResult(
            source=request.source,
            query=request.query,
            live=request.source == "pubmed",
            ok=not errors,
            ready=ready,
            checked_at=checked_at,
            item_count=item_count,
            abstract_count=abstract_count,
            abstract_coverage=_safe_ratio(abstract_count, item_count),
            stored_paper_count=stored_paper_count,
            ncbi_email_configured=bool(self.pubmed_client.email),
            ncbi_api_key_configured=bool(self.pubmed_client.api_key),
            retrieval_manifest=manifest,
            items=items,
            warnings=warnings,
            errors=errors,
        )

    async def run_multi_pass_literature_search(
        self,
        request: MultiPassLiteratureSearchRequest,
    ) -> ReleaseToolEnvelope:
        tool_name = "run_multi_pass_literature_search"
        metadata = get_release_tool_metadata(tool_name)
        run_id = f"biomed-tool-run-{uuid.uuid4().hex[:12]}"
        trace = [
            _tool_trace_step(
                run_id=run_id,
                step="classify",
                status="started",
                input_summary=request.question,
                output_summary="clinical boundary precheck",
                metadata={"clinical_boundary_prechecked": True},
            )
        ]
        if is_clinical_request(request.question):
            trace[0] = trace[0].model_copy(
                update={
                    "status": "completed",
                    "output_summary": "clinical_boundary",
                    "metadata": {
                        **trace[0].metadata,
                        "clinical_boundary": True,
                        "clinical_boundary_before_memory": True,
                    },
                }
            )
            return release_error(
                tool_name=tool_name,
                code="clinical_boundary",
                message=(
                    "Biomedical Evidence tools are research-only and were not executed "
                    "for a clinical or patient-specific request."
                ),
                trace={
                    "trace": [item.model_dump(mode="json") for item in trace],
                    "memory_used": False,
                    "memory_as_evidence": False,
                },
                metadata=metadata,
            )

        budget = _release_tool_budget(
            max_tool_steps=request.max_tool_steps,
            max_retrieval_queries=request.max_queries,
            max_followup_queries=request.max_followups,
            max_papers=request.max_results,
            max_evidence_items=0,
            max_llm_calls=1 if request.use_llm_planner else 0,
            max_wall_clock_seconds=request.max_wall_clock_seconds,
        )
        memory_trace, project = self._release_project_memory_trace(
            project_id=request.project_id,
            request_context=request.project_context,
        )
        if request.project_id and project is None:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="project_id was provided but no biomedical project exists.",
                detail={"project_id": request.project_id},
                trace={
                    "trace": [item.model_dump(mode="json") for item in trace],
                    "memory": memory_trace,
                    "budget": budget,
                },
                metadata=metadata,
            )
        active_question = request.question
        project_context = request.project_context
        if project is not None:
            project_context = _project_context_text(
                project=project,
                request_context=request.project_context,
            )
        plan_request = PlanBiomedicalSearchRequest(
            question=active_question,
            max_results=request.max_results,
            source=request.source,
            project_context=project_context,
            use_llm_planner=request.use_llm_planner,
        )
        planning_result = await self.plan_biomedical_search(plan_request)
        trace.extend(
            [
                _tool_trace_step(
                    run_id=run_id,
                    step="plan",
                    status="completed",
                    input_summary=active_question,
                    output_summary=(
                        planning_result.query_plan.primary_query
                        if planning_result.query_plan is not None
                        else "no query plan"
                    ),
                    warnings=(
                        planning_result.query_plan.warnings
                        if planning_result.query_plan is not None
                        else []
                    ),
                    metadata={
                        "query_plan": (
                            planning_result.query_plan.model_dump(mode="json")
                            if planning_result.query_plan is not None
                            else None
                        ),
                        "memory": memory_trace,
                    },
                ),
                _tool_trace_step(
                    run_id=run_id,
                    step="validate_plan",
                    status="completed",
                    input_summary="structured planner output",
                    output_summary=planning_result.validation.status,
                    warnings=planning_result.validation.warnings,
                    metadata={
                        "validation": planning_result.validation.model_dump(
                            mode="json"
                        )
                    },
                ),
            ]
        )
        if planning_result.classification.clinical_boundary:
            return release_error(
                tool_name=tool_name,
                code="clinical_boundary",
                message="Planner classified the request as clinical; retrieval was not executed.",
                trace={
                    "trace": [item.model_dump(mode="json") for item in trace],
                    "memory": memory_trace,
                    "budget": budget,
                },
                metadata=metadata,
            )
        if not planning_result.validation.valid:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="Retrieval plan validation failed; no literature search executed.",
                detail={
                    "validation": planning_result.validation.model_dump(mode="json")
                },
                warnings=planning_result.validation.warnings,
                trace={
                    "trace": [item.model_dump(mode="json") for item in trace],
                    "memory": memory_trace,
                    "budget": budget,
                },
                metadata=metadata,
            )
        search_request = (
            planning_result.search_request
            if planning_result.search_request is not None
            else SearchBiomedicalLiteratureRequest(
                query=active_question,
                max_results=request.max_results,
                source=request.source,
            )
        )
        planned_query_count = 1
        if request.execute_support_refute and planning_result.query_plan is not None:
            specs, _ = _planned_retrieval_specs(
                base_request=search_request,
                query_plan=planning_result.query_plan,
            )
            planned_query_count = len(specs)
        if planned_query_count > request.max_queries:
            return release_error(
                tool_name=tool_name,
                code="budget_exceeded",
                message="Planned retrieval query count exceeded max_queries.",
                detail={
                    "planned_query_count": planned_query_count,
                    "max_queries": request.max_queries,
                },
                trace={
                    "trace": [item.model_dump(mode="json") for item in trace],
                    "memory": memory_trace,
                    "budget": budget,
                },
                metadata=metadata,
            )
        answer_request = AnswerWithEvidenceRequest(
            question=active_question,
            max_papers=request.max_results,
            project_id=request.project_id,
            project_context=project_context,
            source=request.source,
            include_rejected_papers=request.include_rejected_papers,
            use_llm_planner=request.use_llm_planner,
            execute_support_refute=request.execute_support_refute,
        )
        (
            metadata_items,
            retrieval_manifest,
            retrieval_bundle,
            _paper_intents,
            _paper_retrieval_ids,
        ) = await self._retrieve_answer_papers(
            request=answer_request,
            planning_result=planning_result,
            search_request=search_request,
            run_id=run_id,
        )
        if project is not None:
            (
                metadata_items,
                retrieval_manifest,
                retrieval_bundle,
                project_retrieval_trace,
            ) = self._apply_project_memory_to_retrieval(
                project=project,
                request=answer_request,
                metadata=metadata_items,
                retrieval_manifest=retrieval_manifest,
                retrieval_bundle=retrieval_bundle,
            )
            memory_trace.update(_memory_effects_from_project_trace(project_retrieval_trace))
            self.storage.save_retrieval_manifest(retrieval_manifest)
            self.storage.link_retrieval_papers(
                retrieval_manifest.retrieval_id,
                source=request.source,
                paper_ids=[item.paper_id for item in metadata_items],
            )
        trace.append(
            _tool_trace_step(
                run_id=run_id,
                step="retrieve",
                status="completed",
                input_summary=search_request.query,
                output_summary=retrieval_manifest.retrieval_id,
                warnings=_merge_unique(
                    retrieval_manifest.warnings,
                    retrieval_bundle.warnings if retrieval_bundle else [],
                ),
                metadata={
                    "retrieval_id": retrieval_manifest.retrieval_id,
                    "paper_ids": [item.paper_id for item in metadata_items],
                    "retrieval_bundle": _retrieval_bundle_trace(retrieval_bundle),
                    "memory": memory_trace,
                    "budget": {
                        **budget,
                        "retrieval_queries_used": planned_query_count,
                        "papers_returned": len(metadata_items),
                    },
                },
            )
        )
        step_telemetry = build_step_telemetry(
            trace,
            run_id=run_id,
            coverage_matrix=(
                retrieval_bundle.coverage_matrix if retrieval_bundle is not None else []
            ),
            stop_reason=(
                retrieval_bundle.stop_reason if retrieval_bundle is not None else None
            ),
        )
        result = MultiPassLiteratureSearchResult(
            run_id=run_id,
            source=request.source,
            classification=planning_result.classification,
            query_plan=planning_result.query_plan,
            validation=planning_result.validation,
            retrieval_manifest=retrieval_manifest,
            retrieval_bundle=retrieval_bundle,
            paper_ids=[item.paper_id for item in metadata_items],
            item_count=len(metadata_items),
            memory_trace=memory_trace,
            budget=budget,
            step_telemetry=step_telemetry,
        )
        return release_ok(
            tool_name=tool_name,
            result=result.model_dump(mode="json"),
            ids={
                "run_id": run_id,
                "retrieval_id": retrieval_manifest.retrieval_id,
                "bundle_id": retrieval_bundle.bundle_id if retrieval_bundle else "",
            },
            warnings=_merge_unique(
                retrieval_manifest.warnings,
                retrieval_bundle.warnings if retrieval_bundle else [],
            ),
            trace={
                "trace": [item.model_dump(mode="json") for item in trace],
                "step_telemetry": step_telemetry.model_dump(mode="json"),
                "memory": memory_trace,
                "budget": budget,
            },
            metadata=metadata,
        )

    async def extract_evidence_batch(
        self,
        request: EvidenceBatchExtractionRequest,
    ) -> ReleaseToolEnvelope:
        tool_name = "extract_evidence_batch"
        metadata = get_release_tool_metadata(tool_name)
        run = self.storage.get_answer_run(request.run_id) if request.run_id else None
        if request.run_id and run is None:
            return release_error(
                tool_name=tool_name,
                code="unknown_run_id",
                message="No biomedical answer run exists for run_id.",
                detail={"run_id": request.run_id},
                metadata=metadata,
            )
        if run is not None and is_clinical_request(run.answer):
            return release_error(
                tool_name=tool_name,
                code="clinical_boundary",
                message="Clinical refusal runs cannot be used for evidence extraction.",
                detail={"run_id": request.run_id},
                metadata=metadata,
            )
        retrieval_manifest = None
        if request.retrieval_id:
            retrieval_manifest = self.storage.get_retrieval_manifest(
                request.retrieval_id
            )
            if retrieval_manifest is None:
                return release_error(
                    tool_name=tool_name,
                    code="unknown_retrieval_id",
                    message="No retrieval manifest exists for retrieval_id.",
                    detail={"retrieval_id": request.retrieval_id},
                    metadata=metadata,
                )
        elif run is not None:
            retrieval_manifest = run.retrieval_manifest

        paper_ids = _merge_unique(
            request.paper_ids,
            (
                run.retrieval_bundle.deduped_paper_ids
                if run is not None and run.retrieval_bundle is not None
                else []
            ),
            (
                retrieval_manifest.returned_paper_ids
                if retrieval_manifest is not None
                else []
            ),
        )
        if not paper_ids:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="Provide run_id, retrieval_id, or paper_ids for extraction.",
                metadata=metadata,
            )
        if len(paper_ids) > request.max_papers:
            return release_error(
                tool_name=tool_name,
                code="budget_exceeded",
                message="Requested papers exceed max_papers.",
                detail={"paper_count": len(paper_ids), "max_papers": request.max_papers},
                ids={"run_id": request.run_id or ""},
                metadata=metadata,
            )

        source = (
            run.retrieval_manifest.source
            if run is not None and run.retrieval_manifest is not None
            else (
                retrieval_manifest.source
                if retrieval_manifest is not None
                else request.source
            )
        )
        research_question = (
            request.research_question
            or (run.answer if run is not None else "")
            or "Biomedical evidence extraction"
        )
        answer_request = AnswerWithEvidenceRequest(
            question=research_question,
            source=cast(Any, source),
            max_papers=request.max_papers,
            use_llm_extractor=request.use_llm_extractor,
        )
        evidence: list[EvidenceItem] = []
        warnings: list[str] = []
        resolved_paper_ids: list[str] = []
        for paper_id in paper_ids:
            paper = await self.fetch(
                FetchBiomedicalPaperRequest(
                    paper_id=paper_id,
                    source=cast(Any, source),
                )
            )
            if paper is None:
                warnings.append(f"Paper not found: {paper_id}")
                continue
            resolved_paper_ids.append(paper.paper_id)
            extracted = await self._extract_evidence_for_answer(
                request=answer_request,
                paper=paper,
                retrieval_id=(
                    request.retrieval_id
                    or (retrieval_manifest.retrieval_id if retrieval_manifest else None)
                ),
                retrieval_intent="unknown",
            )
            evidence.extend(extracted.evidence)
            if len(evidence) > request.max_evidence_items:
                return release_error(
                    tool_name=tool_name,
                    code="budget_exceeded",
                    message="Extracted evidence exceeded max_evidence_items.",
                    detail={
                        "evidence_count": len(evidence),
                        "max_evidence_items": request.max_evidence_items,
                    },
                    trace={"partial_evidence_count": len(evidence)},
                    ids={"run_id": request.run_id or ""},
                    metadata=metadata,
                )
        if not evidence:
            return release_error(
                tool_name=tool_name,
                code="empty_evidence",
                message="No evidence could be extracted from the selected papers.",
                detail={"paper_ids": paper_ids},
                warnings=warnings,
                ids={"run_id": request.run_id or ""},
                metadata=metadata,
            )
        if run is not None and not run.evidence_summary:
            updated_run = run.model_copy(update={"evidence_summary": evidence})
            self.storage.save_answer_run(updated_run, question=research_question)
        result = EvidenceBatchExtractionResult(
            run_id=request.run_id,
            retrieval_id=(
                request.retrieval_id
                or (retrieval_manifest.retrieval_id if retrieval_manifest else None)
            ),
            source=cast(Any, source),
            paper_ids=resolved_paper_ids,
            evidence=evidence,
            evidence_count=len(evidence),
            extraction_mode_counts=_extraction_mode_counts(evidence),
            warnings=warnings,
            memory_trace=_run_memory_trace(run),
            budget={
                "max_papers": request.max_papers,
                "max_evidence_items": request.max_evidence_items,
                "papers_used": len(resolved_paper_ids),
                "evidence_items": len(evidence),
            },
        )
        return release_ok(
            tool_name=tool_name,
            result=result.model_dump(mode="json"),
            ids={
                "run_id": request.run_id or "",
                "retrieval_id": result.retrieval_id or "",
            },
            warnings=warnings,
            trace={
                "memory": result.memory_trace,
                "budget": result.budget,
            },
            metadata=metadata,
        )

    def analyze_coverage_gaps(
        self,
        request: CoverageGapAnalysisRequest,
    ) -> ReleaseToolEnvelope:
        tool_name = "analyze_coverage_gaps"
        metadata = get_release_tool_metadata(tool_name)
        run = self.storage.get_answer_run(request.run_id) if request.run_id else None
        if request.run_id and run is None:
            return release_error(
                tool_name=tool_name,
                code="unknown_run_id",
                message="No biomedical answer run exists for run_id.",
                detail={"run_id": request.run_id},
                metadata=metadata,
            )
        retrieval_manifest = None
        if request.retrieval_id:
            retrieval_manifest = self.storage.get_retrieval_manifest(
                request.retrieval_id
            )
            if retrieval_manifest is None:
                return release_error(
                    tool_name=tool_name,
                    code="unknown_retrieval_id",
                    message="No retrieval manifest exists for retrieval_id.",
                    detail={"retrieval_id": request.retrieval_id},
                    metadata=metadata,
                )
        elif run is not None:
            retrieval_manifest = run.retrieval_manifest
        if retrieval_manifest is None:
            return release_error(
                tool_name=tool_name,
                code="missing_retrieval_manifest",
                message="Coverage analysis requires run_id with retrieval or retrieval_id.",
                metadata=metadata,
            )

        evidence = run.evidence_summary if run is not None else []
        bundle = run.retrieval_bundle if run is not None else None
        if bundle is None:
            bundle = _retrieval_bundle_from_manifest(retrieval_manifest)
        coverage_matrix = _build_coverage_matrix(bundle, evidence)
        gap_decisions: list[GapSearchDecision] = []
        if run is not None and run.query_plan is not None:
            gap_decisions = _gap_search_decisions(
                coverage_matrix,
                query_plan=run.query_plan,
                existing_queries={record.query.lower() for record in bundle.records},
                max_decisions=max(0, request.max_gap_queries),
            )
        stop_reason = _coverage_stop_reason(coverage_matrix)
        bandit = _bandit_advisory_from_coverage(
            coverage_matrix,
            gap_decisions,
            stop_reason=stop_reason,
        )
        trace = [
            _tool_trace_step(
                run_id=request.run_id or "coverage-gap-analysis",
                step="coverage_gap_analysis",
                status="completed",
                input_summary=request.retrieval_id or request.run_id or "",
                output_summary=stop_reason,
                metadata={
                    "coverage_rows": len(coverage_matrix),
                    "gap_decisions": len(gap_decisions),
                    "advisory_only": True,
                },
            )
        ]
        step_telemetry = build_step_telemetry(
            trace,
            run_id=request.run_id,
            coverage_matrix=coverage_matrix,
            stop_reason=stop_reason,
        )
        result = CoverageGapAnalysisResult(
            run_id=request.run_id,
            retrieval_id=retrieval_manifest.retrieval_id,
            coverage_matrix=coverage_matrix,
            gap_decisions=gap_decisions,
            bandit_advisory=bandit,
            stop_reason=stop_reason,
            memory_trace=_run_memory_trace(run),
            step_telemetry=step_telemetry,
        )
        return release_ok(
            tool_name=tool_name,
            result=result.model_dump(mode="json"),
            ids={
                "run_id": request.run_id or "",
                "retrieval_id": retrieval_manifest.retrieval_id,
            },
            trace={
                "trace": [item.model_dump(mode="json") for item in trace],
                "step_telemetry": step_telemetry.model_dump(mode="json"),
                "memory": result.memory_trace,
            },
            metadata=metadata,
        )

    def build_evidence_packet(
        self,
        request: EvidencePacketBuildRequest,
    ) -> ReleaseToolEnvelope:
        tool_name = "build_evidence_packet"
        metadata = get_release_tool_metadata(tool_name)
        run = self.storage.get_answer_run(request.run_id)
        if run is None:
            return release_error(
                tool_name=tool_name,
                code="unknown_run_id",
                message="No biomedical answer run exists for run_id.",
                detail={"run_id": request.run_id},
                metadata=metadata,
            )
        if run.retrieval_manifest is None:
            return release_error(
                tool_name=tool_name,
                code="missing_retrieval_manifest",
                message="Evidence packet requires a retrieval manifest.",
                detail={"run_id": request.run_id},
                metadata=metadata,
            )
        if not run.evidence_summary:
            return release_error(
                tool_name=tool_name,
                code="empty_evidence",
                message="Evidence packet requires extracted evidence.",
                detail={"run_id": request.run_id},
                metadata=metadata,
            )
        selected = _select_evidence_for_packet(
            run.evidence_summary,
            max_items=request.max_evidence_items,
            strategy=request.selection_strategy,
        )
        selected_ids = set(selected.selected_evidence_ids)
        selected_evidence = [
            item for item in run.evidence_summary if item.evidence_id in selected_ids
        ]
        packet_paper_ids = (
            run.retrieval_bundle.deduped_paper_ids
            if run.retrieval_bundle is not None
            else run.retrieval_manifest.returned_paper_ids
        )
        metadata_items = [
            _paper_metadata_from_stored_paper(
                self.storage.get_paper(paper_id, source=run.retrieval_manifest.source)
            )
            for paper_id in packet_paper_ids
        ]
        metadata_items = [item for item in metadata_items if item is not None]
        packet = _build_evidence_packet(
            request=AnswerWithEvidenceRequest(
                question=(
                    run.query_plan.question
                    if run.query_plan is not None
                    else run.answer[:240]
                ),
                source=cast(Any, run.retrieval_manifest.source),
                max_papers=len(metadata_items) or len(run.retrieval_manifest.returned_paper_ids),
            ),
            planning_result=None,
            retrieval_manifest=run.retrieval_manifest,
            retrieval_bundle=run.retrieval_bundle,
            metadata=cast(list[PaperMetadata], metadata_items),
            evidence=selected_evidence,
        )
        updated_run = run.model_copy(update={"evidence_packet": packet})
        self.storage.save_answer_run(updated_run, question=packet.question)
        trace = [
            _tool_trace_step(
                run_id=request.run_id,
                step="build_packet",
                status="completed",
                input_summary=f"{len(run.evidence_summary)} evidence items",
                output_summary=packet.packet_id,
                metadata={
                    "selection": selected.model_dump(mode="json"),
                    "memory": _run_memory_trace(run),
                },
            )
        ]
        step_telemetry = build_step_telemetry(
            trace,
            run_id=request.run_id,
            coverage_matrix=packet.coverage_matrix,
            stop_reason=packet.stop_reason,
        )
        result = EvidencePacketBuildResult(
            run_id=request.run_id,
            evidence_packet=packet,
            selection=selected,
            availability="persisted",
            memory_trace=_run_memory_trace(run),
            step_telemetry=step_telemetry,
        )
        return release_ok(
            tool_name=tool_name,
            result=result.model_dump(mode="json"),
            ids={"run_id": request.run_id, "packet_id": packet.packet_id},
            trace={
                "trace": [item.model_dump(mode="json") for item in trace],
                "step_telemetry": step_telemetry.model_dump(mode="json"),
            },
            metadata=metadata,
        )

    def get_evidence_packet(self, run_id: str) -> ReleaseToolEnvelope:
        tool_name = "get_evidence_packet"
        metadata = get_release_tool_metadata(tool_name)
        run = self.storage.get_answer_run(run_id)
        if run is None:
            return release_error(
                tool_name=tool_name,
                code="unknown_run_id",
                message="No biomedical answer run exists for run_id.",
                detail={"run_id": run_id},
                metadata=metadata,
            )
        availability: str = "unavailable"
        packet = run.evidence_packet
        if packet is not None:
            availability = "persisted"
        result = EvidencePacketGetResult(
            run_id=run_id,
            evidence_packet=packet,
            availability=cast(Any, availability),
            stale=False,
            source=(
                run.retrieval_manifest.source if run.retrieval_manifest is not None else None
            ),
            memory_trace=_run_memory_trace(run),
            step_telemetry=build_step_telemetry(
                self.storage.list_agent_trace_steps(run_id),
                run_id=run_id,
                coverage_matrix=packet.coverage_matrix if packet is not None else [],
                stop_reason=packet.stop_reason if packet is not None else None,
            ),
        )
        if packet is None:
            return release_error(
                tool_name=tool_name,
                code="packet_unavailable",
                message="No persisted evidence packet is available for run_id.",
                detail={"run_id": run_id},
                trace=result.model_dump(mode="json"),
                metadata=metadata,
            )
        return release_ok(
            tool_name=tool_name,
            result=result.model_dump(mode="json"),
            ids={"run_id": run_id, "packet_id": packet.packet_id},
            trace={
                "memory": result.memory_trace,
                "step_telemetry": (
                    result.step_telemetry.model_dump(mode="json")
                    if result.step_telemetry is not None
                    else None
                ),
            },
            metadata=metadata,
        )

    def export_provenance_graph(self, run_id: str) -> ReleaseToolEnvelope:
        tool_name = "export_provenance_graph"
        metadata = get_release_tool_metadata(tool_name)
        run = self.storage.get_answer_run(run_id)
        if run is None:
            return release_error(
                tool_name=tool_name,
                code="unknown_run_id",
                message="No biomedical answer run exists for run_id.",
                detail={"run_id": run_id},
                metadata=metadata,
            )
        try:
            graph = build_provenance_graph(
                answer=run,
                trace=self.storage.list_agent_trace_steps(run_id),
                audit=self.storage.get_latest_citation_audit_for_run(run_id),
                revision=self.storage.get_answer_revision(run_id),
                advisory=self.storage.get_latest_advisory_verifier_for_run(run_id),
            )
        except Exception as exc:
            return release_error(
                tool_name=tool_name,
                code="provenance_unavailable",
                message="Provenance graph could not be constructed.",
                detail={"run_id": run_id, "error": f"{type(exc).__name__}: {exc}"},
                metadata=metadata,
            )
        return release_ok(
            tool_name=tool_name,
            result=graph.model_dump(mode="json"),
            ids={"run_id": run_id, "graph_id": graph.graph_id},
            warnings=graph.warnings,
            trace={
                "schema_version": graph.schema_version,
                "entity_count": len(graph.entities),
                "activity_count": len(graph.activities),
                "agent_count": len(graph.agents),
                "relation_count": len(graph.relations),
                "redactions": graph.redactions,
            },
            metadata=metadata,
        )

    def export_evidence_packet_to_obsidian(
        self,
        request: ObsidianExportRequest,
    ) -> ReleaseToolEnvelope:
        tool_name = "export_evidence_packet_to_obsidian"
        metadata = get_release_tool_metadata(tool_name)
        export_dir, error = self._resolve_obsidian_export_dir(
            request=request,
            tool_name=tool_name,
            metadata=metadata,
        )
        if error is not None:
            return error
        if not request.run_id:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="run_id is required for evidence packet export.",
                metadata=metadata,
            )
        run = self.storage.get_answer_run(request.run_id)
        if run is None:
            return release_error(
                tool_name=tool_name,
                code="unknown_run_id",
                message="No biomedical answer run exists for run_id.",
                detail={"run_id": request.run_id},
                metadata=metadata,
            )
        if run.evidence_packet is None:
            return release_error(
                tool_name=tool_name,
                code="packet_unavailable",
                message="No persisted evidence packet is available for run_id.",
                detail={"run_id": request.run_id},
                metadata=metadata,
            )
        result = export_packet_note(
            packet=run.evidence_packet,
            export_dir=cast(Path, export_dir),
            run_id=request.run_id,
        )
        return _obsidian_export_ok(
            tool_name=tool_name,
            result=result,
            metadata=metadata,
            ids={"run_id": request.run_id, "packet_id": run.evidence_packet.packet_id},
        )

    def export_project_to_obsidian(
        self,
        request: ObsidianExportRequest,
    ) -> ReleaseToolEnvelope:
        tool_name = "export_project_to_obsidian"
        metadata = get_release_tool_metadata(tool_name)
        export_dir, error = self._resolve_obsidian_export_dir(
            request=request,
            tool_name=tool_name,
            metadata=metadata,
        )
        if error is not None:
            return error
        if not request.project_id:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="project_id is required for project export.",
                metadata=metadata,
            )
        project = self.storage.get_project(request.project_id)
        if project is None:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="No biomedical project exists for project_id.",
                detail={"project_id": request.project_id},
                metadata=metadata,
            )
        result = export_project_note(project=project, export_dir=cast(Path, export_dir))
        return _obsidian_export_ok(
            tool_name=tool_name,
            result=result,
            metadata=metadata,
            ids={"project_id": project.project_id},
        )

    def export_research_watch_to_obsidian(
        self,
        request: ObsidianExportRequest,
    ) -> ReleaseToolEnvelope:
        tool_name = "export_research_watch_to_obsidian"
        metadata = get_release_tool_metadata(tool_name)
        export_dir, error = self._resolve_obsidian_export_dir(
            request=request,
            tool_name=tool_name,
            metadata=metadata,
        )
        if error is not None:
            return error
        if not request.watch_id:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="watch_id is required for watch export.",
                metadata=metadata,
            )
        watch = self.storage.get_watch(request.watch_id)
        if watch is None:
            return release_error(
                tool_name=tool_name,
                code="invalid_input",
                message="No research watch exists for watch_id.",
                detail={"watch_id": request.watch_id},
                metadata=metadata,
            )
        result = export_watch_note(watch=watch, export_dir=cast(Path, export_dir))
        return _obsidian_export_ok(
            tool_name=tool_name,
            result=result,
            metadata=metadata,
            ids={"watch_id": watch.watch_id},
        )

    def _resolve_obsidian_export_dir(
        self,
        *,
        request: ObsidianExportRequest,
        tool_name: str,
        metadata: Any,
    ) -> tuple[Path | None, ReleaseToolEnvelope | None]:
        if request.max_files < 1:
            return None, release_error(
                tool_name=tool_name,
                code="budget_exceeded",
                message="Obsidian export requires max_files >= 1.",
                detail={"max_files": request.max_files},
                metadata=metadata,
            )
        export_dir, reason = ensure_obsidian_export_dir(
            workspace=self.workspace,
            export_dir=request.export_dir,
            enabled=request.enabled,
        )
        if reason is not None:
            return None, release_error(
                tool_name=tool_name,
                code="export_path_blocked",
                message=reason,
                detail={
                    "enabled": request.enabled,
                    "export_dir": request.export_dir,
                },
                metadata=metadata,
            )
        return export_dir, None

    async def search_with_manifest(
        self,
        request: SearchBiomedicalLiteratureRequest,
    ) -> SearchBiomedicalLiteratureResult:
        client = self._client(request.source)
        started_at = _now_iso()
        retrieval_id = _retrieval_id(request, started_at)
        compiled_query, normalized_filters, unsupported_filters = _compile_query(
            request
        )
        warnings: list[str] = []
        errors: list[str] = []
        trace: dict[str, object]
        try:
            if request.source == "pubmed":
                pubmed_result = await self.pubmed_client.search_with_trace(
                    compiled_query,
                    max_results=max(0, min(request.max_results, 50)),
                    date_from=request.date_from,
                    date_to=request.date_to,
                )
                items = pubmed_result.items
                trace = pubmed_result.trace
                if request.store:
                    for paper in pubmed_result.papers:
                        self.storage.upsert_paper(paper)
            else:
                items = await client.search(
                    request.query,
                    max_results=max(0, min(request.max_results, 50)),
                    date_from=request.date_from,
                    date_to=request.date_to,
                )
                trace = _mock_trace(
                    query=request.query,
                    max_results=request.max_results,
                    date_from=request.date_from,
                    date_to=request.date_to,
                    returned_ids=[item.paper_id for item in items],
                )
        except LiteratureClientError as exc:
            errors.append(str(exc))
            manifest = _manifest_from_trace(
                retrieval_id=retrieval_id,
                request=request,
                compiled_query=compiled_query,
                normalized_filters=normalized_filters,
                unsupported_filters=unsupported_filters,
                started_at=started_at,
                trace={},
                returned_ids=[],
                duplicate_ids=[],
                warnings=warnings,
                errors=errors,
            )
            self.storage.save_retrieval_manifest(manifest)
            raise
        returned_ids = [item.paper_id for item in items]
        duplicate_ids = cast(list[str], trace.get("duplicate_ids", []))
        manifest = _manifest_from_trace(
            retrieval_id=retrieval_id,
            request=request,
            compiled_query=compiled_query,
            normalized_filters=normalized_filters,
            unsupported_filters=unsupported_filters,
            started_at=started_at,
            trace=trace,
            returned_ids=returned_ids,
            duplicate_ids=duplicate_ids,
            warnings=warnings,
            errors=errors,
        )
        self.storage.save_retrieval_manifest(manifest)
        if request.store:
            self.storage.link_retrieval_papers(
                manifest.retrieval_id,
                source=request.source,
                paper_ids=returned_ids,
            )
            for item in items:
                stored = self.storage.get_paper(item.paper_id, source=request.source)
                paper = stored or await client.fetch(item.paper_id)
                if paper is not None:
                    self.storage.upsert_paper(paper)
        return SearchBiomedicalLiteratureResult(
            items=items,
            retrieval_manifest=manifest,
        )

    async def fetch(
        self, request: FetchBiomedicalPaperRequest
    ) -> BiomedicalPaper | None:
        stored = self.storage.get_paper(request.paper_id, source=request.source)
        if stored is not None:
            return stored
        paper = await self._client(request.source).fetch(request.paper_id)
        if paper is not None:
            self.storage.upsert_paper(paper)
        return paper

    def extract_evidence(
        self,
        request: EvidenceExtractionRequest,
        *,
        retrieval_id: str | None = None,
        retrieval_intent: RetrievalIntent = "unknown",
        extraction_mode: ExtractionMode = "deterministic",
    ) -> EvidenceExtractionResult:
        self.storage.upsert_paper(request.paper)
        result = self.extractor.extract(
            request.paper,
            research_question=request.research_question,
        )
        if result.evidence:
            result = result.model_copy(
                update={
                    "evidence": [
                        item.model_copy(
                            update={
                                "retrieval_intent": retrieval_intent,
                                "extraction_mode": extraction_mode,
                            }
                        )
                        for item in result.evidence
                    ]
                }
            )
        for item in result.evidence:
            self.storage.upsert_evidence(
                item,
                paper_source=request.paper.source,
                retrieval_id=retrieval_id,
            )
        return result

    async def _extract_evidence_for_answer(
        self,
        *,
        request: AnswerWithEvidenceRequest,
        paper: BiomedicalPaper,
        retrieval_id: str | None,
        retrieval_intent: RetrievalIntent,
    ) -> EvidenceExtractionResult:
        if request.use_llm_extractor:
            llm_result = await self._llm_extract_evidence_or_none(
                paper=paper,
                research_question=request.question,
                retrieval_id=retrieval_id,
                retrieval_intent=retrieval_intent,
            )
            if llm_result is not None:
                return llm_result
        return self.extract_evidence(
            EvidenceExtractionRequest(
                paper=paper,
                research_question=request.question,
            ),
            retrieval_id=retrieval_id,
            retrieval_intent=retrieval_intent,
            extraction_mode=(
                "fallback" if request.use_llm_extractor else "deterministic"
            ),
        )

    async def _llm_extract_evidence_or_none(
        self,
        *,
        paper: BiomedicalPaper,
        research_question: str,
        retrieval_id: str | None,
        retrieval_intent: RetrievalIntent,
    ) -> EvidenceExtractionResult | None:
        if self.revision_provider is None or not self.revision_model:
            return None
        prompt_payload = _llm_extraction_payload(
            paper=paper,
            research_question=research_question,
            retrieval_intent=retrieval_intent,
        )
        prompt_text = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
        try:
            response = await self.revision_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract biomedical evidence from one retrieved paper. "
                            "Return one valid JSON object only. Use only exact spans "
                            "from the supplied title or abstract. Do not infer beyond "
                            "the supplied paper text."
                        ),
                    },
                    {"role": "user", "content": prompt_text},
                ],
                tools=[],
                model=self.revision_model,
                max_tokens=1600,
                tool_choice="none",
                disable_thinking=True,
            )
            parsed = _parse_json_object(str(getattr(response, "content", "") or ""))
            raw_items = parsed.get("evidence")
            if not isinstance(raw_items, list):
                return None
            evidence: list[EvidenceItem] = []
            for index, raw_item in enumerate(raw_items[:3]):
                if not isinstance(raw_item, dict):
                    continue
                item = _evidence_item_from_llm(
                    raw_item,
                    paper=paper,
                    index=index,
                    model=self.revision_model,
                    prompt_hash=prompt_hash,
                    retrieval_intent=retrieval_intent,
                )
                if item is not None:
                    evidence.append(item)
            if not evidence:
                return None
            result = EvidenceExtractionResult(
                paper_id=paper.paper_id,
                evidence=evidence,
                reason=None,
            )
            self.storage.upsert_paper(paper)
            for item in result.evidence:
                self.storage.upsert_evidence(
                    item,
                    paper_source=paper.source,
                    retrieval_id=retrieval_id,
                )
            return result
        except Exception:
            return None

    async def plan_biomedical_search(
        self,
        request: PlanBiomedicalSearchRequest,
    ) -> PlanBiomedicalSearchResult:
        classification = _classify_biomedical_question(
            request.question,
            mode="deterministic",
        )
        query_plan: BiomedicalQueryPlan | None = None
        if classification.allowed_next_step == "plan_retrieval":
            query_plan = _deterministic_query_plan(
                request=request,
                classification=classification,
            )
            if request.use_llm_planner:
                llm_result = await self._llm_plan_or_none(
                    request=request,
                    fallback_classification=classification,
                    fallback_plan=query_plan,
                )
                if llm_result is not None:
                    classification, query_plan = llm_result
                else:
                    classification = classification.model_copy(
                        update={
                            "classifier_mode": "fallback",
                            "warnings": _merge_unique(
                                classification.warnings,
                                [
                                    _llm_planner_unavailable_reason(
                                        self.revision_provider,
                                        self.revision_model,
                                    )
                                ],
                            ),
                        }
                    )
                    query_plan = query_plan.model_copy(
                        update={
                            "planner_mode": "fallback",
                            "warnings": _merge_unique(
                                query_plan.warnings,
                                [
                                    _llm_planner_unavailable_reason(
                                        self.revision_provider,
                                        self.revision_model,
                                    )
                                ],
                            ),
                        }
                    )
        validation = _validate_query_plan(
            classification=classification,
            query_plan=query_plan,
        )
        return PlanBiomedicalSearchResult(
            classification=classification,
            query_plan=query_plan,
            validation=validation,
            search_request=validation.executable_request if validation.valid else None,
        )

    async def _llm_plan_or_none(
        self,
        *,
        request: PlanBiomedicalSearchRequest,
        fallback_classification: BiomedicalQuestionClassification,
        fallback_plan: BiomedicalQueryPlan,
    ) -> tuple[BiomedicalQuestionClassification, BiomedicalQueryPlan] | None:
        if self.revision_provider is None or not self.revision_model:
            return None
        prompt_payload = _llm_planner_payload(
            request=request,
            fallback_classification=fallback_classification,
            fallback_plan=fallback_plan,
        )
        prompt_text = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
        try:
            response = await self.revision_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You classify biomedical user questions and produce "
                            "structured retrieval plans. Return one valid JSON object "
                            "only. Never override deterministic clinical guardrails. "
                            "Do not answer the biomedical question."
                        ),
                    },
                    {"role": "user", "content": prompt_text},
                ],
                tools=[],
                model=self.revision_model,
                max_tokens=1600,
                tool_choice="none",
                disable_thinking=True,
            )
            raw = str(getattr(response, "content", "") or "")
            parsed = _parse_json_object(raw)
            classification_payload = parsed.get("classification")
            if not isinstance(classification_payload, dict):
                classification_payload = parsed.get("deterministic_classification")
            query_plan_payload = parsed.get("query_plan")
            if not isinstance(query_plan_payload, dict):
                query_plan_payload = parsed.get("deterministic_query_plan")
            classification = _classification_from_llm(
                classification_payload,
                fallback=fallback_classification,
                model=self.revision_model,
                prompt_hash=prompt_hash,
            )
            if (
                classification.clinical_boundary
                or classification.allowed_next_step != "plan_retrieval"
            ):
                return classification, fallback_plan.model_copy(
                    update={
                        "planner_mode": "fallback",
                        "warnings": _merge_unique(
                            fallback_plan.warnings,
                            [
                                "LLM classification blocked retrieval; deterministic plan was not executed."
                            ],
                        ),
                    }
                )
            plan = _query_plan_from_llm(
                query_plan_payload,
                fallback=fallback_plan,
                model=self.revision_model,
                prompt_hash=prompt_hash,
                raw_response=parsed,
            )
            return classification, plan
        except Exception:
            return None

    async def answer_with_evidence(
        self,
        request: AnswerWithEvidenceRequest,
    ) -> AnswerWithEvidenceResult:
        run_id = f"biomed-run-{uuid.uuid4().hex[:12]}"
        project: BiomedProject | None = None
        project_context_trace: dict[str, object] = {
            "project_id": request.project_id,
            "project_found": False,
            "memory_used": False,
            "clinical_boundary_prechecked": is_clinical_request(request.question),
        }
        active_request = request
        if (
            request.project_id
            and not project_context_trace["clinical_boundary_prechecked"]
        ):
            project = self.storage.get_project(request.project_id)
            if project is None:
                raise ValueError("project not found")
            project_context = _project_context_text(
                project=project,
                request_context=request.project_context,
            )
            active_request = request.model_copy(
                update={"project_context": project_context}
            )
            project_context_trace.update(
                {
                    "project_found": True,
                    "memory_used": True,
                    "include_keywords": project.include_keywords,
                    "exclude_keywords": project.exclude_keywords,
                    "preferred_methods": project.preferred_methods,
                    "preferred_species": project.preferred_species,
                    "preferred_study_types": project.preferred_study_types,
                }
            )
        planning_result: PlanBiomedicalSearchResult | None = None
        if active_request.use_llm_planner:
            planning_result = await self.plan_biomedical_search(
                PlanBiomedicalSearchRequest(
                    question=active_request.question,
                    max_results=active_request.max_papers,
                    source=active_request.source,
                    project_context=active_request.project_context,
                    use_llm_planner=active_request.use_llm_planner,
                )
            )
        clinical_boundary = bool(
            project_context_trace["clinical_boundary_prechecked"]
        ) or bool(planning_result and planning_result.classification.clinical_boundary)
        if clinical_boundary:
            result = AnswerWithEvidenceResult(
                run_id=run_id,
                answer=clinical_refusal(),
                citations=[],
                evidence_summary=[],
                conflicting_evidence=[],
                limitations=[
                    "The request crossed the clinical-use boundary and was redirected."
                ],
                uncertainty_level="high",
                suggested_next_steps=[
                    "Reframe as a non-clinical research question.",
                    "Consult a qualified clinician for patient-specific decisions.",
                ],
                not_medical_advice=True,
                disclaimer=RESEARCH_USE_DISCLAIMER,
                project_id=None,
                project_context_used=None,
                project_context_trace={
                    **project_context_trace,
                    "memory_used": False,
                    "clinical_boundary_blocked_memory": True,
                },
                question_classification=(
                    planning_result.classification
                    if planning_result is not None
                    else None
                ),
                query_plan=(
                    planning_result.query_plan if planning_result is not None else None
                ),
                query_plan_validation=(
                    planning_result.validation if planning_result is not None else None
                ),
            )
            self.storage.save_answer_run(result, question=request.question)
            return result

        if planning_result is not None and not planning_result.validation.valid:
            result = AnswerWithEvidenceResult(
                run_id=run_id,
                answer=_planning_abstention(planning_result.classification),
                citations=[],
                evidence_summary=[],
                conflicting_evidence=[],
                limitations=planning_result.validation.errors
                or planning_result.validation.warnings
                or ["The retrieval plan was not valid enough to execute."],
                uncertainty_level="high",
                suggested_next_steps=_planner_next_steps(
                    planning_result.classification
                ),
                not_medical_advice=True,
                disclaimer=RESEARCH_USE_DISCLAIMER,
                project_id=active_request.project_id,
                project_context_used=active_request.project_context,
                project_context_trace=project_context_trace,
                question_classification=planning_result.classification,
                query_plan=planning_result.query_plan,
                query_plan_validation=planning_result.validation,
            )
            self.storage.save_answer_run(result, question=request.question)
            return result

        search_request = (
            planning_result.search_request
            if planning_result is not None
            and planning_result.search_request is not None
            else SearchBiomedicalLiteratureRequest(
                query=active_request.question,
                max_results=active_request.max_papers,
                source=active_request.source,
            )
        )
        (
            metadata,
            retrieval_manifest,
            retrieval_bundle,
            paper_intents,
            paper_retrieval_ids,
        ) = await self._retrieve_answer_papers(
            request=active_request,
            planning_result=planning_result,
            search_request=search_request,
            run_id=run_id,
        )
        if project is not None:
            (
                metadata,
                retrieval_manifest,
                retrieval_bundle,
                project_retrieval_trace,
            ) = self._apply_project_memory_to_retrieval(
                project=project,
                request=active_request,
                metadata=metadata,
                retrieval_manifest=retrieval_manifest,
                retrieval_bundle=retrieval_bundle,
            )
            project_context_trace.update(project_retrieval_trace)
            self.storage.save_retrieval_manifest(retrieval_manifest)
            self.storage.link_retrieval_papers(
                retrieval_manifest.retrieval_id,
                source=active_request.source,
                paper_ids=[item.paper_id for item in metadata],
            )
        evidence: list[EvidenceItem] = []
        papers: dict[str, BiomedicalPaper] = {}
        for item in metadata:
            paper = await self.fetch(
                FetchBiomedicalPaperRequest(
                    paper_id=item.paper_id, source=active_request.source
                )
            )
            if paper is None:
                continue
            papers[paper.paper_id] = paper
            extracted = await self._extract_evidence_for_answer(
                request=active_request,
                paper=paper,
                retrieval_id=paper_retrieval_ids.get(
                    item.paper_id,
                    retrieval_manifest.retrieval_id,
                ),
                retrieval_intent=paper_intents.get(item.paper_id, "unknown"),
            )
            evidence.extend(extracted.evidence)

        if retrieval_bundle is not None:
            (
                metadata,
                retrieval_bundle,
                paper_intents,
                paper_retrieval_ids,
                papers,
                evidence,
            ) = await self._apply_gap_directed_retrieval(
                request=active_request,
                planning_result=planning_result,
                metadata=metadata,
                retrieval_bundle=retrieval_bundle,
                paper_intents=paper_intents,
                paper_retrieval_ids=paper_retrieval_ids,
                papers=papers,
                evidence=evidence,
                project=project,
            )
        evidence_packet = _build_evidence_packet(
            request=active_request,
            planning_result=planning_result,
            retrieval_manifest=retrieval_manifest,
            retrieval_bundle=retrieval_bundle,
            metadata=metadata,
            evidence=evidence,
        )

        citations = [
            Citation(
                paper_id=item.paper_id,
                title=papers.get(
                    item.paper_id,
                    BiomedicalPaper(
                        paper_id=item.paper_id,
                        source=active_request.source,
                        title=item.paper_id,
                    ),
                ).title,
                source=(
                    papers[item.paper_id].source
                    if item.paper_id in papers
                    else active_request.source
                ),
                doi=papers[item.paper_id].doi if item.paper_id in papers else None,
                url=papers[item.paper_id].url if item.paper_id in papers else None,
                cited_claim=item.claim,
            )
            for item in evidence
            if item.paper_id in papers
        ]
        conflicting = [
            item for item in evidence if item.evidence_direction == "contradicts"
        ]
        limitations = _collect_limitations(evidence)
        if not citations and active_request.require_citations:
            answer = (
                f"{RESEARCH_USE_DISCLAIMER}\n\n"
                "I could not retrieve citation-backed evidence for this question in "
                "the selected source. I will not make strong biomedical claims without "
                "retrieved citations."
            )
            uncertainty: ConfidenceLevel = "high"
            synthesis_outcome = _SynthesisOutcome(
                answer=answer,
                mode="deterministic",
                model=None,
                prompt_hash=None,
            )
        else:
            deterministic_answer = _compose_answer(
                question=active_request.question,
                evidence=evidence,
                papers=papers,
                project_context=active_request.project_context,
            )
            uncertainty = _uncertainty(evidence)
            synthesis_outcome = _SynthesisOutcome(
                answer=deterministic_answer,
                mode="deterministic",
                model=None,
                prompt_hash=None,
            )
            if active_request.use_llm_synthesis:
                synthesis_outcome = await self._llm_synthesis_or_fallback(
                    request=active_request,
                    deterministic_answer=deterministic_answer,
                    citations=citations,
                    evidence=evidence,
                    papers=papers,
                    retrieval_manifest=retrieval_manifest,
                    retrieval_bundle=retrieval_bundle,
                    evidence_packet=evidence_packet,
                    uncertainty=uncertainty,
                    run_id=run_id,
                )
            answer = synthesis_outcome.answer
        result = AnswerWithEvidenceResult(
            run_id=run_id,
            retrieval_id=retrieval_manifest.retrieval_id,
            retrieval_manifest=retrieval_manifest,
            retrieval_bundle=retrieval_bundle,
            answer=answer,
            citations=citations,
            evidence_summary=evidence,
            conflicting_evidence=conflicting,
            limitations=limitations,
            uncertainty_level=uncertainty,
            suggested_next_steps=_suggest_next_steps(
                evidence, bool(active_request.project_context)
            ),
            not_medical_advice=True,
            disclaimer=RESEARCH_USE_DISCLAIMER,
            project_id=active_request.project_id,
            project_context_used=active_request.project_context,
            project_context_trace=project_context_trace,
            question_classification=(
                planning_result.classification if planning_result is not None else None
            ),
            query_plan=(
                planning_result.query_plan if planning_result is not None else None
            ),
            query_plan_validation=(
                planning_result.validation if planning_result is not None else None
            ),
            evidence_packet=evidence_packet,
            synthesis_mode=cast(Any, synthesis_outcome.mode),
            synthesis_model=synthesis_outcome.model,
            synthesis_prompt_hash=synthesis_outcome.prompt_hash,
            synthesis_fallback_reason=synthesis_outcome.fallback_reason,
        )
        self.storage.save_answer_run(result, question=request.question)
        return result

    async def _retrieve_answer_papers(
        self,
        *,
        request: AnswerWithEvidenceRequest,
        planning_result: PlanBiomedicalSearchResult | None,
        search_request: SearchBiomedicalLiteratureRequest,
        run_id: str,
    ) -> tuple[
        list[PaperMetadata],
        RetrievalManifest,
        RetrievalBundle | None,
        dict[str, RetrievalIntent],
        dict[str, str],
    ]:
        if (
            not request.execute_support_refute
            or planning_result is None
            or planning_result.query_plan is None
        ):
            search_result = await self.search_with_manifest(search_request)
            intent: RetrievalIntent = (
                "primary"
                if planning_result is not None and planning_result.query_plan
                else "unknown"
            )
            return (
                search_result.items,
                search_result.retrieval_manifest,
                None,
                {item.paper_id: intent for item in search_result.items},
                {
                    item.paper_id: search_result.retrieval_manifest.retrieval_id
                    for item in search_result.items
                },
            )

        specs, bundle_warnings = _planned_retrieval_specs(
            base_request=search_request,
            query_plan=planning_result.query_plan,
        )
        records: list[RetrievalBundleRecord] = []
        unique_items: list[PaperMetadata] = []
        seen_paper_ids: set[str] = set()
        duplicate_paper_ids: list[str] = []
        paper_intents: dict[str, RetrievalIntent] = {}
        paper_retrieval_ids: dict[str, str] = {}
        primary_manifest: RetrievalManifest | None = None
        for subquestion, retrieval_request in specs:
            intent = subquestion.retrieval_intent
            literature_result = await self.search_literature(
                _literature_request_from_search_request(
                    retrieval_request,
                    retrieval_intent=intent,
                    project_id=request.project_id,
                    require_abstract=True,
                )
            )
            search_items = [
                _paper_metadata_from_literature_record(item)
                for item in literature_result.items
            ]
            manifest = literature_result.retrieval_manifest
            if primary_manifest is None:
                primary_manifest = manifest
            returned_ids = [item.paper_id for item in search_items]
            records.append(
                RetrievalBundleRecord(
                    intent=intent,
                    query=retrieval_request.query,
                    query_id=subquestion.subquestion_id,
                    subquestion_id=subquestion.subquestion_id,
                    reason=subquestion.reason,
                    pass_index=1,
                    retrieval_id=manifest.retrieval_id,
                    manifest=manifest,
                    returned_paper_ids=returned_ids,
                    coverage=literature_result.coverage,
                    warnings=literature_result.warnings,
                    errors=literature_result.errors,
                )
            )
            for item in search_items:
                if item.paper_id in seen_paper_ids:
                    duplicate_paper_ids.append(item.paper_id)
                    continue
                seen_paper_ids.add(item.paper_id)
                unique_items.append(item)
                paper_intents[item.paper_id] = intent
                paper_retrieval_ids[item.paper_id] = manifest.retrieval_id

        if primary_manifest is None:
            primary_result = await self.search_with_manifest(search_request)
            primary_manifest = primary_result.retrieval_manifest
            unique_items = primary_result.items
            paper_intents = {item.paper_id: "primary" for item in primary_result.items}
            paper_retrieval_ids = {
                item.paper_id: primary_manifest.retrieval_id
                for item in primary_result.items
            }

        bundle = RetrievalBundle(
            bundle_id=f"{run_id}-retrieval-bundle",
            source=search_request.source,
            executed_multi_query=len(records) > 1,
            records=records,
            deduped_paper_ids=[item.paper_id for item in unique_items],
            duplicate_paper_ids=duplicate_paper_ids,
            subquestions=[subquestion for subquestion, _ in specs],
            stop_reason="first_pass_complete",
            warnings=bundle_warnings,
        )
        return (
            unique_items,
            primary_manifest,
            bundle,
            paper_intents,
            paper_retrieval_ids,
        )

    async def _apply_gap_directed_retrieval(
        self,
        *,
        request: AnswerWithEvidenceRequest,
        planning_result: PlanBiomedicalSearchResult | None,
        metadata: list[PaperMetadata],
        retrieval_bundle: RetrievalBundle,
        paper_intents: dict[str, RetrievalIntent],
        paper_retrieval_ids: dict[str, str],
        papers: dict[str, BiomedicalPaper],
        evidence: list[EvidenceItem],
        project: BiomedProject | None,
    ) -> tuple[
        list[PaperMetadata],
        RetrievalBundle,
        dict[str, RetrievalIntent],
        dict[str, str],
        dict[str, BiomedicalPaper],
        list[EvidenceItem],
    ]:
        coverage = _build_coverage_matrix(retrieval_bundle, evidence)
        if (
            not request.execute_support_refute
            or planning_result is None
            or planning_result.query_plan is None
        ):
            return (
                metadata,
                retrieval_bundle.model_copy(
                    update={
                        "coverage_matrix": coverage,
                        "stop_reason": "multi_pass_not_requested",
                    }
                ),
                paper_intents,
                paper_retrieval_ids,
                papers,
                evidence,
            )

        decisions = _gap_search_decisions(
            coverage,
            query_plan=planning_result.query_plan,
            existing_queries={record.query.lower() for record in retrieval_bundle.records},
            max_decisions=2,
        )
        if not decisions:
            return (
                metadata,
                retrieval_bundle.model_copy(
                    update={
                        "coverage_matrix": coverage,
                        "gap_decisions": [],
                        "stop_reason": _coverage_stop_reason(coverage),
                    }
                ),
                paper_intents,
                paper_retrieval_ids,
                papers,
                evidence,
            )

        records = list(retrieval_bundle.records)
        duplicate_paper_ids = list(retrieval_bundle.duplicate_paper_ids)
        seen_paper_ids = {item.paper_id for item in metadata}
        rejected_ids: set[str] = set()
        if project is not None and not request.include_rejected_papers:
            project_decisions = self.storage.get_project_paper_decision_map(
                project.project_id,
                source=request.source,
            )
            rejected_ids = {
                paper_id
                for paper_id, decision in project_decisions.items()
                if decision.decision == "rejected"
            }

        updated_decisions: list[GapSearchDecision] = []
        warnings = list(retrieval_bundle.warnings)
        for decision in decisions:
            try:
                literature_result = await self.search_literature(
                    LiteratureSearchRequest(
                        query=decision.followup_query,
                        max_results=max(1, min(request.max_papers, 3)),
                        date_from=planning_result.query_plan.date_from,
                        date_to=planning_result.query_plan.date_to,
                        source=request.source,
                        mesh_terms=planning_result.query_plan.mesh_terms,
                        publication_types=planning_result.query_plan.publication_types,
                        study_types=planning_result.query_plan.study_types,
                        species_terms=planning_result.query_plan.species_terms,
                        exclude_terms=planning_result.query_plan.exclude_terms,
                        retrieval_intent=decision.retrieval_intent,
                        project_id=request.project_id,
                        require_abstract=True,
                        store=True,
                    )
                )
            except LiteratureClientError as exc:
                updated_decisions.append(
                    decision.model_copy(
                        update={
                            "executed": False,
                            "stop_reason": f"follow-up retrieval failed: {exc}",
                        }
                    )
                )
                warnings.append(f"Gap follow-up failed: {exc}")
                continue

            manifest = literature_result.retrieval_manifest
            returned_ids = [item.paper_id for item in literature_result.items]
            added_ids: list[str] = []
            for record in literature_result.items:
                item = _paper_metadata_from_literature_record(record)
                if item.paper_id in rejected_ids:
                    warnings.append(
                        "Project memory excluded a rejected paper from gap follow-up."
                    )
                    continue
                if item.paper_id in seen_paper_ids:
                    duplicate_paper_ids.append(item.paper_id)
                    continue
                seen_paper_ids.add(item.paper_id)
                metadata.append(item)
                added_ids.append(item.paper_id)
                paper_intents[item.paper_id] = decision.retrieval_intent
                paper_retrieval_ids[item.paper_id] = manifest.retrieval_id
                paper = await self.fetch(
                    FetchBiomedicalPaperRequest(
                        paper_id=item.paper_id,
                        source=request.source,
                    )
                )
                if paper is None:
                    continue
                papers[paper.paper_id] = paper
                extracted = await self._extract_evidence_for_answer(
                    request=request,
                    paper=paper,
                    retrieval_id=manifest.retrieval_id,
                    retrieval_intent=decision.retrieval_intent,
                )
                evidence.extend(extracted.evidence)
            records.append(
                RetrievalBundleRecord(
                    intent=decision.retrieval_intent,
                    query=decision.followup_query,
                    query_id=decision.gap_id,
                    subquestion_id=decision.subquestion_id,
                    reason=decision.reason,
                    pass_index=2,
                    retrieval_id=manifest.retrieval_id,
                    manifest=manifest,
                    returned_paper_ids=returned_ids,
                    added_paper_ids=added_ids,
                    coverage=literature_result.coverage,
                    warnings=literature_result.warnings,
                    errors=literature_result.errors,
                )
            )
            updated_decisions.append(
                decision.model_copy(
                    update={
                        "executed": True,
                        "retrieval_id": manifest.retrieval_id,
                        "returned_paper_ids": returned_ids,
                        "added_paper_ids": added_ids,
                        "stop_reason": (
                            "added_new_papers"
                            if added_ids
                            else "no_new_unique_papers"
                        ),
                    }
                )
            )

        updated_bundle = retrieval_bundle.model_copy(
            update={
                "records": records,
                "deduped_paper_ids": [item.paper_id for item in metadata],
                "duplicate_paper_ids": _merge_unique(duplicate_paper_ids),
                "coverage_matrix": _build_coverage_matrix(
                    retrieval_bundle.model_copy(update={"records": records}),
                    evidence,
                ),
                "gap_decisions": updated_decisions,
                "stop_reason": "gap_followup_complete",
                "warnings": _merge_unique(warnings),
            }
        )
        return (
            metadata,
            updated_bundle,
            paper_intents,
            paper_retrieval_ids,
            papers,
            evidence,
        )

    def _apply_project_memory_to_retrieval(
        self,
        *,
        project: BiomedProject,
        request: AnswerWithEvidenceRequest,
        metadata: list[PaperMetadata],
        retrieval_manifest: RetrievalManifest,
        retrieval_bundle: RetrievalBundle | None,
    ) -> tuple[
        list[PaperMetadata],
        RetrievalManifest,
        RetrievalBundle | None,
        dict[str, object],
    ]:
        decisions = self.storage.get_project_paper_decision_map(
            project.project_id,
            source=request.source,
        )
        original_ids = [item.paper_id for item in metadata]
        original_position = {
            paper_id: index for index, paper_id in enumerate(original_ids)
        }
        rejected_ids = [
            paper_id
            for paper_id in original_ids
            if decisions.get(paper_id) is not None
            and decisions[paper_id].decision == "rejected"
        ]
        saved_ids = [
            paper_id
            for paper_id in original_ids
            if decisions.get(paper_id) is not None
            and decisions[paper_id].decision == "saved"
        ]
        needs_review_ids = [
            paper_id
            for paper_id in original_ids
            if decisions.get(paper_id) is not None
            and decisions[paper_id].decision == "needs_review"
        ]
        if request.include_rejected_papers:
            filtered = list(metadata)
            dropped_rejected_ids: list[str] = []
        else:
            filtered = [
                item
                for item in metadata
                if decisions.get(item.paper_id) is None
                or decisions[item.paper_id].decision != "rejected"
            ]
            dropped_rejected_ids = rejected_ids

        def priority(item: PaperMetadata) -> tuple[int, int]:
            decision = decisions.get(item.paper_id)
            if decision is not None and decision.decision == "saved":
                bucket = 0
            elif decision is not None and decision.decision == "needs_review":
                bucket = 1
            elif decision is not None and decision.decision == "rejected":
                bucket = 3
            else:
                bucket = 2
            return bucket, original_position.get(item.paper_id, 9999)

        sorted_metadata = sorted(filtered, key=priority)
        returned_ids = [item.paper_id for item in sorted_metadata]
        warnings = list(retrieval_manifest.warnings)
        if dropped_rejected_ids:
            warnings.append(
                "Project memory excluded rejected papers from evidence extraction."
            )
        if saved_ids:
            warnings.append("Project memory prioritized saved papers.")
        updated_manifest = retrieval_manifest.model_copy(
            update={
                "returned_paper_ids": returned_ids,
                "deduped_result_count": len(returned_ids),
                "dropped_or_duplicate_ids": _merge_unique(
                    retrieval_manifest.dropped_or_duplicate_ids,
                    dropped_rejected_ids,
                ),
                "warnings": _merge_unique(warnings),
            }
        )
        updated_bundle = retrieval_bundle
        if retrieval_bundle is not None:
            updated_bundle = retrieval_bundle.model_copy(
                update={
                    "deduped_paper_ids": returned_ids,
                    "warnings": _merge_unique(
                        retrieval_bundle.warnings,
                        (
                            ["Project paper decisions were applied after retrieval."]
                            if decisions
                            else []
                        ),
                    ),
                }
            )
        trace: dict[str, object] = {
            "project_filter_applied": bool(decisions),
            "original_paper_ids": original_ids,
            "returned_paper_ids": returned_ids,
            "saved_paper_ids": saved_ids,
            "needs_review_paper_ids": needs_review_ids,
            "rejected_paper_ids": rejected_ids,
            "dropped_rejected_paper_ids": dropped_rejected_ids,
            "include_rejected_papers": request.include_rejected_papers,
        }
        return sorted_metadata, updated_manifest, updated_bundle, trace

    def _release_project_memory_trace(
        self,
        *,
        project_id: str | None,
        request_context: str | None,
    ) -> tuple[dict[str, object], BiomedProject | None]:
        trace: dict[str, object] = {
            "memory_used": False,
            "memory_sources": [],
            "memory_effects": [],
            "memory_as_evidence": False,
            "clinical_boundary_before_memory": True,
        }
        if not project_id:
            return trace, None
        project = self.storage.get_project(project_id)
        if project is None:
            trace.update({"project_id": project_id, "project_found": False})
            return trace, None
        effects: list[str] = []
        if project.include_keywords:
            effects.append("added_include_keyword_preferences")
        if project.exclude_keywords:
            effects.append("added_excluded_term_preferences")
        if project.preferred_methods:
            effects.append("added_preferred_method_filter")
        if request_context:
            effects.append("merged_request_project_context")
        trace.update(
            {
                "project_id": project.project_id,
                "project_found": True,
                "memory_used": True,
                "memory_sources": [f"biomed_project:{project.project_id}"],
                "memory_effects": effects,
                "include_keywords": project.include_keywords,
                "exclude_keywords": project.exclude_keywords,
                "preferred_methods": project.preferred_methods,
                "preferred_species": project.preferred_species,
                "preferred_study_types": project.preferred_study_types,
            }
        )
        return trace, project

    async def answer_with_audit(
        self,
        request: AnswerWithEvidenceRequest,
    ) -> AuditedAnswerResult:
        draft_result = await self.answer_with_evidence(request)
        clinical_boundary = is_clinical_request(request.question) or bool(
            draft_result.question_classification
            and draft_result.question_classification.clinical_boundary
        )
        audit = await self._audit_answer_with_optional_logic(
            CitationAuditRequest(
                answer=draft_result.answer,
                citations=draft_result.citations,
                evidence_items=draft_result.evidence_summary,
                run_id=draft_result.run_id,
                retrieval_id=draft_result.retrieval_id,
                observed_uncertainty=draft_result.uncertainty_level,
                retrieval_manifest=draft_result.retrieval_manifest,
                use_llm_claim_logic=request.use_llm_claim_logic,
                export_logic_facts=request.export_logic_facts,
            ),
            clinical_boundary=clinical_boundary,
        )
        advisory_verifier = await self._llm_advisory_verifier_or_fallback(
            request=request,
            draft_result=draft_result,
            audit=audit,
            clinical_boundary=clinical_boundary,
        )
        revision = await self._llm_revision_or_none(
            request=request,
            draft_result=draft_result,
            audit=audit,
            clinical_boundary=clinical_boundary,
            advisory_verifier=advisory_verifier,
        )
        if revision is None:
            revision = _build_answer_revision(
                draft_result=draft_result,
                audit=audit,
                clinical_boundary=clinical_boundary,
                use_llm_revision=request.use_llm_revision,
                advisory_verifier=advisory_verifier,
                fallback_reason_override=(
                    None
                    if not request.use_llm_revision
                    else _llm_unavailable_reason(
                        self.revision_provider, self.revision_model
                    )
                ),
            )
        final_result = draft_result.model_copy(
            update={
                "answer": revision.final_answer,
                "limitations": _merge_unique(
                    draft_result.limitations,
                    revision.added_limitations,
                ),
                "uncertainty_level": _revised_uncertainty(
                    draft_result.uncertainty_level,
                    audit,
                    revision,
                ),
            }
        )
        trace = _build_trace_steps(
            request=request,
            result=final_result,
            audit=audit,
            advisory_verifier=advisory_verifier,
            revision=revision,
            clinical_boundary=clinical_boundary,
        )
        if final_result.project_id:
            self._record_project_review_queue(
                project_id=final_result.project_id,
                result=final_result,
                audit=audit,
                advisory_verifier=advisory_verifier,
            )
        if advisory_verifier is not None:
            self.storage.save_advisory_verifier(advisory_verifier)
        self.storage.save_answer_revision(revision)
        self.storage.save_agent_trace_steps(trace)
        self.storage.save_answer_run(final_result, question=request.question)
        return AuditedAnswerResult(
            answer_result=final_result,
            draft_answer=revision.draft_answer,
            final_answer=revision.final_answer,
            audit=audit,
            advisory_verifier=advisory_verifier,
            revision=revision,
            trace=trace,
            final_action=revision.revision_action,
        )

    async def _audit_answer_with_optional_logic(
        self,
        request: CitationAuditRequest,
        *,
        clinical_boundary: bool,
    ) -> CitationAuditResult:
        use_claim_logic = request.use_llm_claim_logic and not clinical_boundary
        export_logic_facts = request.export_logic_facts and not clinical_boundary
        active_request = request.model_copy(
            update={
                "use_llm_claim_logic": use_claim_logic,
                "export_logic_facts": export_logic_facts,
            }
        )
        if not use_claim_logic:
            return self.audit_answer(active_request)
        logic_outcome = await self._llm_claim_logic_frames_or_fallback(
            answer=active_request.answer,
            citations=active_request.citations,
            evidence_items=active_request.evidence_items,
        )
        return self.audit_answer(
            active_request,
            logic_claim_frames=(
                logic_outcome.claim_frames if logic_outcome.claim_frames else None
            ),
            logic_evidence_frames=(
                logic_outcome.evidence_frames if logic_outcome.evidence_frames else None
            ),
            logic_parser_fallback_reason=logic_outcome.fallback_reason,
        )

    async def _llm_claim_logic_frames_or_fallback(
        self,
        *,
        answer: str,
        citations: list[Citation],
        evidence_items: list[EvidenceItem],
    ) -> _LogicParserOutcome:
        claims = extract_atomic_claims(answer)
        if not claims or not evidence_items:
            return _LogicParserOutcome(
                claim_frames={},
                evidence_frames={},
                prompt_hash=None,
                model=None,
                fallback_reason=(
                    "LLM claim logic parser skipped because no atomic claims or "
                    "evidence items were available."
                ),
            )
        if self.revision_provider is None or not self.revision_model:
            return _LogicParserOutcome(
                claim_frames={},
                evidence_frames={},
                prompt_hash=None,
                model=None,
                fallback_reason=_llm_claim_logic_unavailable_reason(
                    self.revision_provider,
                    self.revision_model,
                ),
            )
        prompt_payload = _llm_claim_logic_payload(
            claims=claims,
            citations=citations,
            evidence_items=evidence_items,
        )
        prompt_text = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
        try:
            response = await self.revision_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Parse biomedical answer claims and evidence spans into "
                            "logical frames. Return one valid JSON object only. Use "
                            "only the supplied claims and evidence items. Do not decide "
                            "the final audit verdict."
                        ),
                    },
                    {"role": "user", "content": prompt_text},
                ],
                tools=[],
                model=self.revision_model,
                max_tokens=4200,
                tool_choice="none",
                disable_thinking=True,
            )
            parsed = _parse_json_object(str(getattr(response, "content", "") or ""))
            claim_frames = _logic_claim_frames_from_llm(
                parsed.get("claim_frames"),
                claims=claims,
                model=self.revision_model,
                prompt_hash=prompt_hash,
            )
            evidence_frames = _logic_evidence_frames_from_llm(
                parsed.get("evidence_frames"),
                evidence_items=evidence_items,
                model=self.revision_model,
                prompt_hash=prompt_hash,
            )
            if set(claim_frames) != {claim.claim_id for claim in claims}:
                raise ValueError("LLM claim logic parser returned incomplete claims.")
            if set(evidence_frames) != {item.evidence_id for item in evidence_items}:
                raise ValueError("LLM claim logic parser returned incomplete evidence.")
            return _LogicParserOutcome(
                claim_frames=claim_frames,
                evidence_frames=evidence_frames,
                prompt_hash=prompt_hash,
                model=self.revision_model,
            )
        except Exception as exc:
            return _LogicParserOutcome(
                claim_frames={},
                evidence_frames={},
                prompt_hash=prompt_hash,
                model=self.revision_model,
                fallback_reason=(
                    "LLM claim logic parser failed schema validation or parsing; "
                    f"deterministic fallback used. {type(exc).__name__}: {exc}"
                ),
            )

    def _record_project_review_queue(
        self,
        *,
        project_id: str,
        result: AnswerWithEvidenceResult,
        audit: CitationAuditResult,
        advisory_verifier: AdvisoryVerifierResult | None,
    ) -> None:
        if self.storage.get_project(project_id) is None:
            return
        now = _now_iso()
        for claim_audit in audit.failed_claims:
            risk: ConfidenceLevel = (
                "high"
                if claim_audit.verdict in {"overclaimed", "contradicted"}
                else "medium"
            )
            self.storage.upsert_project_review_item(
                ProjectReviewQueueItem(
                    item_id=f"biomed-proj-review-{uuid.uuid4().hex[:12]}",
                    project_id=project_id,
                    item_type="claim_audit_failure",
                    title=claim_audit.claim,
                    reason=claim_audit.reason,
                    risk_level=risk,
                    run_id=result.run_id,
                    evidence_id=(
                        claim_audit.evidence_ids[0]
                        if claim_audit.evidence_ids
                        else None
                    ),
                    audit_id=audit.audit_id,
                    verifier_id=(
                        advisory_verifier.verifier_id
                        if advisory_verifier is not None
                        else None
                    ),
                    created_at=now,
                )
            )
        for evidence in result.conflicting_evidence:
            self.storage.upsert_project_review_item(
                ProjectReviewQueueItem(
                    item_id=f"biomed-proj-review-{uuid.uuid4().hex[:12]}",
                    project_id=project_id,
                    item_type="conflicting_evidence",
                    title=evidence.claim,
                    reason=evidence.finding,
                    risk_level="high",
                    run_id=result.run_id,
                    evidence_id=evidence.evidence_id,
                    audit_id=audit.audit_id,
                    verifier_id=(
                        advisory_verifier.verifier_id
                        if advisory_verifier is not None
                        else None
                    ),
                    created_at=now,
                )
            )
        if advisory_verifier is None:
            return
        for disagreement in advisory_verifier.disagreements:
            if not disagreement.high_risk:
                continue
            self.storage.upsert_project_review_item(
                ProjectReviewQueueItem(
                    item_id=f"biomed-proj-review-{uuid.uuid4().hex[:12]}",
                    project_id=project_id,
                    item_type="advisory_disagreement",
                    title=disagreement.claim,
                    reason=disagreement.reason,
                    risk_level=disagreement.risk_level,
                    run_id=result.run_id,
                    evidence_id=None,
                    audit_id=audit.audit_id,
                    verifier_id=advisory_verifier.verifier_id,
                    created_at=now,
                )
            )

    async def _llm_advisory_verifier_or_fallback(
        self,
        *,
        request: AnswerWithEvidenceRequest,
        draft_result: AnswerWithEvidenceResult,
        audit: CitationAuditResult,
        clinical_boundary: bool,
    ) -> AdvisoryVerifierResult | None:
        if not request.use_llm_verifier or clinical_boundary:
            return None
        if self.revision_provider is None or not self.revision_model:
            return _fallback_advisory_verifier(
                draft_result=draft_result,
                audit=audit,
                provider=self.revision_provider,
                model=self.revision_model,
            )
        prompt_payload = _llm_advisory_verifier_payload(
            request=request,
            draft_result=draft_result,
            audit=audit,
        )
        prompt_text = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
        try:
            response = await self.revision_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an advisory biomedical claim verifier. "
                            "Return one valid JSON object only. You may flag risks "
                            "or disagreement with the deterministic audit, but you "
                            "must not override deterministic audit failures. Use only "
                            "the supplied answer, citations, evidence items, and audit."
                        ),
                    },
                    {"role": "user", "content": prompt_text},
                ],
                tools=[],
                model=self.revision_model,
                max_tokens=2200,
                tool_choice="none",
                disable_thinking=True,
            )
            parsed = _parse_json_object(str(getattr(response, "content", "") or ""))
            return _advisory_verifier_from_llm(
                parsed,
                draft_result=draft_result,
                audit=audit,
                model=self.revision_model,
                prompt_hash=prompt_hash,
            )
        except Exception:
            return _fallback_advisory_verifier(
                draft_result=draft_result,
                audit=audit,
                provider=self.revision_provider,
                model=self.revision_model,
                prompt_hash=prompt_hash,
                fallback_reason=(
                    "LLM verifier was requested, but the advisory verifier adapter "
                    "fell back to deterministic audit only."
                ),
            )

    async def _llm_revision_or_none(
        self,
        *,
        request: AnswerWithEvidenceRequest,
        draft_result: AnswerWithEvidenceResult,
        audit: CitationAuditResult,
        clinical_boundary: bool,
        advisory_verifier: AdvisoryVerifierResult | None = None,
    ) -> AnswerRevision | None:
        if (
            not request.use_llm_revision
            or clinical_boundary
            or self.revision_provider is None
            or not self.revision_model
        ):
            return None
        prompt_payload = _llm_revision_payload(
            request=request,
            draft_result=draft_result,
            audit=audit,
            advisory_verifier=advisory_verifier,
        )
        prompt_text = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
        try:
            response = await self.revision_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You revise biomedical research answers using only supplied "
                            "evidence and citations. Return one valid JSON object only. "
                            "Every sentence in final_answer that states biomedical "
                            "evidence, uncertainty, limitations, comparisons, or "
                            "recommendations must include at least one supplied citation "
                            "label. Use bracketed paper-id labels such as "
                            "[MOCK-PMID-1001], not bare parenthetical identifiers. The "
                            "research-use disclaimer may remain uncited. Do not add "
                            "future-work, expert-review, or causality caveats unless "
                            "they are directly grounded in supplied evidence and cited. "
                            "If you cannot produce a fully cited answer, copy draft_answer."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt_text,
                    },
                ],
                tools=[],
                model=self.revision_model,
                max_tokens=3000,
                tool_choice="none",
                disable_thinking=True,
            )
            raw = str(getattr(response, "content", "") or "")
            parsed = _parse_json_object(raw)
            final_answer = _normalize_llm_answer_text(
                str(parsed.get("final_answer") or "")
            )
            if not final_answer:
                return None
            parsed["final_answer"] = final_answer
            post_audit = await self._audit_answer_with_optional_logic(
                CitationAuditRequest(
                    answer=final_answer,
                    citations=draft_result.citations,
                    evidence_items=draft_result.evidence_summary,
                    run_id=draft_result.run_id,
                    retrieval_id=draft_result.retrieval_id,
                    observed_uncertainty=cast(
                        ConfidenceLevel | None, parsed.get("uncertainty_level")
                    ),
                    retrieval_manifest=draft_result.retrieval_manifest,
                    use_llm_claim_logic=request.use_llm_claim_logic,
                    export_logic_facts=request.export_logic_facts,
                ),
                clinical_boundary=clinical_boundary,
            )
            repair_changed_claims: list[str] = []
            repair_removed_claims: list[str] = []
            repair_added_limitations: list[str] = []
            if post_audit.recommended_action in {"revise", "refuse_or_abstain"}:
                repaired_answer, removed_claims = _remove_failed_claim_lines(
                    final_answer,
                    post_audit.failed_claims,
                )
                if not repaired_answer or repaired_answer == final_answer:
                    return None
                repaired_audit = await self._audit_answer_with_optional_logic(
                    CitationAuditRequest(
                        answer=repaired_answer,
                        citations=draft_result.citations,
                        evidence_items=draft_result.evidence_summary,
                        run_id=draft_result.run_id,
                        retrieval_id=draft_result.retrieval_id,
                        observed_uncertainty=cast(
                            ConfidenceLevel | None,
                            parsed.get("uncertainty_level"),
                        ),
                        retrieval_manifest=draft_result.retrieval_manifest,
                        use_llm_claim_logic=request.use_llm_claim_logic,
                        export_logic_facts=request.export_logic_facts,
                    ),
                    clinical_boundary=clinical_boundary,
                )
                if repaired_audit.recommended_action in {"revise", "refuse_or_abstain"}:
                    return None
                final_answer = repaired_answer
                post_audit = repaired_audit
                repair_changed_claims = removed_claims
                repair_removed_claims = removed_claims
                repair_added_limitations = [
                    "Removed unsupported or overclaimed LLM-generated lines during post-audit repair."
                ]
            now = _now_iso()
            final_action = "pass" if final_answer == draft_result.answer else "revise"
            return AnswerRevision(
                revision_id=_revision_id(draft_result.run_id, audit.audit_id),
                run_id=draft_result.run_id,
                audit_id=audit.audit_id,
                post_revision_audit_id=post_audit.audit_id,
                revision_mode="llm",
                llm_model=self.revision_model,
                llm_prompt_hash=prompt_hash,
                llm_raw_response=parsed,
                draft_answer=draft_result.answer,
                final_answer=final_answer,
                changed_claims=_merge_unique(
                    _coerce_string_list(parsed.get("changed_claims")),
                    repair_changed_claims,
                ),
                removed_claims=_merge_unique(
                    _coerce_string_list(parsed.get("removed_claims")),
                    repair_removed_claims,
                ),
                softened_claims=_merge_unique(
                    _coerce_string_list(parsed.get("softened_claims")),
                ),
                added_limitations=_merge_unique(
                    _coerce_string_list(parsed.get("added_limitations")),
                    repair_added_limitations,
                ),
                revision_action=cast(Any, final_action),
                created_at=now,
            )
        except Exception:
            return None

    async def _llm_synthesis_or_fallback(
        self,
        *,
        request: AnswerWithEvidenceRequest,
        deterministic_answer: str,
        citations: list[Citation],
        evidence: list[EvidenceItem],
        papers: dict[str, BiomedicalPaper],
        retrieval_manifest: RetrievalManifest,
        retrieval_bundle: RetrievalBundle | None,
        evidence_packet: EvidencePacketSummary | None,
        uncertainty: ConfidenceLevel,
        run_id: str,
    ) -> _SynthesisOutcome:
        if self.revision_provider is None or not self.revision_model:
            return _SynthesisOutcome(
                answer=deterministic_answer,
                mode="fallback",
                model=None,
                prompt_hash=None,
                fallback_reason=_llm_synthesis_unavailable_reason(
                    self.revision_provider,
                    self.revision_model,
                ),
            )
        prompt_payload = _llm_synthesis_payload(
            request=request,
            evidence=evidence,
            citations=citations,
            papers=papers,
            retrieval_manifest=retrieval_manifest,
            retrieval_bundle=retrieval_bundle,
            evidence_packet=evidence_packet,
            uncertainty=uncertainty,
        )
        prompt_text = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
        try:
            response = await self.revision_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Synthesize a biomedical research answer using only supplied "
                            "evidence items and citations. Return one valid JSON object "
                            "only with final_answer. Every biomedical claim, limitation, "
                            "uncertainty statement, comparison, or interpretation must "
                            "include at least one supplied bracket citation such as "
                            "[MOCK-PMID-1001]. Do not add clinical advice or uncited "
                            "future-work claims."
                        ),
                    },
                    {"role": "user", "content": prompt_text},
                ],
                tools=[],
                model=self.revision_model,
                max_tokens=2600,
                tool_choice="none",
                disable_thinking=True,
            )
            parsed = _parse_json_object(str(getattr(response, "content", "") or ""))
            final_answer = _normalize_llm_answer_text(
                str(parsed.get("final_answer") or "")
            )
            if not final_answer:
                raise ValueError("LLM synthesis returned empty final_answer.")
            synthesis_audit = self.audit_answer(
                CitationAuditRequest(
                    answer=final_answer,
                    citations=citations,
                    evidence_items=evidence,
                    run_id=run_id,
                    retrieval_id=retrieval_manifest.retrieval_id,
                    observed_uncertainty=cast(
                        ConfidenceLevel | None,
                        parsed.get("uncertainty_level") or uncertainty,
                    ),
                    retrieval_manifest=retrieval_manifest,
                    use_llm_claim_logic=False,
                    export_logic_facts=False,
                )
            )
            if synthesis_audit.recommended_action in {"revise", "refuse_or_abstain"}:
                return _SynthesisOutcome(
                    answer=deterministic_answer,
                    mode="fallback",
                    model=self.revision_model,
                    prompt_hash=prompt_hash,
                    fallback_reason=(
                        "LLM synthesis failed deterministic citation audit and was "
                        "not accepted."
                    ),
                )
            return _SynthesisOutcome(
                answer=final_answer,
                mode="llm",
                model=self.revision_model,
                prompt_hash=prompt_hash,
            )
        except Exception:
            return _SynthesisOutcome(
                answer=deterministic_answer,
                mode="fallback",
                model=self.revision_model,
                prompt_hash=prompt_hash,
                fallback_reason="LLM synthesis was requested, but the adapter fell back to deterministic synthesis.",
            )

    def list_evidence(
        self,
        *,
        q: str = "",
        paper_id: str = "",
        direction: str = "",
        entity: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, object]], int]:
        return self.storage.list_evidence(
            q=q,
            paper_id=paper_id,
            direction=direction,
            entity=entity,
            page=page,
            page_size=page_size,
        )

    def get_graph(
        self,
        *,
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
    ) -> EvidenceGraph:
        rows, _ = self.storage.list_evidence(
            q=topic,
            paper_id=paper_id,
            direction=direction,
            entity=entity,
            page=1,
            page_size=200,
        )
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        topic_id = ""
        if topic.strip():
            topic_id = f"topic:{_slug(topic)}"
            nodes[topic_id] = GraphNode(id=topic_id, label=topic.strip(), kind="topic")
        for row in rows:
            paper_node = f"paper:{row['paper_id']}"
            nodes.setdefault(
                paper_node,
                GraphNode(
                    id=paper_node,
                    label=str(row.get("paper_title") or row["paper_id"]),
                    kind="paper",
                    data={
                        "paper_id": str(row["paper_id"]),
                        "url": row.get("paper_url"),
                    },
                ),
            )
            claim_node = f"claim:{row['evidence_id']}"
            nodes[claim_node] = GraphNode(
                id=claim_node,
                label=str(row["claim"]),
                kind="claim",
                data={
                    "direction": str(row["evidence_direction"]),
                    "confidence": str(row["confidence"]),
                },
            )
            edges.append(
                GraphEdge(
                    source=paper_node, target=claim_node, type="PAPER_REPORTS_CLAIM"
                )
            )
            if topic_id:
                edge_type = (
                    "CLAIM_CONTRADICTS_TOPIC"
                    if row["evidence_direction"] == "contradicts"
                    else "CLAIM_SUPPORTS_TOPIC"
                )
                edges.append(
                    GraphEdge(source=claim_node, target=topic_id, type=edge_type)
                )
            for raw_entity in cast(list[object], row.get("entities", [])):
                if not isinstance(raw_entity, dict):
                    continue
                label = str(raw_entity.get("name") or "")
                if not label:
                    continue
                entity_node = f"entity:{_slug(label)}"
                nodes.setdefault(
                    entity_node,
                    GraphNode(
                        id=entity_node,
                        label=label,
                        kind="entity",
                        data={"entity_type": str(raw_entity.get("entity_type") or "")},
                    ),
                )
                edges.append(
                    GraphEdge(
                        source=claim_node,
                        target=entity_node,
                        type="CLAIM_MENTIONS_ENTITY",
                    )
                )
            for method in cast(list[object], row.get("methods", [])):
                method_node = f"method:{_slug(str(method))}"
                nodes.setdefault(
                    method_node,
                    GraphNode(id=method_node, label=str(method), kind="method"),
                )
                edges.append(
                    GraphEdge(
                        source=claim_node, target=method_node, type="CLAIM_USES_METHOD"
                    )
                )
            for dataset in cast(list[object], row.get("datasets_or_cohorts", [])):
                dataset_node = f"dataset:{_slug(str(dataset))}"
                nodes.setdefault(
                    dataset_node,
                    GraphNode(id=dataset_node, label=str(dataset), kind="dataset"),
                )
                edges.append(
                    GraphEdge(
                        source=claim_node,
                        target=dataset_node,
                        type="CLAIM_BASED_ON_DATASET",
                    )
                )
            for limitation in cast(list[object], row.get("limitations", [])):
                limitation_node = f"limitation:{_slug(str(limitation))}"
                nodes.setdefault(
                    limitation_node,
                    GraphNode(
                        id=limitation_node, label=str(limitation), kind="limitation"
                    ),
                )
                edges.append(
                    GraphEdge(
                        source=claim_node,
                        target=limitation_node,
                        type="CLAIM_HAS_LIMITATION",
                    )
                )
        return EvidenceGraph(nodes=list(nodes.values()), edges=edges)

    def get_graph_v1(
        self,
        *,
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
        run_id: str = "",
        validate: bool = False,
    ) -> BiomedEvidenceGraph | None:
        clean_run_id = run_id.strip()
        if clean_run_id:
            run = self.storage.get_answer_run(clean_run_id)
            if run is None:
                return None
            graph = build_run_graph(
                run,
                audit=self.storage.get_latest_citation_audit_for_run(clean_run_id),
                scope=GraphScope(
                    kind="run",
                    identifiers={"run_id": clean_run_id},
                    filters={"validate": validate},
                ),
            )
            return _with_graph_validation(graph, validate=validate)

        rows, _ = self.storage.list_evidence(
            q=topic,
            paper_id=paper_id,
            direction=direction,
            entity=entity,
            page=1,
            page_size=200,
        )
        retrieval_manifests: list[RetrievalManifest] = []
        seen_retrieval_ids: set[str] = set()
        for row in rows:
            retrieval_id = str(row.get("retrieval_id") or "").strip()
            if not retrieval_id or retrieval_id in seen_retrieval_ids:
                continue
            seen_retrieval_ids.add(retrieval_id)
            manifest = self.storage.get_retrieval_manifest(retrieval_id)
            if manifest is not None:
                retrieval_manifests.append(manifest)
        scope_kind = _graph_scope_kind(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
        )
        graph = build_graph_from_evidence(
            rows,
            retrieval_manifests=retrieval_manifests,
            scope=GraphScope(
                kind=scope_kind,
                identifiers={
                    key: value
                    for key, value in {
                        "paper_id": paper_id.strip(),
                    }.items()
                    if value
                },
                filters={
                    key: value
                    for key, value in {
                        "topic": topic.strip(),
                        "entity": entity.strip(),
                        "paper_id": paper_id.strip(),
                        "direction": direction.strip(),
                        "validate": validate,
                    }.items()
                    if value not in {"", False}
                },
            ),
        )
        return _with_graph_validation(graph, validate=validate)

    def create_watch(self, request: WatchTopicCreateRequest) -> WatchTopic:
        now = _now_iso()
        watch = WatchTopic(
            watch_id=f"watch-{uuid.uuid4().hex[:12]}",
            topic=request.topic,
            description=request.description,
            include_keywords=request.include_keywords,
            exclude_keywords=request.exclude_keywords,
            preferred_methods=request.preferred_methods,
            min_relevance_score=max(0.0, min(1.0, request.min_relevance_score)),
            schedule=request.schedule,
            enabled=True,
            created_at=now,
            updated_at=now,
            next_check_at=_next_check(now, request.schedule),
        )
        return self.storage.create_watch(watch)

    def update_watch(
        self,
        watch_id: str,
        request: WatchTopicUpdateRequest,
    ) -> WatchTopic | None:
        current = self.storage.get_watch(watch_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={
                "topic": request.topic if request.topic is not None else current.topic,
                "description": (
                    request.description
                    if request.description is not None
                    else current.description
                ),
                "include_keywords": (
                    request.include_keywords
                    if request.include_keywords is not None
                    else current.include_keywords
                ),
                "exclude_keywords": (
                    request.exclude_keywords
                    if request.exclude_keywords is not None
                    else current.exclude_keywords
                ),
                "preferred_methods": (
                    request.preferred_methods
                    if request.preferred_methods is not None
                    else current.preferred_methods
                ),
                "min_relevance_score": (
                    max(0.0, min(1.0, request.min_relevance_score))
                    if request.min_relevance_score is not None
                    else current.min_relevance_score
                ),
                "schedule": (
                    request.schedule
                    if request.schedule is not None
                    else current.schedule
                ),
                "enabled": (
                    request.enabled if request.enabled is not None else current.enabled
                ),
                "updated_at": _now_iso(),
            }
        )
        return self.storage.update_watch(updated)

    def list_watches(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[WatchTopic], int]:
        return self.storage.list_watches(page=page, page_size=page_size)

    def delete_watch(self, watch_id: str) -> bool:
        return self.storage.delete_watch(watch_id)

    async def check_watch(
        self, watch_id: str, *, source: str = "mock"
    ) -> WatchCheckResult | None:
        watch = self.storage.get_watch(watch_id)
        if watch is None:
            return None
        checked_at = _now_iso()
        if not watch.enabled:
            return WatchCheckResult(watch=watch, decisions=[], checked_at=checked_at)
        existing, _ = self.storage.list_watch_decisions(
            watch_id=watch_id, page=1, page_size=500
        )
        existing_paper_ids = {item.paper_id for item in existing}
        query = " ".join([watch.topic, *watch.include_keywords]).strip()
        search_result = await self.search_with_manifest(
            SearchBiomedicalLiteratureRequest(query=query, max_results=10, source=source)  # type: ignore[arg-type]
        )
        metadata = search_result.items
        retrieval_manifest = search_result.retrieval_manifest
        paper_ids = [item.paper_id for item in metadata]
        new_paper_ids = [
            paper_id for paper_id in paper_ids if paper_id not in existing_paper_ids
        ]
        snapshot = WatchSnapshot(
            snapshot_id=f"watch-snapshot-{uuid.uuid4().hex[:12]}",
            watch_id=watch.watch_id,
            retrieval_id=retrieval_manifest.retrieval_id,
            paper_ids=paper_ids,
            new_paper_ids=new_paper_ids,
            created_at=checked_at,
        )
        self.storage.save_watch_snapshot(snapshot)
        decisions: list[WatchDecisionDetail] = []
        for meta in metadata:
            if meta.paper_id not in new_paper_ids:
                continue
            paper = await self.fetch(
                FetchBiomedicalPaperRequest(paper_id=meta.paper_id, source=source)  # type: ignore[arg-type]
            )
            if paper is None:
                continue
            score, rationale = _score_watch_relevance(watch, paper)
            decision_value = "push" if score >= watch.min_relevance_score else "skip"
            uncertainty = (
                "low" if score >= 0.85 else "medium" if score >= 0.5 else "high"
            )
            if decision_value == "push":
                extracted = self.extract_evidence(
                    EvidenceExtractionRequest(
                        paper=paper, research_question=watch.topic
                    )
                )
                key_claim = extracted.evidence[0].claim if extracted.evidence else ""
                limitation = (
                    extracted.evidence[0].limitations[0]
                    if extracted.evidence and extracted.evidence[0].limitations
                    else "No explicit limitation extracted."
                )
            else:
                key_claim = ""
                limitation = "Below relevance threshold."
            notification = {
                "title": paper.title,
                "citation": _citation_label(paper),
                "summary": _three_line_summary(paper.abstract or paper.title),
                "relevance_reason": rationale,
                "key_evidence_claim": key_claim,
                "limitation_or_uncertainty": limitation,
                "dashboard_path": f"/?view=plugin:biomed_evidence&paper_id={paper.paper_id}",
                "retrieval_id": retrieval_manifest.retrieval_id,
                "snapshot_id": snapshot.snapshot_id,
            }
            decision = WatchDecisionDetail(
                decision_id=_decision_id(watch.watch_id, paper.paper_id),
                watch_id=watch.watch_id,
                paper_id=paper.paper_id,
                retrieval_id=retrieval_manifest.retrieval_id,
                snapshot_id=snapshot.snapshot_id,
                relevance_score=round(score, 3),
                decision=decision_value,
                rationale=rationale,
                uncertainty=uncertainty,
                dedupe_reason=None,
                created_at=checked_at,
                title=paper.title,
                source=paper.source,
                notification=notification,
            )
            self.storage.upsert_watch_decision(decision, source=paper.source)
            decisions.append(decision)
        updated_watch = watch.model_copy(
            update={
                "last_checked_at": checked_at,
                "next_check_at": _next_check(checked_at, watch.schedule),
                "updated_at": checked_at,
            }
        )
        self.storage.update_watch(updated_watch)
        return WatchCheckResult(
            watch=updated_watch,
            decisions=decisions,
            checked_at=checked_at,
            retrieval_manifest=retrieval_manifest,
            snapshot=snapshot,
        )

    def list_watch_decisions(
        self,
        *,
        watch_id: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[WatchDecisionDetail], int]:
        return self.storage.list_watch_decisions(
            watch_id=watch_id,
            page=page,
            page_size=page_size,
        )

    def get_answer_run(self, run_id: str) -> AnswerWithEvidenceResult | None:
        return self.storage.get_answer_run(run_id)

    def get_retrieval_manifest(self, retrieval_id: str) -> RetrievalManifest | None:
        return self.storage.get_retrieval_manifest(retrieval_id)

    def audit_answer(
        self,
        request: CitationAuditRequest,
        *,
        logic_claim_frames: dict[str, LogicalClaimFrame] | None = None,
        logic_evidence_frames: dict[str, LogicalEvidenceFrame] | None = None,
        logic_parser_fallback_reason: str | None = None,
    ) -> CitationAuditResult:
        audit = validate_citation_support(
            answer=request.answer,
            citations=request.citations,
            evidence_items=request.evidence_items,
            run_id=request.run_id,
            retrieval_id=request.retrieval_id,
            observed_uncertainty=request.observed_uncertainty,
            retrieval_manifest=request.retrieval_manifest,
            use_llm_claim_logic=request.use_llm_claim_logic,
            export_logic_facts=request.export_logic_facts,
            logic_claim_frames=logic_claim_frames,
            logic_evidence_frames=logic_evidence_frames,
            logic_parser_fallback_reason=logic_parser_fallback_reason,
        )
        self.storage.save_citation_audit(audit)
        return audit

    def audit_answer_run(self, run_id: str) -> CitationAuditResult | None:
        result = self.storage.get_answer_run(run_id)
        if result is None:
            return None
        return self.audit_answer(
            CitationAuditRequest(
                answer=result.answer,
                citations=result.citations,
                evidence_items=result.evidence_summary,
                run_id=result.run_id,
                retrieval_id=result.retrieval_id,
                observed_uncertainty=result.uncertainty_level,
                retrieval_manifest=result.retrieval_manifest,
            )
        )

    def get_citation_audit(self, audit_id: str) -> CitationAuditResult | None:
        return self.storage.get_citation_audit(audit_id)

    def get_latest_citation_audit_for_run(
        self, run_id: str
    ) -> CitationAuditResult | None:
        return self.storage.get_latest_citation_audit_for_run(run_id)

    def get_answer_trace(self, run_id: str) -> dict[str, object] | None:
        result = self.storage.get_answer_run(run_id)
        if result is None:
            return None
        trace = self.storage.list_agent_trace_steps(run_id)
        revision = self.storage.get_answer_revision(run_id)
        latest_audit = self.storage.get_latest_citation_audit_for_run(run_id)
        latest_advisory = self.storage.get_latest_advisory_verifier_for_run(run_id)
        coverage_matrix = (
            result.evidence_packet.coverage_matrix
            if result.evidence_packet is not None
            else (
                result.retrieval_bundle.coverage_matrix
                if result.retrieval_bundle is not None
                else []
            )
        )
        stop_reason = (
            result.evidence_packet.stop_reason
            if result.evidence_packet is not None
            else (
                result.retrieval_bundle.stop_reason
                if result.retrieval_bundle is not None
                else None
            )
        )
        step_telemetry = build_step_telemetry(
            trace,
            run_id=run_id,
            coverage_matrix=coverage_matrix,
            stop_reason=stop_reason,
        )
        return {
            "run_id": run_id,
            "answer_run": result.model_dump(mode="json"),
            "trace": [item.model_dump(mode="json") for item in trace],
            "step_telemetry": step_telemetry.model_dump(mode="json"),
            "memory": _run_memory_trace(result),
            "revision": (
                revision.model_dump(mode="json") if revision is not None else None
            ),
            "latest_citation_audit": (
                latest_audit.model_dump(mode="json")
                if latest_audit is not None
                else None
            ),
            "latest_advisory_verifier": (
                latest_advisory.model_dump(mode="json")
                if latest_advisory is not None
                else None
            ),
        }

    def get_answer_argument_graph(self, run_id: str) -> ArgumentGraphResult | None:
        result = self.storage.get_answer_run(run_id)
        if result is None:
            return None
        latest_audit = self.storage.get_latest_citation_audit_for_run(run_id)
        return build_argument_graph(run=result, audit=latest_audit)

    def get_answer_math_signals(self, run_id: str) -> MathSignalsResult | None:
        result = self.storage.get_answer_run(run_id)
        if result is None:
            return None
        trace = self.storage.list_agent_trace_steps(run_id)
        latest_audit = self.storage.get_latest_citation_audit_for_run(run_id)
        revision = self.storage.get_answer_revision(run_id)
        coverage_matrix = (
            result.evidence_packet.coverage_matrix
            if result.evidence_packet is not None
            else (
                result.retrieval_bundle.coverage_matrix
                if result.retrieval_bundle is not None
                else []
            )
        )
        stop_reason = (
            result.evidence_packet.stop_reason
            if result.evidence_packet is not None
            else (
                result.retrieval_bundle.stop_reason
                if result.retrieval_bundle is not None
                else None
            )
        )
        step_telemetry = build_step_telemetry(
            trace,
            run_id=run_id,
            coverage_matrix=coverage_matrix,
            stop_reason=stop_reason,
        )
        argument_graph = build_argument_graph(run=result, audit=latest_audit)
        return build_math_signals(
            run=result,
            audit=latest_audit,
            revision=revision,
            step_telemetry=step_telemetry,
            argument_graph=argument_graph,
        )

    def list_answer_audits(
        self,
        *,
        run_id: str = "",
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[dict[str, object]], int]:
        return self.storage.list_citation_audits(
            run_id=run_id,
            page=page,
            page_size=page_size,
        )

    def find_conflicting_evidence(
        self,
        request: ConflictAuditRequest,
    ) -> ConflictAuditResult:
        evidence = request.evidence_items or self._stored_evidence_for_topic(
            request.topic or request.claim
        )
        result = audit_conflicts(
            claim=request.claim,
            topic=request.topic or request.claim,
            evidence_items=evidence,
            retrieval_id=request.retrieval_id,
        )
        self.storage.save_conflict_audit(result)
        return result

    async def export_report(self, request: ExportEvidenceReportRequest) -> str:
        result: AnswerWithEvidenceResult | None = None
        if request.run_id:
            result = self.storage.get_answer_run(request.run_id)
        if result is None and request.question:
            result = await self.answer_with_evidence(
                AnswerWithEvidenceRequest(question=request.question, source="mock")
            )
        if result is None:
            raise ValueError("No answer run or question was provided for export.")
        if request.format == "json":
            return result.model_dump_json(indent=2)
        return _render_markdown_report(result)

    def _client(self, source: str) -> MockLiteratureClient | PubMedLiteratureClient:
        if source == "pubmed":
            return self.pubmed_client
        return self.mock_client

    def _stored_evidence_for_topic(self, topic: str) -> list[EvidenceItem]:
        rows, _ = self.storage.list_evidence(q=topic, page=1, page_size=200)
        items: list[EvidenceItem] = []
        for row in rows:
            try:
                items.append(
                    EvidenceItem.model_validate(
                        {
                            "evidence_id": row["evidence_id"],
                            "paper_id": row["paper_id"],
                            "claim": row["claim"],
                            "finding": row["finding"],
                            "evidence_direction": row["evidence_direction"],
                            "entities": row.get("entities", []),
                            "methods": row.get("methods", []),
                            "datasets_or_cohorts": row.get("datasets_or_cohorts", []),
                            "limitations": row.get("limitations", []),
                            "confidence": row["confidence"],
                            "evidence_span": row.get("evidence_span"),
                            "requires_expert_review": row.get(
                                "requires_expert_review", True
                            ),
                        }
                    )
                )
            except Exception:
                continue
        return items


def _compile_query(
    request: SearchBiomedicalLiteratureRequest,
) -> tuple[str, dict[str, object], list[str]]:
    normalized_query = re.sub(r"\s+", " ", request.query or "").strip()
    filters: dict[str, object] = {
        "max_results": max(0, min(request.max_results, 50)),
        "date_from": request.date_from,
        "date_to": request.date_to,
        "publication_types": _clean_list(request.publication_types),
        "study_types": _clean_list(request.study_types),
        "mesh_terms": _clean_list(request.mesh_terms),
        "species_terms": _clean_list(request.species_terms),
        "exclude_terms": _clean_list(request.exclude_terms),
    }
    unsupported: list[str] = []
    if request.source == "mock":
        for key in (
            "publication_types",
            "study_types",
            "mesh_terms",
            "species_terms",
            "exclude_terms",
        ):
            if filters[key]:
                unsupported.append(f"mock:{key}")
        return normalized_query, filters, unsupported

    parts = [normalized_query] if normalized_query else []
    for term in cast(list[str], filters["mesh_terms"]):
        parts.append(f'"{_pubmed_term(term)}"[MeSH Terms]')
    for term in cast(list[str], filters["species_terms"]):
        parts.append(f'"{_pubmed_term(term)}"[MeSH Terms]')
    for term in cast(list[str], filters["publication_types"]):
        parts.append(f'"{_pubmed_term(term)}"[Publication Type]')
    if filters["study_types"]:
        unsupported.append("pubmed:study_types")
    compiled = " AND ".join(parts) if parts else ""
    exclude_terms = cast(list[str], filters["exclude_terms"])
    if exclude_terms:
        excludes = " OR ".join(
            f'"{_pubmed_term(term)}"[All Fields]' for term in exclude_terms
        )
        compiled = f"({compiled}) NOT ({excludes})" if compiled else f"NOT ({excludes})"
    return compiled, filters, unsupported


def _manifest_from_trace(
    *,
    retrieval_id: str,
    request: SearchBiomedicalLiteratureRequest,
    compiled_query: str,
    normalized_filters: dict[str, object],
    unsupported_filters: list[str],
    started_at: str,
    trace: dict[str, object],
    returned_ids: list[str],
    duplicate_ids: list[str],
    warnings: list[str],
    errors: list[str],
) -> RetrievalManifest:
    trace_warnings = [
        str(item) for item in cast(list[object], trace.get("warnings", [])) if str(item)
    ]
    trace_errors = [
        str(item) for item in cast(list[object], trace.get("errors", [])) if str(item)
    ]
    warnings = [*warnings, *trace_warnings]
    errors = [*errors, *trace_errors]
    raw_result_count = _safe_int(trace.get("raw_result_count"), len(returned_ids))
    pages_requested = _safe_int(trace.get("pages_requested"), 1)
    pages_completed = _safe_int(trace.get("pages_completed"), 0)
    if pages_completed < pages_requested and raw_result_count > len(returned_ids):
        warnings = [
            *warnings,
            "Search completed fewer pages than requested; inspect external source limits.",
        ]
    request_parameters = [
        cast(dict[str, object], item)
        for item in cast(list[object], trace.get("request_parameters", []))
        if isinstance(item, dict)
    ]
    api_endpoints = [
        str(item)
        for item in cast(list[object], trace.get("api_endpoints", []))
        if str(item)
    ]
    return RetrievalManifest(
        retrieval_id=retrieval_id,
        source=request.source,
        original_query=request.query,
        compiled_query=compiled_query,
        normalized_filters=normalized_filters,
        unsupported_filters=unsupported_filters,
        api_endpoints=api_endpoints,
        request_parameters=request_parameters,
        page_size=_safe_int(
            trace.get("page_size"),
            max(1, min(request.max_results, 50)),
        ),
        pages_requested=pages_requested,
        pages_completed=pages_completed,
        raw_result_count=raw_result_count,
        deduped_result_count=len(returned_ids),
        returned_paper_ids=returned_ids,
        dropped_or_duplicate_ids=duplicate_ids,
        started_at=started_at,
        finished_at=_now_iso(),
        warnings=warnings,
        errors=errors,
    )


def _mock_trace(
    *,
    query: str,
    max_results: int,
    date_from: str | None,
    date_to: str | None,
    returned_ids: list[str],
) -> dict[str, object]:
    return {
        "api_endpoints": ["mock://biomed_evidence/search"],
        "request_parameters": [
            {
                "query": query,
                "max_results": max(0, min(max_results, 50)),
                "date_from": date_from,
                "date_to": date_to,
            }
        ],
        "page_size": max(1, min(max_results, 50)) if max_results else 1,
        "pages_requested": 1,
        "pages_completed": 1,
        "raw_result_count": len(returned_ids),
        "duplicate_ids": [],
    }


def _classify_biomedical_question(
    question: str,
    *,
    mode: str,
    model: str | None = None,
    prompt_hash: str | None = None,
    rationale: str = "",
    warnings: list[str] | None = None,
) -> BiomedicalQuestionClassification:
    normalized = re.sub(r"\s+", " ", question or "").strip()
    risk_flags: list[str] = []
    if is_clinical_request(normalized):
        risk_flags.append("clinical_or_patient_specific")
        return BiomedicalQuestionClassification(
            question=question,
            normalized_question=normalized,
            intent="clinical_or_patient_specific",
            clinical_boundary=True,
            needs_clarification=False,
            risk_flags=risk_flags,
            allowed_next_step="refuse",
            classifier_mode=cast(Any, mode),
            llm_model=model,
            llm_prompt_hash=prompt_hash,
            rationale=rationale or "Deterministic clinical guardrail matched.",
            warnings=warnings or [],
        )
    terms = _terms(normalized)
    if len(terms) < 2:
        return BiomedicalQuestionClassification(
            question=question,
            normalized_question=normalized,
            intent="needs_clarification",
            clinical_boundary=False,
            needs_clarification=True,
            risk_flags=[],
            allowed_next_step="clarify",
            classifier_mode=cast(Any, mode),
            llm_model=model,
            llm_prompt_hash=prompt_hash,
            rationale=rationale
            or "Question is too short to form a reliable retrieval plan.",
            warnings=warnings or [],
        )
    if not _looks_biomedical(normalized):
        return BiomedicalQuestionClassification(
            question=question,
            normalized_question=normalized,
            intent="out_of_scope",
            clinical_boundary=False,
            needs_clarification=False,
            risk_flags=["non_biomedical"],
            allowed_next_step="abstain",
            classifier_mode=cast(Any, mode),
            llm_model=model,
            llm_prompt_hash=prompt_hash,
            rationale=rationale
            or "Question does not appear to ask about biomedical literature.",
            warnings=warnings or [],
        )
    return BiomedicalQuestionClassification(
        question=question,
        normalized_question=normalized,
        intent="research_question",
        clinical_boundary=False,
        needs_clarification=False,
        risk_flags=[],
        allowed_next_step="plan_retrieval",
        classifier_mode=cast(Any, mode),
        llm_model=model,
        llm_prompt_hash=prompt_hash,
        rationale=rationale
        or "Question is suitable for research literature retrieval.",
        warnings=warnings or [],
    )


def _deterministic_query_plan(
    *,
    request: PlanBiomedicalSearchRequest,
    classification: BiomedicalQuestionClassification,
) -> BiomedicalQueryPlan:
    primary_query = _planner_primary_query(classification.normalized_question)
    mesh_terms = _infer_mesh_terms(classification.normalized_question)
    include_terms = _infer_include_terms(classification.normalized_question)
    refute_seed = primary_query or classification.normalized_question
    max_results = max(1, min(request.max_results, 50))
    support_queries = [
        f"{refute_seed} association evidence",
        f"{refute_seed} mechanism evidence",
    ]
    refute_queries = [
        f"{refute_seed} contradictory evidence",
        f"{refute_seed} negative results limitations",
    ]
    subquestions = _deterministic_retrieval_subquestions(
        question=request.question,
        primary_query=primary_query or classification.normalized_question,
        support_queries=support_queries,
        refute_queries=refute_queries,
        max_results=max(1, min(max_results, 5)),
    )
    warnings = (
        [
            "Project context was treated as retrieval preference only, not biomedical evidence."
        ]
        if request.project_context
        else []
    )
    return BiomedicalQueryPlan(
        plan_id=_plan_id(
            classification.normalized_question, request.source, "deterministic"
        ),
        question=request.question,
        source=request.source,
        planner_mode="deterministic",
        primary_query=primary_query or classification.normalized_question,
        mesh_terms=mesh_terms,
        include_terms=include_terms,
        exclude_terms=[
            "dosage",
            "dose",
            "treatment recommendation",
            "case report",
        ],
        study_types=_infer_study_types(classification.normalized_question),
        species_terms=_infer_species_terms(classification.normalized_question),
        support_queries=support_queries,
        refute_queries=refute_queries,
        subquestions=subquestions,
        max_results=max_results,
        rationale="Deterministic query plan derived from biomedical terms in the question.",
        warnings=warnings,
    )


def _deterministic_retrieval_subquestions(
    *,
    question: str,
    primary_query: str,
    support_queries: list[str],
    refute_queries: list[str],
    max_results: int,
) -> list[RetrievalSubquestion]:
    specs: list[tuple[RetrievalIntent, str, str, str]] = [
        (
            "background",
            "What is the biomedical context for the relationship in the question?",
            f"{primary_query} background",
            "Establish core biomedical context before narrower support/refute searches.",
        ),
    ]
    if "recent" in question.lower():
        specs.append(
            (
                "recent",
                "Which recent papers update this evidence base?",
                f"{primary_query} recent evidence",
                "The user asked for recent evidence, so run an explicit recency-oriented query.",
            )
        )
    if support_queries:
        specs.append(
            (
                "support",
                "Which papers support the relationship in the question?",
                support_queries[0],
                "Find direct supporting evidence for the proposed relationship.",
            )
        )
    if len(support_queries) > 1:
        specs.append(
            (
                "mechanism",
                "Which papers describe plausible mechanisms for the relationship?",
                support_queries[1],
                "Separate mechanistic evidence from general association evidence.",
            )
        )
    if refute_queries:
        specs.append(
            (
                "refute",
                "Which papers report conflicting, negative, or null findings?",
                refute_queries[0],
                "Actively look for evidence that could weaken or contradict the answer.",
            )
        )
    if len(refute_queries) > 1:
        specs.append(
            (
                "limitation",
                "Which papers clarify study-design or evidence limitations?",
                refute_queries[1],
                "Capture limitations so the final answer does not overstate evidence.",
            )
        )
    result: list[RetrievalSubquestion] = []
    seen_queries: set[str] = set()
    for index, (intent, subquestion, query, reason) in enumerate(specs, start=1):
        if len(result) >= 5:
            break
        clean_query = re.sub(r"\s+", " ", query).strip()
        if not clean_query or clean_query.lower() in seen_queries:
            continue
        seen_queries.add(clean_query.lower())
        result.append(
            RetrievalSubquestion(
                subquestion_id=_subquestion_id(question, intent, index),
                question=subquestion,
                query=clean_query[:300].rstrip(),
                retrieval_intent=intent,
                reason=reason,
                max_results=max_results,
            )
        )
    return result


def _validate_query_plan(
    *,
    classification: BiomedicalQuestionClassification,
    query_plan: BiomedicalQueryPlan | None,
) -> QueryPlanValidation:
    warnings: list[str] = []
    errors: list[str] = []
    if classification.allowed_next_step != "plan_retrieval":
        errors.append(
            f"Classifier allowed next step is {classification.allowed_next_step}."
        )
        return QueryPlanValidation(
            valid=False,
            status="invalid",
            warnings=classification.warnings,
            errors=errors,
        )
    if query_plan is None:
        return QueryPlanValidation(
            valid=False,
            status="invalid",
            warnings=classification.warnings,
            errors=["No query plan was produced."],
        )
    primary_query = re.sub(r"\s+", " ", query_plan.primary_query).strip()
    if not primary_query:
        errors.append("Primary query is empty.")
    if len(primary_query) > 300:
        errors.append("Primary query exceeds 300 characters.")
    if is_clinical_request(primary_query):
        errors.append("Primary query contains clinical or patient-specific intent.")
    if not query_plan.support_queries:
        warnings.append("Planner did not produce support queries.")
    if not query_plan.refute_queries:
        warnings.append("Planner did not produce refute queries.")
    executable_request: SearchBiomedicalLiteratureRequest | None = None
    compiled_query = ""
    unsupported_filters: list[str] = []
    if not errors:
        executable_request = SearchBiomedicalLiteratureRequest(
            query=_executable_query(query_plan),
            max_results=max(1, min(query_plan.max_results, 50)),
            date_from=query_plan.date_from,
            date_to=query_plan.date_to,
            source=query_plan.source,
            publication_types=_clean_list(query_plan.publication_types),
            study_types=_clean_list(query_plan.study_types),
            mesh_terms=_clean_list(query_plan.mesh_terms),
            species_terms=_clean_list(query_plan.species_terms),
            exclude_terms=_clean_list(query_plan.exclude_terms),
        )
        compiled_query, _, unsupported_filters = _compile_query(executable_request)
        if unsupported_filters:
            warnings.extend(
                f"Unsupported filter: {item}" for item in unsupported_filters
            )
    warnings = _merge_unique(classification.warnings, query_plan.warnings, warnings)
    status = "invalid" if errors else "valid_with_warnings" if warnings else "valid"
    return QueryPlanValidation(
        valid=not errors,
        status=cast(Any, status),
        warnings=warnings,
        errors=errors,
        unsupported_filters=unsupported_filters,
        compiled_query=compiled_query,
        executable_request=executable_request,
    )


def _planned_retrieval_specs(
    *,
    base_request: SearchBiomedicalLiteratureRequest,
    query_plan: BiomedicalQueryPlan,
) -> tuple[
    list[tuple[RetrievalSubquestion, SearchBiomedicalLiteratureRequest]], list[str]
]:
    specs: list[tuple[RetrievalSubquestion, SearchBiomedicalLiteratureRequest]] = []
    warnings: list[str] = []
    seen_queries: set[str] = set()
    max_results = max(1, min(base_request.max_results, query_plan.max_results, 5))

    def add(subquestion: RetrievalSubquestion) -> None:
        intent = subquestion.retrieval_intent
        query = subquestion.query
        compiled = re.sub(r"\s+", " ", query).strip()
        if not compiled:
            warnings.append(f"Skipped empty {intent} query.")
            return
        if len(compiled) > 300:
            warnings.append(f"Truncated overlong {intent} query to 300 characters.")
            compiled = compiled[:300].rstrip()
        key = compiled.lower()
        if key in seen_queries:
            warnings.append(f"Skipped duplicate {intent} query: {compiled[:120]}")
            return
        seen_queries.add(key)
        sub_max_results = max(1, min(subquestion.max_results, max_results))
        specs.append(
            (
                subquestion.model_copy(
                    update={
                        "query": compiled,
                        "max_results": sub_max_results,
                    }
                ),
                base_request.model_copy(
                    update={"query": compiled, "max_results": sub_max_results}
                ),
            )
        )

    primary = RetrievalSubquestion(
        subquestion_id=_subquestion_id(query_plan.question, "primary", 0),
        question="Primary retrieval query for the user question.",
        query=base_request.query or query_plan.primary_query,
        retrieval_intent="primary",
        reason="Preserve a primary retrieval record for backward-compatible provenance.",
        max_results=max_results,
    )
    add(primary)

    subquestions = query_plan.subquestions or _deterministic_retrieval_subquestions(
        question=query_plan.question,
        primary_query=base_request.query or query_plan.primary_query,
        support_queries=_clean_list(query_plan.support_queries),
        refute_queries=_clean_list(query_plan.refute_queries),
        max_results=max_results,
    )
    if len(subquestions) > 5:
        warnings.append("Retrieval subquestions were capped at 5 for V2.6.")
    for subquestion in subquestions[:5]:
        add(subquestion)
    return specs, warnings


def _literature_request_from_search_request(
    request: SearchBiomedicalLiteratureRequest,
    *,
    retrieval_intent: RetrievalIntent,
    project_id: str | None,
    require_abstract: bool,
) -> LiteratureSearchRequest:
    return LiteratureSearchRequest(
        query=request.query,
        max_results=request.max_results,
        date_from=request.date_from,
        date_to=request.date_to,
        source=request.source,
        publication_types=request.publication_types,
        study_types=request.study_types,
        mesh_terms=request.mesh_terms,
        species_terms=request.species_terms,
        exclude_terms=request.exclude_terms,
        retrieval_intent=retrieval_intent,
        project_id=project_id,
        require_abstract=require_abstract,
        store=request.store,
    )


def _tool_trace_step(
    *,
    run_id: str,
    step: str,
    status: str,
    input_summary: str = "",
    output_summary: str = "",
    warnings: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> AgentTraceStep:
    return AgentTraceStep(
        step_id=f"{run_id}-{step}-{uuid.uuid4().hex[:8]}",
        run_id=run_id,
        step=cast(Any, step),
        status=cast(Any, status),
        input_summary=input_summary[:500],
        output_summary=output_summary[:500],
        warnings=warnings or [],
        metadata=metadata or {},
        created_at=_now_iso(),
    )


def _release_tool_budget(
    *,
    max_tool_steps: int,
    max_retrieval_queries: int,
    max_followup_queries: int,
    max_papers: int,
    max_evidence_items: int,
    max_llm_calls: int,
    max_wall_clock_seconds: int,
) -> dict[str, object]:
    return {
        "max_tool_steps": max(1, max_tool_steps),
        "max_retrieval_queries": max(1, max_retrieval_queries),
        "max_followup_queries": max(0, max_followup_queries),
        "max_papers": max(1, max_papers),
        "max_evidence_items": max(0, max_evidence_items),
        "max_llm_calls": max(0, max_llm_calls),
        "max_wall_clock_seconds": max(1, max_wall_clock_seconds),
    }


def _memory_effects_from_project_trace(trace: dict[str, object]) -> dict[str, object]:
    effects = list(cast(list[str], trace.get("memory_effects", [])))
    if trace.get("saved_paper_ids"):
        effects.append("prioritized_saved_papers")
    if trace.get("dropped_rejected_paper_ids"):
        effects.append("excluded_rejected_papers")
    return {
        "memory_used": bool(trace.get("project_filter_applied") or effects),
        "memory_effects": _merge_unique(effects),
        "memory_as_evidence": False,
        "retrieval_memory_trace": trace,
    }


def _run_memory_trace(run: AnswerWithEvidenceResult | None) -> dict[str, object]:
    if run is None:
        return {"memory_used": False, "memory_sources": [], "memory_as_evidence": False}
    trace = dict(run.project_context_trace or {})
    trace.setdefault("memory_used", bool(run.project_id))
    trace.setdefault(
        "memory_sources",
        [f"biomed_project:{run.project_id}"] if run.project_id else [],
    )
    trace.setdefault("memory_effects", [])
    trace["memory_as_evidence"] = False
    return trace


def _retrieval_bundle_from_manifest(manifest: RetrievalManifest) -> RetrievalBundle:
    return RetrievalBundle(
        bundle_id=f"{manifest.retrieval_id}-bundle",
        source=cast(Any, manifest.source),
        executed_multi_query=False,
        records=[
            RetrievalBundleRecord(
                intent="primary",
                query=manifest.original_query,
                retrieval_id=manifest.retrieval_id,
                manifest=manifest,
                returned_paper_ids=manifest.returned_paper_ids,
                pass_index=1,
                warnings=manifest.warnings,
                errors=manifest.errors,
            )
        ],
        deduped_paper_ids=manifest.returned_paper_ids,
        stop_reason="single_retrieval_manifest",
        warnings=manifest.warnings,
    )


def _paper_metadata_from_stored_paper(paper: BiomedicalPaper | None) -> PaperMetadata | None:
    if paper is None:
        return None
    if paper.source not in {"pubmed", "mock"}:
        return None
    return PaperMetadata(
        paper_id=paper.paper_id,
        source=cast(Any, paper.source),
        title=paper.title,
        authors=paper.authors,
        journal=paper.journal,
        publication_date=paper.publication_date,
        abstract_available=bool((paper.abstract or "").strip()),
        doi=paper.doi,
        url=paper.url,
    )


def _select_evidence_for_packet(
    evidence: list[EvidenceItem],
    *,
    max_items: int,
    strategy: EvidencePacketSelectionStrategy,
) -> EvidencePacketSelectionResult:
    capped_max = max(1, max_items)

    def contribution(item: EvidenceItem) -> dict[str, object]:
        return {
            "retrieval_intent": item.retrieval_intent,
            "evidence_direction": item.evidence_direction,
            "paper_id": item.paper_id,
            "has_limitations": bool(item.limitations),
            "method_count": len(item.methods),
            "entity_count": len(item.entities),
            "confidence": item.confidence,
        }

    def token_estimate(item: EvidenceItem) -> int:
        text = " ".join([item.claim, item.finding, item.evidence_span or ""])
        return max(16, int(len(text.split()) * 1.35) + 8)

    def score(item: EvidenceItem) -> float:
        direction_bonus = {
            "supports": 3.0,
            "contradicts": 3.5,
            "inconclusive": 2.5,
            "background": 1.5,
        }.get(item.evidence_direction, 1.0)
        confidence_bonus = {"high": 1.5, "medium": 1.0, "low": 0.5}.get(
            item.confidence,
            0.5,
        )
        limitation_bonus = 0.4 if item.limitations else 0.0
        method_bonus = min(0.5, 0.1 * len(item.methods))
        return direction_bonus + confidence_bonus + limitation_bonus + method_bonus

    if strategy == "all_valid":
        ranked = list(evidence)
        protected = [
            item
            for item in evidence
            if item.evidence_direction in {"contradicts", "inconclusive"}
            or bool(item.limitations)
        ]
    else:
        protected = [
            item
            for item in evidence
            if item.evidence_direction in {"contradicts", "inconclusive"}
            or bool(item.limitations)
        ]
        protected_ids = {item.evidence_id for item in protected}
        ranked_rest = sorted(
            [item for item in evidence if item.evidence_id not in protected_ids],
            key=lambda item: (-score(item), item.paper_id, item.evidence_id),
        )
        ranked = sorted(
            protected,
            key=lambda item: (-score(item), item.paper_id, item.evidence_id),
        ) + ranked_rest
    protected_ids = {item.evidence_id for item in protected}
    effective_max = min(capped_max, len(ranked))
    selected_items = ranked[:effective_max]
    selected_ids = {item.evidence_id for item in selected_items}
    protected_selected_count = len(protected_ids & selected_ids)
    selected = [
        EvidenceSelectionItem(
            evidence_id=item.evidence_id,
            paper_id=item.paper_id,
            selected=True,
            reason=(
                "kept by release packet selector; conflict and limitation coverage "
                "are prioritized."
            ),
            score=score(item),
            coverage_contribution=contribution(item),
            token_estimate=token_estimate(item),
        )
        for item in selected_items
    ]
    dropped = [
        EvidenceSelectionItem(
            evidence_id=item.evidence_id,
            paper_id=item.paper_id,
            selected=False,
            reason="dropped because max_evidence_items was reached.",
            score=score(item),
            coverage_contribution=contribution(item),
            token_estimate=token_estimate(item),
        )
        for item in evidence
        if item.evidence_id not in selected_ids
    ]
    selected_papers = {item.paper_id for item in selected_items}
    input_papers = {item.paper_id for item in evidence}
    selected_claims = {item.claim.strip().lower() for item in selected_items}
    input_claims = {item.claim.strip().lower() for item in evidence}
    return EvidencePacketSelectionResult(
        strategy=strategy,
        max_items=effective_max,
        selected=selected,
        dropped=dropped,
        selected_evidence_ids=[item.evidence_id for item in selected_items],
        dropped_evidence_ids=[item.evidence_id for item in evidence if item.evidence_id not in selected_ids],
        coverage_contribution={
            "selected_paper_count": len(selected_papers),
            "input_paper_count": len(input_papers),
            "selected_claim_count": len(selected_claims),
            "input_claim_count": len(input_claims),
            "directions": {
                direction: sum(
                    1 for item in selected_items if item.evidence_direction == direction
                )
                for direction in sorted({item.evidence_direction for item in evidence})
            },
            "protected_evidence_retained": all(
                item.evidence_id in selected_ids
                for item in evidence
                if item.evidence_direction in {"contradicts", "inconclusive"}
                or bool(item.limitations)
            ),
            "protected_evidence_input_count": len(protected_ids),
            "protected_evidence_selected_count": protected_selected_count,
        },
        token_estimate=sum(token_estimate(item) for item in selected_items),
        duplicate_evidence_delta=max(0, len(evidence) - len(input_claims))
        - max(0, len(selected_items) - len(selected_claims)),
        trace={
            "input_evidence_count": len(evidence),
            "selected_count": len(selected),
            "dropped_count": len(dropped),
            "requested_max_items": capped_max,
            "effective_max_items": effective_max,
            "hard_cap_enforced": True,
            "protected_evidence_input_count": len(protected_ids),
            "protected_evidence_selected_count": protected_selected_count,
            "protected_evidence_omitted_count": max(
                0,
                len(protected_ids) - protected_selected_count,
            ),
            "objective": [
                "subquestion coverage",
                "retrieval-intent diversity",
                "support/refute/limitation balance",
                "paper provenance quality",
                "abstract/span availability",
                "duplicate-paper penalty",
                "redundant-claim penalty",
                "source-warning penalty",
            ],
            "advisory_only": False,
        },
    )


def _bandit_advisory_from_coverage(
    coverage: list[CoverageMatrixRow],
    gap_decisions: list[GapSearchDecision],
    *,
    stop_reason: str,
) -> BanditAdvisoryResult:
    counts: dict[str, int] = {}
    for row in coverage:
        counts[row.coverage_status] = counts.get(row.coverage_status, 0) + 1
    if counts.get("conflicted", 0) > 0:
        return BanditAdvisoryResult(
            action="manual_review",
            reason="Coverage includes conflicted rows; reviewer inspection is advised.",
            confidence=0.8,
            expected_additional_steps=1.0,
            based_on={
                "coverage_status_counts": counts,
                "stop_reason": stop_reason,
                "autonomous_runtime_control": False,
                "clinical_and_source_policy_priority": True,
            },
        )
    if gap_decisions:
        action: str = "search_refute"
        if any(decision.retrieval_intent == "support" for decision in gap_decisions):
            action = "search_support"
        if any(decision.retrieval_intent == "limitation" for decision in gap_decisions):
            action = "search_limitation"
        if any(decision.retrieval_intent == "mechanism" for decision in gap_decisions):
            action = "search_mechanism"
        return BanditAdvisoryResult(
            action=cast(Any, action),
            reason="Coverage gaps remain; a bounded follow-up query may improve balance.",
            confidence=0.65,
            expected_additional_steps=float(min(2, len(gap_decisions))),
            based_on={
                "coverage_status_counts": counts,
                "gap_decision_count": len(gap_decisions),
                "stop_reason": stop_reason,
                "autonomous_runtime_control": False,
                "clinical_and_source_policy_priority": True,
            },
        )
    if counts.get("weak", 0) or counts.get("missing", 0) or counts.get("source_limited", 0):
        return BanditAdvisoryResult(
            action="broaden_query",
            reason="Coverage is weak or source-limited, but no safe follow-up query was generated.",
            confidence=0.55,
            expected_additional_steps=1.0,
            based_on={
                "coverage_status_counts": counts,
                "stop_reason": stop_reason,
                "autonomous_runtime_control": False,
                "clinical_and_source_policy_priority": True,
            },
        )
    return BanditAdvisoryResult(
        action="stop",
        reason="Coverage is sufficient for the current bounded workflow.",
        confidence=0.7,
        expected_additional_steps=0.0,
        based_on={
            "coverage_status_counts": counts,
            "stop_reason": stop_reason,
            "autonomous_runtime_control": False,
            "clinical_and_source_policy_priority": True,
        },
    )


def _obsidian_export_ok(
    *,
    tool_name: str,
    result: ObsidianExportResult,
    metadata: Any,
    ids: dict[str, str],
) -> ReleaseToolEnvelope:
    note_ids = {
        f"note_{index}_path": note.path
        for index, note in enumerate(result.notes, start=1)
    }
    return release_ok(
        tool_name=tool_name,
        result=result.model_dump(mode="json"),
        ids={**ids, **note_ids, "export_id": result.export_id},
        warnings=result.warnings,
        trace={
            "export_type": result.export_type,
            "export_dir": result.export_dir,
            "note_count": result.note_count,
            "source_of_truth": result.source_of_truth,
            "imported_as_evidence": result.imported_as_evidence,
            "notes": [note.model_dump(mode="json") for note in result.notes],
        },
        metadata=metadata,
    )


def _paper_metadata_from_literature_record(record: LiteraturePaperRecord) -> PaperMetadata:
    return PaperMetadata(
        paper_id=record.paper_id,
        source=record.source,
        title=record.title,
        authors=record.authors,
        journal=record.journal,
        publication_date=record.publication_date,
        abstract_available=record.abstract_available,
        doi=record.doi,
        url=record.url,
    )


def _build_coverage_matrix(
    bundle: RetrievalBundle,
    evidence: list[EvidenceItem],
) -> list[CoverageMatrixRow]:
    evidence_by_paper: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        evidence_by_paper.setdefault(item.paper_id, []).append(item)
    subquestions = {item.subquestion_id: item for item in bundle.subquestions}
    rows: list[CoverageMatrixRow] = []
    for index, record in enumerate(bundle.records, start=1):
        paper_ids = _merge_unique(record.returned_paper_ids)
        record_evidence = [
            item
            for paper_id in paper_ids
            for item in evidence_by_paper.get(paper_id, [])
        ]
        conflicts = sum(
            1 for item in record_evidence if item.evidence_direction == "contradicts"
        )
        limitations = sum(1 for item in record_evidence if item.limitations)
        status, gap_reason = _coverage_status(
            record=record,
            papers_found=len(paper_ids),
            evidence_count=len(record_evidence),
            conflicts=conflicts,
        )
        subquestion = (
            subquestions.get(record.subquestion_id or "")
            if record.subquestion_id
            else None
        )
        rows.append(
            CoverageMatrixRow(
                subquestion_id=record.subquestion_id
                or record.query_id
                or _subquestion_id(record.query, record.intent, index),
                subquestion=(
                    subquestion.question
                    if subquestion is not None
                    else record.reason or record.query
                ),
                retrieval_intent=record.intent,
                pass_index=record.pass_index,
                query=record.query,
                retrieval_ids=([record.retrieval_id] if record.retrieval_id else []),
                paper_ids=paper_ids,
                papers_found=len(paper_ids),
                evidence_count=len(record_evidence),
                citations=len(record_evidence),
                conflicts=conflicts,
                limitations=limitations,
                coverage_status=status,
                gap_reason=gap_reason,
            )
        )
    return rows


def _coverage_status(
    *,
    record: RetrievalBundleRecord,
    papers_found: int,
    evidence_count: int,
    conflicts: int,
) -> tuple[CoverageStatus, str | None]:
    if record.errors:
        return "source_limited", "retrieval errors limited this subquestion."
    if papers_found == 0:
        return "source_limited", "no papers were returned for this subquestion."
    if evidence_count == 0:
        return "missing", "papers were returned but no usable evidence span was extracted."
    if (
        conflicts > 0
        and record.intent in {"primary", "background", "support", "mechanism", "recent"}
    ):
        return "conflicted", "conflicting evidence was found and must stay visible."
    if evidence_count < min(2, papers_found) and papers_found >= 2:
        return "weak", "evidence coverage is sparse relative to returned papers."
    return "covered", None


def _gap_search_decisions(
    coverage: list[CoverageMatrixRow],
    *,
    query_plan: BiomedicalQueryPlan,
    existing_queries: set[str],
    max_decisions: int,
) -> list[GapSearchDecision]:
    result: list[GapSearchDecision] = []
    for row in coverage:
        if row.pass_index != 1:
            continue
        if row.retrieval_intent == "primary":
            continue
        if row.coverage_status not in {"weak", "missing", "source_limited"}:
            continue
        followup_query = _followup_query_for_gap(row, query_plan)
        if followup_query.lower() in existing_queries:
            followup_query = f"{followup_query} additional evidence"
        result.append(
            GapSearchDecision(
                gap_id=_gap_id(row.subquestion_id, row.coverage_status),
                subquestion_id=row.subquestion_id,
                retrieval_intent=row.retrieval_intent,
                followup_query=followup_query[:300].rstrip(),
                reason=row.gap_reason
                or f"{row.retrieval_intent} coverage was {row.coverage_status}.",
            )
        )
        if len(result) >= max(0, max_decisions):
            break
    return result


def _followup_query_for_gap(
    row: CoverageMatrixRow,
    query_plan: BiomedicalQueryPlan,
) -> str:
    base = query_plan.primary_query or row.query
    if row.retrieval_intent == "refute":
        suffix = "conflicting evidence negative results null findings"
    elif row.retrieval_intent == "mechanism":
        suffix = "mechanism pathway biological process"
    elif row.retrieval_intent == "limitation":
        suffix = "limitations study design cohort model system"
    elif row.retrieval_intent == "recent":
        suffix = "recent evidence"
    elif row.retrieval_intent == "background":
        suffix = "background review"
    else:
        suffix = "supporting evidence"
    return re.sub(r"\s+", " ", f"{base} {suffix}").strip()


def _gap_id(subquestion_id: str, status: str) -> str:
    digest = hashlib.sha256(f"{subquestion_id}:{status}".encode("utf-8")).hexdigest()[
        :12
    ]
    return f"gap-{digest}"


def _coverage_stop_reason(coverage: list[CoverageMatrixRow]) -> str:
    if not coverage:
        return "no_multi_pass_coverage"
    actionable = [
        row
        for row in coverage
        if row.retrieval_intent != "primary"
        and row.coverage_status in {"weak", "missing", "source_limited"}
    ]
    if not actionable:
        return "coverage_sufficient"
    return "gaps_recorded_without_followup"


def _build_evidence_packet(
    *,
    request: AnswerWithEvidenceRequest,
    planning_result: PlanBiomedicalSearchResult | None,
    retrieval_manifest: RetrievalManifest,
    retrieval_bundle: RetrievalBundle | None,
    metadata: list[PaperMetadata],
    evidence: list[EvidenceItem],
) -> EvidencePacketSummary:
    bundle_manifest_ids = (
        [
            record.retrieval_id
            for record in retrieval_bundle.records
            if record.retrieval_id
        ]
        if retrieval_bundle is not None
        else []
    )
    coverage_matrix = (
        retrieval_bundle.coverage_matrix if retrieval_bundle is not None else []
    )
    coverage_gaps = [
        row
        for row in coverage_matrix
        if row.coverage_status in {"weak", "missing", "source_limited", "conflicted"}
    ]
    source_warnings = _merge_unique(
        retrieval_manifest.warnings,
        retrieval_bundle.warnings if retrieval_bundle is not None else [],
        *(
            [record.warnings for record in retrieval_bundle.records]
            if retrieval_bundle is not None
            else []
        ),
    )
    return EvidencePacketSummary(
        packet_id=_evidence_packet_id(request.question, retrieval_manifest.retrieval_id),
        question=request.question,
        planner_mode=(
            planning_result.query_plan.planner_mode
            if planning_result is not None and planning_result.query_plan is not None
            else "deterministic"
        ),
        source=request.source,
        subquestions=(
            retrieval_bundle.subquestions if retrieval_bundle is not None else []
        ),
        retrieval_manifest_ids=_merge_unique(
            [retrieval_manifest.retrieval_id],
            bundle_manifest_ids,
        ),
        paper_ids=[item.paper_id for item in metadata],
        evidence_ids=[item.evidence_id for item in evidence],
        supported_claims=_merge_unique(
            [
                item.claim
                for item in evidence
                if item.evidence_direction in {"supports", "background"}
            ]
        )[:12],
        conflicting_claims=_merge_unique(
            [
                item.claim
                for item in evidence
                if item.evidence_direction in {"contradicts", "inconclusive"}
            ]
        )[:12],
        limitations=_merge_unique(_collect_limitations(evidence))[:12],
        coverage_matrix=coverage_matrix,
        coverage_gaps=coverage_gaps,
        gap_decisions=(
            retrieval_bundle.gap_decisions if retrieval_bundle is not None else []
        ),
        source_warnings=source_warnings,
        stop_reason=(
            retrieval_bundle.stop_reason
            if retrieval_bundle is not None and retrieval_bundle.stop_reason
            else "single_pass"
        ),
        created_at=_now_iso(),
    )


def _evidence_packet_id(question: str, retrieval_id: str) -> str:
    digest = hashlib.sha256(f"{question}:{retrieval_id}".encode("utf-8")).hexdigest()[
        :16
    ]
    return f"packet-{digest}"


def _llm_extraction_payload(
    *,
    paper: BiomedicalPaper,
    research_question: str,
    retrieval_intent: RetrievalIntent,
) -> dict[str, object]:
    return {
        "instructions": [
            "Extract at most two evidence items from this one paper.",
            "Use only the supplied title and abstract.",
            "Each evidence_span must be an exact substring of title or abstract after whitespace normalization.",
            "If no relevant evidence is present, return an empty evidence list.",
            "Do not infer beyond the paper text.",
        ],
        "research_question": research_question,
        "retrieval_intent": retrieval_intent,
        "paper": {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "abstract": paper.abstract or "",
            "source": paper.source,
            "mesh_terms": paper.mesh_terms,
            "keywords": paper.keywords,
        },
        "output_schema": {
            "evidence": [
                {
                    "claim": "short claim grounded in the span",
                    "finding": "short finding; preferably the span itself",
                    "evidence_direction": "supports|contradicts|inconclusive|background",
                    "evidence_span": "exact title/abstract substring",
                    "confidence": "low|medium|high",
                    "entities": [
                        {
                            "name": "entity",
                            "entity_type": "gene|protein|cell_type|disease|pathway|drug|method|dataset|organism|other",
                        }
                    ],
                    "methods": ["method strings"],
                    "datasets_or_cohorts": ["dataset/cohort strings"],
                    "limitations": ["limitation strings"],
                }
            ]
        },
    }


def _evidence_item_from_llm(
    value: dict[str, object],
    *,
    paper: BiomedicalPaper,
    index: int,
    model: str,
    prompt_hash: str,
    retrieval_intent: RetrievalIntent,
) -> EvidenceItem | None:
    span = _grounded_span(
        str(value.get("evidence_span") or value.get("finding") or ""),
        paper,
    )
    if span is None:
        return None
    claim = re.sub(r"\s+", " ", str(value.get("claim") or "")).strip()
    if not claim:
        claim = _claim_from_span(paper, span)
    return EvidenceItem(
        evidence_id=_llm_evidence_id(paper.paper_id, span, index),
        paper_id=paper.paper_id,
        claim=claim,
        finding=span,
        evidence_direction=_coerce_evidence_direction(
            value.get("evidence_direction"), span
        ),
        entities=_coerce_entities(value.get("entities")),
        methods=_coerce_string_list(value.get("methods")),
        datasets_or_cohorts=_coerce_string_list(value.get("datasets_or_cohorts")),
        limitations=_coerce_string_list(value.get("limitations"))
        or ["LLM span-grounded extraction from title/abstract only."],
        confidence=_coerce_confidence(value.get("confidence")),
        evidence_span=span,
        retrieval_intent=retrieval_intent,
        extraction_mode="llm",
        extractor_model=model,
        extractor_prompt_hash=prompt_hash,
        requires_expert_review=True,
    )


def _llm_claim_logic_payload(
    *,
    claims: list[AtomicClaim],
    citations: list[Citation],
    evidence_items: list[EvidenceItem],
) -> dict[str, object]:
    return {
        "instructions": [
            "Parse each supplied atomic claim into exactly one LogicalClaimFrame.",
            "Parse each supplied evidence item into exactly one LogicalEvidenceFrame.",
            "Use only the supplied text; do not add outside biomedical facts.",
            "Preserve claim_id, evidence_id, paper_id, claim_text, and evidence_text exactly.",
            "Return all frames; missing frames make the parser fail.",
            "Do not decide the final entailment verdict.",
        ],
        "allowed_values": {
            "predicate": [
                "associated_with",
                "correlates_with",
                "causes_or_drives",
                "is_mechanistically_linked_to",
                "increases",
                "decreases",
                "predicts",
                "treats",
                "diagnoses",
                "is_marker_of",
                "has_no_effect",
                "uncertain_or_inconclusive",
                "unspecified",
            ],
            "polarity": ["positive", "negative", "uncertain", "unspecified"],
            "modality": [
                "possible",
                "definitive",
                "strong",
                "moderate",
                "suggestive",
                "inconclusive",
                "unspecified",
            ],
            "population": [
                "human",
                "animal",
                "in_vitro",
                "mixed",
                "unspecified",
            ],
            "claim_strength": [
                "causal",
                "association",
                "mechanistic",
                "prognostic",
                "diagnostic",
                "treatment",
                "clinical",
                "uncertainty",
                "background",
                "unspecified",
            ],
            "study_design": [
                "randomized_trial",
                "interventional",
                "longitudinal",
                "observational",
                "cross_sectional",
                "case_control",
                "cohort",
                "preclinical",
                "in_vitro",
                "review",
                "meta_analysis",
                "abstract_only",
                "unspecified",
            ],
            "evidence_strength": [
                "abstract_only",
                "animal_or_in_vitro",
                "observational",
                "longitudinal",
                "interventional",
                "review_or_guideline",
                "not_assessed",
            ],
        },
        "logical_entity_schema": {
            "text": "exact entity text",
            "entity_type": "biological_process|disease|cell_type|pathway|gene|protein|drug|method|organism|unspecified",
            "normalized_id": None,
            "source_span": "optional exact source substring",
        },
        "claims": [
            {
                "claim_id": claim.claim_id,
                "claim_text": claim.text,
                "claim_type": claim.claim_type,
                "cited_paper_ids": claim.cited_paper_ids,
            }
            for claim in claims
        ],
        "citations": [
            {
                "paper_id": citation.paper_id,
                "title": citation.title,
                "cited_claim": citation.cited_claim,
            }
            for citation in citations
        ],
        "evidence_items": [
            {
                "evidence_id": item.evidence_id,
                "paper_id": item.paper_id,
                "claim": item.claim,
                "finding": item.finding,
                "evidence_text": item.evidence_span or item.finding or item.claim,
                "evidence_direction": item.evidence_direction,
                "confidence": item.confidence,
                "entities": [entity.model_dump(mode="json") for entity in item.entities],
                "methods": item.methods,
                "datasets_or_cohorts": item.datasets_or_cohorts,
                "limitations": item.limitations,
            }
            for item in evidence_items
        ],
        "output_schema": {
            "claim_frames": [
                {
                    "claim_id": "claim id from input",
                    "claim_text": "exact claim_text from input",
                    "subject": "LogicalEntity object",
                    "predicate": "allowed predicate",
                    "object": "LogicalEntity object",
                    "polarity": "allowed polarity",
                    "modality": "allowed modality",
                    "population": "allowed population",
                    "claim_strength": "allowed claim_strength",
                    "scope": ["scope terms"],
                    "qualifiers": ["qualifier terms"],
                    "hedging": False,
                    "source_spans": ["exact source substrings"],
                }
            ],
            "evidence_frames": [
                {
                    "evidence_id": "evidence id from input",
                    "paper_id": "paper id from input",
                    "evidence_text": "exact evidence_text from input",
                    "subject": "LogicalEntity object",
                    "predicate": "allowed predicate",
                    "object": "LogicalEntity object",
                    "polarity": "allowed polarity",
                    "modality": "allowed modality",
                    "population": "allowed population",
                    "model_system": "human cohort|mouse model|cell culture|other|null",
                    "study_design": "allowed study_design",
                    "evidence_strength": "allowed evidence_strength",
                    "limitations": ["limitations"],
                    "source_spans": ["exact source substrings"],
                }
            ],
        },
    }


def _logic_claim_frames_from_llm(
    value: object,
    *,
    claims: list[AtomicClaim],
    model: str,
    prompt_hash: str,
) -> dict[str, LogicalClaimFrame]:
    if not isinstance(value, list):
        raise ValueError("claim_frames must be a list.")
    claim_lookup = {claim.claim_id: claim for claim in claims}
    frames: dict[str, LogicalClaimFrame] = {}
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("claim frame must be an object.")
        claim_id = str(raw.get("claim_id") or "")
        claim = claim_lookup.get(claim_id)
        if claim is None:
            raise ValueError(f"unknown claim_id: {claim_id}")
        payload = {
            **raw,
            "claim_id": claim.claim_id,
            "claim_text": claim.text,
            "parser_mode": "llm",
            "parser_model": model,
            "parser_prompt_hash": prompt_hash,
            "parser_warnings": _coerce_string_list(raw.get("parser_warnings")),
        }
        frames[claim.claim_id] = LogicalClaimFrame.model_validate(payload)
    return frames


def _logic_evidence_frames_from_llm(
    value: object,
    *,
    evidence_items: list[EvidenceItem],
    model: str,
    prompt_hash: str,
) -> dict[str, LogicalEvidenceFrame]:
    if not isinstance(value, list):
        raise ValueError("evidence_frames must be a list.")
    evidence_lookup = {item.evidence_id: item for item in evidence_items}
    frames: dict[str, LogicalEvidenceFrame] = {}
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("evidence frame must be an object.")
        evidence_id = str(raw.get("evidence_id") or "")
        item = evidence_lookup.get(evidence_id)
        if item is None:
            raise ValueError(f"unknown evidence_id: {evidence_id}")
        payload = {
            **raw,
            "evidence_id": item.evidence_id,
            "paper_id": item.paper_id,
            "evidence_text": item.evidence_span or item.finding or item.claim,
            "parser_mode": "llm",
            "parser_model": model,
            "parser_prompt_hash": prompt_hash,
            "parser_warnings": _coerce_string_list(raw.get("parser_warnings")),
        }
        frames[item.evidence_id] = LogicalEvidenceFrame.model_validate(payload)
    return frames


def _llm_synthesis_payload(
    *,
    request: AnswerWithEvidenceRequest,
    evidence: list[EvidenceItem],
    citations: list[Citation],
    papers: dict[str, BiomedicalPaper],
    retrieval_manifest: RetrievalManifest,
    retrieval_bundle: RetrievalBundle | None,
    evidence_packet: EvidencePacketSummary | None,
    uncertainty: ConfidenceLevel,
) -> dict[str, object]:
    return {
        "instructions": [
            "Answer only from supplied evidence_items.",
            "Use bracket paper-id citations like [MOCK-PMID-1001] on every biomedical claim.",
            "Do not include uncited future-work, clinical, dosing, diagnosis, treatment, or patient-specific advice.",
            "Mention uncertainty and limitations only when supported by supplied evidence.",
            "Return JSON with final_answer, uncertainty_level, and optional added_limitations.",
        ],
        "question": request.question,
        "project_context": request.project_context,
        "research_only_boundary": RESEARCH_USE_DISCLAIMER,
        "observed_uncertainty": uncertainty,
        "retrieval": {
            "retrieval_id": retrieval_manifest.retrieval_id,
            "source": retrieval_manifest.source,
            "compiled_query": retrieval_manifest.compiled_query,
            "bundle": _retrieval_bundle_trace(retrieval_bundle),
        },
        "evidence_packet": (
            evidence_packet.model_dump(mode="json")
            if evidence_packet is not None
            else None
        ),
        "citations": [citation.model_dump(mode="json") for citation in citations],
        "evidence_items": [
            {
                **item.model_dump(mode="json"),
                "paper_title": (
                    papers[item.paper_id].title
                    if item.paper_id in papers
                    else item.paper_id
                ),
            }
            for item in evidence[:12]
        ],
    }


def _grounded_span(raw_span: str, paper: BiomedicalPaper) -> str | None:
    target = _normalize_space(raw_span)
    if len(target) < 8:
        return None
    candidates = [target]
    trimmed = target.rstrip(".,;: ")
    if trimmed and trimmed != target:
        candidates.append(trimmed)
    for source in (paper.title, paper.abstract or ""):
        normalized_source = _normalize_space(source)
        lowered_source = normalized_source.lower()
        for candidate in candidates:
            if candidate.lower() in lowered_source:
                return candidate
    return None


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _claim_from_span(paper: BiomedicalPaper, span: str) -> str:
    clean = span.rstrip(".")
    if len(clean) > 180:
        clean = clean[:177].rstrip() + "..."
    return f"{paper.title}: {clean}"


def _llm_evidence_id(paper_id: str, span: str, index: int) -> str:
    digest = hashlib.sha256(f"{paper_id}:{index}:{span}".encode("utf-8")).hexdigest()[
        :16
    ]
    return f"ev-llm-{digest}"


def _coerce_evidence_direction(value: object, span: str) -> Any:
    direction = str(value or "").strip()
    if direction in {"supports", "contradicts", "inconclusive", "background"}:
        return direction
    low = span.lower()
    if any(
        marker in low
        for marker in (
            "did not",
            "failed to",
            "no association",
            "not associated",
            "contradict",
        )
    ):
        return "contradicts"
    if any(
        marker in low for marker in ("inconclusive", "weakened", "limited", "ambiguous")
    ):
        return "inconclusive"
    if any(
        marker in low
        for marker in (
            "associated",
            "correlated",
            "linked",
            "identified",
            "enriched",
            "suggest",
        )
    ):
        return "supports"
    return "background"


def _coerce_confidence(value: object) -> Any:
    confidence = str(value or "").strip()
    if confidence in {"low", "medium", "high"}:
        return confidence
    return "low"


def _coerce_entities(value: object) -> list[BiomedicalEntity]:
    if not isinstance(value, list):
        return []
    result: list[BiomedicalEntity] = []
    seen: set[str] = set()
    for raw in value[:12]:
        name = ""
        entity_type = "other"
        if isinstance(raw, dict):
            name = _normalize_space(str(raw.get("name") or ""))
            entity_type = str(raw.get("entity_type") or "other").strip()
        elif isinstance(raw, str):
            name = _normalize_space(raw)
        if entity_type not in {
            "gene",
            "protein",
            "cell_type",
            "disease",
            "pathway",
            "drug",
            "method",
            "dataset",
            "organism",
            "other",
        }:
            entity_type = "other"
        key = f"{entity_type}:{name.lower()}"
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(BiomedicalEntity(name=name, entity_type=cast(Any, entity_type)))
    return result


def _llm_planner_payload(
    *,
    request: PlanBiomedicalSearchRequest,
    fallback_classification: BiomedicalQuestionClassification,
    fallback_plan: BiomedicalQueryPlan,
) -> dict[str, object]:
    return {
        "instructions": [
            "Classify the user question and produce a biomedical literature retrieval plan.",
            "Return JSON with classification and query_plan objects only.",
            "Do not answer the biomedical question.",
            "Do not override deterministic clinical guardrails.",
            "Use only these intents: research_question, clinical_or_patient_specific, needs_clarification, out_of_scope.",
            "The query plan must include primary_query, mesh_terms, include_terms, exclude_terms, support_queries, refute_queries, subquestions, max_results, and rationale.",
            "Subquestions should use retrieval_intent values: background, support, refute, mechanism, limitation, recent.",
            "Keep queries concise and suitable for PubMed or deterministic mock retrieval.",
        ],
        "question": request.question,
        "source": request.source,
        "max_results": request.max_results,
        "project_context": request.project_context,
        "deterministic_classification": fallback_classification.model_dump(mode="json"),
        "deterministic_query_plan": fallback_plan.model_dump(mode="json"),
    }


def _classification_from_llm(
    value: object,
    *,
    fallback: BiomedicalQuestionClassification,
    model: str,
    prompt_hash: str,
) -> BiomedicalQuestionClassification:
    if not isinstance(value, dict):
        return fallback.model_copy(
            update={
                "classifier_mode": "fallback",
                "warnings": _merge_unique(
                    fallback.warnings, ["LLM classification was not an object."]
                ),
            }
        )
    intent = str(value.get("intent") or fallback.intent)
    if intent not in {
        "research_question",
        "clinical_or_patient_specific",
        "needs_clarification",
        "out_of_scope",
    }:
        intent = fallback.intent
    normalized = re.sub(
        r"\s+",
        " ",
        str(value.get("normalized_question") or fallback.normalized_question),
    ).strip()
    clinical_boundary = fallback.clinical_boundary or bool(
        value.get("clinical_boundary")
    )
    if clinical_boundary:
        intent = "clinical_or_patient_specific"
        allowed_next_step = "refuse"
        needs_clarification = False
    else:
        needs_clarification = (
            bool(value.get("needs_clarification")) or intent == "needs_clarification"
        )
        allowed_next_step = str(
            value.get("allowed_next_step") or fallback.allowed_next_step
        )
        if allowed_next_step not in {"plan_retrieval", "clarify", "refuse", "abstain"}:
            allowed_next_step = fallback.allowed_next_step
        if intent == "needs_clarification":
            allowed_next_step = "clarify"
        elif intent == "out_of_scope":
            allowed_next_step = "abstain"
        elif intent == "research_question":
            allowed_next_step = "plan_retrieval"
    return BiomedicalQuestionClassification(
        question=fallback.question,
        normalized_question=normalized,
        intent=cast(Any, intent),
        clinical_boundary=clinical_boundary,
        needs_clarification=needs_clarification,
        risk_flags=_merge_unique(
            fallback.risk_flags,
            _coerce_string_list(value.get("risk_flags")),
        ),
        allowed_next_step=cast(Any, allowed_next_step),
        classifier_mode="llm",
        llm_model=model,
        llm_prompt_hash=prompt_hash,
        rationale=str(value.get("rationale") or fallback.rationale),
        warnings=_coerce_string_list(value.get("warnings")),
    )


def _query_plan_from_llm(
    value: object,
    *,
    fallback: BiomedicalQueryPlan,
    model: str,
    prompt_hash: str,
    raw_response: dict[str, object],
) -> BiomedicalQueryPlan:
    if not isinstance(value, dict):
        return fallback.model_copy(
            update={
                "planner_mode": "fallback",
                "warnings": _merge_unique(
                    fallback.warnings, ["LLM query_plan was not an object."]
                ),
            }
        )
    primary_query = re.sub(
        r"\s+",
        " ",
        str(value.get("primary_query") or fallback.primary_query),
    ).strip()
    max_results = max(
        1, min(_safe_int(value.get("max_results"), fallback.max_results), 50)
    )
    support_queries = (
        _coerce_string_list(value.get("support_queries")) or fallback.support_queries
    )
    refute_queries = (
        _coerce_string_list(value.get("refute_queries")) or fallback.refute_queries
    )
    subquestions = _coerce_retrieval_subquestions(
        value.get("subquestions"),
        fallback=fallback,
        support_queries=support_queries,
        refute_queries=refute_queries,
        max_results=max(1, min(max_results, 5)),
    )
    return BiomedicalQueryPlan(
        plan_id=_plan_id(fallback.question, fallback.source, "llm", prompt_hash),
        question=fallback.question,
        source=fallback.source,
        planner_mode="llm",
        primary_query=primary_query or fallback.primary_query,
        mesh_terms=_coerce_string_list(value.get("mesh_terms")) or fallback.mesh_terms,
        include_terms=_coerce_string_list(value.get("include_terms"))
        or fallback.include_terms,
        exclude_terms=_coerce_string_list(value.get("exclude_terms"))
        or fallback.exclude_terms,
        date_from=str(value.get("date_from") or "") or fallback.date_from,
        date_to=str(value.get("date_to") or "") or fallback.date_to,
        publication_types=_coerce_string_list(value.get("publication_types")),
        study_types=_coerce_string_list(value.get("study_types"))
        or fallback.study_types,
        species_terms=_coerce_string_list(value.get("species_terms"))
        or fallback.species_terms,
        support_queries=support_queries,
        refute_queries=refute_queries,
        subquestions=subquestions,
        max_results=max_results,
        rationale=str(value.get("rationale") or fallback.rationale),
        warnings=_coerce_string_list(value.get("warnings")),
        llm_model=model,
        llm_prompt_hash=prompt_hash,
        llm_raw_response=raw_response,
    )


def _coerce_retrieval_subquestions(
    value: object,
    *,
    fallback: BiomedicalQueryPlan,
    support_queries: list[str],
    refute_queries: list[str],
    max_results: int,
) -> list[RetrievalSubquestion]:
    allowed: set[str] = {
        "primary",
        "background",
        "support",
        "refute",
        "mechanism",
        "limitation",
        "recent",
    }
    result: list[RetrievalSubquestion] = []
    seen_queries: set[str] = set()
    if isinstance(value, list):
        for index, raw in enumerate(value, start=1):
            if not isinstance(raw, dict):
                continue
            query = re.sub(r"\s+", " ", str(raw.get("query") or "")).strip()
            if not query:
                continue
            intent = str(raw.get("retrieval_intent") or raw.get("intent") or "support")
            if intent not in allowed:
                intent = "support"
            key = query.lower()
            if key in seen_queries:
                continue
            seen_queries.add(key)
            question = re.sub(
                r"\s+",
                " ",
                str(raw.get("question") or raw.get("subquestion") or query),
            ).strip()
            reason = re.sub(
                r"\s+",
                " ",
                str(raw.get("reason") or f"LLM planned {intent} retrieval."),
            ).strip()
            result.append(
                RetrievalSubquestion(
                    subquestion_id=str(
                        raw.get("subquestion_id")
                        or _subquestion_id(fallback.question, intent, index)
                    ),
                    question=question[:300].rstrip(),
                    query=query[:300].rstrip(),
                    retrieval_intent=cast(Any, intent),
                    reason=reason[:300].rstrip(),
                    max_results=max(1, min(_safe_int(raw.get("max_results"), max_results), 10)),
                )
            )
            if len(result) >= 5:
                break
    if result:
        return result
    if fallback.subquestions:
        return fallback.subquestions
    return _deterministic_retrieval_subquestions(
        question=fallback.question,
        primary_query=fallback.primary_query,
        support_queries=support_queries,
        refute_queries=refute_queries,
        max_results=max_results,
    )


def _planner_primary_query(question: str) -> str:
    stopwords = {
        "what",
        "which",
        "recent",
        "evidence",
        "links",
        "link",
        "does",
        "between",
        "role",
        "roles",
        "study",
        "studies",
    }
    terms = [term for term in _terms(question) if term not in stopwords]
    return " ".join(_merge_unique(terms))[:240].strip()


def _infer_mesh_terms(question: str) -> list[str]:
    lowered = question.lower()
    terms: list[str] = []
    if "alzheimer" in lowered:
        terms.append("Alzheimer Disease")
    if "microglia" in lowered or "microglial" in lowered:
        terms.append("Microglia")
    if "amyloid" in lowered:
        terms.append("Amyloid beta-Peptides")
    if "cancer" in lowered or "tumor" in lowered or "tumour" in lowered:
        terms.append("Neoplasms")
    if "melanoma" in lowered:
        terms.append("Melanoma")
    return _merge_unique(terms)


def _infer_include_terms(question: str) -> list[str]:
    lowered = question.lower()
    candidates = [
        "TREM2",
        "neuroinflammation",
        "amyloid",
        "spatial transcriptomics",
        "single-nucleus RNA-seq",
        "CSF",
        "cognitive decline",
    ]
    return [term for term in candidates if term.lower() in lowered]


def _infer_study_types(question: str) -> list[str]:
    lowered = question.lower()
    result: list[str] = []
    if "longitudinal" in lowered or "progression" in lowered:
        result.append("longitudinal")
    if "human" in lowered or "patient" in lowered:
        result.append("human")
    if "mouse" in lowered or "animal" in lowered:
        result.append("animal")
    return result


def _infer_species_terms(question: str) -> list[str]:
    lowered = question.lower()
    if "mouse" in lowered or "mice" in lowered:
        return ["Mice"]
    if "human" in lowered or "patient" in lowered:
        return ["Humans"]
    return []


def _looks_biomedical(question: str) -> bool:
    lowered = question.lower()
    markers = {
        "alzheimer",
        "microglia",
        "microglial",
        "amyloid",
        "protein",
        "gene",
        "cell",
        "disease",
        "clinical",
        "biomedical",
        "cancer",
        "tumor",
        "cohort",
        "transcriptomics",
        "neuroinflammation",
        "csf",
        "trem2",
    }
    return any(marker in lowered for marker in markers)


def _executable_query(plan: BiomedicalQueryPlan) -> str:
    return " ".join(
        _merge_unique(
            [plan.primary_query],
            plan.include_terms,
        )
    ).strip()


def _planning_abstention(classification: BiomedicalQuestionClassification) -> str:
    if classification.intent == "needs_clarification":
        return (
            f"{RESEARCH_USE_DISCLAIMER}\n\n"
            "I need a more specific biomedical research question before I can "
            "retrieve and cite literature safely."
        )
    if classification.intent == "out_of_scope":
        return (
            f"{RESEARCH_USE_DISCLAIMER}\n\n"
            "This request does not appear to be a biomedical literature research "
            "question, so I will not fabricate a biomedical evidence answer."
        )
    return (
        f"{RESEARCH_USE_DISCLAIMER}\n\n"
        "The retrieval plan did not pass validation, so I will not answer with "
        "unsupported biomedical claims."
    )


def _planner_next_steps(classification: BiomedicalQuestionClassification) -> list[str]:
    if classification.intent == "needs_clarification":
        return [
            "Add the disease, biological mechanism, population, or study type of interest.",
            "Ask for evidence rather than diagnosis or treatment advice.",
        ]
    if classification.intent == "out_of_scope":
        return ["Reframe the request as a biomedical literature research question."]
    return ["Inspect planner warnings and revise the search question."]


def _plan_id(question: str, source: str, mode: str, nonce: str = "") -> str:
    digest = hashlib.sha256(
        f"{question.lower()}:{source}:{mode}:{nonce}".encode("utf-8")
    ).hexdigest()[:16]
    return f"plan-{digest}"


def _subquestion_id(question: str, intent: str, index: int) -> str:
    digest = hashlib.sha256(
        f"{question.lower()}:{intent}:{index}".encode("utf-8")
    ).hexdigest()[:12]
    return f"subq-{digest}"


def _safe_int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return fallback
    try:
        return int(cast(float, value)) if isinstance(value, float) else fallback
    except (TypeError, ValueError, OverflowError):
        return fallback


def _retrieval_id(request: SearchBiomedicalLiteratureRequest, started_at: str) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "source": request.source,
                "query": request.query,
                "max_results": request.max_results,
                "date_from": request.date_from,
                "date_to": request.date_to,
                "publication_types": request.publication_types,
                "study_types": request.study_types,
                "mesh_terms": request.mesh_terms,
                "species_terms": request.species_terms,
                "exclude_terms": request.exclude_terms,
                "started_at": started_at,
                "nonce": uuid.uuid4().hex,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"retrieval-{digest}"


def _clean_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = re.sub(r"\s+", " ", value).strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def _project_context_text(
    *,
    project: BiomedProject,
    request_context: str | None,
) -> str:
    lines = [
        "Project memory is context only, not biomedical evidence.",
        f"Project: {project.name}",
    ]
    if project.description:
        lines.append(f"Description: {project.description}")
    if project.research_question:
        lines.append(f"Research question: {project.research_question}")
    if project.include_keywords:
        lines.append(f"Include keywords: {', '.join(project.include_keywords)}")
    if project.exclude_keywords:
        lines.append(f"Exclude keywords: {', '.join(project.exclude_keywords)}")
    if project.preferred_methods:
        lines.append(f"Preferred methods: {', '.join(project.preferred_methods)}")
    if project.preferred_species:
        lines.append(f"Preferred species: {', '.join(project.preferred_species)}")
    if project.preferred_study_types:
        lines.append(
            f"Preferred study types: {', '.join(project.preferred_study_types)}"
        )
    if request_context and request_context.strip():
        lines.append(f"User request context: {request_context.strip()}")
    return "\n".join(lines)


def _project_brief_markdown(
    *,
    project: BiomedProject,
    title: str,
    saved_decisions: list[ProjectPaperDecision],
    audited_claims: list[ProjectClaimRecord],
    review_queue: list[ProjectReviewQueueItem],
    storage: BiomedStorage,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Project: {project.name}",
        "",
        "Project memory is context only. Brief findings are promoted only when linked to audit IDs.",
    ]
    if project.research_question:
        lines.extend(["", f"Research question: {project.research_question}"])
    lines.extend(["", "## Saved Papers"])
    if not saved_decisions:
        lines.append("- None recorded.")
    for decision in saved_decisions:
        paper = storage.get_paper(decision.paper_id, source=decision.source)
        title_text = paper.title if paper is not None else decision.paper_id
        reason = f" Reason: {decision.reason}" if decision.reason else ""
        lines.append(
            f"- {title_text} (`{decision.paper_id}`, {decision.source}).{reason}"
        )
    lines.extend(["", "## Audited Claims"])
    if not audited_claims:
        lines.append("- No project claims are linked to audits yet.")
    for claim in audited_claims:
        evidence_ids = ", ".join(claim.evidence_ids) or "none"
        audit_ids = ", ".join(claim.audit_ids) or "none"
        verifier_ids = ", ".join(claim.verifier_ids) or "none"
        lines.append(
            f"- {claim.claim} Status: {claim.status}. Evidence: {evidence_ids}. "
            f"Audits: {audit_ids}. Verifiers: {verifier_ids}."
        )
    lines.extend(["", "## Review Queue"])
    if not review_queue:
        lines.append("- No review items recorded.")
    for item in review_queue[:25]:
        lines.append(
            f"- [{item.risk_level}] {item.item_type}: {item.title}. {item.reason}"
        )
    return "\n".join(lines).strip() + "\n"


def _pubmed_term(value: str) -> str:
    return value.replace('"', "").strip()


def _compose_answer(
    *,
    question: str,
    evidence: list[EvidenceItem],
    papers: dict[str, BiomedicalPaper],
    project_context: str | None,
) -> str:
    groups: dict[str, list[EvidenceItem]] = {
        "supports": [],
        "contradicts": [],
        "inconclusive": [],
        "background": [],
    }
    for item in evidence:
        groups.setdefault(item.evidence_direction, []).append(item)
    lines = [
        RESEARCH_USE_DISCLAIMER,
        "",
        f"Research question: {question}",
    ]
    if project_context:
        lines.append(f"Project context used as preference only: {project_context}")
    if groups["supports"]:
        lines.append("")
        lines.append("Evidence supporting the hypothesis:")
        for item in groups["supports"][:5]:
            lines.append(_evidence_bullet(item, papers))
    if groups["contradicts"]:
        lines.append("")
        lines.append("Evidence that contradicts or limits the hypothesis:")
        for item in groups["contradicts"][:5]:
            lines.append(_evidence_bullet(item, papers))
    if groups["inconclusive"]:
        lines.append("")
        lines.append("Inconclusive evidence:")
        for item in groups["inconclusive"][:5]:
            lines.append(_evidence_bullet(item, papers))
    lines.append("")
    lines.append(
        "Interpretation: the retrieved evidence supports a research association, "
        "not a clinical or causal conclusion. Limitations and uncertainty should be "
        "reviewed by a domain expert."
    )
    return "\n".join(lines)


def _evidence_bullet(item: EvidenceItem, papers: dict[str, BiomedicalPaper]) -> str:
    paper = papers.get(item.paper_id)
    cite = _citation_label(paper) if paper else item.paper_id
    return f"- {item.finding} [{cite}]"


def _citation_label(paper: BiomedicalPaper | None) -> str:
    if paper is None:
        return "citation unavailable"
    author = paper.authors[0] if paper.authors else "Unknown author"
    year = (paper.publication_date or "n.d.")[:4]
    return f"{author} et al., {year}; {paper.paper_id}"


def _collect_limitations(evidence: list[EvidenceItem]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in evidence:
        for limitation in item.limitations:
            if limitation not in seen:
                seen.add(limitation)
                result.append(limitation)
    if not result:
        result.append(
            "No explicit limitations were extracted from retrieved abstracts."
        )
    return result


def _uncertainty(evidence: list[EvidenceItem]) -> ConfidenceLevel:
    if not evidence:
        return "high"
    if any(
        item.evidence_direction in {"contradicts", "inconclusive"} for item in evidence
    ):
        return "high"
    if any(item.confidence == "low" for item in evidence):
        return "medium"
    return "low"


def _suggest_next_steps(evidence: list[EvidenceItem], has_context: bool) -> list[str]:
    steps = [
        "Inspect the cited abstracts and evidence spans manually.",
        "Prioritize studies with human cohorts, longitudinal designs, or public datasets.",
        "Track contradictory and inconclusive findings separately.",
    ]
    if not has_context:
        steps.append(
            "Add project context such as preferred methods or exclusion criteria."
        )
    if not evidence:
        steps.append("Broaden the search query or switch to PubMed for live retrieval.")
    return steps


def _llm_advisory_verifier_payload(
    *,
    request: AnswerWithEvidenceRequest,
    draft_result: AnswerWithEvidenceResult,
    audit: CitationAuditResult,
) -> dict[str, object]:
    return {
        "instructions": [
            "Review the answer as an advisory verifier only.",
            "The deterministic audit is the verifier of record and cannot be overridden.",
            "Use only supplied answer, citations, evidence_items, and deterministic_audit.",
            "Flag possible unsupported claims, overclaims, missing uncertainty, or clinical drift.",
            "Return JSON with advisory_action, claim_reviews, warnings, and errors.",
            "Allowed advisory_action values: pass, pass_with_limitations, revise, refuse_or_abstain, needs_expert_review.",
            "Allowed advisory_verdict values: supported, partial_support, overclaimed, contradicted, insufficient_evidence, irrelevant_citation, not_cited, uncertain, not_assessed.",
        ],
        "question": request.question,
        "research_only_boundary": RESEARCH_USE_DISCLAIMER,
        "answer": draft_result.answer,
        "citations": [item.model_dump(mode="json") for item in draft_result.citations],
        "evidence_items": [
            item.model_dump(mode="json") for item in draft_result.evidence_summary
        ],
        "retrieval_manifest": (
            draft_result.retrieval_manifest.model_dump(mode="json")
            if draft_result.retrieval_manifest is not None
            else None
        ),
        "deterministic_audit": audit.model_dump(mode="json"),
        "output_schema": {
            "advisory_action": "pass|pass_with_limitations|revise|refuse_or_abstain|needs_expert_review",
            "claim_reviews": [
                {
                    "claim_id": "optional deterministic claim id",
                    "claim": "claim text",
                    "advisory_verdict": "supported|partial_support|overclaimed|contradicted|insufficient_evidence|irrelevant_citation|not_cited|uncertain|not_assessed",
                    "advisory_action": "pass|pass_with_limitations|revise|refuse_or_abstain|needs_expert_review",
                    "risk_level": "low|medium|high",
                    "cited_paper_ids": ["paper ids"],
                    "rationale": "brief grounded rationale",
                    "suggested_revision": "optional concise suggestion",
                }
            ],
            "warnings": ["optional warnings"],
            "errors": ["optional errors"],
        },
    }


def _fallback_advisory_verifier(
    *,
    draft_result: AnswerWithEvidenceResult,
    audit: CitationAuditResult,
    provider: object | None,
    model: str,
    prompt_hash: str | None = None,
    fallback_reason: str | None = None,
) -> AdvisoryVerifierResult:
    return AdvisoryVerifierResult(
        verifier_id=_advisory_verifier_id(draft_result.run_id, audit.audit_id),
        run_id=draft_result.run_id,
        audit_id=audit.audit_id,
        retrieval_id=draft_result.retrieval_id,
        verifier_mode="fallback",
        llm_model=model or None,
        llm_prompt_hash=prompt_hash,
        fallback_reason=fallback_reason
        or _llm_verifier_unavailable_reason(provider, model),
        deterministic_action=audit.recommended_action,
        advisory_action=cast(
            Any, _advisory_action_from_audit(audit.recommended_action)
        ),
        claim_reviews=[],
        disagreements=[],
        high_risk_disagreement_count=0,
        created_at=_now_iso(),
    )


def _advisory_verifier_from_llm(
    parsed: dict[str, object],
    *,
    draft_result: AnswerWithEvidenceResult,
    audit: CitationAuditResult,
    model: str,
    prompt_hash: str,
) -> AdvisoryVerifierResult:
    claim_reviews = _coerce_advisory_claim_reviews(parsed.get("claim_reviews"))
    advisory_action = _coerce_advisory_action(
        parsed.get("advisory_action"),
        default=_aggregate_advisory_action(claim_reviews, audit),
    )
    disagreements = _advisory_disagreements(
        claim_reviews,
        audit=audit,
    )
    return AdvisoryVerifierResult(
        verifier_id=_advisory_verifier_id(draft_result.run_id, audit.audit_id),
        run_id=draft_result.run_id,
        audit_id=audit.audit_id,
        retrieval_id=draft_result.retrieval_id,
        verifier_mode="llm",
        llm_model=model,
        llm_prompt_hash=prompt_hash,
        llm_raw_response=parsed,
        deterministic_action=audit.recommended_action,
        advisory_action=cast(Any, advisory_action),
        claim_reviews=claim_reviews,
        disagreements=disagreements,
        high_risk_disagreement_count=sum(1 for item in disagreements if item.high_risk),
        created_at=_now_iso(),
        warnings=_coerce_string_list(parsed.get("warnings")),
        errors=_coerce_string_list(parsed.get("errors")),
    )


def _coerce_advisory_claim_reviews(value: object) -> list[AdvisoryClaimReview]:
    if not isinstance(value, list):
        return []
    reviews: list[AdvisoryClaimReview] = []
    for raw in value[:20]:
        if not isinstance(raw, dict):
            continue
        claim = _normalize_space(str(raw.get("claim") or ""))
        if not claim:
            continue
        reviews.append(
            AdvisoryClaimReview(
                claim_id=_optional_string(raw.get("claim_id")),
                claim=claim,
                advisory_verdict=cast(
                    Any, _coerce_advisory_verdict(raw.get("advisory_verdict"))
                ),
                advisory_action=cast(
                    Any, _coerce_advisory_action(raw.get("advisory_action"))
                ),
                risk_level=cast(Any, _coerce_confidence(raw.get("risk_level"))),
                cited_paper_ids=_coerce_string_list(raw.get("cited_paper_ids")),
                rationale=_normalize_space(str(raw.get("rationale") or "")),
                suggested_revision=_optional_string(raw.get("suggested_revision")),
            )
        )
    return reviews


def _advisory_disagreements(
    reviews: list[AdvisoryClaimReview],
    *,
    audit: CitationAuditResult,
) -> list[AdvisoryVerifierDisagreement]:
    by_id = {item.claim_id: item for item in audit.claim_audits}
    by_claim = {_norm_claim(item.claim): item for item in audit.claim_audits}
    disagreements: list[AdvisoryVerifierDisagreement] = []
    for review in reviews:
        deterministic = by_id.get(review.claim_id or "") or by_claim.get(
            _norm_claim(review.claim)
        )
        if not _is_advisory_disagreement(review, deterministic, audit):
            continue
        high_risk = _is_high_risk_advisory_disagreement(
            review,
            deterministic,
            audit,
        )
        disagreements.append(
            AdvisoryVerifierDisagreement(
                claim_id=deterministic.claim_id if deterministic else review.claim_id,
                claim=deterministic.claim if deterministic else review.claim,
                deterministic_verdict=(
                    deterministic.verdict if deterministic is not None else None
                ),
                deterministic_action=audit.recommended_action,
                advisory_verdict=review.advisory_verdict,
                advisory_action=review.advisory_action,
                risk_level=review.risk_level,
                high_risk=high_risk,
                reason=review.rationale
                or "Advisory verifier disagreed with deterministic audit.",
            )
        )
    return disagreements


def _is_advisory_disagreement(
    review: AdvisoryClaimReview,
    deterministic: ClaimAuditItem | None,
    audit: CitationAuditResult,
) -> bool:
    advisory_problem = review.advisory_verdict in {
        "overclaimed",
        "contradicted",
        "insufficient_evidence",
        "irrelevant_citation",
        "not_cited",
        "uncertain",
    } or review.advisory_action in {
        "revise",
        "refuse_or_abstain",
        "needs_expert_review",
    }
    if deterministic is None:
        return advisory_problem
    deterministic_problem = deterministic.verdict not in {
        "supported",
        "partial_support",
    } or audit.recommended_action in {"revise", "refuse_or_abstain"}
    if deterministic_problem:
        return review.advisory_action in {"pass", "pass_with_limitations"} or (
            review.advisory_verdict in {"supported", "partial_support"}
        )
    return advisory_problem


def _is_high_risk_advisory_disagreement(
    review: AdvisoryClaimReview,
    deterministic: ClaimAuditItem | None,
    audit: CitationAuditResult,
) -> bool:
    if review.risk_level == "high" or review.advisory_action == "refuse_or_abstain":
        return True
    if deterministic is None:
        return review.advisory_action in {"revise", "needs_expert_review"}
    deterministic_passed = deterministic.verdict in {
        "supported",
        "partial_support",
    } and audit.recommended_action in {"pass", "pass_with_limitations"}
    return (
        deterministic_passed
        and review.advisory_action
        in {
            "revise",
            "needs_expert_review",
        }
        and review.risk_level in {"medium", "high"}
    )


def _aggregate_advisory_action(
    reviews: list[AdvisoryClaimReview],
    audit: CitationAuditResult,
) -> str:
    actions = {item.advisory_action for item in reviews}
    if "refuse_or_abstain" in actions:
        return "refuse_or_abstain"
    if "revise" in actions:
        return "revise"
    if "needs_expert_review" in actions:
        return "needs_expert_review"
    if audit.recommended_action == "pass_with_limitations":
        return "pass_with_limitations"
    return "pass"


def _coerce_advisory_action(value: object, *, default: str = "pass") -> str:
    action = str(value or "").strip()
    if action in {
        "pass",
        "pass_with_limitations",
        "revise",
        "refuse_or_abstain",
        "needs_expert_review",
    }:
        return action
    return default


def _coerce_advisory_verdict(value: object) -> str:
    verdict = str(value or "").strip()
    if verdict in {
        "supported",
        "partial_support",
        "overclaimed",
        "contradicted",
        "insufficient_evidence",
        "irrelevant_citation",
        "not_cited",
        "uncertain",
        "not_assessed",
    }:
        return verdict
    return "not_assessed"


def _advisory_action_from_audit(value: str) -> str:
    if value in {"pass", "pass_with_limitations", "revise", "refuse_or_abstain"}:
        return value
    return "pass"


def _advisory_revision_limitations(
    advisory_verifier: AdvisoryVerifierResult | None,
) -> list[str]:
    if advisory_verifier is None or not advisory_verifier.disagreements:
        return []
    return [
        ("Advisory verifier flagged high-risk disagreement: " f"{item.reason}")
        for item in advisory_verifier.disagreements
        if item.high_risk
    ]


def _advisory_verifier_id(run_id: str, audit_id: str) -> str:
    digest = hashlib.sha256(
        f"{run_id}:{audit_id}:advisory".encode("utf-8")
    ).hexdigest()[:16]
    return f"adv-{digest}"


def _optional_string(value: object) -> str | None:
    text = _normalize_space(str(value or ""))
    return text or None


def _norm_claim(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _build_answer_revision(
    *,
    draft_result: AnswerWithEvidenceResult,
    audit: CitationAuditResult,
    clinical_boundary: bool,
    use_llm_revision: bool = False,
    advisory_verifier: AdvisoryVerifierResult | None = None,
    fallback_reason_override: str | None = None,
) -> AnswerRevision:
    now = _now_iso()
    revision_mode = "fallback" if use_llm_revision else "deterministic"
    fallback_reason = (
        fallback_reason_override
        or "LLM revision was requested, but no framework provider is configured for this service instance."
        if use_llm_revision
        else None
    )
    if clinical_boundary or audit.recommended_action == "refuse_or_abstain":
        final_answer = clinical_refusal()
        return AnswerRevision(
            revision_id=_revision_id(draft_result.run_id, audit.audit_id),
            run_id=draft_result.run_id,
            audit_id=audit.audit_id,
            revision_mode=cast(Any, revision_mode),
            fallback_reason=fallback_reason,
            draft_answer=draft_result.answer,
            final_answer=final_answer,
            changed_claims=[],
            removed_claims=[item.claim for item in audit.failed_claims],
            softened_claims=[],
            added_limitations=[
                "The request crossed the clinical-use boundary or contained clinical-risk claims."
            ],
            refusal_reason="clinical_or_patient_specific_boundary",
            revision_action="refuse",
            created_at=now,
        )

    advisory_limitations = _advisory_revision_limitations(advisory_verifier)
    failed_by_claim = {item.claim_id: item for item in audit.failed_claims}
    if (
        not failed_by_claim
        and audit.recommended_action == "pass"
        and not advisory_limitations
    ):
        return AnswerRevision(
            revision_id=_revision_id(draft_result.run_id, audit.audit_id),
            run_id=draft_result.run_id,
            audit_id=audit.audit_id,
            revision_mode=cast(Any, revision_mode),
            fallback_reason=fallback_reason,
            draft_answer=draft_result.answer,
            final_answer=draft_result.answer,
            revision_action="pass",
            created_at=now,
        )

    removed_claims: list[str] = []
    softened_claims: list[str] = []
    changed_claims: list[str] = []
    added_limitations: list[str] = list(advisory_limitations)
    revised_lines: list[str] = []
    for raw_line in draft_result.answer.splitlines():
        match = _matching_failed_claim(raw_line, failed_by_claim.values())
        if match is None:
            revised_lines.append(raw_line)
            continue
        if match.verdict in {
            "not_cited",
            "irrelevant_citation",
            "insufficient_evidence",
        }:
            removed_claims.append(match.claim)
            changed_claims.append(match.claim)
            added_limitations.append(f"Removed unsupported claim: {match.claim}")
            continue
        if match.verdict in {"overclaimed", "contradicted"}:
            if not match.cited_paper_ids:
                removed_claims.append(match.claim)
                changed_claims.append(match.claim)
                added_limitations.append(
                    f"Removed uncited audited claim: {match.claim}"
                )
                continue
            softened = _soften_claim_line(raw_line, match)
            revised_lines.append(softened)
            softened_claims.append(match.claim)
            changed_claims.append(match.claim)
            reason = match.overclaim_reason or match.reason
            added_limitations.append(f"Softened audited claim: {reason}")
            continue
        revised_lines.append(raw_line)

    final_answer = "\n".join(revised_lines).strip()
    if not final_answer or _only_policy_text(final_answer):
        final_answer = (
            f"{RESEARCH_USE_DISCLAIMER}\n\n"
            "After claim-level audit, the draft did not contain enough "
            "citation-supported evidence to answer this biomedical research "
            "question without overclaiming."
        )
        added_limitations.append(
            "The audited draft had no remaining supported research claims."
        )
        action = "abstain"
    else:
        action = "revise"
    conflict_or_uncertainty = (
        not audit.conflict_awareness
        or not audit.uncertainty_calibrated
        or any(item.verdict == "contradicted" for item in audit.failed_claims)
    )
    if added_limitations or conflict_or_uncertainty:
        final_answer = _append_audit_limitations(final_answer, added_limitations, audit)
    return AnswerRevision(
        revision_id=_revision_id(draft_result.run_id, audit.audit_id),
        run_id=draft_result.run_id,
        audit_id=audit.audit_id,
        revision_mode=cast(Any, revision_mode),
        fallback_reason=fallback_reason,
        draft_answer=draft_result.answer,
        final_answer=final_answer,
        changed_claims=_merge_unique(changed_claims),
        removed_claims=_merge_unique(removed_claims),
        softened_claims=_merge_unique(softened_claims),
        added_limitations=_merge_unique(added_limitations),
        refusal_reason=None,
        revision_action=cast(Any, action),
        created_at=now,
    )


def _retrieval_bundle_trace(bundle: RetrievalBundle | None) -> dict[str, object] | None:
    if bundle is None:
        return None
    return {
        "bundle_id": bundle.bundle_id,
        "source": bundle.source,
        "executed_multi_query": bundle.executed_multi_query,
        "deduped_paper_ids": bundle.deduped_paper_ids,
        "duplicate_paper_ids": bundle.duplicate_paper_ids,
        "subquestions": [
            item.model_dump(mode="json") for item in bundle.subquestions
        ],
        "coverage_matrix": [
            item.model_dump(mode="json") for item in bundle.coverage_matrix
        ],
        "gap_decisions": [
            item.model_dump(mode="json") for item in bundle.gap_decisions
        ],
        "stop_reason": bundle.stop_reason,
        "warnings": bundle.warnings,
        "records": [
            {
                "intent": record.intent,
                "query": record.query,
                "query_id": record.query_id,
                "subquestion_id": record.subquestion_id,
                "reason": record.reason,
                "pass_index": record.pass_index,
                "retrieval_id": record.retrieval_id,
                "returned_paper_ids": record.returned_paper_ids,
                "added_paper_ids": record.added_paper_ids,
                "coverage": (
                    record.coverage.model_dump(mode="json")
                    if record.coverage is not None
                    else None
                ),
                "warnings": record.warnings,
                "errors": record.errors,
                "skipped_reason": record.skipped_reason,
            }
            for record in bundle.records
        ],
    }


def _evidence_intent_counts(evidence: list[EvidenceItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in evidence:
        counts[item.retrieval_intent] = counts.get(item.retrieval_intent, 0) + 1
    return counts


def _extraction_mode_counts(evidence: list[EvidenceItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in evidence:
        counts[item.extraction_mode] = counts.get(item.extraction_mode, 0) + 1
    return counts


def _remove_failed_claim_lines(
    answer: str,
    failed_claims: Iterable[ClaimAuditItem],
) -> tuple[str, list[str]]:
    failed = list(failed_claims)
    if not failed:
        return answer.strip(), []
    kept_lines: list[str] = []
    removed_claims: list[str] = []
    for line in answer.splitlines():
        match = _matching_failed_claim(line, failed)
        if match is None:
            kept_lines.append(line)
            continue
        removed_claims.append(match.claim)
    return _drop_empty_markdown_sections("\n".join(kept_lines)), _merge_unique(
        removed_claims
    )


def _drop_empty_markdown_sections(answer: str) -> str:
    lines = answer.strip().splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_markdown_section_heading(line):
            kept.append(line)
            index += 1
            continue

        next_index = index + 1
        while next_index < len(lines) and not _is_markdown_section_heading(
            lines[next_index]
        ):
            next_index += 1
        body = lines[index + 1 : next_index]
        if any(item.strip() for item in body):
            kept.extend(lines[index:next_index])
        else:
            while kept and not kept[-1].strip():
                kept.pop()
        index = next_index
    return "\n".join(kept).strip()


def _is_markdown_section_heading(line: str) -> bool:
    stripped = line.strip()
    if re.match(r"^#{1,6}\s+\S", stripped):
        return True
    return (
        stripped.startswith("**")
        and stripped.endswith("**")
        and stripped.count("**") == 2
    )


def _build_trace_steps(
    *,
    request: AnswerWithEvidenceRequest,
    result: AnswerWithEvidenceResult,
    audit: CitationAuditResult,
    advisory_verifier: AdvisoryVerifierResult | None,
    revision: AnswerRevision,
    clinical_boundary: bool,
) -> list[AgentTraceStep]:
    steps: list[AgentTraceStep] = []

    def add(
        step: str,
        status: str,
        input_summary: str,
        output_summary: str,
        *,
        warnings: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        steps.append(
            AgentTraceStep(
                step_id=_trace_step_id(result.run_id, step),
                run_id=result.run_id,
                step=cast(Any, step),
                status=cast(Any, status),
                input_summary=input_summary,
                output_summary=output_summary,
                warnings=warnings or [],
                metadata=metadata or {},
                created_at=_now_iso(),
            )
        )

    add(
        "classify",
        "completed",
        request.question,
        (
            result.question_classification.intent
            if result.question_classification is not None
            else "clinical_refuse" if clinical_boundary else "research_ok"
        ),
        warnings=(
            result.question_classification.warnings
            if result.question_classification is not None
            else []
        ),
        metadata={
            "source": request.source,
            "project_id": result.project_id,
            "classification": (
                result.question_classification.model_dump(mode="json")
                if result.question_classification is not None
                else None
            ),
        },
    )
    add(
        "plan",
        (
            "skipped"
            if clinical_boundary
            else "completed" if result.query_plan is not None else "skipped"
        ),
        (
            "structured planner"
            if result.query_plan is not None
            else "answer_with_audit request"
        ),
        (
            result.query_plan.primary_query
            if result.query_plan is not None
            else (
                "clinical boundary stopped retrieval"
                if clinical_boundary
                else "reused answer_with_evidence retrieval plan"
            )
        ),
        warnings=result.query_plan.warnings if result.query_plan is not None else [],
        metadata={
            "query_plan": (
                result.query_plan.model_dump(mode="json")
                if result.query_plan is not None
                else None
            ),
            "support_query_count": (
                len(result.query_plan.support_queries) if result.query_plan else 0
            ),
            "refute_query_count": (
                len(result.query_plan.refute_queries) if result.query_plan else 0
            ),
        },
    )
    add(
        "validate_plan",
        ("completed" if result.query_plan_validation is not None else "skipped"),
        result.query_plan.primary_query if result.query_plan is not None else "",
        (
            result.query_plan_validation.status
            if result.query_plan_validation is not None
            else "no structured planner requested"
        ),
        warnings=(
            result.query_plan_validation.warnings
            if result.query_plan_validation is not None
            else []
        ),
        metadata={
            "validation": (
                result.query_plan_validation.model_dump(mode="json")
                if result.query_plan_validation is not None
                else None
            ),
        },
    )
    add(
        "retrieve",
        "skipped" if clinical_boundary else "completed",
        request.question,
        result.retrieval_id or "no retrieval",
        warnings=_merge_unique(
            result.retrieval_manifest.warnings if result.retrieval_manifest else [],
            result.retrieval_bundle.warnings if result.retrieval_bundle else [],
        ),
        metadata={
            "retrieval_id": result.retrieval_id,
            "papers": (
                result.retrieval_manifest.returned_paper_ids
                if result.retrieval_manifest is not None
                else []
            ),
            "retrieval_bundle": _retrieval_bundle_trace(result.retrieval_bundle),
            "evidence_packet": (
                result.evidence_packet.model_dump(mode="json")
                if result.evidence_packet is not None
                else None
            ),
            "project_context_trace": result.project_context_trace,
        },
    )
    add(
        "extract",
        "skipped" if clinical_boundary else "completed",
        "retrieved papers",
        f"{len(result.evidence_summary)} evidence items",
        metadata={
            "evidence_intent_counts": _evidence_intent_counts(result.evidence_summary),
            "extraction_mode_counts": _extraction_mode_counts(result.evidence_summary),
            "evidence_packet_id": (
                result.evidence_packet.packet_id
                if result.evidence_packet is not None
                else None
            ),
            "coverage_gap_count": (
                len(result.evidence_packet.coverage_gaps)
                if result.evidence_packet is not None
                else 0
            ),
        },
    )
    add(
        "draft",
        "completed",
        "evidence summary",
        f"{len(revision.draft_answer)} draft characters",
        metadata={
            "synthesis_mode": result.synthesis_mode,
            "synthesis_model": result.synthesis_model,
            "synthesis_prompt_hash": result.synthesis_prompt_hash,
            "synthesis_fallback_reason": result.synthesis_fallback_reason,
        },
    )
    add(
        "audit",
        "completed",
        revision.draft_answer[:240],
        audit.audit_id,
        metadata={
            "claim_support_rate": audit.claim_support_rate,
            "citation_precision": audit.citation_precision,
            "unsupported_claim_rate": audit.unsupported_claim_rate,
            "overclaim_rate": audit.overclaim_rate,
            "recommended_action": audit.recommended_action,
            "logic_audit": _logic_audit_trace(audit),
        },
    )
    add(
        "advisory_verify",
        (
            "skipped"
            if not request.use_llm_verifier or clinical_boundary
            else "completed"
        ),
        audit.recommended_action,
        (
            advisory_verifier.advisory_action
            if advisory_verifier is not None
            else "LLM verifier not requested"
        ),
        warnings=advisory_verifier.warnings if advisory_verifier is not None else [],
        metadata={
            "verifier_mode": (
                advisory_verifier.verifier_mode
                if advisory_verifier is not None
                else None
            ),
            "verifier_model": (
                advisory_verifier.llm_model if advisory_verifier is not None else None
            ),
            "deterministic_action": audit.recommended_action,
            "advisory_action": (
                advisory_verifier.advisory_action
                if advisory_verifier is not None
                else None
            ),
            "disagreement_count": (
                len(advisory_verifier.disagreements)
                if advisory_verifier is not None
                else 0
            ),
            "high_risk_disagreement_count": (
                advisory_verifier.high_risk_disagreement_count
                if advisory_verifier is not None
                else 0
            ),
            "fallback_reason": (
                advisory_verifier.fallback_reason
                if advisory_verifier is not None
                else None
            ),
        },
    )
    add(
        "revise",
        "completed",
        audit.recommended_action,
        revision.revision_action,
        metadata={
            "revision_mode": revision.revision_mode,
            "fallback_reason": revision.fallback_reason,
            "changed_claims": revision.changed_claims,
            "removed_claims": revision.removed_claims,
            "softened_claims": revision.softened_claims,
        },
    )
    add(
        "post_audit",
        "completed" if revision.post_revision_audit_id else "skipped",
        revision.revision_action,
        revision.post_revision_audit_id
        or "deterministic revision did not require a separate post-audit",
    )
    add(
        "finalize",
        "completed",
        revision.revision_action,
        result.run_id,
        metadata={"final_answer_chars": len(revision.final_answer)},
    )
    return steps


def _logic_audit_trace(audit: CitationAuditResult) -> dict[str, object]:
    logic_results = [
        item.logic_audit for item in audit.claim_audits if item.logic_audit is not None
    ]
    verdict_counts: dict[str, int] = {}
    rules: dict[str, int] = {}
    parser_modes: dict[str, int] = {}
    parser_models: set[str] = set()
    parser_prompt_hashes: set[str] = set()
    parser_warning_count = 0
    fact_exports = 0
    fact_count = 0

    def count_parser_frame(
        frame: LogicalClaimFrame | LogicalEvidenceFrame | None,
    ) -> None:
        nonlocal parser_warning_count
        if frame is None:
            return
        parser_modes[frame.parser_mode] = parser_modes.get(frame.parser_mode, 0) + 1
        if frame.parser_model:
            parser_models.add(frame.parser_model)
        if frame.parser_prompt_hash:
            parser_prompt_hashes.add(frame.parser_prompt_hash)
        parser_warning_count += len(frame.parser_warnings)

    for logic in logic_results:
        verdict_counts[logic.logic_verdict] = (
            verdict_counts.get(logic.logic_verdict, 0) + 1
        )
        count_parser_frame(logic.claim_frame)
        for frame in logic.evidence_frames:
            count_parser_frame(frame)
        if logic.logic_fact_export is not None:
            fact_exports += 1
            fact_count += len(logic.logic_fact_export.facts)
        for rule in logic.rules_triggered:
            rules[rule] = rules.get(rule, 0) + 1
    return {
        "enabled": bool(logic_results),
        "claim_count": len(logic_results),
        "verdict_counts": verdict_counts,
        "rules_triggered": rules,
        "parser_mode_counts": parser_modes,
        "parser_models": sorted(parser_models),
        "parser_prompt_hashes": sorted(parser_prompt_hashes),
        "parser_warning_count": parser_warning_count,
        "fact_export_count": fact_exports,
        "fact_count": fact_count,
    }


def _llm_revision_payload(
    *,
    request: AnswerWithEvidenceRequest,
    draft_result: AnswerWithEvidenceResult,
    audit: CitationAuditResult,
    advisory_verifier: AdvisoryVerifierResult | None = None,
) -> dict[str, object]:
    manifest = draft_result.retrieval_manifest
    return {
        "instructions": [
            "Use only supplied evidence items and citations.",
            "Keep citation labels exactly as provided.",
            "Do not introduce uncited biomedical claims.",
            "Every sentence that states biomedical evidence, uncertainty, limitations, comparisons, or recommendations must include at least one supplied citation label.",
            "Only the research-use disclaimer may remain uncited.",
            "Use bracketed paper-id labels such as [MOCK-PMID-1001]; do not use bare parenthetical identifiers such as (MOCK-PMID-1001).",
            "Do not add future-work, expert-review, or causality caveats unless they are directly grounded in supplied evidence and cited.",
            "Prefer concise bullets; place citation labels in the same sentence as the claim they support.",
            "Do not provide diagnosis, treatment, dosing, prognosis, or patient-specific advice.",
            "If evidence is insufficient, say so.",
            "Return JSON with final_answer, changed_claims, removed_claims, softened_claims, added_limitations, and uncertainty_level.",
        ],
        "acceptance_gate": (
            "The framework will run a post-revision citation audit and reject the LLM "
            "revision if unsupported, overclaimed, or uncited biomedical claims remain."
        ),
        "question": request.question,
        "draft_answer": draft_result.answer,
        "citations": [item.model_dump(mode="json") for item in draft_result.citations],
        "evidence_items": [
            item.model_dump(mode="json") for item in draft_result.evidence_summary
        ],
        "limitations": draft_result.limitations,
        "retrieval_manifest": (
            manifest.model_dump(mode="json") if manifest is not None else None
        ),
        "audit": audit.model_dump(mode="json"),
        "advisory_verifier": (
            advisory_verifier.model_dump(mode="json")
            if advisory_verifier is not None
            else None
        ),
    }


def _parse_json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise ValueError("LLM revision response must be a JSON object.")
    return cast(dict[str, object], loaded)


def _normalize_llm_answer_text(raw: str) -> str:
    text = raw.strip()
    return text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")


def _coerce_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _llm_unavailable_reason(provider: object | None, model: str) -> str:
    if provider is None:
        return "LLM revision was requested, but no framework provider is configured for this service instance."
    if not model:
        return "LLM revision was requested, but no revision model is configured."
    return "LLM revision was requested, but the LLM revision adapter fell back to deterministic revision."


def _llm_synthesis_unavailable_reason(provider: object | None, model: str) -> str:
    if provider is None:
        return "LLM synthesis was requested, but no framework provider is configured for this service instance."
    if not model:
        return "LLM synthesis was requested, but no synthesis model is configured."
    return "LLM synthesis was requested, but the LLM synthesis adapter fell back to deterministic synthesis."


def _llm_verifier_unavailable_reason(provider: object | None, model: str) -> str:
    if provider is None:
        return "LLM verifier was requested, but no framework provider is configured for this service instance."
    if not model:
        return "LLM verifier was requested, but no verifier model is configured."
    return "LLM verifier was requested, but the LLM verifier adapter fell back to deterministic audit only."


def _llm_planner_unavailable_reason(provider: object | None, model: str) -> str:
    if provider is None:
        return "LLM planner was requested, but no framework provider is configured for this service instance."
    if not model:
        return "LLM planner was requested, but no planner model is configured."
    return "LLM planner was requested, but the planner adapter fell back to deterministic planning."


def _llm_claim_logic_unavailable_reason(provider: object | None, model: str) -> str:
    if provider is None:
        return "LLM claim logic parser was requested, but no framework provider is configured for this service instance."
    if not model:
        return "LLM claim logic parser was requested, but no parser model is configured."
    return "LLM claim logic parser was requested, but deterministic logic parsing was used."


def _matching_failed_claim(
    line: str,
    failed_claims: Iterable[ClaimAuditItem],
) -> ClaimAuditItem | None:
    best: tuple[ClaimAuditItem, float] | None = None
    for claim in failed_claims:
        score = _claim_match_score(line, claim.claim)
        if score < 0.55:
            continue
        if best is None or score > best[1]:
            best = (claim, score)
    return best[0] if best is not None else None


def _claim_match_score(line: str, claim: str) -> float:
    line_terms = set(_terms(line))
    claim_terms = set(_terms(claim))
    if not line_terms or not claim_terms:
        return 0.0
    return len(line_terms & claim_terms) / len(claim_terms)


def _soften_claim_line(line: str, claim: ClaimAuditItem) -> str:
    prefix = ""
    body = line
    if line.strip().startswith("- "):
        prefix = "- "
        body = line.strip()[2:]
    softened = re.sub(r"\bcauses?\b", "is associated with", body, flags=re.IGNORECASE)
    softened = re.sub(r"\bdrives?\b", "is linked to", softened, flags=re.IGNORECASE)
    softened = re.sub(r"\bproves?\b", "suggests", softened, flags=re.IGNORECASE)
    softened = re.sub(r"\bestablishes?\b", "suggests", softened, flags=re.IGNORECASE)
    if claim.verdict == "contradicted":
        softened = (
            f"Audit note: retrieved evidence conflicts with this claim; {softened}"
        )
    elif claim.overclaim_reason:
        softened = f"Audit-softened claim: {softened}"
    return f"{prefix}{softened}"


def _append_audit_limitations(
    answer: str,
    added_limitations: list[str],
    audit: CitationAuditResult,
) -> str:
    limitations = _merge_unique(
        added_limitations,
        audit.uncertainty_audit.reasons,
    )
    if not limitations:
        return answer
    lines = [answer.rstrip(), "", "Audit limitations:"]
    for limitation in limitations[:8]:
        lines.append(f"- {limitation}")
    return "\n".join(lines)


def _only_policy_text(answer: str) -> bool:
    cleaned = " ".join(answer.lower().split())
    disclaimer = " ".join(RESEARCH_USE_DISCLAIMER.lower().split())
    return bool(cleaned) and cleaned == disclaimer


def _revised_uncertainty(
    original: ConfidenceLevel,
    audit: CitationAuditResult,
    revision: AnswerRevision,
) -> ConfidenceLevel:
    if revision.revision_action in {"refuse", "abstain"}:
        return "high"
    expected = audit.uncertainty_audit.expected_uncertainty
    if _uncertainty_rank_service(expected) > _uncertainty_rank_service(original):
        return expected
    return original


def _uncertainty_rank_service(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value, 2)


def _merge_unique(*groups: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            clean = str(value).strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            result.append(clean)
    return result


def _template_source_policy(source: str) -> ReleaseToolSourcePolicy:
    return "live_opt_in" if source == "pubmed" else "mock_only"


def _clean_template_id(value: str) -> str:
    base = _slug(value)
    if not base.startswith("biomed-template-"):
        base = f"biomed-template-{base}"
    return base


def default_workflow_templates() -> list[SavedToolChainTemplate]:
    now = "builtin"
    return [
        SavedToolChainTemplate(
            template_id="biomed-template-mock-ci",
            name="Mock CI Workflow",
            description=(
                "Deterministic mock-source workflow for regression checks and demos."
            ),
            builtin=True,
            source="mock",
            source_policy="mock_only",
            max_papers=5,
            max_queries=4,
            max_followups=0,
            execute_support_refute=True,
            use_llm_claim_logic=True,
            export_logic_facts=True,
            export_provenance=True,
            required_skills=[
                "biomed-evidence-review",
                "biomed-clinical-boundary",
            ],
            stop_conditions=[
                "clinical_boundary",
                "budget_exceeded",
                "empty_evidence",
            ],
            created_at=now,
            updated_at=now,
        ),
        SavedToolChainTemplate(
            template_id="biomed-template-pubmed-live-research",
            name="PubMed Live Research Workflow",
            description=(
                "Opt-in live PubMed workflow with LLM planning, extraction, "
                "synthesis, verifier, revision, and provenance."
            ),
            builtin=True,
            source="pubmed",
            source_policy="live_opt_in",
            max_papers=3,
            max_queries=6,
            max_followups=1,
            execute_support_refute=True,
            use_llm_planner=True,
            use_llm_extractor=True,
            use_llm_synthesis=True,
            use_llm_verifier=True,
            use_llm_revision=True,
            use_llm_claim_logic=True,
            export_logic_facts=True,
            export_provenance=True,
            required_skills=[
                "biomed-evidence-review",
                "biomed-clinical-boundary",
            ],
            stop_conditions=[
                "clinical_boundary",
                "source_policy_blocked",
                "external_source_unavailable",
                "llm_schema_invalid",
            ],
            created_at=now,
            updated_at=now,
        ),
        SavedToolChainTemplate(
            template_id="biomed-template-clinical-guarded",
            name="Conservative Clinical-Guarded Workflow",
            description=(
                "Small deterministic workflow that prioritizes clinical-boundary "
                "refusal before any retrieval or LLM path."
            ),
            builtin=True,
            source="mock",
            source_policy="mock_only",
            max_papers=3,
            max_queries=2,
            max_followups=0,
            execute_support_refute=False,
            clinical_guard_required=True,
            export_provenance=False,
            required_skills=["biomed-clinical-boundary"],
            stop_conditions=["clinical_boundary"],
            created_at=now,
            updated_at=now,
        ),
        SavedToolChainTemplate(
            template_id="biomed-template-deep-audit",
            name="Deep Audit Workflow",
            description=(
                "High-scrutiny mock-source workflow for citation audit, logic facts, "
                "revision, packet inspection, and provenance export."
            ),
            builtin=True,
            source="mock",
            source_policy="mock_only",
            max_papers=10,
            max_queries=6,
            max_followups=2,
            execute_support_refute=True,
            use_llm_planner=True,
            use_llm_extractor=True,
            use_llm_synthesis=True,
            use_llm_verifier=True,
            use_llm_revision=True,
            use_llm_claim_logic=True,
            export_logic_facts=True,
            export_provenance=True,
            required_skills=[
                "biomed-evidence-review",
                "biomed-clinical-boundary",
                "biomed-project-memory-watch",
            ],
            stop_conditions=[
                "clinical_boundary",
                "budget_exceeded",
                "empty_evidence",
                "provenance_unavailable",
            ],
            created_at=now,
            updated_at=now,
        ),
    ]


def _revision_id(run_id: str, audit_id: str | None) -> str:
    digest = hashlib.sha256(f"{run_id}:{audit_id or ''}".encode("utf-8")).hexdigest()[
        :16
    ]
    return f"revision-{digest}"


def _trace_step_id(run_id: str, step: str) -> str:
    digest = hashlib.sha256(f"{run_id}:{step}".encode("utf-8")).hexdigest()[:16]
    return f"trace-{digest}"


def _score_watch_relevance(
    watch: WatchTopic, paper: BiomedicalPaper
) -> tuple[float, str]:
    haystack = " ".join(
        [
            paper.title,
            paper.abstract or "",
            " ".join(paper.keywords),
            " ".join(paper.mesh_terms),
        ]
    ).lower()
    exclude_hits = [kw for kw in watch.exclude_keywords if kw.lower() in haystack]
    if exclude_hits:
        return 0.0, f"Excluded by keyword(s): {', '.join(exclude_hits)}"
    topic_terms = _terms(" ".join([watch.topic, *watch.include_keywords]))
    if not topic_terms:
        return 0.0, "No topic terms configured."
    hits = [term for term in topic_terms if term in haystack]
    method_hits = [
        method for method in watch.preferred_methods if method.lower() in haystack
    ]
    score = min(
        1.0, (len(hits) / len(topic_terms)) * 0.85 + min(0.15, len(method_hits) * 0.05)
    )
    if score >= watch.min_relevance_score:
        reason = f"Matched topic terms: {', '.join(hits[:8]) or 'none'}"
        if method_hits:
            reason += f"; preferred methods: {', '.join(method_hits)}"
    else:
        reason = f"Matched {len(hits)}/{len(topic_terms)} topic terms, below threshold."
    return score, reason


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}", text or "")
        if token.lower() not in {"the", "and", "for", "with", "topic"}
    ]


def _three_line_summary(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return ["No abstract available.", "", ""]
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    lines = [sentence.strip() for sentence in sentences if sentence.strip()][:3]
    while len(lines) < 3:
        lines.append("")
    return lines


def _render_markdown_report(result: AnswerWithEvidenceResult) -> str:
    lines = [
        "# Biomedical Evidence Report",
        "",
        f"- Run ID: `{result.run_id}`",
        f"- Generated at: `{_now_iso()}`",
        f"- Uncertainty: `{result.uncertainty_level}`",
        "",
        "## Answer",
        "",
        result.answer,
        "",
        "## Evidence",
        "",
    ]
    for item in result.evidence_summary:
        lines.append(
            f"- `{item.evidence_direction}` {item.claim} "
            f"(paper `{item.paper_id}`, confidence `{item.confidence}`)"
        )
    lines.extend(["", "## Citations", ""])
    for citation in result.citations:
        parts = [citation.title, citation.paper_id]
        if citation.doi:
            parts.append(f"doi:{citation.doi}")
        if citation.url:
            parts.append(citation.url)
        lines.append("- " + " | ".join(parts))
    if result.retrieval_manifest is not None:
        manifest = result.retrieval_manifest
        lines.extend(
            [
                "",
                "## Retrieval Provenance",
                "",
                f"- Retrieval ID: `{manifest.retrieval_id}`",
                f"- Source: `{manifest.source}`",
                f"- Original query: `{manifest.original_query}`",
                f"- Compiled query: `{manifest.compiled_query}`",
                f"- Result count: `{manifest.deduped_result_count}`",
                f"- Pages completed: `{manifest.pages_completed}`",
            ]
        )
        if manifest.warnings:
            lines.append(f"- Warnings: {'; '.join(manifest.warnings)}")
        if manifest.unsupported_filters:
            lines.append(
                f"- Unsupported filters: {'; '.join(manifest.unsupported_filters)}"
            )
    lines.extend(["", "## Limitations", ""])
    for limitation in result.limitations:
        lines.append(f"- {limitation}")
    lines.extend(["", "## Disclaimer", "", result.disclaimer])
    return "\n".join(lines)


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return clean[:80] or hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _with_graph_validation(
    graph: BiomedEvidenceGraph,
    *,
    validate: bool,
) -> BiomedEvidenceGraph:
    if not validate:
        return graph
    return graph.model_copy(update={"validation": validate_evidence_graph(graph)})


def _graph_scope_kind(
    *,
    topic: str,
    entity: str,
    paper_id: str,
    direction: str,
) -> str:
    if paper_id.strip():
        return "paper"
    if entity.strip():
        return "entity"
    if topic.strip():
        return "topic"
    if direction.strip():
        return "custom"
    return "global"


def _decision_id(watch_id: str, paper_id: str) -> str:
    digest = hashlib.sha256(f"{watch_id}:{paper_id}".encode("utf-8")).hexdigest()[:16]
    return f"wd-{digest}"


def _next_check(now_iso: str, schedule: str) -> str | None:
    if schedule == "manual":
        return None
    now = datetime.fromisoformat(now_iso)
    delta = timedelta(days=7 if schedule == "weekly" else 1)
    return (now + delta).isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
