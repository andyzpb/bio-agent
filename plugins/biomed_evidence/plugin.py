from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from agent.lifecycle.types import PreToolCtx, PromptRenderCtx
from agent.plugins import Plugin, on_tool_pre, tool
from agent.prompting import PromptSectionRender
from agent.tool_hooks import HookOutcome
from plugins.biomed_evidence.graph import (
    build_evidence_card as build_graph_evidence_card,
    graph_to_json_dict,
    shortest_path as graph_shortest_path,
    validate_evidence_graph as validate_graph_object,
)
from plugins.biomed_evidence.guardrails import is_clinical_request
from plugins.biomed_evidence.literature_client import LiteratureClientError
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    BiomedProject,
    BiomedProjectCreateRequest,
    BiomedProjectUpdateRequest,
    BiomedicalPaper,
    Citation,
    CitationAuditRequest,
    ConflictAuditRequest,
    CoverageGapAnalysisRequest,
    EvidenceBatchExtractionRequest,
    EvidenceExtractionRequest,
    EvidenceItem,
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
    SavedToolChainTemplateRunRequest,
    SavedToolChainTemplateSaveRequest,
    WatchTopicCreateRequest,
    WatchTopicUpdateRequest,
)
from plugins.biomed_evidence.service import BiomedEvidenceService
from plugins.biomed_evidence.tool_contracts import (
    list_release_tool_contracts,
    release_source_policy_error,
)

_PROMPT_CTX_SLOT = "prompt:ctx"

_RELEASE_TOOL_NAMES = frozenset(
    item.tool_name for item in list_release_tool_contracts()
)
_RELEASE_SOURCE_TOOL_NAMES = frozenset(
    item.tool_name
    for item in list_release_tool_contracts()
    if item.source_policy != "no_source"
)

_BIOMED_TOOL_NAMES = frozenset(
    {
        "plan_biomedical_search",
        "check_literature_access",
        "search_literature",
        "search_biomedical_literature",
        "fetch_biomedical_paper",
        "extract_evidence",
        "answer_with_evidence",
        "answer_with_audit",
        "create_biomed_project",
        "list_biomed_projects",
        "update_biomed_project",
        "record_project_paper_decision",
        "save_project_paper",
        "reject_project_paper",
        "list_project_paper_decisions",
        "record_project_claim",
        "save_project_claim",
        "list_project_evidence",
        "list_project_review_queue",
        "generate_project_evidence_brief",
        "watch_research_topic",
        "list_research_watch_topics",
        "update_research_watch_topic",
        "delete_research_watch_topic",
        "get_evidence_graph",
        "get_evidence_card",
        "validate_evidence_graph",
        "find_evidence_path",
        "export_evidence_graph_json",
        "get_run_evidence_review",
        "export_evidence_report",
        "validate_citation_support",
        "audit_biomedical_answer",
        "find_conflicting_evidence",
    }
) | _RELEASE_TOOL_NAMES

_TOOLS_WITH_SOURCE = frozenset(
    {
        "plan_biomedical_search",
        "check_literature_access",
        "search_literature",
        "search_biomedical_literature",
        "fetch_biomedical_paper",
        "answer_with_evidence",
        "answer_with_audit",
        "record_project_paper_decision",
        "save_project_paper",
        "reject_project_paper",
        "find_conflicting_evidence",
    }
) | (_RELEASE_SOURCE_TOOL_NAMES - {"run_saved_tool_chain_template"})

_TOOLS_WITH_PROJECT_ID = frozenset(
    {
        "search_literature",
        "run_multi_pass_literature_search",
        "answer_with_evidence",
        "answer_with_audit",
        "update_biomed_project",
        "record_project_paper_decision",
        "save_project_paper",
        "reject_project_paper",
        "list_project_paper_decisions",
        "record_project_claim",
        "save_project_claim",
        "list_project_evidence",
        "list_project_review_queue",
        "generate_project_evidence_brief",
        "export_project_to_obsidian",
        "run_saved_tool_chain_template",
    }
)

_TOOLS_WITH_OPTIONAL_ACTIVE_PROJECT = frozenset(
    {
        "search_literature",
        "run_multi_pass_literature_search",
        "answer_with_evidence",
        "answer_with_audit",
        "list_project_evidence",
        "list_project_review_queue",
        "generate_project_evidence_brief",
        "run_saved_tool_chain_template",
    }
)

_TOOL_LLM_FLAGS: dict[str, tuple[str, ...]] = {
    "plan_biomedical_search": ("use_llm_planner",),
    "answer_with_evidence": (
        "use_llm_planner",
        "execute_support_refute",
        "use_llm_extractor",
        "use_llm_synthesis",
    ),
    "answer_with_audit": (
        "use_llm_revision",
        "use_llm_planner",
        "execute_support_refute",
        "use_llm_extractor",
        "use_llm_synthesis",
        "use_llm_verifier",
        "use_llm_claim_logic",
        "export_logic_facts",
    ),
    "validate_citation_support": (
        "use_llm_claim_logic",
        "export_logic_facts",
    ),
    "run_multi_pass_literature_search": (
        "use_llm_planner",
        "execute_support_refute",
    ),
    "extract_evidence_batch": ("use_llm_extractor",),
}

_BIOMED_INTENT_TERMS = (
    "biomedical",
    "pubmed",
    "citation",
    "evidence",
    "paper",
    "abstract",
    "study",
    "trial",
    "cohort",
    "gene",
    "protein",
    "disease",
    "alzheimer",
    "microglia",
    "microglial",
    "amyloid",
    "tau",
    "neuro",
    "cancer",
    "inflammation",
    "pathway",
    "patient",
    "dose",
    "treatment",
)


class BiomedEvidencePlugin(Plugin):
    name = "biomed_evidence"

    async def initialize(self) -> None:
        workspace = self.context.workspace or (Path.home() / ".akashic" / "workspace")
        self._service = BiomedEvidenceService(workspace)

    async def terminate(self) -> None:
        service = getattr(self, "_service", None)
        if service is not None:
            await service.aclose()

    def prompt_render_modules(self) -> list[object]:
        return [BiomedPromptContextModule(self)]

    @on_tool_pre()
    async def guard_biomedical_tool(self, event: PreToolCtx) -> HookOutcome | None:
        if event.tool_name not in _BIOMED_TOOL_NAMES:
            return None
        args = dict(event.arguments)
        clinical_text = _clinical_signal_text(event, args)
        if is_clinical_request(clinical_text):
            return HookOutcome(
                decision="deny",
                reason=(
                    "biomed_evidence guardrail: clinical_boundary "
                    "(clinical_or_patient_specific_boundary). "
                    "Reframe the request as a non-clinical biomedical research question."
                ),
                extra_message=(
                    "Biomedical Evidence tools are research-only and were not executed "
                    "for a clinical or patient-specific request."
                ),
            )

        messages: list[str] = []
        project_error = self._validate_or_apply_project(event.tool_name, args, messages)
        if project_error:
            return HookOutcome(decision="deny", reason=project_error)
        source_error = self._apply_source_policy(event.tool_name, args, messages)
        if source_error:
            return HookOutcome(decision="deny", reason=source_error)
        self._apply_count_caps(args, messages)
        self._apply_search_defaults(event.tool_name, args, messages)
        self._apply_default_llm_flags(event.tool_name, args, messages)
        self._remember_tool_preferences(args)
        reason = "; ".join(messages)
        if args != event.arguments:
            return HookOutcome(
                updated_input=args,
                reason=reason,
                extra_message=reason,
            )
        if reason:
            return HookOutcome(reason=reason, extra_message=reason)
        return None

    @tool(
        name="plan_biomedical_search",
        risk="read-only",
        search_hint="classify biomedical question create structured retrieval plan",
    )
    async def plan_biomedical_search(
        self,
        event,
        question: str,
        max_results: int = 10,
        source: Literal["pubmed", "mock"] = "mock",
        project_context: str | None = None,
        use_llm_planner: bool = False,
    ) -> str:
        """Classify a biomedical question and produce a structured retrieval plan.

        Args:
            question: Biomedical research question.
            max_results: Maximum papers to retrieve if the plan is valid.
            source: Literature source.
            project_context: Optional user project context, treated as preference only.
            use_llm_planner: Request framework-governed LLM planning when configured.
        """
        result = await self._service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question=question,
                max_results=max_results,
                source=source,
                project_context=project_context,
                use_llm_planner=use_llm_planner,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="check_literature_access",
        risk="read-only",
        search_hint="check live PubMed biomedical literature access readiness",
    )
    async def check_literature_access(
        self,
        event,
        query: str = "microglia Alzheimer disease",
        max_results: int = 3,
        source: Literal["pubmed", "mock"] = "pubmed",
        date_from: str | None = None,
        date_to: str | None = None,
        require_abstract: bool = True,
    ) -> str:
        """Check whether the configured literature source is usable end to end.

        Args:
            query: Smoke query used for source readiness.
            max_results: Maximum papers to retrieve.
            source: Literature source, normally pubmed for live readiness.
            date_from: Optional publication date lower bound.
            date_to: Optional publication date upper bound.
            require_abstract: Require at least one fetched abstract for readiness.
        """
        result = await self._service.check_literature_access(
            LiteratureAccessCheckRequest(
                query=query,
                max_results=max_results,
                source=source,
                date_from=date_from,
                date_to=date_to,
                require_abstract=require_abstract,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="search_literature",
        risk="read-only",
        search_hint="controlled biomedical literature search PubMed mock retrieval manifest",
    )
    async def search_literature(
        self,
        event,
        query: str,
        max_results: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
        source: Literal["pubmed", "mock"] = "mock",
        mesh_terms: list[str] | None = None,
        article_types: list[str] | None = None,
        publication_types: list[str] | None = None,
        study_types: list[str] | None = None,
        species_terms: list[str] | None = None,
        exclude_terms: list[str] | None = None,
        retrieval_intent: Literal[
            "primary",
            "background",
            "support",
            "refute",
            "mechanism",
            "limitation",
            "recent",
            "unknown",
        ] = "unknown",
        project_id: str | None = None,
        require_abstract: bool = True,
        store: bool = True,
    ) -> str:
        """Run controlled biomedical literature retrieval without synthesizing an answer.

        Args:
            query: Biomedical literature query.
            max_results: Maximum number of papers to return.
            date_from: Optional publication date lower bound.
            date_to: Optional publication date upper bound.
            source: Literature source, default mock for deterministic demos.
            mesh_terms: Optional MeSH terms for structured sources.
            article_types: Optional publication/article type filters.
            publication_types: Optional PubMed publication type filters.
            study_types: Optional study-design hints.
            species_terms: Optional species MeSH terms.
            exclude_terms: Optional exclusion terms.
            retrieval_intent: Retrieval purpose for downstream trace.
            project_id: Optional project context for validation and trace only.
            require_abstract: Whether abstract coverage should be reported as required.
            store: Persist retrieved papers for downstream evidence workflows.
        """
        try:
            result = await self._service.search_literature(
                LiteratureSearchRequest(
                    query=query,
                    max_results=max_results,
                    date_from=date_from,
                    date_to=date_to,
                    source=source,
                    mesh_terms=mesh_terms or [],
                    article_types=article_types or [],
                    publication_types=publication_types or [],
                    study_types=study_types or [],
                    species_terms=species_terms or [],
                    exclude_terms=exclude_terms or [],
                    retrieval_intent=retrieval_intent,
                    project_id=project_id,
                    require_abstract=require_abstract,
                    store=store,
                )
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        except LiteratureClientError as exc:
            return _dump(
                {
                    "error": "literature_client_error",
                    "message": str(exc),
                    "source": source,
                    "query": query,
                }
            )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="search_biomedical_literature",
        risk="read-only",
        search_hint="PubMed biomedical literature paper search mock",
    )
    async def search_biomedical_literature(
        self,
        event,
        query: str,
        max_results: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
        source: Literal["pubmed", "mock"] = "mock",
    ) -> str:
        """Search biomedical literature metadata.

        Args:
            query: Biomedical literature query.
            max_results: Maximum number of papers to return.
            date_from: Optional publication date lower bound.
            date_to: Optional publication date upper bound.
            source: Literature source, default mock for deterministic demos.
        """
        try:
            result = await self._service.search_literature(
                LiteratureSearchRequest(
                    query=query,
                    max_results=max_results,
                    date_from=date_from,
                    date_to=date_to,
                    source=source,
                )
            )
        except LiteratureClientError as exc:
            return _dump(
                {
                    "error": "literature_client_error",
                    "message": str(exc),
                    "source": source,
                    "query": query,
                }
            )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="fetch_biomedical_paper",
        risk="read-only",
        search_hint="fetch PubMed paper abstract metadata",
    )
    async def fetch_biomedical_paper(
        self,
        event,
        paper_id: str,
        source: Literal["pubmed", "mock"] = "mock",
    ) -> str:
        """Fetch biomedical paper metadata and abstract.

        Args:
            paper_id: Source paper identifier.
            source: Literature source.
        """
        paper = await self._service.fetch(
            FetchBiomedicalPaperRequest(paper_id=paper_id, source=source)
        )
        if paper is None:
            return _dump({"paper": None, "error": "paper_not_found"})
        return _dump({"paper": paper.model_dump(mode="json")})

    @tool(
        name="extract_evidence",
        risk="read-only",
        search_hint="extract biomedical claims entities limitations evidence",
    )
    async def extract_evidence(
        self,
        event,
        paper: dict,
        research_question: str | None = None,
    ) -> str:
        """Extract structured evidence from a biomedical paper object.

        Args:
            paper: BiomedicalPaper-compatible object.
            research_question: Optional question used to select evidence.
        """
        request = EvidenceExtractionRequest(
            paper=BiomedicalPaper.model_validate(paper),
            research_question=research_question,
        )
        result = self._service.extract_evidence(request)
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="create_biomed_project",
        risk="read-write",
        search_hint="create biomedical project workspace memory evidence review",
    )
    async def create_biomed_project(
        self,
        event,
        name: str,
        description: str | None = None,
        research_question: str = "",
        include_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        preferred_methods: list[str] | None = None,
        preferred_species: list[str] | None = None,
        preferred_study_types: list[str] | None = None,
    ) -> str:
        """Create a biomedical evidence project workspace."""
        project = self._service.create_project(
            BiomedProjectCreateRequest(
                name=name,
                description=description,
                research_question=research_question,
                include_keywords=include_keywords or [],
                exclude_keywords=exclude_keywords or [],
                preferred_methods=preferred_methods or [],
                preferred_species=preferred_species or [],
                preferred_study_types=preferred_study_types or [],
            )
        )
        return _dump(project.model_dump(mode="json"))

    @tool(
        name="list_biomed_projects",
        risk="read-only",
        search_hint="list biomedical project workspaces",
    )
    async def list_biomed_projects(
        self,
        event,
        page: int = 1,
        page_size: int = 50,
    ) -> str:
        """List biomedical evidence project workspaces."""
        items, total = self._service.list_projects(page=page, page_size=page_size)
        return _dump(
            {
                "items": [item.model_dump(mode="json") for item in items],
                "total": total,
            }
        )

    @tool(
        name="update_biomed_project",
        risk="read-write",
        search_hint="update biomedical project workspace preferences",
    )
    async def update_biomed_project(
        self,
        event,
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        research_question: str | None = None,
        include_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        preferred_methods: list[str] | None = None,
        preferred_species: list[str] | None = None,
        preferred_study_types: list[str] | None = None,
    ) -> str:
        """Update a biomedical evidence project workspace."""
        project = self._service.update_project(
            project_id,
            BiomedProjectUpdateRequest(
                name=name,
                description=description,
                research_question=research_question,
                include_keywords=include_keywords,
                exclude_keywords=exclude_keywords,
                preferred_methods=preferred_methods,
                preferred_species=preferred_species,
                preferred_study_types=preferred_study_types,
            ),
        )
        if project is None:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(project.model_dump(mode="json"))

    @tool(
        name="record_project_paper_decision",
        risk="read-write",
        search_hint="save reject needs review biomedical project paper",
    )
    async def record_project_paper_decision(
        self,
        event,
        project_id: str,
        paper_id: str,
        source: Literal["pubmed", "mock"] = "mock",
        decision: Literal["saved", "rejected", "needs_review"] = "saved",
        reason: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        run_id: str | None = None,
        retrieval_id: str | None = None,
    ) -> str:
        """Record a project paper decision used for future retrieval filtering."""
        try:
            result = self._service.save_project_paper_decision(
                project_id,
                ProjectPaperDecisionRequest(
                    paper_id=paper_id,
                    source=source,
                    decision=decision,
                    reason=reason,
                    tags=tags or [],
                    notes=notes,
                    run_id=run_id,
                    retrieval_id=retrieval_id,
                ),
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="save_project_paper",
        risk="read-write",
        search_hint="save biomedical project paper",
    )
    async def save_project_paper(
        self,
        event,
        project_id: str,
        paper_id: str,
        source: Literal["pubmed", "mock"] = "mock",
        reason: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        run_id: str | None = None,
        retrieval_id: str | None = None,
    ) -> str:
        """Mark a paper as saved in a project."""
        try:
            result = self._service.save_project_paper_decision(
                project_id,
                ProjectPaperDecisionRequest(
                    paper_id=paper_id,
                    source=source,
                    decision="saved",
                    reason=reason,
                    tags=tags or [],
                    notes=notes,
                    run_id=run_id,
                    retrieval_id=retrieval_id,
                ),
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="reject_project_paper",
        risk="read-write",
        search_hint="reject biomedical project paper",
    )
    async def reject_project_paper(
        self,
        event,
        project_id: str,
        paper_id: str,
        source: Literal["pubmed", "mock"] = "mock",
        reason: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        run_id: str | None = None,
        retrieval_id: str | None = None,
    ) -> str:
        """Mark a paper as rejected in a project."""
        try:
            result = self._service.save_project_paper_decision(
                project_id,
                ProjectPaperDecisionRequest(
                    paper_id=paper_id,
                    source=source,
                    decision="rejected",
                    reason=reason,
                    tags=tags or [],
                    notes=notes,
                    run_id=run_id,
                    retrieval_id=retrieval_id,
                ),
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="list_project_paper_decisions",
        risk="read-only",
        search_hint="list biomedical project saved rejected papers",
    )
    async def list_project_paper_decisions(
        self,
        event,
        project_id: str,
        decision: Literal["", "saved", "rejected", "needs_review"] = "",
        page: int = 1,
        page_size: int = 100,
    ) -> str:
        """List project paper decisions."""
        try:
            items, total = self._service.list_project_paper_decisions(
                project_id,
                decision=decision,
                page=page,
                page_size=page_size,
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(
            {
                "items": [item.model_dump(mode="json") for item in items],
                "total": total,
            }
        )

    @tool(
        name="record_project_claim",
        risk="read-write",
        search_hint="record biomedical project claim evidence audit status",
    )
    async def record_project_claim(
        self,
        event,
        project_id: str,
        claim: str,
        status: Literal[
            "supported",
            "mixed",
            "uncertain",
            "rejected",
            "needs_review",
        ] = "needs_review",
        evidence_ids: list[str] | None = None,
        audit_ids: list[str] | None = None,
        verifier_ids: list[str] | None = None,
        notes: str | None = None,
    ) -> str:
        """Record a project-level claim linked to audited evidence."""
        try:
            result = self._service.save_project_claim_record(
                project_id,
                ProjectClaimRecordRequest(
                    claim=claim,
                    status=status,
                    evidence_ids=evidence_ids or [],
                    audit_ids=audit_ids or [],
                    verifier_ids=verifier_ids or [],
                    notes=notes,
                ),
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="save_project_claim",
        risk="read-write",
        search_hint="save biomedical project claim",
    )
    async def save_project_claim(
        self,
        event,
        project_id: str,
        claim: str,
        status: Literal[
            "supported",
            "mixed",
            "uncertain",
            "rejected",
            "needs_review",
        ] = "needs_review",
        evidence_ids: list[str] | None = None,
        audit_ids: list[str] | None = None,
        verifier_ids: list[str] | None = None,
        notes: str | None = None,
    ) -> str:
        """Save a project-level claim linked to audited evidence."""
        try:
            result = self._service.save_project_claim_record(
                project_id,
                ProjectClaimRecordRequest(
                    claim=claim,
                    status=status,
                    evidence_ids=evidence_ids or [],
                    audit_ids=audit_ids or [],
                    verifier_ids=verifier_ids or [],
                    notes=notes,
                ),
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="list_project_evidence",
        risk="read-only",
        search_hint="list biomedical project evidence decisions claims queue briefs",
    )
    async def list_project_evidence(
        self,
        event,
        project_id: str,
        page: int = 1,
        page_size: int = 100,
    ) -> str:
        """Return a project evidence workspace snapshot."""
        try:
            paper_decisions, paper_total = self._service.list_project_paper_decisions(
                project_id,
                page=page,
                page_size=page_size,
            )
            claims, claim_total = self._service.list_project_claim_records(
                project_id,
                page=page,
                page_size=page_size,
            )
            review_queue, review_total = self._service.list_project_review_queue(
                project_id,
                page=page,
                page_size=page_size,
            )
            briefs, brief_total = self._service.list_project_briefs(
                project_id,
                page=page,
                page_size=page_size,
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(
            {
                "project_id": project_id,
                "paper_decisions": [
                    item.model_dump(mode="json") for item in paper_decisions
                ],
                "paper_decision_total": paper_total,
                "claims": [item.model_dump(mode="json") for item in claims],
                "claim_total": claim_total,
                "review_queue": [item.model_dump(mode="json") for item in review_queue],
                "review_queue_total": review_total,
                "briefs": [item.model_dump(mode="json") for item in briefs],
                "brief_total": brief_total,
            }
        )

    @tool(
        name="list_project_review_queue",
        risk="read-only",
        search_hint="list biomedical project review queue audit verifier",
    )
    async def list_project_review_queue(
        self,
        event,
        project_id: str,
        page: int = 1,
        page_size: int = 100,
    ) -> str:
        """List project review queue items generated from audit/verifier runs."""
        try:
            items, total = self._service.list_project_review_queue(
                project_id,
                page=page,
                page_size=page_size,
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(
            {
                "items": [item.model_dump(mode="json") for item in items],
                "total": total,
            }
        )

    @tool(
        name="generate_project_evidence_brief",
        risk="read-write",
        search_hint="generate biomedical project evidence brief",
    )
    async def generate_project_evidence_brief(
        self,
        event,
        project_id: str,
        title: str | None = None,
        format: Literal["markdown", "json"] = "markdown",
    ) -> str:
        """Generate and persist a project evidence brief."""
        try:
            brief = self._service.generate_project_evidence_brief(
                GenerateProjectEvidenceBriefRequest(
                    project_id=project_id,
                    title=title,
                    format=format,
                )
            )
        except ValueError:
            return _dump({"error": "project_not_found", "project_id": project_id})
        return _dump(brief.model_dump(mode="json"))

    @tool(
        name="list_biomed_workflow_templates",
        risk="read-only",
        search_hint="list saved biomedical workflow tool chain templates",
    )
    async def list_biomed_workflow_templates(self, event) -> str:
        """List built-in and saved biomedical tool-chain workflow templates."""
        result = self._service.list_workflow_templates()
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="save_biomed_workflow_template",
        risk="read-write",
        search_hint="save biomedical workflow tool chain template",
    )
    async def save_biomed_workflow_template(
        self,
        event,
        name: str,
        template_id: str | None = None,
        description: str | None = None,
        source: Literal["pubmed", "mock"] = "mock",
        max_papers: int = 5,
        execute_support_refute: bool = True,
        use_llm_planner: bool = False,
        use_llm_extractor: bool = False,
        use_llm_synthesis: bool = False,
        use_llm_verifier: bool = False,
        use_llm_revision: bool = False,
        use_llm_claim_logic: bool = False,
        export_logic_facts: bool = False,
        export_provenance: bool = True,
    ) -> str:
        """Save a reusable biomedical audited-answer workflow template."""
        try:
            result = self._service.save_workflow_template(
                SavedToolChainTemplateSaveRequest(
                    template_id=template_id,
                    name=name,
                    description=description,
                    source=source,
                    max_papers=max_papers,
                    execute_support_refute=execute_support_refute,
                    use_llm_planner=use_llm_planner,
                    use_llm_extractor=use_llm_extractor,
                    use_llm_synthesis=use_llm_synthesis,
                    use_llm_verifier=use_llm_verifier,
                    use_llm_revision=use_llm_revision,
                    use_llm_claim_logic=use_llm_claim_logic,
                    export_logic_facts=export_logic_facts,
                    export_provenance=export_provenance,
                    required_skills=[
                        "biomed-evidence-review",
                        "biomed-clinical-boundary",
                    ],
                    stop_conditions=[
                        "clinical_boundary",
                        "source_policy_blocked",
                        "empty_evidence",
                    ],
                )
            )
        except ValueError as exc:
            return _dump({"error": "invalid_template", "message": str(exc)})
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="delete_biomed_workflow_template",
        risk="read-write",
        search_hint="delete custom biomedical workflow template",
    )
    async def delete_biomed_workflow_template(self, event, template_id: str) -> str:
        """Delete a custom biomedical workflow template. Built-ins are immutable."""
        return _dump(
            {
                "deleted": self._service.delete_workflow_template(template_id),
                "template_id": template_id,
            }
        )

    @tool(
        name="run_saved_tool_chain_template",
        risk="read-only",
        search_hint="run saved biomedical tool chain template audited answer",
    )
    async def run_saved_tool_chain_template(
        self,
        event,
        template_id: str,
        question: str,
        project_id: str | None = None,
        project_context: str | None = None,
        source_override: Literal["pubmed", "mock"] | None = None,
        max_papers_override: int | None = None,
        allow_live_pubmed: bool | None = None,
    ) -> str:
        """Run a saved biomedical workflow template with policy revalidation."""
        result = await self._service.run_workflow_template(
            template_id,
            SavedToolChainTemplateRunRequest(
                question=question,
                project_id=project_id,
                project_context=project_context,
                source_override=source_override,
                max_papers_override=max_papers_override,
                allow_live_pubmed=(
                    allow_live_pubmed
                    if allow_live_pubmed is not None
                    else _config_bool(self, "allow_live_pubmed_tools", False)
                ),
            ),
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="answer_with_evidence",
        risk="read-only",
        search_hint="citation grounded biomedical research answer",
    )
    async def answer_with_evidence(
        self,
        event,
        question: str,
        max_papers: int = 10,
        project_id: str | None = None,
        project_context: str | None = None,
        require_citations: bool = True,
        source: Literal["pubmed", "mock"] = "mock",
        include_rejected_papers: bool = False,
        use_llm_planner: bool = False,
        execute_support_refute: bool = False,
        use_llm_extractor: bool = False,
        use_llm_synthesis: bool = False,
    ) -> str:
        """Answer a biomedical research question with citations and uncertainty.

        Args:
            question: Biomedical research question.
            max_papers: Maximum papers to retrieve.
            project_id: Optional biomedical project workspace id.
            project_context: Optional user project context, treated as preference only.
            require_citations: Whether to avoid strong claims without citations.
            source: Literature source.
            include_rejected_papers: Include papers previously rejected in the project.
            use_llm_planner: Request framework-governed retrieval planning when configured.
            execute_support_refute: Execute planner support/refute queries and bundle manifests.
            use_llm_extractor: Request framework-governed span-grounded evidence extraction.
            use_llm_synthesis: Request framework-governed evidence-constrained synthesis.
        """
        result = await self._service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question=question,
                max_papers=max_papers,
                project_id=project_id,
                project_context=project_context,
                require_citations=require_citations,
                source=source,
                include_rejected_papers=include_rejected_papers,
                use_llm_planner=use_llm_planner,
                execute_support_refute=execute_support_refute,
                use_llm_extractor=use_llm_extractor,
                use_llm_synthesis=use_llm_synthesis,
                use_llm_revision=False,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="answer_with_audit",
        risk="read-only",
        search_hint="citation audited biomedical research answer with trace",
    )
    async def answer_with_audit(
        self,
        event,
        question: str,
        max_papers: int = 10,
        project_id: str | None = None,
        project_context: str | None = None,
        require_citations: bool = True,
        source: Literal["pubmed", "mock"] = "mock",
        include_rejected_papers: bool = False,
        use_llm_revision: bool = False,
        use_llm_planner: bool = False,
        execute_support_refute: bool = False,
        use_llm_extractor: bool = False,
        use_llm_synthesis: bool = False,
        use_llm_verifier: bool = False,
        use_llm_claim_logic: bool = False,
        export_logic_facts: bool = False,
    ) -> str:
        """Answer a biomedical research question, audit claims, revise, and return trace.

        Args:
            question: Biomedical research question.
            max_papers: Maximum papers to retrieve.
            project_id: Optional biomedical project workspace id.
            project_context: Optional user project context, treated as preference only.
            require_citations: Whether to avoid strong claims without citations.
            source: Literature source.
            include_rejected_papers: Include papers previously rejected in the project.
            use_llm_revision: Request framework-governed LLM revision when configured.
            use_llm_planner: Request framework-governed retrieval planning when configured.
            execute_support_refute: Execute planner support/refute queries and bundle manifests.
            use_llm_extractor: Request framework-governed span-grounded evidence extraction.
            use_llm_synthesis: Request framework-governed evidence-constrained synthesis.
            use_llm_verifier: Request framework-governed advisory verifier review.
            use_llm_claim_logic: Request claim logic audit frames; falls back deterministically when no LLM parser is configured.
            export_logic_facts: Export deterministic symbolic logic facts for audited claims.
        """
        result = await self._service.answer_with_audit(
            AnswerWithEvidenceRequest(
                question=question,
                max_papers=max_papers,
                project_id=project_id,
                project_context=project_context,
                require_citations=require_citations,
                source=source,
                include_rejected_papers=include_rejected_papers,
                use_llm_revision=use_llm_revision,
                use_llm_planner=use_llm_planner,
                execute_support_refute=execute_support_refute,
                use_llm_extractor=use_llm_extractor,
                use_llm_synthesis=use_llm_synthesis,
                use_llm_verifier=use_llm_verifier,
                use_llm_claim_logic=use_llm_claim_logic,
                export_logic_facts=export_logic_facts,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="run_multi_pass_literature_search",
        risk="read-only",
        search_hint="toolized biomedical planner retrieval bundle no answer",
    )
    async def run_multi_pass_literature_search(
        self,
        event,
        question: str,
        source: Literal["pubmed", "mock"] = "mock",
        max_results: int = 10,
        max_queries: int = 6,
        max_followups: int = 0,
        max_tool_steps: int = 20,
        max_wall_clock_seconds: int = 180,
        project_id: str | None = None,
        project_context: str | None = None,
        include_rejected_papers: bool = False,
        use_llm_planner: bool = False,
        execute_support_refute: bool = True,
    ) -> str:
        """Run planner plus controlled literature retrieval without answering."""
        result = await self._service.run_multi_pass_literature_search(
            MultiPassLiteratureSearchRequest(
                question=question,
                source=source,
                max_results=max_results,
                max_queries=max_queries,
                max_followups=max_followups,
                max_tool_steps=max_tool_steps,
                max_wall_clock_seconds=max_wall_clock_seconds,
                project_id=project_id,
                project_context=project_context,
                include_rejected_papers=include_rejected_papers,
                use_llm_planner=use_llm_planner,
                execute_support_refute=execute_support_refute,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="extract_evidence_batch",
        risk="read-only",
        search_hint="toolized batch evidence extraction from run retrieval papers",
    )
    async def extract_evidence_batch(
        self,
        event,
        run_id: str | None = None,
        retrieval_id: str | None = None,
        paper_ids: list[str] | None = None,
        source: Literal["pubmed", "mock"] = "mock",
        research_question: str | None = None,
        use_llm_extractor: bool = False,
        max_papers: int = 10,
        max_evidence_items: int = 50,
    ) -> str:
        """Extract evidence from a run, retrieval manifest, or explicit paper ids."""
        result = await self._service.extract_evidence_batch(
            EvidenceBatchExtractionRequest(
                run_id=run_id,
                retrieval_id=retrieval_id,
                paper_ids=paper_ids or [],
                source=source,
                research_question=research_question,
                use_llm_extractor=use_llm_extractor,
                max_papers=max_papers,
                max_evidence_items=max_evidence_items,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="analyze_coverage_gaps",
        risk="read-only",
        search_hint="toolized coverage gap analysis advisory only",
    )
    async def analyze_coverage_gaps(
        self,
        event,
        run_id: str | None = None,
        retrieval_id: str | None = None,
        source: Literal["pubmed", "mock"] = "mock",
        research_question: str | None = None,
        max_gap_queries: int = 2,
    ) -> str:
        """Analyze evidence coverage gaps without fetching or inventing evidence."""
        result = self._service.analyze_coverage_gaps(
            CoverageGapAnalysisRequest(
                run_id=run_id,
                retrieval_id=retrieval_id,
                source=source,
                research_question=research_question,
                max_gap_queries=max_gap_queries,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="build_evidence_packet",
        risk="read-only",
        search_hint="toolized evidence packet builder selection trace",
    )
    async def build_evidence_packet(
        self,
        event,
        run_id: str,
        max_evidence_items: int = 12,
        selection_strategy: Literal["all_valid", "submodular_greedy"] = "submodular_greedy",
    ) -> str:
        """Build or refresh a single downstream evidence packet for a run."""
        result = self._service.build_evidence_packet(
            EvidencePacketBuildRequest(
                run_id=run_id,
                max_evidence_items=max_evidence_items,
                selection_strategy=selection_strategy,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="get_evidence_packet",
        risk="read-only",
        search_hint="get persisted evidence packet no retrieval",
    )
    async def get_evidence_packet(self, event, run_id: str) -> str:
        """Return a persisted evidence packet without running retrieval."""
        result = self._service.get_evidence_packet(run_id)
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="get_answer_trace",
        risk="read-only",
        search_hint="get answer trace telemetry memory audit revision",
    )
    async def get_answer_trace(self, event, run_id: str) -> str:
        """Return persisted audited-answer trace and advisory telemetry."""
        result = self._service.get_answer_trace(run_id)
        if result is None:
            return _dump({"ok": False, "error_code": "unknown_run_id", "run_id": run_id})
        return _dump(result)

    @tool(
        name="export_provenance_graph",
        risk="read-only",
        search_hint="export answer run provenance graph prov openlineage compatible",
    )
    async def export_provenance_graph(self, event, run_id: str) -> str:
        """Return a redacted provenance graph for an answer run."""
        result = self._service.export_provenance_graph(run_id)
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="export_evidence_packet_to_obsidian",
        risk="read-write",
        search_hint="export evidence packet reviewer note obsidian one way",
    )
    async def export_evidence_packet_to_obsidian(
        self,
        event,
        run_id: str,
        export_dir: str | None = None,
        enabled: bool | None = None,
        max_files: int | None = None,
    ) -> str:
        """Export a persisted evidence packet as one-way Obsidian Markdown."""
        result = self._service.export_evidence_packet_to_obsidian(
            ObsidianExportRequest(
                run_id=run_id,
                export_dir=export_dir or _config_str(self, "obsidian_export_dir", ""),
                enabled=(
                    enabled
                    if enabled is not None
                    else _config_bool(self, "enable_obsidian_export", False)
                ),
                max_files=max_files
                if max_files is not None
                else _config_int(self, "max_obsidian_export_files", 50),
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="export_project_to_obsidian",
        risk="read-write",
        search_hint="export biomedical project reviewer memory obsidian one way",
    )
    async def export_project_to_obsidian(
        self,
        event,
        project_id: str,
        export_dir: str | None = None,
        enabled: bool | None = None,
        max_files: int | None = None,
    ) -> str:
        """Export a biomedical project as one-way Obsidian Markdown."""
        result = self._service.export_project_to_obsidian(
            ObsidianExportRequest(
                project_id=project_id,
                export_dir=export_dir or _config_str(self, "obsidian_export_dir", ""),
                enabled=(
                    enabled
                    if enabled is not None
                    else _config_bool(self, "enable_obsidian_export", False)
                ),
                max_files=max_files
                if max_files is not None
                else _config_int(self, "max_obsidian_export_files", 50),
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="export_research_watch_to_obsidian",
        risk="read-write",
        search_hint="export research watch reviewer note obsidian one way",
    )
    async def export_research_watch_to_obsidian(
        self,
        event,
        watch_id: str,
        export_dir: str | None = None,
        enabled: bool | None = None,
        max_files: int | None = None,
    ) -> str:
        """Export a research watch topic as one-way Obsidian Markdown."""
        result = self._service.export_research_watch_to_obsidian(
            ObsidianExportRequest(
                watch_id=watch_id,
                export_dir=export_dir or _config_str(self, "obsidian_export_dir", ""),
                enabled=(
                    enabled
                    if enabled is not None
                    else _config_bool(self, "enable_obsidian_export", False)
                ),
                max_files=max_files
                if max_files is not None
                else _config_int(self, "max_obsidian_export_files", 50),
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="validate_citation_support",
        risk="read-only",
        search_hint="audit biomedical answer claim citation evidence support",
    )
    async def validate_citation_support(
        self,
        event,
        answer: str,
        citations: list[dict] | None = None,
        evidence_items: list[dict] | None = None,
        run_id: str | None = None,
        retrieval_id: str | None = None,
        observed_uncertainty: Literal["low", "medium", "high"] | None = None,
        use_llm_claim_logic: bool = False,
        export_logic_facts: bool = False,
    ) -> str:
        """Audit whether biomedical answer claims are supported by citations.

        Args:
            answer: Answer text to audit.
            citations: Citation objects from answer_with_evidence.
            evidence_items: EvidenceItem objects from answer_with_evidence.
            run_id: Optional answer run id.
            retrieval_id: Optional retrieval manifest id.
            observed_uncertainty: Answer uncertainty label.
            use_llm_claim_logic: Request claim logic audit frames; falls back deterministically when no LLM parser is configured.
            export_logic_facts: Export deterministic symbolic logic facts for audited claims.
        """
        result = self._service.audit_answer(
            CitationAuditRequest(
                answer=answer,
                citations=[Citation.model_validate(item) for item in (citations or [])],
                evidence_items=[
                    EvidenceItem.model_validate(item) for item in (evidence_items or [])
                ],
                run_id=run_id,
                retrieval_id=retrieval_id,
                observed_uncertainty=observed_uncertainty,
                use_llm_claim_logic=use_llm_claim_logic,
                export_logic_facts=export_logic_facts,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="audit_biomedical_answer",
        risk="read-only",
        search_hint="audit saved biomedical answer run claims citations",
    )
    async def audit_biomedical_answer(
        self,
        event,
        run_id: str,
    ) -> str:
        """Audit a saved biomedical answer run by run id.

        Args:
            run_id: Saved answer run id.
        """
        result = self._service.audit_answer_run(run_id)
        if result is None:
            return _dump({"error": "answer_run_not_found", "run_id": run_id})
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="find_conflicting_evidence",
        risk="read-only",
        search_hint="find supporting contradicting inconclusive biomedical evidence",
    )
    async def find_conflicting_evidence(
        self,
        event,
        claim: str,
        topic: str = "",
        source: Literal["pubmed", "mock"] = "mock",
        evidence_items: list[dict] | None = None,
        retrieval_id: str | None = None,
    ) -> str:
        """Find conflict signals for a biomedical claim.

        Args:
            claim: Claim to inspect.
            topic: Optional topic used to retrieve stored evidence.
            source: Literature source.
            evidence_items: Optional EvidenceItem objects to inspect directly.
            retrieval_id: Optional retrieval manifest id.
        """
        result = self._service.find_conflicting_evidence(
            ConflictAuditRequest(
                claim=claim,
                topic=topic,
                source=source,
                evidence_items=[
                    EvidenceItem.model_validate(item) for item in (evidence_items or [])
                ],
                retrieval_id=retrieval_id,
            )
        )
        return _dump(result.model_dump(mode="json"))

    @tool(
        name="watch_research_topic",
        risk="read-write",
        search_hint="create biomedical research watch topic",
    )
    async def watch_research_topic(
        self,
        event,
        topic: str,
        description: str | None = None,
        include_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        preferred_methods: list[str] | None = None,
        min_relevance_score: float = 0.7,
        schedule: Literal["daily", "weekly", "manual"] = "daily",
    ) -> str:
        """Create a biomedical research watch topic.

        Args:
            topic: Topic to monitor.
            description: Optional topic description.
            include_keywords: Keywords that increase relevance.
            exclude_keywords: Keywords that exclude papers.
            preferred_methods: Preferred study methods.
            min_relevance_score: Push threshold.
            schedule: daily, weekly, or manual.
        """
        watch = self._service.create_watch(
            WatchTopicCreateRequest(
                topic=topic,
                description=description,
                include_keywords=include_keywords or [],
                exclude_keywords=exclude_keywords or [],
                preferred_methods=preferred_methods or [],
                min_relevance_score=min_relevance_score,
                schedule=schedule,
            )
        )
        return _dump(watch.model_dump(mode="json"))

    @tool(
        name="list_research_watch_topics",
        risk="read-only",
        search_hint="list biomedical research watch topics",
    )
    async def list_research_watch_topics(
        self,
        event,
        page: int = 1,
        page_size: int = 100,
    ) -> str:
        """List biomedical research watch topics.

        Args:
            page: Page number.
            page_size: Page size.
        """
        items, total = self._service.list_watches(page=page, page_size=page_size)
        return _dump(
            {
                "items": [item.model_dump(mode="json") for item in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        )

    @tool(
        name="update_research_watch_topic",
        risk="read-write",
        search_hint="update pause resume biomedical watch topic",
    )
    async def update_research_watch_topic(
        self,
        event,
        watch_id: str,
        topic: str | None = None,
        description: str | None = None,
        include_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
        preferred_methods: list[str] | None = None,
        min_relevance_score: float | None = None,
        schedule: Literal["daily", "weekly", "manual"] | None = None,
        enabled: bool | None = None,
    ) -> str:
        """Update a biomedical research watch topic.

        Args:
            watch_id: Watch topic id.
            topic: New topic text.
            description: New description.
            include_keywords: Replacement include keywords.
            exclude_keywords: Replacement exclude keywords.
            preferred_methods: Replacement preferred methods.
            min_relevance_score: New threshold.
            schedule: New schedule.
            enabled: Whether watch is active.
        """
        watch = self._service.update_watch(
            watch_id,
            WatchTopicUpdateRequest(
                topic=topic,
                description=description,
                include_keywords=include_keywords,
                exclude_keywords=exclude_keywords,
                preferred_methods=preferred_methods,
                min_relevance_score=min_relevance_score,
                schedule=schedule,
                enabled=enabled,
            ),
        )
        if watch is None:
            return _dump({"error": "watch_not_found", "watch_id": watch_id})
        return _dump(watch.model_dump(mode="json"))

    @tool(
        name="delete_research_watch_topic",
        risk="read-write",
        search_hint="delete biomedical research watch topic",
    )
    async def delete_research_watch_topic(
        self,
        event,
        watch_id: str,
    ) -> str:
        """Delete a biomedical research watch topic.

        Args:
            watch_id: Watch topic id.
        """
        return _dump(
            {"deleted": self._service.delete_watch(watch_id), "watch_id": watch_id}
        )

    @tool(
        name="get_evidence_graph",
        risk="read-only",
        search_hint="biomedical evidence graph entities claims papers",
    )
    async def get_evidence_graph(
        self,
        event,
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
    ) -> str:
        """Get a lightweight biomedical evidence graph.

        Args:
            topic: Optional topic filter.
            entity: Optional entity filter.
            paper_id: Optional paper id filter.
            direction: Optional evidence direction filter.
        """
        graph = self._service.get_graph(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
        )
        return _dump(graph.model_dump(mode="json"))

    @tool(
        name="get_evidence_card",
        risk="read-only",
        search_hint="biomedical evidence card claim support paper audit graph",
    )
    async def get_evidence_card(
        self,
        event,
        claim_id: str,
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
        run_id: str = "",
    ) -> str:
        """Get an evidence card for a biomedical claim in the v1 evidence graph."""
        graph = self._service.get_graph_v1(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
            run_id=run_id,
        )
        if graph is None:
            return _dump({"error_code": "unknown_run_id", "run_id": run_id})
        node_id = claim_id if claim_id.startswith("claim:") else f"claim:{claim_id}"
        try:
            card = build_graph_evidence_card(graph, node_id)
        except ValueError:
            return _dump({"error_code": "unknown_claim_id", "claim_id": claim_id})
        return _dump(card.model_dump(mode="json"))

    @tool(
        name="validate_evidence_graph",
        risk="read-only",
        search_hint="validate biomedical evidence graph claim support provenance",
    )
    async def validate_evidence_graph(
        self,
        event,
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
        run_id: str = "",
    ) -> str:
        """Validate a v1 biomedical evidence graph built from current storage."""
        graph = self._service.get_graph_v1(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
            run_id=run_id,
        )
        if graph is None:
            return _dump({"error_code": "unknown_run_id", "run_id": run_id})
        return _dump(validate_graph_object(graph).model_dump(mode="json"))

    @tool(
        name="find_evidence_path",
        risk="read-only",
        search_hint="find path between biomedical evidence graph nodes claim paper entity",
    )
    async def find_evidence_path(
        self,
        event,
        source: str,
        target: str,
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
        run_id: str = "",
        max_depth: int = 6,
    ) -> str:
        """Find a short path between two v1 evidence graph node IDs."""
        graph = self._service.get_graph_v1(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
            run_id=run_id,
        )
        if graph is None:
            return _dump({"error_code": "unknown_run_id", "run_id": run_id})
        path = graph_shortest_path(
            graph,
            source,
            target,
            max_depth=max(1, min(max_depth, 20)),
        )
        if not path:
            return _dump(
                {
                    "error_code": "graph_path_not_found",
                    "source": source,
                    "target": target,
                }
            )
        nodes = {node.id: node for node in graph.nodes}
        return _dump(
            {
                "schema_version": graph.schema_version,
                "path": path,
                "nodes": [
                    nodes[node_id].model_dump(mode="json")
                    for node_id in path
                    if node_id in nodes
                ],
            }
        )

    @tool(
        name="export_evidence_graph_json",
        risk="read-only",
        search_hint="export biomedical evidence graph json redacted schema v1",
    )
    async def export_evidence_graph_json(
        self,
        event,
        topic: str = "",
        entity: str = "",
        paper_id: str = "",
        direction: str = "",
        run_id: str = "",
        validate: bool = True,
    ) -> str:
        """Export a redacted v1 biomedical evidence graph JSON object.

        Args:
            topic: Optional topic filter.
            entity: Optional entity filter.
            paper_id: Optional paper id filter.
            direction: Optional evidence direction filter.
            run_id: Optional answer run id for a run-scoped graph.
            validate: Attach graph validation before export.
        """
        graph = self._service.get_graph_v1(
            topic=topic,
            entity=entity,
            paper_id=paper_id,
            direction=direction,
            run_id=run_id,
            validate=validate,
        )
        if graph is None:
            return _dump({"error_code": "unknown_run_id", "run_id": run_id})
        return _dump(graph_to_json_dict(graph))

    @tool(
        name="get_run_evidence_review",
        risk="read-only",
        search_hint="review biomedical answer run claims evidence cards validation snapshot",
    )
    async def get_run_evidence_review(
        self,
        event,
        run_id: str,
        include_graph: bool = False,
    ) -> str:
        """Get a product-facing evidence review for an answer run."""
        review = self._service.get_run_evidence_review(
            run_id,
            include_graph=include_graph,
        )
        if review is None:
            return _dump({"error_code": "unknown_run_id", "run_id": run_id})
        return _dump(review.model_dump(mode="json"))

    @tool(
        name="export_evidence_report",
        risk="read-only",
        search_hint="export biomedical evidence report markdown json",
    )
    async def export_evidence_report(
        self,
        event,
        run_id: str | None = None,
        question: str | None = None,
        format: Literal["markdown", "json"] = "markdown",
    ) -> str:
        """Export a biomedical evidence report.

        Args:
            run_id: Existing answer run id.
            question: Optional question to answer and export if run_id is absent.
            format: markdown or json.
        """
        report = await self._service.export_report(
            ExportEvidenceReportRequest(run_id=run_id, question=question, format=format)
        )
        return report

    def _validate_or_apply_project(
        self,
        tool_name: str,
        args: dict[str, Any],
        messages: list[str],
    ) -> str:
        project_id = _clean_str(args.get("project_id"))
        if (
            not project_id
            and tool_name in _TOOLS_WITH_OPTIONAL_ACTIVE_PROJECT
            and _config_bool(self, "auto_use_active_project", False)
        ):
            active_project_id = _clean_str(self.context.kv_store.get("active_project_id"))
            if active_project_id:
                args["project_id"] = active_project_id
                project_id = active_project_id
                messages.append("applied active biomedical project from plugin KV")
        if not project_id or tool_name not in _TOOLS_WITH_PROJECT_ID:
            return ""
        service = getattr(self, "_service", None)
        if not isinstance(service, BiomedEvidenceService):
            return "biomed_evidence guardrail: service_unavailable_for_project_validation"
        if service.get_project(project_id) is None:
            return f"biomed_evidence guardrail: project_not_found ({project_id})"
        return ""

    def _apply_source_policy(
        self,
        tool_name: str,
        args: dict[str, Any],
        messages: list[str],
    ) -> str:
        if tool_name not in _TOOLS_WITH_SOURCE:
            return ""
        source = _clean_str(args.get("source"))
        if not source:
            source = _config_str(self, "default_source", "mock")
            args["source"] = source
            messages.append(f"applied default biomedical source: {source}")
        if source not in {"mock", "pubmed"}:
            return f"biomed_evidence guardrail: unsupported_source ({source})"
        policy_error = release_source_policy_error(
            tool_name=tool_name,
            source=source,
            allow_live_pubmed_tools=_config_bool(
                self,
                "allow_live_pubmed_tools",
                False,
            ),
        )
        if policy_error is not None:
            return (
                "biomed_evidence guardrail: "
                f"{policy_error.error_code}: {policy_error.message}"
            )
        return ""

    def _apply_count_caps(self, args: dict[str, Any], messages: list[str]) -> None:
        _cap_int_arg(
            args,
            "max_results",
            _config_int(self, "max_search_results", 10),
            messages,
        )
        _cap_int_arg(
            args,
            "max_papers",
            _config_int(self, "max_answer_papers", 10),
            messages,
        )
        _cap_int_arg(
            args,
            "page_size",
            _config_int(self, "max_page_size", 100),
            messages,
        )
        _cap_int_arg(
            args,
            "max_queries",
            _config_int(self, "max_retrieval_queries", 6),
            messages,
        )
        _cap_int_arg(
            args,
            "max_followups",
            _config_int(self, "max_followup_queries", 2),
            messages,
        )
        _cap_int_arg(
            args,
            "max_evidence_items",
            _config_int(self, "max_evidence_items", 50),
            messages,
        )
        _cap_int_arg(
            args,
            "max_tool_steps",
            _config_int(self, "max_tool_steps", 20),
            messages,
        )

    def _apply_search_defaults(
        self,
        tool_name: str,
        args: dict[str, Any],
        messages: list[str],
    ) -> None:
        if tool_name != "search_literature" or "require_abstract" in args:
            return
        value = _config_bool(self, "default_require_abstract", True)
        args["require_abstract"] = value
        messages.append(
            "applied default biomedical search requirement: "
            f"require_abstract={str(value).lower()}"
        )

    def _apply_default_llm_flags(
        self,
        tool_name: str,
        args: dict[str, Any],
        messages: list[str],
    ) -> None:
        for flag in _TOOL_LLM_FLAGS.get(tool_name, ()):
            if flag in args:
                continue
            value = _config_bool(self, f"default_{flag}", False)
            if not value:
                continue
            args[flag] = True
            messages.append(f"applied default biomedical LLM flag: {flag}=true")

    def _remember_tool_preferences(self, args: dict[str, Any]) -> None:
        source = _clean_str(args.get("source"))
        if source:
            self.context.kv_store.set("last_source", source)
        project_id = _clean_str(args.get("project_id"))
        if project_id:
            self.context.kv_store.set("active_project_id", project_id)
        watch_id = _clean_str(args.get("watch_id"))
        if watch_id:
            self.context.kv_store.set("active_watch_id", watch_id)
        llm_options = {
            key: bool(args[key])
            for flags in _TOOL_LLM_FLAGS.values()
            for key in flags
            if key in args
        }
        if llm_options:
            self.context.kv_store.set("last_llm_options", llm_options)

    def active_project_prompt_context(self) -> str:
        project = self._active_project()
        if project is None:
            return ""
        pieces = [
            f"- Active project: {project.name} ({project.project_id})",
        ]
        if project.research_question:
            pieces.append(f"- Research question: {project.research_question}")
        if project.include_keywords:
            pieces.append(
                "- Include keywords: " + ", ".join(project.include_keywords[:8])
            )
        if project.exclude_keywords:
            pieces.append(
                "- Exclude keywords: " + ", ".join(project.exclude_keywords[:8])
            )
        if project.preferred_methods:
            pieces.append(
                "- Preferred methods: " + ", ".join(project.preferred_methods[:8])
            )
        return "\n".join(pieces)

    def should_inject_prompt_context(self, content: str) -> bool:
        if not _config_bool(self, "enable_prompt_context", True):
            return False
        if self._active_project() is not None:
            return True
        text = content.lower()
        return any(term in text for term in _BIOMED_INTENT_TERMS) or is_clinical_request(
            content
        )

    def _active_project(self) -> BiomedProject | None:
        project_id = _clean_str(self.context.kv_store.get("active_project_id"))
        if not project_id:
            return None
        service = getattr(self, "_service", None)
        if not isinstance(service, BiomedEvidenceService):
            return None
        return service.get_project(project_id)


class BiomedPromptContextModule:
    slot = "biomed_evidence.prompt_context"
    requires = ("prompt_render.emit", _PROMPT_CTX_SLOT)
    produces = (_PROMPT_CTX_SLOT,)

    def __init__(self, plugin: BiomedEvidencePlugin) -> None:
        self._plugin = plugin

    async def run(self, frame: Any) -> Any:
        ctx = frame.slots.get(_PROMPT_CTX_SLOT)
        if not isinstance(ctx, PromptRenderCtx):
            return frame
        if not self._plugin.should_inject_prompt_context(ctx.content):
            return frame
        project_context = self._plugin.active_project_prompt_context()
        default_source = _config_str(self._plugin, "default_source", "mock")
        live_pubmed = _config_bool(self._plugin, "allow_live_pubmed_tools", False)
        lines = [
            "### Biomedical Evidence Plugin Context",
            "- Biomedical Evidence is research-only. Refuse or redirect diagnosis, dosing, treatment, prognosis, and patient-specific medical requests.",
            "- Use retrieved literature, citations, evidence spans, and audit results for biomedical factual claims.",
            "- Project memory, saved papers, rejected papers, and preferences are context only; never cite them as biomedical evidence.",
            f"- Default biomedical tool source: {default_source}. Live PubMed tool calls enabled: {str(live_pubmed).lower()}.",
        ]
        if project_context:
            lines.append(project_context)
            lines.append(
                "- Treat the active project as retrieval preference context, not as a source of biomedical facts."
            )
        ctx.system_sections_bottom.append(
            PromptSectionRender(
                name="biomed_evidence_context",
                content="\n".join(lines),
                is_static=False,
            )
        )
        return frame


def _dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _clinical_signal_text(event: PreToolCtx, args: dict[str, Any]) -> str:
    parts = [event.request_text]
    for key in (
        "question",
        "query",
        "claim",
        "topic",
        "research_question",
        "project_context",
        "answer",
    ):
        value = args.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(part for part in parts if part)


def _cap_int_arg(
    args: dict[str, Any],
    key: str,
    cap: int,
    messages: list[str],
) -> None:
    if key not in args or cap <= 0:
        return
    try:
        value = int(args[key])
    except (TypeError, ValueError):
        return
    if value <= cap:
        return
    args[key] = cap
    messages.append(f"capped {key} from {value} to {cap}")


def _config_bool(plugin: BiomedEvidencePlugin, key: str, default: bool) -> bool:
    config = getattr(plugin.context, "config", None)
    if config is None:
        return default
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _config_int(plugin: BiomedEvidencePlugin, key: str, default: int) -> int:
    config = getattr(plugin.context, "config", None)
    if config is None:
        return default
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _config_str(plugin: BiomedEvidencePlugin, key: str, default: str) -> str:
    config = getattr(plugin.context, "config", None)
    if config is None:
        return default
    value = config.get(key, default)
    if value is None:
        return default
    cleaned = str(value).strip()
    return cleaned or default


def _clean_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
