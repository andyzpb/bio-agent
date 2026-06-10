from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, cast

import httpx

from plugins.biomed_evidence.citation_auditor import (
    find_conflicting_evidence as audit_conflicts,
    validate_citation_support,
)
from plugins.biomed_evidence.evidence_extractor import EvidenceExtractor
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
from plugins.biomed_evidence.schemas import (
    AgentTraceStep,
    AnswerWithEvidenceRequest,
    AnswerWithEvidenceResult,
    AnswerRevision,
    AuditedAnswerResult,
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
    EvidenceExtractionRequest,
    EvidenceExtractionResult,
    EvidenceGraph,
    EvidenceItem,
    ExportEvidenceReportRequest,
    FetchBiomedicalPaperRequest,
    GraphEdge,
    GraphNode,
    PaperMetadata,
    PlanBiomedicalSearchRequest,
    PlanBiomedicalSearchResult,
    QueryPlanValidation,
    RetrievalManifest,
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

    async def search(
        self,
        request: SearchBiomedicalLiteratureRequest,
    ) -> list[PaperMetadata]:
        return (await self.search_with_manifest(request)).items

    async def search_with_manifest(
        self,
        request: SearchBiomedicalLiteratureRequest,
    ) -> SearchBiomedicalLiteratureResult:
        client = self._client(request.source)
        started_at = _now_iso()
        retrieval_id = _retrieval_id(request, started_at)
        compiled_query, normalized_filters, unsupported_filters = _compile_query(request)
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

    async def fetch(self, request: FetchBiomedicalPaperRequest) -> BiomedicalPaper | None:
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
    ) -> EvidenceExtractionResult:
        self.storage.upsert_paper(request.paper)
        result = self.extractor.extract(
            request.paper,
            research_question=request.research_question,
        )
        for item in result.evidence:
            self.storage.upsert_evidence(
                item,
                paper_source=request.paper.source,
                retrieval_id=retrieval_id,
            )
        return result

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
            classification = _classification_from_llm(
                parsed.get("classification"),
                fallback=fallback_classification,
                model=self.revision_model,
                prompt_hash=prompt_hash,
            )
            if classification.clinical_boundary or classification.allowed_next_step != "plan_retrieval":
                return classification, fallback_plan.model_copy(
                    update={
                        "planner_mode": "fallback",
                        "warnings": _merge_unique(
                            fallback_plan.warnings,
                            ["LLM classification blocked retrieval; deterministic plan was not executed."],
                        ),
                    }
                )
            plan = _query_plan_from_llm(
                parsed.get("query_plan"),
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
        planning_result: PlanBiomedicalSearchResult | None = None
        if request.use_llm_planner:
            planning_result = await self.plan_biomedical_search(
                PlanBiomedicalSearchRequest(
                    question=request.question,
                    max_results=request.max_papers,
                    source=request.source,
                    project_context=request.project_context,
                    use_llm_planner=request.use_llm_planner,
                )
            )
        clinical_boundary = (
            is_clinical_request(request.question)
            or bool(planning_result and planning_result.classification.clinical_boundary)
        )
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
                project_context_used=request.project_context,
                question_classification=(
                    planning_result.classification if planning_result is not None else None
                ),
                query_plan=planning_result.query_plan if planning_result is not None else None,
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
                suggested_next_steps=_planner_next_steps(planning_result.classification),
                not_medical_advice=True,
                disclaimer=RESEARCH_USE_DISCLAIMER,
                project_context_used=request.project_context,
                question_classification=planning_result.classification,
                query_plan=planning_result.query_plan,
                query_plan_validation=planning_result.validation,
            )
            self.storage.save_answer_run(result, question=request.question)
            return result

        search_request = (
            planning_result.search_request
            if planning_result is not None and planning_result.search_request is not None
            else SearchBiomedicalLiteratureRequest(
                query=request.question,
                max_results=request.max_papers,
                source=request.source,
            )
        )
        search_result = await self.search_with_manifest(search_request)
        metadata = search_result.items
        retrieval_manifest = search_result.retrieval_manifest
        evidence: list[EvidenceItem] = []
        papers: dict[str, BiomedicalPaper] = {}
        for item in metadata:
            paper = await self.fetch(
                FetchBiomedicalPaperRequest(paper_id=item.paper_id, source=request.source)
            )
            if paper is None:
                continue
            papers[paper.paper_id] = paper
            extracted = self.extract_evidence(
                EvidenceExtractionRequest(
                    paper=paper,
                    research_question=request.question,
                ),
                retrieval_id=retrieval_manifest.retrieval_id,
            )
            evidence.extend(extracted.evidence)

        citations = [
            Citation(
                paper_id=item.paper_id,
                title=papers.get(item.paper_id, BiomedicalPaper(
                    paper_id=item.paper_id,
                    source=request.source,
                    title=item.paper_id,
                )).title,
                source=papers[item.paper_id].source if item.paper_id in papers else request.source,
                doi=papers[item.paper_id].doi if item.paper_id in papers else None,
                url=papers[item.paper_id].url if item.paper_id in papers else None,
                cited_claim=item.claim,
            )
            for item in evidence
            if item.paper_id in papers
        ]
        conflicting = [item for item in evidence if item.evidence_direction == "contradicts"]
        limitations = _collect_limitations(evidence)
        if not citations and request.require_citations:
            answer = (
                f"{RESEARCH_USE_DISCLAIMER}\n\n"
                "I could not retrieve citation-backed evidence for this question in "
                "the selected source. I will not make strong biomedical claims without "
                "retrieved citations."
            )
            uncertainty: ConfidenceLevel = "high"
        else:
            answer = _compose_answer(
                question=request.question,
                evidence=evidence,
                papers=papers,
                project_context=request.project_context,
            )
            uncertainty = _uncertainty(evidence)
        result = AnswerWithEvidenceResult(
            run_id=run_id,
            retrieval_id=retrieval_manifest.retrieval_id,
            retrieval_manifest=retrieval_manifest,
            answer=answer,
            citations=citations,
            evidence_summary=evidence,
            conflicting_evidence=conflicting,
            limitations=limitations,
            uncertainty_level=uncertainty,
            suggested_next_steps=_suggest_next_steps(evidence, bool(request.project_context)),
            not_medical_advice=True,
            disclaimer=RESEARCH_USE_DISCLAIMER,
            project_context_used=request.project_context,
            question_classification=(
                planning_result.classification if planning_result is not None else None
            ),
            query_plan=planning_result.query_plan if planning_result is not None else None,
            query_plan_validation=(
                planning_result.validation if planning_result is not None else None
            ),
        )
        self.storage.save_answer_run(result, question=request.question)
        return result

    async def answer_with_audit(
        self,
        request: AnswerWithEvidenceRequest,
    ) -> AuditedAnswerResult:
        draft_result = await self.answer_with_evidence(request)
        clinical_boundary = is_clinical_request(request.question) or bool(
            draft_result.question_classification
            and draft_result.question_classification.clinical_boundary
        )
        audit = self.audit_answer(
            CitationAuditRequest(
                answer=draft_result.answer,
                citations=draft_result.citations,
                evidence_items=draft_result.evidence_summary,
                run_id=draft_result.run_id,
                retrieval_id=draft_result.retrieval_id,
                observed_uncertainty=draft_result.uncertainty_level,
                retrieval_manifest=draft_result.retrieval_manifest,
            )
        )
        revision = await self._llm_revision_or_none(
            request=request,
            draft_result=draft_result,
            audit=audit,
            clinical_boundary=clinical_boundary,
        )
        if revision is None:
            revision = _build_answer_revision(
                draft_result=draft_result,
                audit=audit,
                clinical_boundary=clinical_boundary,
                use_llm_revision=request.use_llm_revision,
                fallback_reason_override=(
                    None
                    if not request.use_llm_revision
                    else _llm_unavailable_reason(self.revision_provider, self.revision_model)
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
            revision=revision,
            clinical_boundary=clinical_boundary,
        )
        self.storage.save_answer_revision(revision)
        self.storage.save_agent_trace_steps(trace)
        self.storage.save_answer_run(final_result, question=request.question)
        return AuditedAnswerResult(
            answer_result=final_result,
            draft_answer=revision.draft_answer,
            final_answer=revision.final_answer,
            audit=audit,
            revision=revision,
            trace=trace,
            final_action=revision.revision_action,
        )

    async def _llm_revision_or_none(
        self,
        *,
        request: AnswerWithEvidenceRequest,
        draft_result: AnswerWithEvidenceResult,
        audit: CitationAuditResult,
        clinical_boundary: bool,
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
            post_audit = self.audit_answer(
                CitationAuditRequest(
                    answer=final_answer,
                    citations=draft_result.citations,
                    evidence_items=draft_result.evidence_summary,
                    run_id=draft_result.run_id,
                    retrieval_id=draft_result.retrieval_id,
                    observed_uncertainty=cast(ConfidenceLevel | None, parsed.get("uncertainty_level")),
                    retrieval_manifest=draft_result.retrieval_manifest,
                )
            )
            if post_audit.recommended_action in {"revise", "refuse_or_abstain"}:
                return None
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
                changed_claims=_coerce_string_list(parsed.get("changed_claims")),
                removed_claims=_coerce_string_list(parsed.get("removed_claims")),
                softened_claims=_coerce_string_list(parsed.get("softened_claims")),
                added_limitations=_coerce_string_list(parsed.get("added_limitations")),
                revision_action=cast(Any, final_action),
                created_at=now,
            )
        except Exception:
            return None

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
                    data={"paper_id": str(row["paper_id"]), "url": row.get("paper_url")},
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
            edges.append(GraphEdge(source=paper_node, target=claim_node, type="PAPER_REPORTS_CLAIM"))
            if topic_id:
                edge_type = (
                    "CLAIM_CONTRADICTS_TOPIC"
                    if row["evidence_direction"] == "contradicts"
                    else "CLAIM_SUPPORTS_TOPIC"
                )
                edges.append(GraphEdge(source=claim_node, target=topic_id, type=edge_type))
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
                edges.append(GraphEdge(source=claim_node, target=entity_node, type="CLAIM_MENTIONS_ENTITY"))
            for method in cast(list[object], row.get("methods", [])):
                method_node = f"method:{_slug(str(method))}"
                nodes.setdefault(method_node, GraphNode(id=method_node, label=str(method), kind="method"))
                edges.append(GraphEdge(source=claim_node, target=method_node, type="CLAIM_USES_METHOD"))
            for dataset in cast(list[object], row.get("datasets_or_cohorts", [])):
                dataset_node = f"dataset:{_slug(str(dataset))}"
                nodes.setdefault(dataset_node, GraphNode(id=dataset_node, label=str(dataset), kind="dataset"))
                edges.append(GraphEdge(source=claim_node, target=dataset_node, type="CLAIM_BASED_ON_DATASET"))
            for limitation in cast(list[object], row.get("limitations", [])):
                limitation_node = f"limitation:{_slug(str(limitation))}"
                nodes.setdefault(
                    limitation_node,
                    GraphNode(id=limitation_node, label=str(limitation), kind="limitation"),
                )
                edges.append(GraphEdge(source=claim_node, target=limitation_node, type="CLAIM_HAS_LIMITATION"))
        return EvidenceGraph(nodes=list(nodes.values()), edges=edges)

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
                "schedule": request.schedule if request.schedule is not None else current.schedule,
                "enabled": request.enabled if request.enabled is not None else current.enabled,
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

    async def check_watch(self, watch_id: str, *, source: str = "mock") -> WatchCheckResult | None:
        watch = self.storage.get_watch(watch_id)
        if watch is None:
            return None
        checked_at = _now_iso()
        if not watch.enabled:
            return WatchCheckResult(watch=watch, decisions=[], checked_at=checked_at)
        existing, _ = self.storage.list_watch_decisions(watch_id=watch_id, page=1, page_size=500)
        existing_paper_ids = {item.paper_id for item in existing}
        query = " ".join([watch.topic, *watch.include_keywords]).strip()
        search_result = await self.search_with_manifest(
            SearchBiomedicalLiteratureRequest(query=query, max_results=10, source=source)  # type: ignore[arg-type]
        )
        metadata = search_result.items
        retrieval_manifest = search_result.retrieval_manifest
        paper_ids = [item.paper_id for item in metadata]
        new_paper_ids = [paper_id for paper_id in paper_ids if paper_id not in existing_paper_ids]
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
            uncertainty = "low" if score >= 0.85 else "medium" if score >= 0.5 else "high"
            if decision_value == "push":
                extracted = self.extract_evidence(
                    EvidenceExtractionRequest(paper=paper, research_question=watch.topic)
                )
                key_claim = extracted.evidence[0].claim if extracted.evidence else ""
                limitation = extracted.evidence[0].limitations[0] if extracted.evidence and extracted.evidence[0].limitations else "No explicit limitation extracted."
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

    def audit_answer(self, request: CitationAuditRequest) -> CitationAuditResult:
        audit = validate_citation_support(
            answer=request.answer,
            citations=request.citations,
            evidence_items=request.evidence_items,
            run_id=request.run_id,
            retrieval_id=request.retrieval_id,
            observed_uncertainty=request.observed_uncertainty,
            retrieval_manifest=request.retrieval_manifest,
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

    def get_latest_citation_audit_for_run(self, run_id: str) -> CitationAuditResult | None:
        return self.storage.get_latest_citation_audit_for_run(run_id)

    def get_answer_trace(self, run_id: str) -> dict[str, object] | None:
        result = self.storage.get_answer_run(run_id)
        if result is None:
            return None
        trace = self.storage.list_agent_trace_steps(run_id)
        revision = self.storage.get_answer_revision(run_id)
        latest_audit = self.storage.get_latest_citation_audit_for_run(run_id)
        return {
            "run_id": run_id,
            "answer_run": result.model_dump(mode="json"),
            "trace": [item.model_dump(mode="json") for item in trace],
            "revision": revision.model_dump(mode="json") if revision is not None else None,
            "latest_citation_audit": (
                latest_audit.model_dump(mode="json") if latest_audit is not None else None
            ),
        }

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
                            "requires_expert_review": row.get("requires_expert_review", True),
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
        str(item)
        for item in cast(list[object], trace.get("warnings", []))
        if str(item)
    ]
    trace_errors = [
        str(item)
        for item in cast(list[object], trace.get("errors", []))
        if str(item)
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
            rationale=rationale or "Question is too short to form a reliable retrieval plan.",
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
            rationale=rationale or "Question does not appear to ask about biomedical literature.",
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
        rationale=rationale or "Question is suitable for research literature retrieval.",
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
    warnings = (
        ["Project context was treated as retrieval preference only, not biomedical evidence."]
        if request.project_context
        else []
    )
    return BiomedicalQueryPlan(
        plan_id=_plan_id(classification.normalized_question, request.source, "deterministic"),
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
        support_queries=[
            f"{refute_seed} association evidence",
            f"{refute_seed} mechanism evidence",
        ],
        refute_queries=[
            f"{refute_seed} contradictory evidence",
            f"{refute_seed} negative results limitations",
        ],
        max_results=max(1, min(request.max_results, 50)),
        rationale="Deterministic query plan derived from biomedical terms in the question.",
        warnings=warnings,
    )


def _validate_query_plan(
    *,
    classification: BiomedicalQuestionClassification,
    query_plan: BiomedicalQueryPlan | None,
) -> QueryPlanValidation:
    warnings: list[str] = []
    errors: list[str] = []
    if classification.allowed_next_step != "plan_retrieval":
        errors.append(f"Classifier allowed next step is {classification.allowed_next_step}.")
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
            warnings.extend(f"Unsupported filter: {item}" for item in unsupported_filters)
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
            "The query plan must include primary_query, mesh_terms, include_terms, exclude_terms, support_queries, refute_queries, max_results, and rationale.",
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
                "warnings": _merge_unique(fallback.warnings, ["LLM classification was not an object."]),
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
    clinical_boundary = fallback.clinical_boundary or bool(value.get("clinical_boundary"))
    if clinical_boundary:
        intent = "clinical_or_patient_specific"
        allowed_next_step = "refuse"
        needs_clarification = False
    else:
        needs_clarification = bool(value.get("needs_clarification")) or intent == "needs_clarification"
        allowed_next_step = str(value.get("allowed_next_step") or fallback.allowed_next_step)
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
                "warnings": _merge_unique(fallback.warnings, ["LLM query_plan was not an object."]),
            }
        )
    primary_query = re.sub(
        r"\s+",
        " ",
        str(value.get("primary_query") or fallback.primary_query),
    ).strip()
    return BiomedicalQueryPlan(
        plan_id=_plan_id(fallback.question, fallback.source, "llm", prompt_hash),
        question=fallback.question,
        source=fallback.source,
        planner_mode="llm",
        primary_query=primary_query or fallback.primary_query,
        mesh_terms=_coerce_string_list(value.get("mesh_terms")) or fallback.mesh_terms,
        include_terms=_coerce_string_list(value.get("include_terms")) or fallback.include_terms,
        exclude_terms=_coerce_string_list(value.get("exclude_terms")) or fallback.exclude_terms,
        date_from=str(value.get("date_from") or "") or fallback.date_from,
        date_to=str(value.get("date_to") or "") or fallback.date_to,
        publication_types=_coerce_string_list(value.get("publication_types")),
        study_types=_coerce_string_list(value.get("study_types")) or fallback.study_types,
        species_terms=_coerce_string_list(value.get("species_terms")) or fallback.species_terms,
        support_queries=_coerce_string_list(value.get("support_queries")) or fallback.support_queries,
        refute_queries=_coerce_string_list(value.get("refute_queries")) or fallback.refute_queries,
        max_results=max(1, min(_safe_int(value.get("max_results"), fallback.max_results), 50)),
        rationale=str(value.get("rationale") or fallback.rationale),
        warnings=_coerce_string_list(value.get("warnings")),
        llm_model=model,
        llm_prompt_hash=prompt_hash,
        llm_raw_response=raw_response,
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
        result.append("No explicit limitations were extracted from retrieved abstracts.")
    return result


def _uncertainty(evidence: list[EvidenceItem]) -> ConfidenceLevel:
    if not evidence:
        return "high"
    if any(item.evidence_direction in {"contradicts", "inconclusive"} for item in evidence):
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
        steps.append("Add project context such as preferred methods or exclusion criteria.")
    if not evidence:
        steps.append("Broaden the search query or switch to PubMed for live retrieval.")
    return steps


def _build_answer_revision(
    *,
    draft_result: AnswerWithEvidenceResult,
    audit: CitationAuditResult,
    clinical_boundary: bool,
    use_llm_revision: bool = False,
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

    failed_by_claim = {item.claim_id: item for item in audit.failed_claims}
    if not failed_by_claim and audit.recommended_action == "pass":
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
    added_limitations: list[str] = []
    revised_lines: list[str] = []
    for raw_line in draft_result.answer.splitlines():
        match = _matching_failed_claim(raw_line, failed_by_claim.values())
        if match is None:
            revised_lines.append(raw_line)
            continue
        if match.verdict in {"not_cited", "irrelevant_citation", "insufficient_evidence"}:
            removed_claims.append(match.claim)
            changed_claims.append(match.claim)
            added_limitations.append(f"Removed unsupported claim: {match.claim}")
            continue
        if match.verdict in {"overclaimed", "contradicted"}:
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
        added_limitations.append("The audited draft had no remaining supported research claims.")
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


def _build_trace_steps(
    *,
    request: AnswerWithEvidenceRequest,
    result: AnswerWithEvidenceResult,
    audit: CitationAuditResult,
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
        "structured planner" if result.query_plan is not None else "answer_with_audit request",
        (
            result.query_plan.primary_query
            if result.query_plan is not None
            else "clinical boundary stopped retrieval" if clinical_boundary else "reused answer_with_evidence retrieval plan"
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
        (
            "completed"
            if result.query_plan_validation is not None
            else "skipped"
        ),
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
        warnings=result.retrieval_manifest.warnings if result.retrieval_manifest else [],
        metadata={
            "retrieval_id": result.retrieval_id,
            "papers": (
                result.retrieval_manifest.returned_paper_ids
                if result.retrieval_manifest is not None
                else []
            ),
        },
    )
    add(
        "extract",
        "skipped" if clinical_boundary else "completed",
        "retrieved papers",
        f"{len(result.evidence_summary)} evidence items",
    )
    add(
        "draft",
        "completed",
        "evidence summary",
        f"{len(revision.draft_answer)} draft characters",
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
        revision.post_revision_audit_id or "deterministic revision did not require a separate post-audit",
    )
    add(
        "finalize",
        "completed",
        revision.revision_action,
        result.run_id,
        metadata={"final_answer_chars": len(revision.final_answer)},
    )
    return steps


def _llm_revision_payload(
    *,
    request: AnswerWithEvidenceRequest,
    draft_result: AnswerWithEvidenceResult,
    audit: CitationAuditResult,
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
        "retrieval_manifest": manifest.model_dump(mode="json") if manifest is not None else None,
        "audit": audit.model_dump(mode="json"),
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
    return (
        text.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
    )


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


def _llm_planner_unavailable_reason(provider: object | None, model: str) -> str:
    if provider is None:
        return "LLM planner was requested, but no framework provider is configured for this service instance."
    if not model:
        return "LLM planner was requested, but no planner model is configured."
    return "LLM planner was requested, but the planner adapter fell back to deterministic planning."


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
        softened = f"Audit note: retrieved evidence conflicts with this claim; {softened}"
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


def _revision_id(run_id: str, audit_id: str | None) -> str:
    digest = hashlib.sha256(f"{run_id}:{audit_id or ''}".encode("utf-8")).hexdigest()[:16]
    return f"revision-{digest}"


def _trace_step_id(run_id: str, step: str) -> str:
    digest = hashlib.sha256(f"{run_id}:{step}".encode("utf-8")).hexdigest()[:16]
    return f"trace-{digest}"


def _score_watch_relevance(watch: WatchTopic, paper: BiomedicalPaper) -> tuple[float, str]:
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
    method_hits = [method for method in watch.preferred_methods if method.lower() in haystack]
    score = min(1.0, (len(hits) / len(topic_terms)) * 0.85 + min(0.15, len(method_hits) * 0.05))
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
