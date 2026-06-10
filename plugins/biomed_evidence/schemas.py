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
ProjectPaperDecisionValue = Literal["saved", "rejected", "needs_review"]
ProjectClaimStatus = Literal[
    "supported",
    "mixed",
    "uncertain",
    "rejected",
    "needs_review",
]
ProjectReviewItemType = Literal[
    "claim_audit_failure",
    "advisory_disagreement",
    "conflicting_evidence",
    "needs_expert_review",
]
ProjectEvidenceBriefFormat = Literal["markdown", "json"]
ClaimType = Literal[
    "background",
    "association",
    "mechanistic_hypothesis",
    "causal",
    "clinical_implication",
    "treatment_recommendation",
    "methodological",
    "uncertainty",
]
CitationSupportVerdict = Literal[
    "supported",
    "partial_support",
    "overclaimed",
    "contradicted",
    "insufficient_evidence",
    "irrelevant_citation",
    "not_cited",
]
EvidenceStrength = Literal[
    "abstract_only",
    "animal_or_in_vitro",
    "observational",
    "longitudinal",
    "interventional",
    "review_or_guideline",
    "not_assessed",
]
AuditRecommendedAction = Literal[
    "pass",
    "pass_with_limitations",
    "revise",
    "refuse_or_abstain",
]
AdvisoryVerifierMode = Literal["llm", "fallback"]
AdvisoryAction = Literal[
    "pass",
    "pass_with_limitations",
    "revise",
    "refuse_or_abstain",
    "needs_expert_review",
]
AdvisoryVerdict = Literal[
    "supported",
    "partial_support",
    "overclaimed",
    "contradicted",
    "insufficient_evidence",
    "irrelevant_citation",
    "not_cited",
    "uncertain",
    "not_assessed",
]
ConflictVerdict = Literal[
    "no_conflict_found",
    "mixed_evidence",
    "contradicted",
    "insufficient_search",
]
TraceStepName = Literal[
    "classify",
    "plan",
    "validate_plan",
    "retrieve",
    "extract",
    "draft",
    "audit",
    "advisory_verify",
    "post_audit",
    "revise",
    "finalize",
]
TraceStepStatus = Literal["started", "completed", "skipped", "failed"]
RevisionAction = Literal["pass", "revise", "refuse", "abstain"]
RevisionMode = Literal["deterministic", "llm", "fallback"]
PlannerMode = Literal["deterministic", "llm", "fallback"]
ExtractionMode = Literal["deterministic", "llm", "fallback"]
SynthesisMode = Literal["deterministic", "llm", "fallback"]
RetrievalIntent = Literal["primary", "support", "refute", "unknown"]
QuestionIntent = Literal[
    "research_question",
    "clinical_or_patient_specific",
    "needs_clarification",
    "out_of_scope",
]
AllowedNextStep = Literal["plan_retrieval", "clarify", "refuse", "abstain"]
PlanValidationStatus = Literal["valid", "valid_with_warnings", "invalid"]


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
    retrieval_intent: RetrievalIntent = "unknown"
    extraction_mode: ExtractionMode = "deterministic"
    extractor_model: str | None = None
    extractor_prompt_hash: str | None = None
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


class BiomedProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    name: str
    description: str | None = None
    research_question: str = ""
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    preferred_methods: list[str] = Field(default_factory=list)
    preferred_species: list[str] = Field(default_factory=list)
    preferred_study_types: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class BiomedProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    research_question: str = ""
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    preferred_methods: list[str] = Field(default_factory=list)
    preferred_species: list[str] = Field(default_factory=list)
    preferred_study_types: list[str] = Field(default_factory=list)


class BiomedProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    research_question: str | None = None
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    preferred_methods: list[str] | None = None
    preferred_species: list[str] | None = None
    preferred_study_types: list[str] | None = None


class ProjectPaperDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    project_id: str
    paper_id: str
    source: Literal["pubmed", "mock"] = "mock"
    decision: ProjectPaperDecisionValue
    reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    run_id: str | None = None
    retrieval_id: str | None = None
    created_at: str
    updated_at: str


class ProjectPaperDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    source: Literal["pubmed", "mock"] = "mock"
    decision: ProjectPaperDecisionValue = "saved"
    reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    run_id: str | None = None
    retrieval_id: str | None = None


class ProjectClaimRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    project_id: str
    claim: str
    status: ProjectClaimStatus = "needs_review"
    evidence_ids: list[str] = Field(default_factory=list)
    audit_ids: list[str] = Field(default_factory=list)
    verifier_ids: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_at: str
    updated_at: str


class ProjectClaimRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    status: ProjectClaimStatus = "needs_review"
    evidence_ids: list[str] = Field(default_factory=list)
    audit_ids: list[str] = Field(default_factory=list)
    verifier_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class ProjectReviewQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    project_id: str
    item_type: ProjectReviewItemType
    title: str
    reason: str
    risk_level: ConfidenceLevel = "medium"
    run_id: str | None = None
    evidence_id: str | None = None
    audit_id: str | None = None
    verifier_id: str | None = None
    created_at: str


class ProjectEvidenceBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief_id: str
    project_id: str
    title: str
    format: ProjectEvidenceBriefFormat = "markdown"
    content: str
    included_claim_ids: list[str] = Field(default_factory=list)
    included_evidence_ids: list[str] = Field(default_factory=list)
    audit_ids: list[str] = Field(default_factory=list)
    verifier_ids: list[str] = Field(default_factory=list)
    created_at: str


class GenerateProjectEvidenceBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    title: str | None = None
    format: ProjectEvidenceBriefFormat = "markdown"


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


class RetrievalBundleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: RetrievalIntent
    query: str
    retrieval_id: str | None = None
    manifest: RetrievalManifest | None = None
    returned_paper_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    skipped_reason: str | None = None


class RetrievalBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    source: Literal["pubmed", "mock"]
    executed_multi_query: bool = False
    records: list[RetrievalBundleRecord] = Field(default_factory=list)
    deduped_paper_ids: list[str] = Field(default_factory=list)
    duplicate_paper_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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


class BiomedicalQuestionClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    normalized_question: str
    intent: QuestionIntent
    clinical_boundary: bool = False
    needs_clarification: bool = False
    risk_flags: list[str] = Field(default_factory=list)
    allowed_next_step: AllowedNextStep
    classifier_mode: PlannerMode = "deterministic"
    llm_model: str | None = None
    llm_prompt_hash: str | None = None
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)


class BiomedicalQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    question: str
    source: Literal["pubmed", "mock"] = "mock"
    planner_mode: PlannerMode = "deterministic"
    primary_query: str
    mesh_terms: list[str] = Field(default_factory=list)
    include_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    publication_types: list[str] = Field(default_factory=list)
    study_types: list[str] = Field(default_factory=list)
    species_terms: list[str] = Field(default_factory=list)
    support_queries: list[str] = Field(default_factory=list)
    refute_queries: list[str] = Field(default_factory=list)
    max_results: int = 10
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)
    llm_model: str | None = None
    llm_prompt_hash: str | None = None
    llm_raw_response: dict[str, object] | None = None


class QueryPlanValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    status: PlanValidationStatus
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    unsupported_filters: list[str] = Field(default_factory=list)
    compiled_query: str = ""
    executable_request: SearchBiomedicalLiteratureRequest | None = None


class PlanBiomedicalSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    max_results: int = 10
    source: Literal["pubmed", "mock"] = "mock"
    project_context: str | None = None
    use_llm_planner: bool = False


class PlanBiomedicalSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: BiomedicalQuestionClassification
    query_plan: BiomedicalQueryPlan | None = None
    validation: QueryPlanValidation
    search_request: SearchBiomedicalLiteratureRequest | None = None


class AnswerWithEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    max_papers: int = 10
    project_id: str | None = None
    project_context: str | None = None
    require_citations: bool = True
    source: Literal["pubmed", "mock"] = "mock"
    include_rejected_papers: bool = False
    use_llm_revision: bool = False
    use_llm_planner: bool = False
    execute_support_refute: bool = False
    use_llm_extractor: bool = False
    use_llm_synthesis: bool = False
    use_llm_verifier: bool = False


class AnswerWithEvidenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    retrieval_id: str | None = None
    retrieval_manifest: RetrievalManifest | None = None
    retrieval_bundle: RetrievalBundle | None = None
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_summary: list[EvidenceItem] = Field(default_factory=list)
    conflicting_evidence: list[EvidenceItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    uncertainty_level: ConfidenceLevel
    suggested_next_steps: list[str] = Field(default_factory=list)
    not_medical_advice: bool = True
    disclaimer: str
    project_id: str | None = None
    project_context_used: str | None = None
    project_context_trace: dict[str, object] = Field(default_factory=dict)
    question_classification: BiomedicalQuestionClassification | None = None
    query_plan: BiomedicalQueryPlan | None = None
    query_plan_validation: QueryPlanValidation | None = None
    synthesis_mode: SynthesisMode = "deterministic"
    synthesis_model: str | None = None
    synthesis_prompt_hash: str | None = None
    synthesis_fallback_reason: str | None = None


class AgentTraceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    run_id: str
    step: TraceStepName
    status: TraceStepStatus
    input_summary: str = ""
    output_summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: str


class AnswerRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str
    run_id: str
    audit_id: str | None = None
    post_revision_audit_id: str | None = None
    revision_mode: RevisionMode = "deterministic"
    llm_model: str | None = None
    llm_prompt_hash: str | None = None
    llm_raw_response: dict[str, object] | None = None
    draft_answer: str
    final_answer: str
    changed_claims: list[str] = Field(default_factory=list)
    removed_claims: list[str] = Field(default_factory=list)
    softened_claims: list[str] = Field(default_factory=list)
    added_limitations: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
    refusal_reason: str | None = None
    revision_action: RevisionAction
    created_at: str


class AtomicClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    text: str
    claim_type: ClaimType
    sentence_index: int | None = None
    cited_paper_ids: list[str] = Field(default_factory=list)


class ClaimAuditItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim: str
    claim_type: ClaimType
    cited_paper_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_span: str | None = None
    verdict: CitationSupportVerdict
    support_score: float = 0.0
    evidence_strength: EvidenceStrength = "not_assessed"
    overclaim_reason: str | None = None
    reason: str
    reviewer_notes: list[str] = Field(default_factory=list)


class UncertaintyAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_uncertainty: ConfidenceLevel
    observed_uncertainty: ConfidenceLevel | None = None
    calibrated: bool
    reasons: list[str] = Field(default_factory=list)
    grade_like_factors: dict[str, str] = Field(default_factory=dict)


class CitationAuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    run_id: str | None = None
    retrieval_id: str | None = None
    claims: list[AtomicClaim] = Field(default_factory=list)
    claim_audits: list[ClaimAuditItem] = Field(default_factory=list)
    uncertainty_audit: UncertaintyAudit
    claim_support_rate: float
    citation_precision: float
    unsupported_claim_rate: float
    overclaim_rate: float
    conflict_awareness: bool
    uncertainty_calibrated: bool
    failed_claims: list[ClaimAuditItem] = Field(default_factory=list)
    recommended_action: AuditRecommendedAction
    created_at: str
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AdvisoryClaimReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str | None = None
    claim: str
    advisory_verdict: AdvisoryVerdict
    advisory_action: AdvisoryAction
    risk_level: ConfidenceLevel
    cited_paper_ids: list[str] = Field(default_factory=list)
    rationale: str
    suggested_revision: str | None = None


class AdvisoryVerifierDisagreement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str | None = None
    claim: str
    deterministic_verdict: CitationSupportVerdict | None = None
    deterministic_action: AuditRecommendedAction
    advisory_verdict: AdvisoryVerdict
    advisory_action: AdvisoryAction
    risk_level: ConfidenceLevel
    high_risk: bool = False
    reason: str


class AdvisoryVerifierResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verifier_id: str
    run_id: str
    audit_id: str
    retrieval_id: str | None = None
    verifier_mode: AdvisoryVerifierMode
    llm_model: str | None = None
    llm_prompt_hash: str | None = None
    llm_raw_response: dict[str, object] | None = None
    fallback_reason: str | None = None
    deterministic_action: AuditRecommendedAction
    advisory_action: AdvisoryAction
    claim_reviews: list[AdvisoryClaimReview] = Field(default_factory=list)
    disagreements: list[AdvisoryVerifierDisagreement] = Field(default_factory=list)
    high_risk_disagreement_count: int = 0
    created_at: str
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AuditedAnswerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_result: AnswerWithEvidenceResult
    draft_answer: str
    final_answer: str
    audit: CitationAuditResult
    advisory_verifier: AdvisoryVerifierResult | None = None
    revision: AnswerRevision
    trace: list[AgentTraceStep] = Field(default_factory=list)
    final_action: RevisionAction


class CitationAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    run_id: str | None = None
    retrieval_id: str | None = None
    observed_uncertainty: ConfidenceLevel | None = None
    retrieval_manifest: RetrievalManifest | None = None


class ConflictAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    topic: str = ""
    source: Literal["pubmed", "mock"] = "mock"
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    retrieval_id: str | None = None


class ConflictAuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_audit_id: str
    claim: str
    topic: str
    retrieval_id: str | None = None
    supporting_papers: list[str] = Field(default_factory=list)
    contradicting_papers: list[str] = Field(default_factory=list)
    inconclusive_papers: list[str] = Field(default_factory=list)
    conflict_axes: list[str] = Field(default_factory=list)
    verdict: ConflictVerdict
    created_at: str


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
