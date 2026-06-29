from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BiomedicalSource = Literal["pubmed", "europe_pmc", "biorxiv", "mock"]
EvidenceDirection = Literal["supports", "contradicts", "inconclusive", "background"]
ConfidenceLevel = Literal["low", "medium", "high"]
PacketLimitationLevel = Literal["low", "medium", "high"]
ReviewPriority = Literal["low", "medium", "high"]
ScopeMatch = Literal["true", "false", "uncertain"]
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
    "graph_validation_issue",
    "snapshot_stale",
    "watch_graph_drift",
    "argument_conflict",
    "argument_unlinked_evidence",
]
ProjectEvidenceBriefFormat = Literal["markdown", "json"]
RunReviewDecisionValue = Literal[
    "accept",
    "needs_more_evidence",
    "flag_overclaim",
    "reject",
]
RunReviewDecisionSource = Literal["api", "dashboard", "tool"]
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
EvidenceMaturity = Literal[
    "emerging_claim",
    "established_association",
    "established_causal_risk_factor",
    "clinical_intervention_claim",
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
    "coverage_gap_analysis",
    "build_packet",
    "draft",
    "audit",
    "advisory_verify",
    "post_audit",
    "revise",
    "review_decision",
    "finalize",
]
TraceStepStatus = Literal["started", "completed", "skipped", "failed"]
RevisionAction = Literal["pass", "revise", "refuse", "abstain"]
RevisionMode = Literal["deterministic", "llm", "fallback"]
PlannerMode = Literal["deterministic", "llm", "fallback"]
ExtractionMode = Literal["deterministic", "llm", "fallback"]
SynthesisMode = Literal["deterministic", "llm", "fallback"]
RetrievalIntent = Literal[
    "primary",
    "background",
    "support",
    "refute",
    "mechanism",
    "limitation",
    "recent",
    "unknown",
]
CoverageStatus = Literal[
    "covered",
    "weak",
    "conflicted",
    "missing",
    "source_limited",
]
QuestionIntent = Literal[
    "research_question",
    "clinical_or_patient_specific",
    "needs_clarification",
    "out_of_scope",
]
AllowedNextStep = Literal["plan_retrieval", "clarify", "refuse", "abstain"]
PlanValidationStatus = Literal["valid", "valid_with_warnings", "invalid"]
LogicParserMode = Literal["llm", "deterministic", "fallback"]
LogicPredicate = Literal[
    "associated_with",
    "correlates_with",
    "causes_or_drives",
    "contributes_to",
    "increases",
    "decreases",
    "predicts",
    "treats",
    "diagnoses",
    "is_marker_of",
    "is_mechanistically_linked_to",
    "is_required_for",
    "is_sufficient_for",
    "has_no_effect",
    "no_observed_benefit",
    "contradicts",
    "uncertain_or_inconclusive",
    "background_relation",
    "unspecified",
]
LogicPolarity = Literal["positive", "negative", "mixed", "uncertain", "unspecified"]
LogicModality = Literal[
    "possible",
    "suggestive",
    "moderate",
    "strong",
    "definitive",
    "inconclusive",
    "unspecified",
]
LogicPopulation = Literal["human", "animal", "in_vitro", "mixed", "unspecified"]
LogicClaimStrength = Literal[
    "background",
    "association",
    "contribution",
    "mechanistic",
    "causal",
    "clinical",
    "treatment",
    "diagnostic",
    "prognostic",
    "uncertainty",
    "unspecified",
]
LogicStudyDesign = Literal[
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
]
LogicVerdict = Literal[
    "entailed",
    "partially_entailed",
    "overclaimed",
    "contradicted",
    "scope_mismatch",
    "modality_mismatch",
    "insufficient_evidence",
    "not_assessed",
]
LogicFactFormat = Literal["text", "json"]
ReleaseToolErrorCode = Literal[
    "clinical_boundary",
    "source_policy_blocked",
    "invalid_input",
    "unknown_run_id",
    "unknown_retrieval_id",
    "unknown_paper_id",
    "missing_retrieval_manifest",
    "empty_evidence",
    "llm_schema_invalid",
    "external_source_unavailable",
    "rate_limited",
    "timeout",
    "budget_exceeded",
    "export_path_blocked",
    "packet_unavailable",
    "provenance_unavailable",
]
ReleaseToolRiskLevel = Literal[
    "read_only",
    "writes_storage",
    "external_network",
    "exports_files",
    "llm_cost",
    "clinical_sensitive",
]
ReleaseToolSourcePolicy = Literal["mock_only", "live_opt_in", "no_source"]
ReleaseToolSideEffect = Literal[
    "read_storage",
    "write_storage",
    "write_files",
    "external_network",
    "llm_call",
]
SavedToolChainWorkflow = Literal["audited_answer"]
EvidencePacketSelectionStrategy = Literal["all_valid", "submodular_greedy"]
EvidencePacketAvailability = Literal[
    "persisted",
    "reconstructed",
    "stale",
    "unavailable",
]
FullTextSourceScope = Literal["abstract", "full_text", "pdf", "unknown"]
BanditAdvisoryAction = Literal[
    "stop",
    "broaden_query",
    "narrow_query",
    "search_support",
    "search_refute",
    "search_mechanism",
    "search_limitation",
    "switch_to_pubmed_if_allowed",
    "manual_review",
]
ObsidianExportType = Literal["evidence_packet", "project", "watch"]
ProvenanceEntityType = Literal[
    "paper",
    "evidence_item",
    "retrieval_manifest",
    "evidence_packet",
    "answer",
    "citation_audit",
    "logic_audit",
    "revision",
    "obsidian_note",
]
ProvenanceActivityType = Literal[
    "classify",
    "plan",
    "search",
    "fetch",
    "extract",
    "gap_analyze",
    "packet_build",
    "synthesize",
    "audit",
    "revise",
    "export",
]
ProvenanceAgentType = Literal[
    "deterministic_service",
    "llm_provider_model",
    "reviewer",
    "plugin_tool",
]
ProvenanceRelationType = Literal[
    "used",
    "generated",
    "wasDerivedFrom",
    "wasAssociatedWith",
]
WorkflowState = Literal[
    "classified",
    "planned",
    "searched",
    "extracted",
    "gap_analyzed",
    "followup_searched",
    "packet_built",
    "synthesized",
    "audited",
    "revised",
    "refused",
    "failed",
]
class ReleaseToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ReleaseToolErrorCode
    message: str
    recoverable: bool = True
    next_allowed_actions: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)


class ReleaseToolMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    risk_level: ReleaseToolRiskLevel = "read_only"
    source_policy: ReleaseToolSourcePolicy = "no_source"
    side_effects: list[ReleaseToolSideEffect] = Field(default_factory=list)
    requires_confirmation: bool = False
    max_runtime_seconds: int = 30
    output_schema_version: str = "release-tool-envelope-v1"


class ReleaseToolEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ReleaseToolError] = Field(default_factory=list)
    error_code: ReleaseToolErrorCode | None = None
    message: str | None = None
    recoverable: bool | None = None
    next_allowed_actions: list[str] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)
    ids: dict[str, str] = Field(default_factory=dict)
    metadata: ReleaseToolMetadata | None = None


class StepTransitionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_state: WorkflowState
    to_state: WorkflowState
    tool_or_route: str
    run_id: str | None = None
    retrieval_id: str | None = None
    packet_id: str | None = None
    source: str | None = None
    planner_mode: PlannerMode | None = None
    extractor_mode: ExtractionMode | None = None
    llm_flags: dict[str, bool] = Field(default_factory=dict)
    coverage_status_summary: dict[str, int] = Field(default_factory=dict)
    step_index: int = 0
    elapsed_time_bucket: str = "not_measured"
    stop_reason: str | None = None
    success_category: str = "completed"


class StepTelemetrySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    transition_records: list[StepTransitionRecord] = Field(default_factory=list)
    transition_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    mean_tool_step_count: float = 0.0
    p95_tool_step_count: float = 0.0
    expected_remaining_steps: float = 0.0
    unusual_path_warnings: list[str] = Field(default_factory=list)
    advisory_only: bool = True


class ArgumentGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: Literal["claim", "evidence", "paper", "limitation"]
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArgumentGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    source: str
    target: str
    edge_type: Literal["supports", "attacks", "qualifies", "limits", "cites"]
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimArgumentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    support_count: int = 0
    attack_count: int = 0
    limitation_count: int = 0
    citation_count: int = 0
    unresolved_conflict_count: int = 0
    strongest_supporting_evidence_ids: list[str] = Field(default_factory=list)
    strongest_attacking_evidence_ids: list[str] = Field(default_factory=list)
    limitation_summary: list[str] = Field(default_factory=list)


class ArgumentGraphResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "biomed-argument-graph-v2"
    run_id: str
    audit_id: str | None = None
    retrieval_id: str | None = None
    status: Literal["ok", "not_applicable"] = "ok"
    advisory_only: bool = True
    nodes: list[ArgumentGraphNode] = Field(default_factory=list)
    edges: list[ArgumentGraphEdge] = Field(default_factory=list)
    claim_summaries: list[ClaimArgumentSummary] = Field(default_factory=list)
    unresolved_conflict_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    not_applicable_reason: str | None = None


class ClaimUncertaintySignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim: str
    risk_bucket: ConfidenceLevel = "medium"
    risk_score: float = 0.0
    recommendation: Literal["answer", "soften", "retrieve_more", "expert_review"] = (
        "expert_review"
    )
    reason_factors: list[str] = Field(default_factory=list)
    support_score: float = 0.0
    citation_verdict: CitationSupportVerdict | None = None
    logic_verdict: LogicVerdict | None = None
    evidence_strength: EvidenceStrength = "not_assessed"


class CoverageDiversitySignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diversity_score: float = 0.0
    paper_count: int = 0
    evidence_count: int = 0
    unique_method_count: int = 0
    unique_model_or_population_count: int = 0
    paper_concentration: dict[str, float] = Field(default_factory=dict)
    retrieval_intent_coverage: dict[str, int] = Field(default_factory=dict)
    limitation_count: int = 0
    duplicate_pressure: int = 0
    concentration_warnings: list[str] = Field(default_factory=list)
    missing_intent_warnings: list[str] = Field(default_factory=list)
    recommended_retrieval_direction: str | None = None


class MathSignalsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    audit_id: str | None = None
    retrieval_id: str | None = None
    status: Literal["ok", "not_applicable"] = "ok"
    advisory_only: bool = True
    answer_uncertainty_bucket: ConfidenceLevel = "medium"
    recommendation: Literal["answer", "soften", "retrieve_more", "expert_review"] = (
        "expert_review"
    )
    claim_uncertainty: list[ClaimUncertaintySignal] = Field(default_factory=list)
    coverage_diversity: CoverageDiversitySignal
    step_telemetry: StepTelemetrySummary
    argument_graph: ArgumentGraphResult
    reason_factors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    not_applicable_reason: str | None = None


class EvidenceSelectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    paper_id: str
    selected: bool
    reason: str
    score: float = 0.0
    coverage_contribution: dict[str, Any] = Field(default_factory=dict)
    token_estimate: int = 0


class EvidencePacketSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: EvidencePacketSelectionStrategy = "submodular_greedy"
    max_items: int = 12
    selected: list[EvidenceSelectionItem] = Field(default_factory=list)
    dropped: list[EvidenceSelectionItem] = Field(default_factory=list)
    selected_evidence_ids: list[str] = Field(default_factory=list)
    dropped_evidence_ids: list[str] = Field(default_factory=list)
    coverage_contribution: dict[str, Any] = Field(default_factory=dict)
    token_estimate: int = 0
    duplicate_evidence_delta: int = 0
    trace: dict[str, Any] = Field(default_factory=dict)


class BanditAdvisoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisory_only: bool = True
    action: BanditAdvisoryAction = "stop"
    reason: str
    confidence: float = 0.0
    expected_additional_steps: float = 0.0
    based_on: dict[str, Any] = Field(default_factory=dict)


class SavedToolChainTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    name: str
    description: str | None = None
    workflow: SavedToolChainWorkflow = "audited_answer"
    builtin: bool = False
    source: Literal["pubmed", "mock"] = "mock"
    source_policy: ReleaseToolSourcePolicy = "live_opt_in"
    max_papers: int = 5
    max_queries: int = 6
    max_followups: int = 0
    max_tool_steps: int = 20
    max_wall_clock_seconds: int = 180
    include_rejected_papers: bool = False
    require_citations: bool = True
    execute_support_refute: bool = True
    use_llm_planner: bool = False
    use_llm_extractor: bool = False
    use_llm_synthesis: bool = False
    use_llm_verifier: bool = False
    use_llm_revision: bool = False
    use_llm_claim_logic: bool = False
    export_logic_facts: bool = False
    build_evidence_packet: bool = True
    export_provenance: bool = True
    clinical_guard_required: bool = True
    required_skills: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class SavedToolChainTemplateSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str | None = None
    name: str
    description: str | None = None
    workflow: SavedToolChainWorkflow = "audited_answer"
    source: Literal["pubmed", "mock"] = "mock"
    max_papers: int = 5
    max_queries: int = 6
    max_followups: int = 0
    max_tool_steps: int = 20
    max_wall_clock_seconds: int = 180
    include_rejected_papers: bool = False
    require_citations: bool = True
    execute_support_refute: bool = True
    use_llm_planner: bool = False
    use_llm_extractor: bool = False
    use_llm_synthesis: bool = False
    use_llm_verifier: bool = False
    use_llm_revision: bool = False
    use_llm_claim_logic: bool = False
    export_logic_facts: bool = False
    build_evidence_packet: bool = True
    export_provenance: bool = True
    clinical_guard_required: bool = True
    required_skills: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)


class SavedToolChainTemplateListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SavedToolChainTemplate] = Field(default_factory=list)
    total: int = 0


class SavedToolChainTemplateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    project_id: str | None = None
    project_context: str | None = None
    source_override: Literal["pubmed", "mock"] | None = None
    max_papers_override: int | None = None
    allow_live_pubmed: bool = False


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
    source_scope: FullTextSourceScope = "abstract"
    document_id: str | None = None
    section_id: str | None = None
    section_label: str | None = None
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    source_hash: str | None = None
    scope_match: ScopeMatch = "uncertain"
    scope_mismatch_reasons: list[str] = Field(default_factory=list)
    scope_matched_terms: list[str] = Field(default_factory=list)


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
    store: bool = True


class LiteratureSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    max_results: int = 10
    date_from: str | None = None
    date_to: str | None = None
    source: Literal["pubmed", "mock"] = "mock"
    mesh_terms: list[str] = Field(default_factory=list)
    article_types: list[str] = Field(default_factory=list)
    publication_types: list[str] = Field(default_factory=list)
    study_types: list[str] = Field(default_factory=list)
    species_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    retrieval_intent: RetrievalIntent = "unknown"
    project_id: str | None = None
    require_abstract: bool = True
    store: bool = True


class LiteratureAccessCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = "microglia Alzheimer disease"
    max_results: int = 3
    date_from: str | None = None
    date_to: str | None = None
    source: Literal["pubmed", "mock"] = "pubmed"
    require_abstract: bool = True


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
    cache_status: Literal["hit", "miss", "write", "disabled", "error"] | None = None
    cache_key: str | None = None
    cache_basis: str | None = None
    software_version: str = "biomed-evidence-v1.2"


class SearchBiomedicalLiteratureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PaperMetadata] = Field(default_factory=list)
    retrieval_manifest: RetrievalManifest


class LiteraturePaperRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    source: Literal["pubmed", "mock"]
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    publication_date: str | None = None
    doi: str | None = None
    url: str | None = None
    source_rank: int
    abstract_available: bool
    mesh_terms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class LiteratureSearchCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_count: int = 0
    abstract_count: int = 0
    abstract_coverage: float = 0.0
    stored_paper_count: int = 0
    skipped_no_abstract_count: int = 0


class LiteratureSourceTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["pubmed", "mock"]
    live: bool = False
    query_used: str
    compiled_query: str
    retrieval_intent: RetrievalIntent = "unknown"
    project_id: str | None = None
    store_requested: bool = True
    require_abstract: bool = True
    stored_paper_ids: list[str] = Field(default_factory=list)
    unsupported_filters: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class LiteratureSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["pubmed", "mock"]
    query: str
    query_used: str
    retrieval_intent: RetrievalIntent = "unknown"
    live: bool = False
    items: list[LiteraturePaperRecord] = Field(default_factory=list)
    retrieval_manifest: RetrievalManifest
    coverage: LiteratureSearchCoverage
    source_trace: LiteratureSourceTrace
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RetrievalSubquestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subquestion_id: str
    question: str
    query: str
    retrieval_intent: RetrievalIntent
    reason: str
    max_results: int = 5


class CoverageMatrixRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subquestion_id: str
    subquestion: str
    retrieval_intent: RetrievalIntent
    pass_index: int = 1
    query: str
    retrieval_ids: list[str] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)
    papers_found: int = 0
    evidence_count: int = 0
    citations: int = 0
    conflicts: int = 0
    limitations: int = 0
    coverage_status: CoverageStatus
    gap_reason: str | None = None


class GapSearchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str
    subquestion_id: str
    retrieval_intent: RetrievalIntent
    followup_query: str
    reason: str
    executed: bool = False
    retrieval_id: str | None = None
    returned_paper_ids: list[str] = Field(default_factory=list)
    added_paper_ids: list[str] = Field(default_factory=list)
    stop_reason: str | None = None


class EvidencePacketSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    question: str
    planner_mode: PlannerMode = "deterministic"
    source: Literal["pubmed", "mock"] = "mock"
    subquestions: list[RetrievalSubquestion] = Field(default_factory=list)
    retrieval_manifest_ids: list[str] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    supported_claims: list[str] = Field(default_factory=list)
    conflicting_claims: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    coverage_matrix: list[CoverageMatrixRow] = Field(default_factory=list)
    coverage_gaps: list[CoverageMatrixRow] = Field(default_factory=list)
    gap_decisions: list[GapSearchDecision] = Field(default_factory=list)
    source_warnings: list[str] = Field(default_factory=list)
    stop_reason: str = "not_started"
    created_at: str


class LiteratureAccessCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["pubmed", "mock"]
    query: str
    live: bool = False
    ok: bool
    ready: bool
    checked_at: str
    item_count: int = 0
    abstract_count: int = 0
    abstract_coverage: float = 0.0
    stored_paper_count: int = 0
    ncbi_email_configured: bool = False
    ncbi_api_key_configured: bool = False
    retrieval_manifest: RetrievalManifest | None = None
    items: list[PaperMetadata] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RetrievalBundleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: RetrievalIntent
    query: str
    query_id: str | None = None
    subquestion_id: str | None = None
    reason: str | None = None
    pass_index: int = 1
    retrieval_id: str | None = None
    manifest: RetrievalManifest | None = None
    returned_paper_ids: list[str] = Field(default_factory=list)
    added_paper_ids: list[str] = Field(default_factory=list)
    coverage: LiteratureSearchCoverage | None = None
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
    subquestions: list[RetrievalSubquestion] = Field(default_factory=list)
    coverage_matrix: list[CoverageMatrixRow] = Field(default_factory=list)
    gap_decisions: list[GapSearchDecision] = Field(default_factory=list)
    stop_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class WatchSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    watch_id: str
    retrieval_id: str
    paper_ids: list[str] = Field(default_factory=list)
    new_paper_ids: list[str] = Field(default_factory=list)
    created_at: str


class FullTextSpanLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_scope: FullTextSourceScope = "full_text"
    document_id: str
    section_id: str
    section_label: str | None = None
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    source_hash: str


class FullTextSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    document_id: str
    paper_id: str
    label: str = "Full text"
    text: str
    ordinal: int = 0
    page_start: int | None = None
    page_end: int | None = None
    source_hash: str
    created_at: str


class FullTextDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    paper_id: str
    source: BiomedicalSource = "mock"
    content_type: Literal["text/plain", "application/pdf"] = "text/plain"
    title: str | None = None
    source_filename: str | None = None
    provider: str | None = None
    provider_status: str | None = None
    lookup_id_type: Literal["pmid", "pmcid"] | None = None
    license_or_rights: str | None = None
    source_hash: str
    byte_size: int = 0
    section_count: int = 0
    parser: str = "deterministic"
    parser_version: str = "1"
    created_at: str
    updated_at: str


class FullTextIngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = ""
    source: BiomedicalSource = "mock"
    content: str
    content_type: Literal["text/plain", "application/pdf"] = "text/plain"
    source_filename: str | None = None
    provider: str | None = None
    provider_status: str | None = None
    lookup_id_type: Literal["pmid", "pmcid"] | None = None
    license_or_rights: str | None = None
    title: str | None = None
    overwrite: bool = False


class FullTextIngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    document: FullTextDocument | None = None
    sections: list[FullTextSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class FullTextEnhancementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    max_papers: int = 10
    max_evidence_items: int = 20
    source: Literal["pubmed", "mock"] | None = None
    use_open_provider: bool = False
    overwrite_full_text: bool = False


class FullTextEnhancementPaperStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    source: Literal["pubmed", "mock"]
    status: Literal[
        "cached",
        "stored",
        "unavailable",
        "extracted",
        "failed",
        "skipped",
    ]
    document_id: str | None = None
    section_count: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    provider: str | None = None
    provider_status: str | None = None
    source_locator: str | None = None
    lookup_id_type: Literal["pmid", "pmcid"] | None = None
    license_or_rights: str | None = None
    warning: str | None = None
    error: str | None = None


class FullTextEnhancementResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enhancement_id: str
    run_id: str
    source: Literal["pubmed", "mock"]
    processed_paper_ids: list[str] = Field(default_factory=list)
    unavailable_paper_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    extracted_evidence_ids: list[str] = Field(default_factory=list)
    packet_id: str | None = None
    review_available: bool = False
    paper_statuses: list[FullTextEnhancementPaperStatus] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class FullTextReanalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    max_evidence_items: int = 20
    use_llm_revision: bool = False
    use_llm_claim_logic: bool = False
    export_logic_facts: bool = False


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


class AnswerScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    population_terms: list[str] = Field(default_factory=list)
    intervention_terms: list[str] = Field(default_factory=list)
    comparator_terms: list[str] = Field(default_factory=list)
    outcome_terms: list[str] = Field(default_factory=list)
    required_study_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    rationale: str = ""


class EvidenceScopeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_match: ScopeMatch = "uncertain"
    mismatch_reasons: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)


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
    subquestions: list[RetrievalSubquestion] = Field(default_factory=list)
    max_results: int = 10
    rationale: str = ""
    warnings: list[str] = Field(default_factory=list)
    llm_model: str | None = None
    llm_prompt_hash: str | None = None
    llm_raw_response: dict[str, object] | None = None
    answer_scope: AnswerScope | None = None


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
    use_llm_claim_logic: bool = False
    export_logic_facts: bool = False


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
    evidence_maturity: EvidenceMaturity = "emerging_claim"
    scientific_confidence: ConfidenceLevel = "low"
    packet_limitation_level: PacketLimitationLevel = "low"
    review_priority: ReviewPriority = "low"
    suggested_next_steps: list[str] = Field(default_factory=list)
    not_medical_advice: bool = True
    disclaimer: str
    project_id: str | None = None
    project_context_used: str | None = None
    project_context_trace: dict[str, object] = Field(default_factory=dict)
    question_classification: BiomedicalQuestionClassification | None = None
    query_plan: BiomedicalQueryPlan | None = None
    query_plan_validation: QueryPlanValidation | None = None
    evidence_packet: EvidencePacketSummary | None = None
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


class LogicalEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    entity_type: str = "unspecified"
    normalized_id: str | None = None
    source_span: str | None = None


class LogicalClaimFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_text: str
    subject: LogicalEntity
    predicate: LogicPredicate = "unspecified"
    object: LogicalEntity
    polarity: LogicPolarity = "unspecified"
    modality: LogicModality = "unspecified"
    population: LogicPopulation = "unspecified"
    claim_strength: LogicClaimStrength = "unspecified"
    scope: list[str] = Field(default_factory=list)
    qualifiers: list[str] = Field(default_factory=list)
    hedging: bool = False
    source_spans: list[str] = Field(default_factory=list)
    parser_mode: LogicParserMode = "deterministic"
    parser_model: str | None = None
    parser_prompt_hash: str | None = None
    parser_warnings: list[str] = Field(default_factory=list)


class LogicalEvidenceFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    paper_id: str
    evidence_text: str
    subject: LogicalEntity
    predicate: LogicPredicate = "unspecified"
    object: LogicalEntity
    polarity: LogicPolarity = "unspecified"
    modality: LogicModality = "unspecified"
    population: LogicPopulation = "unspecified"
    model_system: str | None = None
    study_design: LogicStudyDesign = "unspecified"
    evidence_strength: EvidenceStrength = "not_assessed"
    limitations: list[str] = Field(default_factory=list)
    source_spans: list[str] = Field(default_factory=list)
    parser_mode: LogicParserMode = "deterministic"
    parser_model: str | None = None
    parser_prompt_hash: str | None = None
    parser_warnings: list[str] = Field(default_factory=list)


class LogicFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predicate: str
    arguments: list[str]
    quoted_arguments: list[bool] = Field(default_factory=list)


class LogicFactExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: str
    claim_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    facts: list[LogicFact] = Field(default_factory=list)
    text: str | None = None
    format: LogicFactFormat = "text"
    exporter_version: str = "logic-fact-export-v1"
    warnings: list[str] = Field(default_factory=list)


class LogicAuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    claim_frame: LogicalClaimFrame | None = None
    evidence_frames: list[LogicalEvidenceFrame] = Field(default_factory=list)
    logic_verdict: LogicVerdict = "not_assessed"
    entailment_score: float = 0.0
    rules_triggered: list[str] = Field(default_factory=list)
    predicate_mismatches: list[dict[str, object]] = Field(default_factory=list)
    scope_mismatches: list[dict[str, object]] = Field(default_factory=list)
    modality_mismatches: list[dict[str, object]] = Field(default_factory=list)
    population_mismatches: list[dict[str, object]] = Field(default_factory=list)
    reason: str
    warnings: list[str] = Field(default_factory=list)
    logic_fact_export: LogicFactExport | None = None


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
    logic_audit: LogicAuditResult | None = None


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


EVIDENCE_REVIEW_SCHEMA_VERSION = "biomed-evidence-review-v1"


class EvidenceGraphSnapshotMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["persisted", "missing", "derived"] = "persisted"
    snapshot_id: str | None = None
    run_id: str
    audit_id: str | None = None
    schema_version: str | None = None
    graph_id: str | None = None
    graph_hash: str | None = None
    source_ids: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    snapshot_required: bool = False
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)
    latest_audit_id: str | None = None
    previous_snapshot_id: str | None = None


class EvidenceGraphSnapshotRecord(EvidenceGraphSnapshotMetadata):
    graph: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)


class RunEvidenceReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_claims: int = 0
    supported: int = 0
    contradicted: int = 0
    qualified: int = 0
    mixed: int = 0
    unsupported: int = 0
    not_assessed: int = 0
    validation_ok: bool = False
    validation_error_count: int = 0
    validation_warning_count: int = 0
    recommended_audit_action: AuditRecommendedAction | None = None
    clinical_refusal: bool = False
    reviewer_accept: int = 0
    reviewer_needs_more_evidence: int = 0
    reviewer_flag_overclaim: int = 0
    reviewer_reject: int = 0


class RunReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str | None = None
    claim_node_id: str | None = None
    decision: RunReviewDecisionValue
    reviewer_note: str | None = None
    decision_source: RunReviewDecisionSource = "api"
    reviewer_id: str | None = None


class RunReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    run_id: str
    claim_id: str
    claim_node_id: str
    snapshot_id: str | None = None
    audit_id: str | None = None
    decision: RunReviewDecisionValue
    reviewer_note: str | None = None
    decision_source: RunReviewDecisionSource = "api"
    reviewer_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class RunEvidenceReviewClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_node_id: str
    claim_text: str
    support_status: str = "not_assessed"
    support_status_reason: str | None = None
    support_counts: dict[str, int] = Field(default_factory=dict)
    audit_verdict: CitationSupportVerdict | None = None
    support_score: float | None = None
    evidence_count: int = 0
    paper_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    limitation_count: int = 0
    review_action: Literal["accept", "needs_review", "needs_revision"] = "needs_review"
    latest_decision: RunReviewDecision | None = None
    evidence_card: dict[str, Any] = Field(default_factory=dict)
    links: dict[str, str] = Field(default_factory=dict)


class RunEvidenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EVIDENCE_REVIEW_SCHEMA_VERSION
    run_id: str
    audit_id: str | None = None
    snapshot: EvidenceGraphSnapshotMetadata
    snapshot_required: bool = False
    summary: RunEvidenceReviewSummary
    claims: list[RunEvidenceReviewClaim] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    graph: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class RunLiteratureSetPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str
    source: Literal["pubmed", "mock"] = "mock"
    title: str = ""
    journal: str | None = None
    publication_date: str | None = None
    doi: str | None = None
    url: str | None = None
    retrieval_rank: int = 0
    abstract_available: bool = False
    decision_id: str | None = None
    decision: ProjectPaperDecisionValue | None = None
    decision_reason: str | None = None
    used_in_answer: bool = False
    evidence_count: int = 0
    has_full_text: bool = False
    packet_included: bool = False
    review_status: Literal["reviewed", "needs_review", "not_reviewed"] = "not_reviewed"


class RunLiteratureSetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_papers: int = 0
    used_in_answer_count: int = 0
    saved_count: int = 0
    rejected_count: int = 0
    needs_review_count: int = 0
    full_text_count: int = 0
    packet_included_count: int = 0
    reviewed_count: int = 0
    not_reviewed_count: int = 0


class RunLiteratureSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    project_id: str | None = None
    retrieval_id: str | None = None
    source: Literal["pubmed", "mock"] = "mock"
    summary: RunLiteratureSetSummary
    papers: list[RunLiteratureSetPaper] = Field(default_factory=list)


class RunReviewPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "biomed-review-packet-v1"
    run_id: str
    review: RunEvidenceReview
    decisions: list[RunReviewDecision] = Field(default_factory=list)
    exported_at: str
    policy: dict[str, object] = Field(default_factory=dict)


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


class MultiPassLiteratureSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    source: Literal["pubmed", "mock"] = "mock"
    max_results: int = 10
    max_queries: int = 6
    max_followups: int = 0
    max_tool_steps: int = 20
    max_wall_clock_seconds: int = 180
    project_id: str | None = None
    project_context: str | None = None
    include_rejected_papers: bool = False
    use_llm_planner: bool = False
    execute_support_refute: bool = True


class MultiPassLiteratureSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    source: Literal["pubmed", "mock"] = "mock"
    classification: BiomedicalQuestionClassification | None = None
    query_plan: BiomedicalQueryPlan | None = None
    validation: QueryPlanValidation | None = None
    retrieval_manifest: RetrievalManifest | None = None
    retrieval_bundle: RetrievalBundle | None = None
    paper_ids: list[str] = Field(default_factory=list)
    item_count: int = 0
    memory_trace: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    step_telemetry: StepTelemetrySummary | None = None


class EvidenceBatchExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    retrieval_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    source: Literal["pubmed", "mock"] = "mock"
    research_question: str | None = None
    use_llm_extractor: bool = False
    max_papers: int = 10
    max_evidence_items: int = 50


class EvidenceBatchExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    retrieval_id: str | None = None
    source: Literal["pubmed", "mock"] = "mock"
    paper_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    evidence_count: int = 0
    extraction_mode_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    memory_trace: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)


class CoverageGapAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    retrieval_id: str | None = None
    source: Literal["pubmed", "mock"] = "mock"
    research_question: str | None = None
    max_gap_queries: int = 2


class CoverageGapAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    retrieval_id: str | None = None
    coverage_matrix: list[CoverageMatrixRow] = Field(default_factory=list)
    gap_decisions: list[GapSearchDecision] = Field(default_factory=list)
    bandit_advisory: BanditAdvisoryResult | None = None
    stop_reason: str = "not_started"
    memory_trace: dict[str, Any] = Field(default_factory=dict)
    step_telemetry: StepTelemetrySummary | None = None


class EvidencePacketBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    max_evidence_items: int = 12
    selection_strategy: EvidencePacketSelectionStrategy = "submodular_greedy"


class EvidencePacketBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    evidence_packet: EvidencePacketSummary
    selection: EvidencePacketSelectionResult
    availability: EvidencePacketAvailability = "persisted"
    memory_trace: dict[str, Any] = Field(default_factory=dict)
    step_telemetry: StepTelemetrySummary | None = None


class EvidencePacketGetResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    evidence_packet: EvidencePacketSummary | None = None
    availability: EvidencePacketAvailability = "unavailable"
    stale: bool = False
    source: Literal["pubmed", "mock"] | None = None
    memory_trace: dict[str, Any] = Field(default_factory=dict)
    step_telemetry: StepTelemetrySummary | None = None


class ObsidianExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    project_id: str | None = None
    watch_id: str | None = None
    export_dir: str | None = None
    enabled: bool = False
    max_files: int = 50


class ObsidianNoteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: str
    export_type: ObsidianExportType
    entity_id: str
    path: str
    filename: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    links: list[str] = Field(default_factory=list)
    sha256: str
    generated_at: str
    source_of_truth: str = "biomed_sqlite"
    imported_as_evidence: bool = False


class ObsidianExportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_id: str
    export_type: ObsidianExportType
    export_dir: str
    notes: list[ObsidianNoteRecord] = Field(default_factory=list)
    note_count: int = 0
    idempotent_key: str
    source_of_truth: str = "biomed_sqlite"
    imported_as_evidence: bool = False
    warnings: list[str] = Field(default_factory=list)


class ProvenanceNodeEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: ProvenanceEntityType
    stable_id: str
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProvenanceActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: ProvenanceActivityType
    label: str
    started_at: str | None = None
    ended_at: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProvenanceAgent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: ProvenanceAgentType
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProvenanceRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    type: ProvenanceRelationType
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProvenanceGraphResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_id: str
    run_id: str
    schema_version: str = "biomed-provenance-v1"
    entities: list[ProvenanceNodeEntity] = Field(default_factory=list)
    activities: list[ProvenanceActivity] = Field(default_factory=list)
    agents: list[ProvenanceAgent] = Field(default_factory=list)
    relations: list[ProvenanceRelation] = Field(default_factory=list)
    redactions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CitationAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    run_id: str | None = None
    retrieval_id: str | None = None
    observed_uncertainty: ConfidenceLevel | None = None
    retrieval_manifest: RetrievalManifest | None = None
    use_llm_claim_logic: bool = False
    export_logic_facts: bool = False


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


class WatchDriftChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_type: Literal[
        "paper_added",
        "paper_removed",
        "claim_added",
        "claim_removed",
        "support_shift",
        "method_added",
        "method_removed",
        "limitation_added",
        "limitation_removed",
        "entity_added",
        "entity_removed",
    ]
    item_id: str
    label: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    paper_ids: list[str] = Field(default_factory=list)


class WatchGraphDriftResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "biomed-watch-graph-drift-v1"
    watch_id: str
    base_snapshot_id: str | None = None
    compare_snapshot_id: str | None = None
    status: Literal["ok", "insufficient_snapshots", "watch_not_found"] = "ok"
    advisory_only: bool = True
    change_count: int = 0
    changes: list[WatchDriftChange] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


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


class PilotReportRoi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_baseline_minutes: float | None = None
    reviewer_minutes: float | None = None
    time_saved_minutes: float | None = None
    roi_basis: str = "not_provided"


class PilotReportObservability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = None
    cache_hit_tokens: int | None = None
    cache_hit_rate: float | None = None
    llm_call_count: int | None = None
    source_call_count: int | None = None
    artifact_cache_hit_count: int | None = None
    artifact_cache_miss_count: int | None = None
    artifact_cache_write_count: int | None = None
    saved_source_call_count: int | None = None
    artifact_cache_hit_rate: float | None = None
    estimated_cost_usd: float | None = None
    latency_seconds: float | None = None
    cache_entries: list[dict[str, Any]] = Field(default_factory=list)
    cache_basis: str = "Biomedical artifact cache telemetry is derived from trace metadata."
    available_fields: list[str] = Field(default_factory=list)
    unavailable_fields: list[str] = Field(default_factory=list)
    basis: str = "Release 2.1 observability contract; telemetry may be unavailable."


class PilotReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "biomed-pilot-report-v1"
    run_id: str
    question: str
    source: Literal["pubmed", "mock"] = "mock"
    generated_at: str
    paper_count: int = 0
    retrieval_id: str | None = None
    evidence_packet_id: str | None = None
    audit_summary: dict[str, Any] = Field(default_factory=dict)
    review_summary: dict[str, Any] = Field(default_factory=dict)
    roi: PilotReportRoi
    observability: PilotReportObservability
    artifact_links: dict[str, str] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class ExportEvidenceReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    question: str | None = None
    format: Literal["markdown", "json"] = "markdown"
    report_type: Literal["standard", "pilot"] = "standard"
    manual_baseline_minutes: float | None = None
    reviewer_minutes: float | None = None


class HarnessScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    source: Literal["pubmed", "mock"] = "mock"
    max_papers: int = 3
    project_id: str | None = None
    require_citations: bool = True
    enable_full_text_enhance: bool = False
    manual_baseline_minutes: float | None = None
    reviewer_minutes: float | None = None
    must_include_citations: bool = True
    forbidden_outputs: list[str] = Field(default_factory=list)
    max_unsupported_rate: float | None = None
    max_overclaim_rate: float | None = None
    require_review_completion: bool = False
    require_literature_set: bool = False


class HarnessScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    run_id: str
    retrieval_id: str | None = None
    source: Literal["pubmed", "mock"] = "mock"
    question: str
    final_answer: str = ""
    literature_set_summary: RunLiteratureSetSummary = Field(
        default_factory=RunLiteratureSetSummary
    )
    pilot_report: PilotReport
    metrics: dict[str, Any] = Field(default_factory=dict)
    gates: dict[str, Any] = Field(default_factory=dict)
    full_text_enhancement: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    passed: bool = False


class PageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, object]]
    total: int
    page: int
    page_size: int
