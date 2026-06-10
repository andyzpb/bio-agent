from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


BiomedicalSource = Literal["pubmed", "europe_pmc", "biorxiv", "mock"]
EvidenceDirection = Literal["supports", "contradicts", "inconclusive", "background"]
ConfidenceLevel = Literal["low", "medium", "high"]
EntityType = Literal[
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
]
WatchSchedule = Literal["daily", "weekly", "manual"]
WatchDecisionValue = Literal["push", "skip", "defer"]


class BiomedicalPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    source: BiomedicalSource
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    publication_date: str | None = None
    doi: str | None = None
    url: str | None = None
    mesh_terms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class PaperMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    source: Literal["pubmed", "mock"]
    title: str
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    publication_date: str | None = None
    abstract_available: bool
    doi: str | None = None
    url: str | None = None


class BiomedicalEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    entity_type: EntityType
    normalized_id: str | None = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    paper_id: str
    claim: str
    finding: str
    evidence_direction: EvidenceDirection
    entities: list[BiomedicalEntity] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    datasets_or_cohorts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel
    evidence_span: str | None = None
    requires_expert_review: bool = True


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    title: str
    source: str
    doi: str | None = None
    url: str | None = None
    cited_claim: str


class WatchTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watch_id: str
    topic: str
    description: str | None = None
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    preferred_methods: list[str] = Field(default_factory=list)
    min_relevance_score: float = 0.7
    schedule: WatchSchedule = "daily"
    enabled: bool = True
    created_at: str
    updated_at: str
    last_checked_at: str | None = None
    next_check_at: str | None = None


class WatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    watch_id: str
    paper_id: str
    retrieval_id: str | None = None
    snapshot_id: str | None = None
    relevance_score: float
    decision: WatchDecisionValue
    rationale: str
    uncertainty: ConfidenceLevel
    dedupe_reason: str | None = None
    created_at: str


class WatchDecisionDetail(WatchDecision):
    title: str | None = None
    source: str | None = None
    notification: dict[str, object] = Field(default_factory=dict)


class SearchBiomedicalLiteratureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    max_results: int = 10
    date_from: str | None = None
    date_to: str | None = None
    source: Literal["pubmed", "mock"] = "mock"
    publication_types: list[str] = Field(default_factory=list)
    study_types: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)
    species_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)


class RetrievalManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_id: str
    source: Literal["pubmed", "mock"]
    original_query: str
    compiled_query: str
    normalized_filters: dict[str, object] = Field(default_factory=dict)
    unsupported_filters: list[str] = Field(default_factory=list)
    api_endpoints: list[str] = Field(default_factory=list)
    request_parameters: list[dict[str, object]] = Field(default_factory=list)
    page_size: int
    pages_requested: int
    pages_completed: int
    raw_result_count: int
    deduped_result_count: int
    returned_paper_ids: list[str] = Field(default_factory=list)
    dropped_or_duplicate_ids: list[str] = Field(default_factory=list)
    started_at: str
    finished_at: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    software_version: str = "biomed-evidence-v1.2"


class SearchBiomedicalLiteratureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PaperMetadata] = Field(default_factory=list)
    retrieval_manifest: RetrievalManifest


class WatchSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    watch_id: str
    retrieval_id: str
    paper_ids: list[str] = Field(default_factory=list)
    new_paper_ids: list[str] = Field(default_factory=list)
    created_at: str


class FetchBiomedicalPaperRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    source: Literal["pubmed", "mock"] = "mock"


class EvidenceExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper: BiomedicalPaper
    research_question: str | None = None


class EvidenceExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    reason: str | None = None


class AnswerWithEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    max_papers: int = 10
    project_context: str | None = None
    require_citations: bool = True
    source: Literal["pubmed", "mock"] = "mock"


class AnswerWithEvidenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    retrieval_id: str | None = None
    retrieval_manifest: RetrievalManifest | None = None
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_summary: list[EvidenceItem] = Field(default_factory=list)
    conflicting_evidence: list[EvidenceItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    uncertainty_level: ConfidenceLevel
    suggested_next_steps: list[str] = Field(default_factory=list)
    not_medical_advice: bool = True
    disclaimer: str
    project_context_used: str | None = None


class WatchTopicCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    description: str | None = None
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    preferred_methods: list[str] = Field(default_factory=list)
    min_relevance_score: float = 0.7
    schedule: WatchSchedule = "daily"


class WatchTopicUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str | None = None
    description: str | None = None
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    preferred_methods: list[str] | None = None
    min_relevance_score: float | None = None
    schedule: WatchSchedule | None = None
    enabled: bool | None = None


class WatchCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watch: WatchTopic
    decisions: list[WatchDecisionDetail] = Field(default_factory=list)
    checked_at: str
    retrieval_manifest: RetrievalManifest | None = None
    snapshot: WatchSnapshot | None = None


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    kind: str
    data: dict[str, object] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    type: str
    data: dict[str, object] = Field(default_factory=dict)


class EvidenceGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class ExportEvidenceReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    question: str | None = None
    format: Literal["markdown", "json"] = "markdown"


class PageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, object]]
    total: int
    page: int
    page_size: int
