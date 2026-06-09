from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import httpx

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
    AnswerWithEvidenceRequest,
    AnswerWithEvidenceResult,
    BiomedicalPaper,
    Citation,
    ConfidenceLevel,
    EvidenceExtractionRequest,
    EvidenceExtractionResult,
    EvidenceGraph,
    EvidenceItem,
    ExportEvidenceReportRequest,
    FetchBiomedicalPaperRequest,
    GraphEdge,
    GraphNode,
    PaperMetadata,
    SearchBiomedicalLiteratureRequest,
    WatchCheckResult,
    WatchDecisionDetail,
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
    ) -> None:
        self.workspace = Path(workspace)
        self.storage = BiomedStorage(self.workspace / "biomed_evidence" / "biomed.db")
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
        client = self._client(request.source)
        try:
            items = await client.search(
                request.query,
                max_results=max(0, min(request.max_results, 50)),
                date_from=request.date_from,
                date_to=request.date_to,
            )
        except LiteratureClientError:
            raise
        for item in items:
            paper = await client.fetch(item.paper_id)
            if paper is not None:
                self.storage.upsert_paper(paper)
        return items

    async def fetch(self, request: FetchBiomedicalPaperRequest) -> BiomedicalPaper | None:
        stored = self.storage.get_paper(request.paper_id, source=request.source)
        if stored is not None and request.source == "mock":
            return stored
        paper = await self._client(request.source).fetch(request.paper_id)
        if paper is not None:
            self.storage.upsert_paper(paper)
        return paper

    def extract_evidence(
        self,
        request: EvidenceExtractionRequest,
    ) -> EvidenceExtractionResult:
        self.storage.upsert_paper(request.paper)
        result = self.extractor.extract(
            request.paper,
            research_question=request.research_question,
        )
        for item in result.evidence:
            self.storage.upsert_evidence(item, paper_source=request.paper.source)
        return result

    async def answer_with_evidence(
        self,
        request: AnswerWithEvidenceRequest,
    ) -> AnswerWithEvidenceResult:
        run_id = f"biomed-run-{uuid.uuid4().hex[:12]}"
        if is_clinical_request(request.question):
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
            )
            self.storage.save_answer_run(result, question=request.question)
            return result

        search_request = SearchBiomedicalLiteratureRequest(
            query=request.question,
            max_results=request.max_papers,
            source=request.source,
        )
        metadata = await self.search(search_request)
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
                )
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
        )
        self.storage.save_answer_run(result, question=request.question)
        return result

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
        metadata = await self.search(
            SearchBiomedicalLiteratureRequest(query=query, max_results=10, source=source)  # type: ignore[arg-type]
        )
        decisions: list[WatchDecisionDetail] = []
        for meta in metadata:
            if meta.paper_id in existing_paper_ids:
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
            }
            decision = WatchDecisionDetail(
                decision_id=_decision_id(watch.watch_id, paper.paper_id),
                watch_id=watch.watch_id,
                paper_id=paper.paper_id,
                relevance_score=round(score, 3),
                decision=decision_value,
                rationale=rationale,
                uncertainty=uncertainty,
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
        return WatchCheckResult(watch=updated_watch, decisions=decisions, checked_at=checked_at)

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
