from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from agent.plugins import Plugin, tool
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    BiomedProjectCreateRequest,
    BiomedProjectUpdateRequest,
    BiomedicalPaper,
    Citation,
    CitationAuditRequest,
    ConflictAuditRequest,
    EvidenceExtractionRequest,
    EvidenceItem,
    ExportEvidenceReportRequest,
    FetchBiomedicalPaperRequest,
    GenerateProjectEvidenceBriefRequest,
    PlanBiomedicalSearchRequest,
    ProjectClaimRecordRequest,
    ProjectPaperDecisionRequest,
    SearchBiomedicalLiteratureRequest,
    WatchTopicCreateRequest,
    WatchTopicUpdateRequest,
)
from plugins.biomed_evidence.service import BiomedEvidenceService


class BiomedEvidencePlugin(Plugin):
    name = "biomed_evidence"

    async def initialize(self) -> None:
        workspace = self.context.workspace or (Path.home() / ".akashic" / "workspace")
        self._service = BiomedEvidenceService(workspace)

    async def terminate(self) -> None:
        service = getattr(self, "_service", None)
        if service is not None:
            await service.aclose()

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
        result = await self._service.search_with_manifest(
            SearchBiomedicalLiteratureRequest(
                query=query,
                max_results=max_results,
                date_from=date_from,
                date_to=date_to,
                source=source,
            )
        )
        return _dump(
            {
                "items": [item.model_dump(mode="json") for item in result.items],
                "retrieval_manifest": result.retrieval_manifest.model_dump(mode="json"),
            }
        )

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


def _dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
