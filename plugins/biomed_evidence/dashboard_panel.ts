/// <reference path="../../types/akashic-dashboard.d.ts" />

type BiomedView = "chat" | "runs" | "queue" | "library" | "settings";
type LegacyBiomedView = "ask" | "projects" | "evidence" | "graph" | "review" | "watch" | "audit" | "trace" | "responsible" | "advanced";

let biomedWorkflowTemplates: SavedToolChainTemplate[] = [];

const BIOMED_VIEW_ITEMS: { id: BiomedView; label: string; description: string }[] = [
  { id: "chat", label: "Chat", description: "agent console" },
  { id: "runs", label: "Runs", description: "workspace" },
  { id: "queue", label: "Review Queue", description: "triage" },
  { id: "library", label: "Library", description: "papers · watch" },
  { id: "settings", label: "Settings", description: "boundary" },
];

interface EvidenceRow {
  evidence_id: string;
  paper_id: string;
  retrieval_id?: string | null;
  retrieval_intent?: string;
  extraction_mode?: string;
  paper_title?: string;
  claim: string;
  finding: string;
  evidence_direction: string;
  confidence: string;
  limitations?: string[];
  entities?: { name: string; entity_type: string }[];
  methods?: string[];
  source_scope?: string;
  document_id?: string | null;
  section_id?: string | null;
  section_label?: string | null;
  page_number?: number | null;
  char_start?: number | null;
  char_end?: number | null;
  source_hash?: string | null;
}

interface RetrievalManifest {
  retrieval_id: string;
  source: string;
  original_query: string;
  compiled_query: string;
  page_size: number;
  pages_requested: number;
  pages_completed: number;
  raw_result_count: number;
  deduped_result_count: number;
  returned_paper_ids: string[];
  dropped_or_duplicate_ids: string[];
  unsupported_filters: string[];
  warnings: string[];
  errors: string[];
}

interface RetrievalBundleRecord {
  intent: string;
  query: string;
  query_id?: string | null;
  subquestion_id?: string | null;
  reason?: string | null;
  pass_index?: number;
  retrieval_id?: string | null;
  returned_paper_ids: string[];
  added_paper_ids?: string[];
  coverage?: {
    item_count: number;
    abstract_count: number;
    abstract_coverage: number;
    stored_paper_count: number;
    skipped_no_abstract_count: number;
  } | null;
  warnings: string[];
  errors: string[];
  skipped_reason?: string | null;
}

interface RetrievalSubquestion {
  subquestion_id: string;
  question: string;
  query: string;
  retrieval_intent: string;
  reason: string;
  max_results: number;
}

interface CoverageMatrixRow {
  subquestion_id: string;
  subquestion: string;
  retrieval_intent: string;
  pass_index: number;
  query: string;
  retrieval_ids: string[];
  paper_ids: string[];
  papers_found: number;
  evidence_count: number;
  citations: number;
  conflicts: number;
  limitations: number;
  coverage_status: string;
  gap_reason?: string | null;
}

interface GapSearchDecision {
  gap_id: string;
  subquestion_id: string;
  retrieval_intent: string;
  followup_query: string;
  reason: string;
  executed: boolean;
  retrieval_id?: string | null;
  returned_paper_ids: string[];
  added_paper_ids: string[];
  stop_reason?: string | null;
}

interface RetrievalBundle {
  bundle_id: string;
  source: string;
  executed_multi_query: boolean;
  records: RetrievalBundleRecord[];
  deduped_paper_ids: string[];
  duplicate_paper_ids: string[];
  subquestions?: RetrievalSubquestion[];
  coverage_matrix?: CoverageMatrixRow[];
  gap_decisions?: GapSearchDecision[];
  stop_reason?: string | null;
  warnings: string[];
}

interface EvidencePacketSummary {
  packet_id: string;
  question: string;
  planner_mode: string;
  source: string;
  subquestions: RetrievalSubquestion[];
  retrieval_manifest_ids: string[];
  paper_ids: string[];
  evidence_ids: string[];
  supported_claims: string[];
  conflicting_claims: string[];
  limitations: string[];
  coverage_matrix: CoverageMatrixRow[];
  coverage_gaps: CoverageMatrixRow[];
  gap_decisions: GapSearchDecision[];
  source_warnings: string[];
  stop_reason: string;
  created_at: string;
}

interface AnswerResult {
  run_id: string;
  project_id?: string | null;
  project_context_trace?: Record<string, unknown>;
  retrieval_id?: string | null;
  retrieval_manifest?: RetrievalManifest | null;
  retrieval_bundle?: RetrievalBundle | null;
  evidence_packet?: EvidencePacketSummary | null;
  answer: string;
  citations: { paper_id: string; title: string; doi?: string | null; url?: string | null; cited_claim: string }[];
  evidence_summary: EvidenceRow[];
  conflicting_evidence: EvidenceRow[];
  limitations: string[];
  uncertainty_level: string;
  scientific_confidence?: string;
  packet_limitation_level?: string;
  review_priority?: string;
  suggested_next_steps: string[];
  not_medical_advice: boolean;
  disclaimer: string;
  synthesis_mode?: string;
  synthesis_model?: string | null;
  synthesis_fallback_reason?: string | null;
}

interface WatchTopic {
  watch_id: string;
  topic: string;
  schedule: string;
  enabled: boolean;
  min_relevance_score: number;
  last_checked_at?: string | null;
  next_check_at?: string | null;
}

interface WatchDecision {
  decision_id: string;
  watch_id: string;
  paper_id: string;
  retrieval_id?: string | null;
  snapshot_id?: string | null;
  relevance_score: number;
  decision: string;
  rationale: string;
  title?: string | null;
}

interface WatchCheckResult {
  decisions: WatchDecision[];
  checked_at: string;
  retrieval_manifest?: RetrievalManifest | null;
  snapshot?: {
    snapshot_id: string;
    watch_id: string;
    retrieval_id: string;
    paper_ids: string[];
    new_paper_ids: string[];
    created_at: string;
  } | null;
}

interface WatchDriftChange {
  change_type: string;
  item_id: string;
  label: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  evidence_ids: string[];
  paper_ids: string[];
}

interface WatchGraphDriftResult {
  schema_version: string;
  watch_id: string;
  base_snapshot_id?: string | null;
  compare_snapshot_id?: string | null;
  status: string;
  advisory_only: boolean;
  change_count: number;
  changes: WatchDriftChange[];
  summary: Record<string, number>;
  warnings: string[];
}

interface FullTextDocument {
  document_id: string;
  paper_id: string;
  source: string;
  content_type: string;
  title?: string | null;
  source_filename?: string | null;
  source_hash: string;
  byte_size: number;
  section_count: number;
  parser: string;
  parser_version: string;
  created_at: string;
  updated_at: string;
}

interface FullTextSection {
  section_id: string;
  document_id: string;
  paper_id: string;
  label: string;
  text: string;
  ordinal: number;
  page_start?: number | null;
  page_end?: number | null;
  source_hash: string;
  created_at: string;
}

interface FullTextIngestionResult {
  ok: boolean;
  document?: FullTextDocument | null;
  sections: FullTextSection[];
  warnings: string[];
  errors: string[];
}

interface LogicFactExport {
  export_id: string;
  evidence_ids: string[];
  facts: { predicate: string; arguments: string[]; quoted_arguments?: boolean[] }[];
  text?: string | null;
  format: string;
  exporter_version: string;
  warnings: string[];
}

interface LogicParserFrame {
  parser_mode?: string;
  parser_model?: string | null;
  parser_prompt_hash?: string | null;
  parser_warnings?: string[];
  [key: string]: unknown;
}

interface LogicAuditResult {
  claim_id: string;
  evidence_ids: string[];
  claim_frame?: LogicParserFrame | null;
  evidence_frames?: LogicParserFrame[];
  logic_verdict: string;
  entailment_score: number;
  rules_triggered: string[];
  predicate_mismatches: Record<string, unknown>[];
  scope_mismatches: Record<string, unknown>[];
  modality_mismatches: Record<string, unknown>[];
  population_mismatches: Record<string, unknown>[];
  reason: string;
  warnings: string[];
  logic_fact_export?: LogicFactExport | null;
}

interface ClaimAuditItem {
  claim_id: string;
  claim: string;
  claim_type: string;
  cited_paper_ids: string[];
  evidence_ids: string[];
  evidence_span?: string | null;
  verdict: string;
  support_score: number;
  evidence_strength: string;
  overclaim_reason?: string | null;
  reason: string;
  reviewer_notes: string[];
  logic_audit?: LogicAuditResult | null;
}

interface CitationAuditResult {
  audit_id: string;
  run_id?: string | null;
  retrieval_id?: string | null;
  claim_support_rate: number;
  citation_precision: number;
  packet_citation_utilization?: number;
  unsupported_claim_rate: number;
  overclaim_rate: number;
  conflict_awareness: boolean;
  uncertainty_calibrated: boolean;
  recommended_action: string;
  claim_audits: ClaimAuditItem[];
  failed_claims: ClaimAuditItem[];
}

interface AdvisoryVerifierDisagreement {
  claim_id?: string | null;
  claim: string;
  deterministic_verdict?: string | null;
  deterministic_action: string;
  advisory_verdict: string;
  advisory_action: string;
  risk_level: string;
  high_risk: boolean;
  reason: string;
}

interface AdvisoryVerifierResult {
  verifier_id: string;
  run_id: string;
  audit_id: string;
  verifier_mode: string;
  llm_model?: string | null;
  fallback_reason?: string | null;
  deterministic_action: string;
  advisory_action: string;
  disagreements: AdvisoryVerifierDisagreement[];
  high_risk_disagreement_count: number;
  warnings: string[];
  errors: string[];
}

interface AgentTraceStep {
  step_id: string;
  run_id: string;
  step: string;
  status: string;
  input_summary: string;
  output_summary: string;
  warnings: string[];
  metadata: Record<string, unknown>;
  created_at: string;
}

interface AnswerRevision {
  revision_id: string;
  run_id: string;
  audit_id?: string | null;
  draft_answer: string;
  final_answer: string;
  changed_claims: string[];
  removed_claims: string[];
  softened_claims: string[];
  added_limitations: string[];
  revision_mode?: string;
  fallback_reason?: string | null;
  refusal_reason?: string | null;
  revision_action: string;
  created_at: string;
}

interface AuditedAnswerResult {
  answer_result: AnswerResult;
  draft_answer: string;
  final_answer: string;
  audit: CitationAuditResult;
  advisory_verifier?: AdvisoryVerifierResult | null;
  revision: AnswerRevision;
  trace: AgentTraceStep[];
  final_action: string;
}

interface AuditRunPayload extends AnswerResult {
  latest_citation_audit?: CitationAuditResult | null;
  latest_advisory_verifier?: AdvisoryVerifierResult | null;
  latest_revision?: AnswerRevision | null;
  trace?: AgentTraceStep[] | null;
}

interface TracePayload {
  run_id: string;
  answer_run: AnswerResult;
  trace: AgentTraceStep[];
  step_telemetry?: StepTelemetrySummary | null;
  observability?: Record<string, unknown> | null;
  memory?: Record<string, unknown>;
  revision?: AnswerRevision | null;
  latest_citation_audit?: CitationAuditResult | null;
  latest_advisory_verifier?: AdvisoryVerifierResult | null;
}

interface StepTelemetrySummary {
  run_id?: string | null;
  transition_records: {
    from_state: string;
    to_state: string;
    tool_or_route: string;
    step_index: number;
    stop_reason?: string | null;
    success_category: string;
  }[];
  transition_matrix: Record<string, Record<string, number>>;
  mean_tool_step_count: number;
  p95_tool_step_count: number;
  expected_remaining_steps: number;
  unusual_path_warnings: string[];
  advisory_only: boolean;
}

interface ArgumentGraphNode {
  node_id: string;
  node_type: string;
  label: string;
  metadata: Record<string, unknown>;
}

interface ArgumentGraphEdge {
  edge_id: string;
  source: string;
  target: string;
  edge_type: string;
  weight: number;
  metadata: Record<string, unknown>;
}

interface ClaimArgumentSummary {
  claim_id: string;
  support_count: number;
  attack_count: number;
  limitation_count: number;
  citation_count: number;
  unresolved_conflict_count: number;
  strongest_supporting_evidence_ids: string[];
  strongest_attacking_evidence_ids: string[];
  limitation_summary: string[];
}

interface ArgumentGraphResult {
  run_id: string;
  audit_id?: string | null;
  retrieval_id?: string | null;
  status: string;
  advisory_only: boolean;
  nodes: ArgumentGraphNode[];
  edges: ArgumentGraphEdge[];
  claim_summaries: ClaimArgumentSummary[];
  unresolved_conflict_count: number;
  warnings: string[];
  not_applicable_reason?: string | null;
}

interface ClaimUncertaintySignal {
  claim_id: string;
  claim: string;
  risk_bucket: string;
  risk_score: number;
  recommendation: string;
  reason_factors: string[];
  support_score: number;
  citation_verdict?: string | null;
  logic_verdict?: string | null;
  evidence_strength: string;
}

interface CoverageDiversitySignal {
  diversity_score: number;
  paper_count: number;
  evidence_count: number;
  unique_method_count: number;
  unique_model_or_population_count: number;
  paper_concentration: Record<string, number>;
  retrieval_intent_coverage: Record<string, number>;
  limitation_count: number;
  duplicate_pressure: number;
  concentration_warnings: string[];
  missing_intent_warnings: string[];
  recommended_retrieval_direction?: string | null;
}

interface MathSignalsResult {
  run_id: string;
  audit_id?: string | null;
  retrieval_id?: string | null;
  status: string;
  advisory_only: boolean;
  answer_uncertainty_bucket: string;
  recommendation: string;
  claim_uncertainty: ClaimUncertaintySignal[];
  coverage_diversity: CoverageDiversitySignal;
  step_telemetry: StepTelemetrySummary;
  argument_graph: ArgumentGraphResult;
  reason_factors: string[];
  warnings: string[];
  not_applicable_reason?: string | null;
}

interface ReleaseToolEnvelope<T = Record<string, unknown>> {
  ok: boolean;
  result: T;
  warnings: string[];
  error_code?: string | null;
  message?: string | null;
  trace: Record<string, unknown>;
  ids: Record<string, string>;
  metadata?: {
    tool_name: string;
    risk_level: string;
    source_policy: string;
    side_effects: string[];
    requires_confirmation: boolean;
  } | null;
}

interface SavedToolChainTemplate {
  template_id: string;
  name: string;
  description?: string | null;
  builtin: boolean;
  source: "mock" | "pubmed";
  source_policy: string;
  max_papers: number;
  max_queries: number;
  max_followups: number;
  max_tool_steps: number;
  max_wall_clock_seconds: number;
  include_rejected_papers: boolean;
  require_citations: boolean;
  execute_support_refute: boolean;
  use_llm_planner: boolean;
  use_llm_extractor: boolean;
  use_llm_synthesis: boolean;
  use_llm_verifier: boolean;
  use_llm_revision: boolean;
  use_llm_claim_logic: boolean;
  export_logic_facts: boolean;
  build_evidence_packet: boolean;
  export_provenance: boolean;
  clinical_guard_required: boolean;
  required_skills: string[];
  stop_conditions: string[];
}

interface SavedToolChainTemplateListResult {
  items: SavedToolChainTemplate[];
  total: number;
}

interface SavedToolChainTemplateRunResult {
  template: SavedToolChainTemplate;
  audited_answer: AuditedAnswerResult;
  provenance?: ReleaseToolEnvelope<ProvenanceGraphResult> | null;
}

interface AnswerRunListItem {
  run_id: string;
  question: string;
  retrieval_id?: string | null;
  created_at: string;
}

interface RunLiteratureSetPaper {
  paper_id: string;
  source: "pubmed" | "mock";
  title: string;
  journal?: string | null;
  publication_date?: string | null;
  retrieval_rank: number;
  abstract_available: boolean;
  decision?: string | null;
  decision_reason?: string | null;
  used_in_answer: boolean;
  evidence_count: number;
  has_full_text: boolean;
  packet_included: boolean;
  review_status: "reviewed" | "needs_review" | "not_reviewed";
}

interface RunLiteratureSetSummary {
  total_papers: number;
  used_in_answer_count: number;
  saved_count: number;
  rejected_count: number;
  needs_review_count: number;
  full_text_count: number;
  packet_included_count: number;
  reviewed_count: number;
  not_reviewed_count: number;
}

interface RunLiteratureSet {
  run_id: string;
  project_id?: string | null;
  retrieval_id?: string | null;
  source: "pubmed" | "mock";
  summary: RunLiteratureSetSummary;
  papers: RunLiteratureSetPaper[];
}

interface FullTextEnhancementPaperStatus {
  paper_id: string;
  source: "pubmed" | "mock";
  status: "cached" | "stored" | "unavailable" | "extracted" | "failed" | "skipped";
  document_id?: string | null;
  section_count: number;
  evidence_ids: string[];
  provider?: string | null;
  provider_status?: string | null;
  source_locator?: string | null;
  lookup_id_type?: "pmid" | "pmcid" | null;
  license_or_rights?: string | null;
  warning?: string | null;
  error?: string | null;
}

interface FullTextEnhancementResult {
  enhancement_id: string;
  run_id: string;
  source: "pubmed" | "mock";
  processed_paper_ids: string[];
  unavailable_paper_ids: string[];
  document_ids: string[];
  extracted_evidence_ids: string[];
  packet_id?: string | null;
  review_available: boolean;
  paper_statuses: FullTextEnhancementPaperStatus[];
  warnings: string[];
  errors: string[];
}

interface WorkspaceRunContext {
  answer: AnswerResult;
  audited?: AuditedAnswerResult | null;
  trace?: TracePayload | null;
  provenance?: ReleaseToolEnvelope<ProvenanceGraphResult> | null;
  literature?: RunLiteratureSet | null;
  fullTextEnhancement?: ReleaseToolEnvelope<FullTextEnhancementResult> | null;
  fullTextReanalysis?: AuditedAnswerResult | null;
  pilotReportMarkdown?: string | null;
  raw?: unknown;
}

interface FullTextRunCacheEntry {
  literature?: RunLiteratureSet | null;
  fullTextEnhancement?: ReleaseToolEnvelope<FullTextEnhancementResult> | null;
  fullTextReanalysis?: AuditedAnswerResult | null;
}

const fullTextRunCache = new Map<string, FullTextRunCacheEntry>();

interface EvidenceSelectionItem {
  evidence_id: string;
  paper_id: string;
  selected: boolean;
  reason: string;
  score: number;
  coverage_contribution: Record<string, unknown>;
  token_estimate: number;
}

interface EvidencePacketSelectionResult {
  strategy: string;
  max_items: number;
  selected: EvidenceSelectionItem[];
  dropped: EvidenceSelectionItem[];
  selected_evidence_ids: string[];
  dropped_evidence_ids: string[];
  coverage_contribution: Record<string, unknown>;
  token_estimate: number;
  duplicate_evidence_delta: number;
  trace: Record<string, unknown>;
}

interface EvidencePacketBuildResult {
  run_id: string;
  evidence_packet: EvidencePacketSummary;
  selection: EvidencePacketSelectionResult;
  availability: string;
  memory_trace: Record<string, unknown>;
  step_telemetry?: StepTelemetrySummary | null;
}

interface ObsidianExportResult {
  export_id: string;
  export_type: string;
  export_dir: string;
  notes: {
    export_id: string;
    export_type: string;
    entity_id: string;
    path: string;
    filename: string;
    links: string[];
    sha256: string;
    imported_as_evidence: boolean;
  }[];
  note_count: number;
  idempotent_key: string;
  source_of_truth: string;
  imported_as_evidence: boolean;
  warnings: string[];
}

interface ProvenanceGraphResult {
  graph_id: string;
  run_id: string;
  schema_version: string;
  entities: { id: string; type: string; stable_id: string; label: string; attributes: Record<string, unknown> }[];
  activities: { id: string; type: string; label: string; attributes: Record<string, unknown> }[];
  agents: { id: string; type: string; label: string; attributes: Record<string, unknown> }[];
  relations: { source: string; target: string; type: string; attributes: Record<string, unknown> }[];
  redactions: string[];
  warnings: string[];
}

interface BiomedEvidenceGraphNode {
  id: string;
  type: string;
  label: string;
  properties: Record<string, unknown>;
}

interface BiomedEvidenceGraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  properties: Record<string, unknown>;
}

interface BiomedEvidenceGraphValidation {
  ok: boolean;
  error_count: number;
  warning_count: number;
  issues: {
    code: string;
    message: string;
    severity: string;
    node_id?: string | null;
    edge_id?: string | null;
    data: Record<string, unknown>;
  }[];
}

interface BiomedEvidenceGraphV1 {
  schema_version: string;
  graph_id?: string | null;
  scope: {
    kind: string;
    identifiers: Record<string, string>;
    filters: Record<string, unknown>;
  };
  nodes: BiomedEvidenceGraphNode[];
  edges: BiomedEvidenceGraphEdge[];
  warnings: string[];
  validation?: BiomedEvidenceGraphValidation | null;
}

interface BiomedEvidenceCard {
  claim_id: string;
  claim_node_id: string;
  claim_text: string;
  support_status: string;
  support_status_reason?: string | null;
  support_counts: Record<string, number>;
  evidence: {
    evidence_id: string;
    evidence_node_id: string;
    relation: string;
    text: string;
    paper_id?: string | null;
    paper_title?: string | null;
    confidence?: string | null;
    evidence_direction?: string | null;
    retrieval_intent?: string | null;
    extraction_mode?: string | null;
    limitations: string[];
    methods: string[];
  }[];
  limitations: string[];
  audit_results: Record<string, unknown>[];
  warnings: string[];
}

interface EvidenceGraphSnapshotMetadata {
  status: "persisted" | "missing" | "derived";
  snapshot_id?: string | null;
  run_id: string;
  audit_id?: string | null;
  schema_version?: string | null;
  graph_id?: string | null;
  graph_hash?: string | null;
  source_ids: Record<string, unknown>;
  created_at?: string | null;
  snapshot_required: boolean;
  stale?: boolean;
  stale_reasons?: string[];
  latest_audit_id?: string | null;
  previous_snapshot_id?: string | null;
}

interface EvidenceGraphSnapshotDiff {
  run_id: string;
  available: boolean;
  reason?: string;
  base_snapshot_id?: string | null;
  compare_snapshot_id?: string | null;
  base_audit_id?: string | null;
  compare_audit_id?: string | null;
  changes: Record<string, unknown>;
}

interface RunEvidenceReviewSummary {
  total_claims: number;
  supported: number;
  contradicted: number;
  qualified: number;
  mixed: number;
  unsupported: number;
  not_assessed: number;
  validation_ok: boolean;
  validation_error_count: number;
  validation_warning_count: number;
  recommended_audit_action?: string | null;
  clinical_refusal: boolean;
  reviewer_accept: number;
  reviewer_needs_more_evidence: number;
  reviewer_flag_overclaim: number;
  reviewer_reject: number;
}

type RunReviewDecisionValue = "accept" | "needs_more_evidence" | "flag_overclaim" | "reject";

interface RunReviewDecision {
  decision_id: string;
  run_id: string;
  claim_id: string;
  claim_node_id: string;
  snapshot_id?: string | null;
  audit_id?: string | null;
  decision: RunReviewDecisionValue;
  reviewer_note?: string | null;
  decision_source: "api" | "dashboard" | "tool";
  reviewer_id?: string | null;
  paper_ids: string[];
  evidence_ids: string[];
  created_at: string;
  updated_at: string;
}

interface RunEvidenceReviewClaim {
  claim_id: string;
  claim_node_id: string;
  claim_text: string;
  support_status: string;
  support_status_reason?: string | null;
  support_counts: Record<string, number>;
  audit_verdict?: string | null;
  support_score?: number | null;
  evidence_count: number;
  paper_ids: string[];
  evidence_ids: string[];
  limitation_count: number;
  review_action: "accept" | "needs_review" | "needs_revision";
  latest_decision?: RunReviewDecision | null;
  evidence_card: BiomedEvidenceCard;
  links: Record<string, string>;
}

interface RunEvidenceReview {
  schema_version: string;
  run_id: string;
  audit_id?: string | null;
  snapshot: EvidenceGraphSnapshotMetadata;
  snapshot_required: boolean;
  summary: RunEvidenceReviewSummary;
  claims: RunEvidenceReviewClaim[];
  links: Record<string, string>;
  validation: BiomedEvidenceGraphValidation;
  graph?: BiomedEvidenceGraphV1 | null;
  warnings: string[];
}

interface BiomedProject {
  project_id: string;
  name: string;
  description?: string | null;
  research_question: string;
  include_keywords: string[];
  exclude_keywords: string[];
  preferred_methods: string[];
  preferred_species: string[];
  preferred_study_types: string[];
  created_at: string;
  updated_at: string;
}

interface ProjectPaperDecision {
  decision_id: string;
  project_id: string;
  paper_id: string;
  source: string;
  decision: string;
  reason?: string | null;
  tags: string[];
  run_id?: string | null;
  retrieval_id?: string | null;
  updated_at: string;
}

interface ProjectClaimRecord {
  claim_id: string;
  project_id: string;
  claim: string;
  status: string;
  evidence_ids: string[];
  audit_ids: string[];
  verifier_ids: string[];
  updated_at: string;
}

interface ProjectReviewQueueItem {
  item_id: string;
  project_id: string;
  item_type: string;
  title: string;
  reason: string;
  risk_level: string;
  run_id?: string | null;
  audit_id?: string | null;
  verifier_id?: string | null;
  created_at: string;
}

interface ProjectEvidenceBrief {
  brief_id: string;
  project_id: string;
  title: string;
  format: string;
  content: string;
  audit_ids: string[];
  verifier_ids: string[];
  created_at: string;
}

interface DashboardChatMessage {
  id: string;
  session_key: string;
  seq: number;
  role: string;
  content: string;
  ts: string;
}

interface DashboardChatSseMessage {
  event: string;
  seq?: number;
  session_key?: string;
  kind?: string;
  label?: string;
  detail?: string;
  content?: string;
  content_delta?: string;
  thinking_delta?: string;
  thinking?: string;
  tool_name?: string;
  call_id?: string;
  arguments?: unknown;
  final_arguments?: unknown;
  status?: string;
  iteration?: number;
  has_more?: boolean;
  latest_seq?: number;
  replay_from_seq?: number | null;
  message?: string;
  content_preview?: string;
}

interface BiomedChatLiveNotice {
  kind: "system";
  seq: number;
  summary: string;
  detail?: string;
}

function biomedChatProgressSummary(event: string, data: DashboardChatSseMessage): string {
  const toolName = String(data.tool_name || "");
  const label = String(data.label || "");
  const detail = String(data.detail || data.message || "");
  if (event === "user_message_accepted") {
    return "Message received";
  }
  if (event === "turn_started") {
    return "Agent started the biomedical review";
  }
  if (event === "assistant_delta") {
    return "Writing the response";
  }
  if (event === "tool_started") {
    return biomedToolProgressSummary(toolName, "started");
  }
  if (event === "tool_completed") {
    return biomedToolProgressSummary(toolName, String(data.status || "completed"));
  }
  if (event === "step") {
    return biomedStepProgressSummary(label || detail);
  }
  if (event === "error") {
    return detail || "Something went wrong";
  }
  return label || detail || "Review workflow is progressing";
}

function biomedToolProgressSummary(toolName: string, status: string): string {
  const done = status === "success" || status === "completed" || status === "done";
  const prefix = done ? "Completed" : "Running";
  const normalized = toolName.toLowerCase();
  if (normalized.includes("workflow") || normalized.includes("tool_chain")) {
    return `${prefix} the evidence review workflow`;
  }
  if (normalized.includes("template")) {
    return `${prefix} the selected review template`;
  }
  if (normalized.includes("plan_biomedical_search") || normalized.includes("plan")) {
    return `${prefix} biomedical search planning`;
  }
  if (normalized.includes("search_literature") || normalized.includes("pubmed") || normalized.includes("literature")) {
    return `${prefix} PubMed literature retrieval`;
  }
  if (normalized.includes("extract")) {
    return `${prefix} evidence extraction`;
  }
  if (normalized.includes("audit") || normalized.includes("verify")) {
    return `${prefix} citation and claim checks`;
  }
  if (normalized.includes("provenance") || normalized.includes("evidence_packet")) {
    return `${prefix} evidence packaging`;
  }
  if (toolName) {
    return `${prefix} ${biomedHumanizeToolName(toolName)}`;
  }
  return done ? "Step completed" : "Working on the biomedical review";
}

function biomedStepProgressSummary(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("assistant response ready")) {
    return "Drafting the final response";
  }
  if (normalized.includes("tools called")) {
    return "Review workflow is progressing";
  }
  if (normalized.includes("accepted")) {
    return "Request accepted";
  }
  if (normalized.includes("started")) {
    return "Agent started the biomedical review";
  }
  return value || "Review workflow is progressing";
}

function biomedHumanizeToolName(value: string): string {
  return value
    .replace(/^mcp__[^.]+\./, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function compactBiomedChatDetail(event: string, data: DashboardChatSseMessage): string | undefined {
  const details: Record<string, unknown> = { event };
  for (const key of ["tool_name", "status", "iteration", "call_id", "detail", "label", "arguments", "final_arguments", "has_more"]) {
    const value = data[key as keyof DashboardChatSseMessage];
    if (value !== undefined && value !== "") {
      details[key] = value;
    }
  }
  if (Object.keys(details).length <= 1) return undefined;
  const serialized = JSON.stringify(details, null, 2);
  return serialized.length > 1400 ? `${serialized.slice(0, 1400)}\n...` : serialized;
}

function viewFromDispatch(dispatch?: PluginDispatch): BiomedView {
  const value = dispatch?.filters["_view"];
  if (value === "chat" || value === "runs" || value === "queue" || value === "library" || value === "settings") {
    return value;
  }
  const legacy = value as LegacyBiomedView | undefined;
  if (legacy === "ask") return "chat";
  if (legacy === "projects" || legacy === "review") return "queue";
  if (legacy === "evidence" || legacy === "graph" || legacy === "watch" || legacy === "advanced") return "library";
  if (legacy === "audit" || legacy === "trace") return "runs";
  if (legacy === "responsible") return "settings";
  return "chat";
}

const TAG_HELP: Record<string, string> = {
  "abstract": "Evidence was extracted from the title or abstract only.",
  "abstract-derived": "The current answer is based on abstract-level evidence.",
  "all_valid": "Include every valid evidence item instead of selecting a smaller packet.",
  "answer": "The run produced an answer without a later revision action.",
  "attack": "This item argues against or limits another claim.",
  "contradicts": "The evidence conflicts with the claim or hypothesis.",
  "defer": "Hold this item for later review instead of using it now.",
  "deterministic": "Generated by deterministic code rather than an LLM call.",
  "document": "A stored full-text document is available for this paper.",
  "dropped": "This item was not selected for the current evidence packet.",
  "entailed": "The evidence logically supports the claim as written.",
  "fallback": "The system used a deterministic fallback because an LLM step failed or was unavailable.",
  "full_text": "Evidence was extracted from stored full text.",
  "full-text-derived": "The current answer is based on full-text evidence.",
  "high": "High confidence, priority, risk, or limitation depending on the surrounding label.",
  "high-risk": "This item needs extra review because errors would be consequential.",
  "inconclusive": "The evidence is mixed, weak, or does not settle the question.",
  "invalid": "The artifact failed validation or is not ready to use.",
  "llm": "Generated or parsed with an LLM-assisted step.",
  "low": "Low confidence, priority, risk, or limitation depending on the surrounding label.",
  "medium": "Medium confidence, priority, risk, or limitation depending on the surrounding label.",
  "mixed abstract/full-text": "The answer combines abstract-level and full-text evidence.",
  "mock": "This result came from the mock literature source.",
  "modality_mismatch": "The claim wording is stronger or different in certainty than the evidence supports.",
  "no evidence": "No evidence items are attached to this answer.",
  "not_assessed": "The logic or audit layer did not assess this item.",
  "overclaimed": "The claim goes beyond what the cited evidence supports.",
  "partially_entailed": "The evidence supports part of the claim but leaves limits or gaps.",
  "pass": "The audit did not require a revision.",
  "pdf": "Evidence was extracted from a PDF-derived full-text document.",
  "pending_audit": "No completed audit is available yet.",
  "pubmed": "This result came from PubMed.",
  "push": "Promote this item into the review or answer workflow.",
  "refuse_or_abstain": "The audit recommends refusing or abstaining instead of answering.",
  "retrieved": "The paper was retrieved but not necessarily used in the final answer.",
  "revise": "The audit recommends revising the draft answer.",
  "reviewed": "A reviewer has already inspected this item.",
  "selected": "This item was selected for the current evidence packet.",
  "skip": "Skip this item for the current workflow.",
  "submodular_greedy": "Select a compact evidence packet that balances relevance and coverage.",
  "supports": "The evidence supports the claim or hypothesis.",
  "valid": "The artifact passed validation.",
};

function tagHelp(value: string): string | undefined {
  if (TAG_HELP[value]) return TAG_HELP[value];
  if (value.startsWith("scientific confidence:")) return "Scientific confidence assigned to the answer.";
  if (value.startsWith("packet limitations:")) return "How limited or complete the current evidence packet is.";
  if (value.startsWith("review priority:")) return "Priority for expert or reviewer follow-up.";
  if (value.startsWith("reviewer_")) return "Latest human reviewer decision for this claim.";
  if (value.match(/^claim citation support /)) return "Share of displayed answer claims supported by cited evidence; this is not hypothesis-level certainty.";
  if (value.match(/^citation alignment /)) return "Share of displayed citations that align with their answer claims.";
  if (value.match(/^packet use /)) return "Share of the evidence packet used by the cited answer.";
  if (value.match(/^support /)) return "Number of supporting evidence items.";
  if (value.match(/^attack /)) return "Number of opposing or limiting argument edges.";
  if (value.match(/^limits /)) return "Number of extracted limitations.";
  if (value.match(/^cites /)) return "Number of citation links attached to this item.";
  if (value.match(/^\d+ evidence$/)) return "Number of evidence items extracted for this paper.";
  return undefined;
}

function pill(value: string): string {
  const help = tagHelp(value);
  const tooltip = help
    ? ` title="${escapeHtml(help)}" aria-label="${escapeHtml(`${value}: ${help}`)}" data-biomed-tooltip="${escapeHtml(help)}"`
    : "";
  return `<span class="biomed-pill biomed-pill-${escapeHtml(value)}"${tooltip}>${escapeHtml(value)}</span>`;
}

function answerQualityPills(answer: AnswerResult): string {
  void answer;
  return "";
}

function renderList(items: unknown[] | undefined): string {
  const values = (items || []).map((item) => String(item || "").trim()).filter(Boolean);
  if (!values.length) return '<span class="biomed-muted">None recorded</span>';
  return `<ul class="biomed-list">${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderBreakableList(items: unknown[] | undefined): string {
  const values = (items || []).map((item) => String(item || "").trim()).filter(Boolean);
  if (!values.length) return '<span class="biomed-muted">None recorded</span>';
  return `<ul class="biomed-list biomed-breakable-list">${values.map((item) => `<li>${breakableText(item)}</li>`).join("")}</ul>`;
}

function breakableText(value: string | null | undefined): string {
  const text = String(value || "").trim();
  return text ? `<span class="biomed-breakable">${escapeHtml(text)}</span>` : "";
}

function compactId(value: string | null | undefined, front = 12, back = 8): string {
  const clean = String(value || "").trim();
  if (!clean || clean.length <= front + back + 1) return clean;
  return `${clean.slice(0, front)}...${clean.slice(-back)}`;
}

function compactCode(value: string | null | undefined): string {
  const clean = String(value || "").trim();
  if (!clean) return "<code>-</code>";
  return `<code title="${escapeHtml(clean)}">${escapeHtml(compactId(clean))}</code>`;
}

function countGraphTypes(items: { type: string }[]): Record<string, number> {
  return items.reduce<Record<string, number>>((acc, item) => {
    acc[item.type] = (acc[item.type] || 0) + 1;
    return acc;
  }, {});
}

function renderGraphValidation(validation: BiomedEvidenceGraphValidation | null | undefined): string {
  if (!validation) return '<div class="biomed-muted">Validation not requested.</div>';
  return `
    <div class="biomed-provenance-grid">
      <div><span>Status</span><strong>${validation.ok ? "valid" : "invalid"}</strong></div>
      <div><span>Errors</span><strong>${validation.error_count}</strong></div>
      <div><span>Warnings</span><strong>${validation.warning_count}</strong></div>
    </div>
    ${validation.issues.length ? `
      <div class="biomed-audit-table">
        ${validation.issues.slice(0, 8).map((issue) => `
          <div class="biomed-audit-row ${issue.severity === "error" ? "is-failed" : ""}">
            <div class="biomed-audit-row-head">
              ${pill(issue.severity)}
              <code>${escapeHtml(issue.code)}</code>
              ${issue.node_id ? `<code>${escapeHtml(issue.node_id)}</code>` : ""}
              ${issue.edge_id ? `<code>${escapeHtml(issue.edge_id)}</code>` : ""}
            </div>
            <div class="biomed-muted">${escapeHtml(issue.message)}</div>
          </div>
        `).join("")}
      </div>
    ` : ""}
  `;
}

function renderGraphNodeInspector(graph: BiomedEvidenceGraphV1, nodeId: string): string {
  const node = graph.nodes.find((item) => item.id === nodeId);
  if (!node) return '<div class="biomed-muted">No node selected.</div>';
  const incoming = graph.edges.filter((edge) => edge.target === node.id);
  const outgoing = graph.edges.filter((edge) => edge.source === node.id);
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Type</span><strong>${escapeHtml(node.type)}</strong></div>
        <div><span>ID</span><code>${escapeHtml(node.id)}</code></div>
        <div><span>Incoming</span><strong>${incoming.length}</strong></div>
        <div><span>Outgoing</span><strong>${outgoing.length}</strong></div>
      </div>
      <div class="biomed-evidence-claim">${escapeHtml(node.label)}</div>
      <pre class="biomed-json">${escapeHtml(JSON.stringify(node.properties, null, 2))}</pre>
      <div class="biomed-two-col">
        <div>
          <div class="biomed-label">Incoming Edges</div>
          ${renderList(incoming.slice(0, 10).map((edge) => `${edge.source} -> ${edge.type}`))}
        </div>
        <div>
          <div class="biomed-label">Outgoing Edges</div>
          ${renderList(outgoing.slice(0, 10).map((edge) => `${edge.type} -> ${edge.target}`))}
        </div>
      </div>
    </div>
  `;
}

function renderBiomedEvidenceCard(card: BiomedEvidenceCard): string {
  return `
    <div class="biomed-provenance biomed-evidence-card-detail">
      <div class="biomed-provenance-grid">
        <div><span>Claim</span><code>${escapeHtml(card.claim_id)}</code></div>
        <div><span>Status</span><strong>${escapeHtml(card.support_status)}</strong></div>
        <div><span>Evidence</span><strong>${card.evidence.length}</strong></div>
        <div><span>Audits</span><strong>${card.audit_results.length}</strong></div>
      </div>
      ${card.support_status_reason ? `<div class="biomed-evidence-finding">${escapeHtml(card.support_status_reason)}</div>` : ""}
      <div class="biomed-evidence-claim">${escapeHtml(card.claim_text)}</div>
      <div class="biomed-audit-table">
        ${card.evidence.map((item) => `
          <div class="biomed-audit-row">
            <div class="biomed-audit-row-head">
              ${pill(item.relation)}
              ${item.confidence ? pill(item.confidence) : ""}
              ${item.evidence_direction ? pill(item.evidence_direction) : ""}
              ${item.paper_id ? `<code>${escapeHtml(item.paper_id)}</code>` : ""}
            </div>
            <div>${escapeHtml(item.text)}</div>
            ${item.paper_title ? `<div class="biomed-muted">${escapeHtml(item.paper_title)}</div>` : ""}
            <div class="biomed-watch-meta">
              retrieval ${escapeHtml(item.retrieval_intent || "-")} · extraction ${escapeHtml(item.extraction_mode || "-")}
            </div>
            ${item.methods.length ? `<div class="biomed-label">Methods</div>${renderList(item.methods)}` : ""}
            ${item.limitations.length ? `<div class="biomed-label">Limitations</div>${renderList(item.limitations)}` : ""}
          </div>
        `).join("") || '<div class="biomed-muted">No evidence linked.</div>'}
      </div>
      ${card.limitations.length ? `<div class="biomed-label">Claim Limitations</div>${renderList(card.limitations)}` : ""}
      ${card.warnings.length ? `<div class="biomed-label">Warnings</div>${renderList(card.warnings)}` : ""}
    </div>
  `;
}

function renderBiomedEvidenceGraph(graph: BiomedEvidenceGraphV1): string {
  const nodeCounts = countGraphTypes(graph.nodes);
  const edgeCounts = countGraphTypes(graph.edges);
  const claimNodes = graph.nodes.filter((node) => node.type === "Claim");
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Schema</span><strong>${escapeHtml(graph.schema_version)}</strong></div>
        <div><span>Scope</span><strong>${escapeHtml(graph.scope.kind)}</strong></div>
        <div><span>Nodes</span><strong>${graph.nodes.length}</strong></div>
        <div><span>Edges</span><strong>${graph.edges.length}</strong></div>
      </div>
      <div class="biomed-two-col">
        <div>
          <div class="biomed-label">Node Types</div>
          <pre class="biomed-json">${escapeHtml(JSON.stringify(nodeCounts, null, 2))}</pre>
        </div>
        <div>
          <div class="biomed-label">Edge Types</div>
          <pre class="biomed-json">${escapeHtml(JSON.stringify(edgeCounts, null, 2))}</pre>
        </div>
      </div>
      <div class="biomed-label">Validation</div>
      ${renderGraphValidation(graph.validation)}
      ${graph.warnings.length ? `<div class="biomed-label">Warnings</div>${renderList(graph.warnings)}` : ""}
    </div>
    <div class="biomed-two-col">
      <div>
        <div class="biomed-label">Nodes</div>
        <div class="biomed-audit-table">
          ${graph.nodes.slice(0, 40).map((node) => `
            <div class="biomed-audit-row">
              <div class="biomed-audit-row-head">
                ${pill(node.type)}
                <code>${escapeHtml(node.id)}</code>
              </div>
              <div>${escapeHtml(node.label)}</div>
              <div class="biomed-action-row">
                <button data-graph-node-id="${escapeHtml(node.id)}">Inspect</button>
                ${node.type === "Claim" ? `<button data-graph-card-id="${escapeHtml(node.id)}">Card</button>` : ""}
              </div>
            </div>
          `).join("") || '<div class="biomed-muted">No graph nodes.</div>'}
        </div>
      </div>
      <div>
        <div class="biomed-label">Claims</div>
        <div class="biomed-audit-table">
          ${claimNodes.slice(0, 20).map((node) => `
            <div class="biomed-audit-row">
              <div class="biomed-audit-row-head">
                ${pill(String(node.properties.support_status || "not_assessed"))}
                <code>${escapeHtml(node.id)}</code>
              </div>
              <div>${escapeHtml(node.label)}</div>
              <div class="biomed-action-row">
                <button data-graph-card-id="${escapeHtml(node.id)}">Card</button>
              </div>
            </div>
          `).join("") || '<div class="biomed-muted">No claim nodes.</div>'}
        </div>
      </div>
    </div>
  `;
}

function reviewFilterClaims(review: RunEvidenceReview, filter: string): RunEvidenceReviewClaim[] {
  if (filter === "needs_review") return review.claims.filter((claim) => claim.review_action !== "accept");
  if (filter === "supported") return review.claims.filter((claim) => claim.support_status === "supported");
  if (filter === "contradicted") return review.claims.filter((claim) => claim.support_status === "contradicted");
  if (filter === "mixed") return review.claims.filter((claim) => claim.support_status === "mixed");
  if (filter === "unsupported") {
    return review.claims.filter((claim) => ["unsupported", "qualified"].includes(claim.support_status));
  }
  return review.claims;
}

function renderRunEvidenceReview(review: RunEvidenceReview, filter = "all"): string {
  const summary = review.summary;
  const claims = reviewFilterClaims(review, filter);
  return `
    <div class="biomed-provenance biomed-review-status">
      <div class="biomed-provenance-grid">
        <div><span>Review</span><strong>${escapeHtml(review.schema_version)}</strong></div>
        <div><span>Run</span><code>${escapeHtml(review.run_id)}</code></div>
        <div><span>Snapshot</span><strong>${escapeHtml(review.snapshot.status)}</strong></div>
        <div><span>Validation</span><strong>${summary.validation_ok ? "valid" : "invalid"}</strong></div>
        <div><span>Audit</span><strong>${escapeHtml(summary.recommended_audit_action || "pending")}</strong></div>
        <div><span>Clinical</span><strong>${summary.clinical_refusal ? "refusal" : "research"}</strong></div>
        <div><span>Claims</span><strong>${summary.total_claims}</strong></div>
        <div><span>Needs Review</span><strong>${review.claims.filter((claim) => claim.review_action !== "accept").length}</strong></div>
        <div><span>Reviewer Accept</span><strong>${summary.reviewer_accept}</strong></div>
        <div><span>Reviewer Flags</span><strong>${summary.reviewer_needs_more_evidence + summary.reviewer_flag_overclaim + summary.reviewer_reject}</strong></div>
      </div>
      ${review.snapshot.graph_hash ? `<div class="biomed-watch-meta">graph hash ${compactCode(review.snapshot.graph_hash)}</div>` : ""}
      ${review.snapshot.snapshot_id ? `<div class="biomed-watch-meta">snapshot ${compactCode(review.snapshot.snapshot_id)}</div>` : ""}
      ${review.warnings.length ? `<div class="biomed-label">Warnings</div>${renderList(review.warnings)}` : ""}
      <div class="biomed-label">Validation</div>
      ${renderGraphValidation(review.validation)}
    </div>
    <div class="biomed-provenance biomed-review-counts">
      <div class="biomed-provenance-grid">
        <div><span>Supported</span><strong>${summary.supported}</strong></div>
        <div><span>Contradicted</span><strong>${summary.contradicted}</strong></div>
        <div><span>Mixed</span><strong>${summary.mixed}</strong></div>
        <div><span>Qualified</span><strong>${summary.qualified}</strong></div>
        <div><span>Unsupported</span><strong>${summary.unsupported}</strong></div>
        <div><span>Not assessed</span><strong>${summary.not_assessed}</strong></div>
        <div><span>Showing</span><strong>${claims.length}</strong></div>
      </div>
    </div>
    <div class="biomed-action-row">
      <button data-review-related="graph">Raw Graph</button>
      <button data-review-related="trace">Trace</button>
      <button data-review-related="provenance">Provenance</button>
      <button data-review-related="packet">Review Packet</button>
      <button data-review-related="export">Export JSON</button>
    </div>
    ${summary.clinical_refusal && !claims.length ? `
      <div class="biomed-policy">
        <strong>Clinical boundary passed.</strong>
        <span>This refusal run has zero biomedical evidence claims.</span>
      </div>
    ` : ""}
    <div class="biomed-review-claim-list">
      ${claims.map((claim) => `
        <article class="biomed-review-claim-card ${claim.review_action !== "accept" ? "is-failed" : ""}" data-review-claim-card="${escapeHtml(claim.claim_node_id)}">
          <div class="biomed-audit-row-head">
            ${pill(claim.review_action)}
            ${pill(claim.support_status)}
            ${claim.audit_verdict ? pill(claim.audit_verdict) : ""}
            ${claim.latest_decision ? pill(`reviewer_${claim.latest_decision.decision}`) : ""}
            <code>${escapeHtml(claim.claim_id)}</code>
          </div>
          <div class="biomed-evidence-claim">${escapeHtml(claim.claim_text)}</div>
          <div class="biomed-watch-meta">
            score ${claim.support_score ?? "-"} · ${claim.evidence_count} evidence · ${claim.paper_ids.length} papers · ${claim.limitation_count} limitations
          </div>
          ${claim.support_status_reason ? `<div class="biomed-evidence-finding">${escapeHtml(claim.support_status_reason)}</div>` : ""}
          ${Object.keys(claim.support_counts || {}).length ? `<div class="biomed-watch-meta">support counts ${escapeHtml(JSON.stringify(claim.support_counts))}</div>` : ""}
          ${claim.latest_decision ? `
            <div class="biomed-review-decision-state">
              <strong>${escapeHtml(claim.latest_decision.decision)}</strong>
              <span>${escapeHtml(claim.latest_decision.updated_at)} · ${escapeHtml(claim.latest_decision.decision_source)}</span>
              ${claim.latest_decision.reviewer_note ? `<p>${escapeHtml(claim.latest_decision.reviewer_note)}</p>` : ""}
            </div>
          ` : ""}
          ${claim.paper_ids.length ? `<div class="biomed-label">Papers</div>${renderList(claim.paper_ids)}` : ""}
          <div class="biomed-review-decision-panel">
            <textarea data-review-note placeholder="Reviewer note">${escapeHtml(claim.latest_decision?.reviewer_note || "")}</textarea>
            <div class="biomed-action-row">
              <button data-review-decision="accept" data-review-decision-claim="${escapeHtml(claim.claim_node_id)}">Accept</button>
              <button data-review-decision="needs_more_evidence" data-review-decision-claim="${escapeHtml(claim.claim_node_id)}">Need More Evidence</button>
              <button data-review-decision="flag_overclaim" data-review-decision-claim="${escapeHtml(claim.claim_node_id)}">Flag Overclaim</button>
              <button data-review-decision="reject" data-review-decision-claim="${escapeHtml(claim.claim_node_id)}">Reject</button>
            </div>
          </div>
          <div class="biomed-action-row">
            <button data-review-inspect-claim="${escapeHtml(claim.claim_node_id)}">Evidence Card</button>
            <button data-review-json-claim="${escapeHtml(claim.claim_node_id)}">Inspect JSON</button>
          </div>
        </article>
      `).join("") || '<div class="biomed-muted">No claims match this filter.</div>'}
    </div>
  `;
}

function renderReviewMainPanel(
  review: RunEvidenceReview,
  trace: TracePayload | null,
  filter: string,
): string {
  const answer = trace?.answer_run.answer || "";
  const question = trace?.answer_run.evidence_packet?.question || "";
  return `
    <div class="biomed-review-main-head">
      <div>
        <div class="biomed-label">Selected Run</div>
        <h2>${escapeHtml(question || "Evidence review")}</h2>
      </div>
      <div class="biomed-review-status-strip">
        ${pill(review.snapshot.status)}
        ${pill(review.summary.validation_ok ? "valid" : "invalid")}
        ${review.summary.recommended_audit_action ? pill(review.summary.recommended_audit_action) : pill("pending_audit")}
      </div>
    </div>
    ${
      answer
        ? `
          <section class="biomed-review-answer">
            <div class="biomed-label">Final Answer</div>
            <p>${escapeHtml(answer)}</p>
          </section>
        `
        : ""
    }
    ${renderRunEvidenceReview(review, filter)}
  `;
}

function renderReviewInspectorEmpty(): string {
  return `
    <div class="biomed-review-inspector-empty">
      <div class="biomed-label">Inspector</div>
      <h3>Select a claim or action</h3>
      <p>Evidence cards, trace, provenance, graph export, and related graph views appear here.</p>
    </div>
  `;
}

function renderEvidenceItem(item: EvidenceRow): string {
  const locator = renderEvidenceLocator(item);
  return `
    <div class="biomed-evidence-item">
      <div class="biomed-evidence-head">
        ${pill(item.evidence_direction)}
        ${pill(item.confidence)}
        ${item.retrieval_intent ? pill(item.retrieval_intent) : ""}
        ${item.extraction_mode ? pill(item.extraction_mode) : ""}
        ${pill(item.source_scope || "abstract")}
        <code>${escapeHtml(item.paper_id)}</code>
      </div>
      <div class="biomed-evidence-claim">${escapeHtml(item.claim)}</div>
      <div class="biomed-evidence-finding">${escapeHtml(item.finding)}</div>
      ${locator}
    </div>
  `;
}

function renderEvidenceLocator(item: EvidenceRow): string {
  if (!item.document_id && !item.section_id && !item.source_hash) return "";
  const range = item.char_start !== undefined && item.char_start !== null
    ? `${item.char_start}${item.char_end !== undefined && item.char_end !== null ? `-${item.char_end}` : ""}`
    : "-";
  return `
    <div class="biomed-watch-meta">
      locator ${escapeHtml(item.section_label || item.section_id || "-")}
      · page ${escapeHtml(String(item.page_number ?? "-"))}
      · chars ${escapeHtml(range)}
      · doc ${escapeHtml(compactId(item.document_id || "-"))}
      · hash ${escapeHtml(compactId(item.source_hash || "-"))}
    </div>
  `;
}

function renderEvidencePacket(packet: EvidencePacketSummary | null | undefined): string {
  if (!packet) return '<div class="biomed-muted">No evidence packet recorded.</div>';
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Packet</span><code>${escapeHtml(packet.packet_id)}</code></div>
        <div><span>Planner</span><strong>${escapeHtml(packet.planner_mode)}</strong></div>
        <div><span>Source</span><strong>${escapeHtml(packet.source)}</strong></div>
        <div><span>Papers</span><strong>${packet.paper_ids.length}</strong></div>
        <div><span>Evidence</span><strong>${packet.evidence_ids.length}</strong></div>
        <div><span>Stop</span><strong>${escapeHtml(packet.stop_reason)}</strong></div>
      </div>
      <div class="biomed-two-col">
        <div>
          <div class="biomed-label">Supported Claims</div>
          ${renderList(packet.supported_claims.slice(0, 5))}
        </div>
        <div>
          <div class="biomed-label">Gaps / Conflicts</div>
          ${renderList(packet.coverage_gaps.slice(0, 5).map((row) => `${row.retrieval_intent}: ${row.coverage_status}${row.gap_reason ? ` - ${row.gap_reason}` : ""}`))}
        </div>
      </div>
      ${packet.source_warnings.length ? `<div class="biomed-label">Source Warnings</div>${renderList(packet.source_warnings)}` : ""}
    </div>
  `;
}

function renderPacketSelection(selection: EvidencePacketSelectionResult | null | undefined): string {
  if (!selection) return '<div class="biomed-muted">No packet selection trace recorded.</div>';
  const itemRow = (item: EvidenceSelectionItem) => `
    <div class="biomed-audit-row ${item.selected ? "" : "is-dropped"}">
      <div class="biomed-audit-row-head">
        ${pill(item.selected ? "selected" : "dropped")}
        ${pill(selection.strategy)}
        <span>score ${Math.round(item.score * 100) / 100}</span>
        <span>${item.token_estimate} tokens</span>
        <code>${escapeHtml(item.paper_id)}</code>
      </div>
      <div class="biomed-evidence-claim"><code>${escapeHtml(item.evidence_id)}</code></div>
      <div class="biomed-evidence-finding">${escapeHtml(item.reason)}</div>
      <pre class="biomed-json">${escapeHtml(JSON.stringify(item.coverage_contribution, null, 2))}</pre>
    </div>
  `;
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Strategy</span><strong>${escapeHtml(selection.strategy)}</strong></div>
        <div><span>Selected</span><strong>${selection.selected.length}</strong></div>
        <div><span>Dropped</span><strong>${selection.dropped.length}</strong></div>
        <div><span>Tokens</span><strong>${selection.token_estimate}</strong></div>
        <div><span>Duplicate Delta</span><strong>${selection.duplicate_evidence_delta}</strong></div>
        <div><span>Protected</span><strong>${String(selection.coverage_contribution.protected_evidence_retained ?? "-")}</strong></div>
      </div>
      <div class="biomed-label">Coverage Contribution</div>
      <pre class="biomed-json">${escapeHtml(JSON.stringify(selection.coverage_contribution, null, 2))}</pre>
      <div class="biomed-two-col">
        <div>
          <div class="biomed-label">Selected Evidence</div>
          <div class="biomed-audit-table">${selection.selected.map(itemRow).join("") || '<div class="biomed-muted">None selected.</div>'}</div>
        </div>
        <div>
          <div class="biomed-label">Dropped Evidence</div>
          <div class="biomed-audit-table">${selection.dropped.map(itemRow).join("") || '<div class="biomed-muted">None dropped.</div>'}</div>
        </div>
      </div>
    </div>
  `;
}

function renderPacketBuildResult(envelope: ReleaseToolEnvelope<EvidencePacketBuildResult>): string {
  if (!envelope.ok) return renderReleaseError(envelope);
  return `
    <div class="biomed-label">Evidence Packet</div>
    ${renderEvidencePacket(envelope.result.evidence_packet)}
    <div class="biomed-label">Selected / Dropped Evidence</div>
    ${renderPacketSelection(envelope.result.selection)}
    ${envelope.result.step_telemetry ? `<div class="biomed-label">Packet Telemetry</div>${renderStepTelemetry(envelope.result.step_telemetry)}` : ""}
  `;
}

function renderStepTelemetry(telemetry: StepTelemetrySummary | null | undefined): string {
  if (!telemetry) return '<div class="biomed-muted">No step telemetry recorded.</div>';
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Advisory</span><strong>${telemetry.advisory_only ? "yes" : "no"}</strong></div>
        <div><span>Mean Steps</span><strong>${telemetry.mean_tool_step_count}</strong></div>
        <div><span>P95 Steps</span><strong>${telemetry.p95_tool_step_count}</strong></div>
        <div><span>Remaining</span><strong>${telemetry.expected_remaining_steps}</strong></div>
        <div><span>Transitions</span><strong>${telemetry.transition_records.length}</strong></div>
        <div><span>Warnings</span><strong>${telemetry.unusual_path_warnings.length}</strong></div>
      </div>
      ${telemetry.unusual_path_warnings.length ? `<div class="biomed-label">Telemetry Warnings</div>${renderList(telemetry.unusual_path_warnings)}` : ""}
      <div class="biomed-label">Transition Matrix</div>
      <pre class="biomed-json">${escapeHtml(JSON.stringify(telemetry.transition_matrix, null, 2))}</pre>
    </div>
  `;
}

function renderArgumentGraph(result: ArgumentGraphResult | null | undefined): string {
  if (!result) return '<div class="biomed-muted">No argument graph loaded.</div>';
  if (result.status === "not_applicable") {
    return `<div class="biomed-muted">${escapeHtml(result.not_applicable_reason || "Argument graph is not applicable for this run.")}</div>`;
  }
  const edgeCounts = result.edges.reduce<Record<string, number>>((acc, edge) => {
    acc[edge.edge_type] = (acc[edge.edge_type] || 0) + 1;
    return acc;
  }, {});
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Status</span><strong>${escapeHtml(result.status)}</strong></div>
        <div><span>Nodes</span><strong>${result.nodes.length}</strong></div>
        <div><span>Edges</span><strong>${result.edges.length}</strong></div>
        <div><span>Conflicts</span><strong>${result.unresolved_conflict_count}</strong></div>
        <div><span>Audit</span><code>${escapeHtml(result.audit_id || "-")}</code></div>
        <div><span>Advisory</span><strong>${result.advisory_only ? "yes" : "no"}</strong></div>
      </div>
      <div class="biomed-label">Edge Mix</div>
      <pre class="biomed-json">${escapeHtml(JSON.stringify(edgeCounts, null, 2))}</pre>
      <div class="biomed-label">Claim Argument Summary</div>
      <div class="biomed-audit-table">
        ${result.claim_summaries.map((item) => `
          <div class="biomed-audit-row ${item.unresolved_conflict_count ? "is-failed" : ""}">
            <div class="biomed-audit-row-head">
              ${pill(`support ${item.support_count}`)}
              ${pill(`attack ${item.attack_count}`)}
              ${pill(`limits ${item.limitation_count}`)}
              ${pill(`cites ${item.citation_count}`)}
            </div>
            <code>${escapeHtml(item.claim_id)}</code>
            ${item.strongest_supporting_evidence_ids.length ? `<div class="biomed-label">Support</div>${renderList(item.strongest_supporting_evidence_ids)}` : ""}
            ${item.strongest_attacking_evidence_ids.length ? `<div class="biomed-label">Attack</div>${renderList(item.strongest_attacking_evidence_ids)}` : ""}
            ${item.limitation_summary.length ? `<div class="biomed-label">Limitations</div>${renderList(item.limitation_summary)}` : ""}
          </div>
        `).join("") || '<div class="biomed-muted">No claim summaries.</div>'}
      </div>
      ${result.warnings.length ? `<div class="biomed-label">Warnings</div>${renderBreakableList(result.warnings)}` : ""}
      <details class="biomed-logic-frames">
        <summary>Raw Argument Graph JSON</summary>
        <pre class="biomed-json">${escapeHtml(JSON.stringify(result, null, 2))}</pre>
      </details>
    </div>
  `;
}

function renderMathSignals(result: MathSignalsResult | null | undefined): string {
  if (!result) return '<div class="biomed-muted">No math signals loaded.</div>';
  if (result.status === "not_applicable") {
    return `
      <div class="biomed-provenance">
        <div class="biomed-provenance-grid">
          <div><span>Status</span><strong>not applicable</strong></div>
          <div><span>Advisory</span><strong>${result.advisory_only ? "yes" : "no"}</strong></div>
        </div>
        <div class="biomed-muted">${escapeHtml(result.not_applicable_reason || "Math review signals are not applicable for this run.")}</div>
      </div>
    `;
  }
  const coverage = result.coverage_diversity;
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Risk</span><strong>${escapeHtml(result.answer_uncertainty_bucket)}</strong></div>
        <div><span>Recommendation</span><strong>${escapeHtml(result.recommendation)}</strong></div>
        <div><span>Diversity</span><strong>${Math.round(coverage.diversity_score * 100)}%</strong></div>
        <div><span>Papers</span><strong>${coverage.paper_count}</strong></div>
        <div><span>Evidence</span><strong>${coverage.evidence_count}</strong></div>
        <div><span>Methods</span><strong>${coverage.unique_method_count}</strong></div>
        <div><span>Model/Population</span><strong>${coverage.unique_model_or_population_count}</strong></div>
        <div><span>Duplicate Pressure</span><strong>${coverage.duplicate_pressure}</strong></div>
      </div>
      <div class="biomed-label">Reason Factors</div>
      ${renderList(result.reason_factors)}
      <div class="biomed-label">Claim Uncertainty</div>
      <div class="biomed-audit-table">
        ${result.claim_uncertainty.map((item) => `
          <div class="biomed-audit-row ${item.risk_bucket === "high" ? "is-failed" : ""}">
            <div class="biomed-audit-row-head">
              ${pill(item.risk_bucket)}
              ${pill(item.recommendation)}
              ${item.citation_verdict ? pill(item.citation_verdict) : ""}
              ${item.logic_verdict ? pill(item.logic_verdict) : ""}
              <span>${Math.round(item.risk_score * 100)}%</span>
            </div>
            <div class="biomed-evidence-claim">${escapeHtml(item.claim)}</div>
            <div class="biomed-watch-meta">support ${Math.round(item.support_score * 100)}% · strength ${escapeHtml(item.evidence_strength)}</div>
            ${renderList(item.reason_factors)}
          </div>
        `).join("") || '<div class="biomed-muted">No audited claims available.</div>'}
      </div>
      <div class="biomed-two-col">
        <div>
          <div class="biomed-label">Paper Concentration</div>
          <pre class="biomed-json">${escapeHtml(JSON.stringify(coverage.paper_concentration, null, 2))}</pre>
        </div>
        <div>
          <div class="biomed-label">Retrieval Intent Coverage</div>
          <pre class="biomed-json">${escapeHtml(JSON.stringify(coverage.retrieval_intent_coverage, null, 2))}</pre>
        </div>
      </div>
      ${coverage.recommended_retrieval_direction ? `<div class="biomed-label">Recommended Retrieval Direction</div><div>${pill(coverage.recommended_retrieval_direction)}</div>` : ""}
      ${coverage.concentration_warnings.length ? `<div class="biomed-label">Concentration Warnings</div>${renderList(coverage.concentration_warnings)}` : ""}
      ${coverage.missing_intent_warnings.length ? `<div class="biomed-label">Missing Intent Warnings</div>${renderList(coverage.missing_intent_warnings)}` : ""}
      ${result.warnings.length ? `<div class="biomed-label">Warnings</div>${renderBreakableList(result.warnings)}` : ""}
      <div class="biomed-label">Step Telemetry</div>
      ${renderStepTelemetry(result.step_telemetry)}
    </div>
  `;
}

function renderObsidianExportResult(envelope: ReleaseToolEnvelope<ObsidianExportResult>): string {
  if (!envelope.ok) return renderReleaseError(envelope);
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Export</span><code>${escapeHtml(envelope.result.export_id)}</code></div>
        <div><span>Type</span><strong>${escapeHtml(envelope.result.export_type)}</strong></div>
        <div><span>Notes</span><strong>${envelope.result.note_count}</strong></div>
        <div><span>Source</span><strong>${escapeHtml(envelope.result.source_of_truth)}</strong></div>
        <div><span>Imported Evidence</span><strong>${envelope.result.imported_as_evidence ? "yes" : "no"}</strong></div>
        <div><span>Directory</span><code>${escapeHtml(envelope.result.export_dir)}</code></div>
      </div>
      <div class="biomed-label">Notes</div>
      ${renderList(envelope.result.notes.map((note) => `${note.filename} | ${note.path} | ${note.sha256.slice(0, 12)}`))}
    </div>
  `;
}

function renderProvenanceResult(envelope: ReleaseToolEnvelope<ProvenanceGraphResult>): string {
  if (!envelope.ok) return renderReleaseError(envelope);
  const graph = envelope.result;
  const counts = (items: { type: string }[]) => items.reduce<Record<string, number>>((acc, item) => {
    acc[item.type] = (acc[item.type] || 0) + 1;
    return acc;
  }, {});
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Graph</span><code>${escapeHtml(graph.graph_id)}</code></div>
        <div><span>Schema</span><strong>${escapeHtml(graph.schema_version)}</strong></div>
        <div><span>Entities</span><strong>${graph.entities.length}</strong></div>
        <div><span>Activities</span><strong>${graph.activities.length}</strong></div>
        <div><span>Agents</span><strong>${graph.agents.length}</strong></div>
        <div><span>Relations</span><strong>${graph.relations.length}</strong></div>
      </div>
      <div class="biomed-two-col">
        <div>
          <div class="biomed-label">Entity Types</div>
          <pre class="biomed-json">${escapeHtml(JSON.stringify(counts(graph.entities), null, 2))}</pre>
        </div>
        <div>
          <div class="biomed-label">Activity Types</div>
          <pre class="biomed-json">${escapeHtml(JSON.stringify(counts(graph.activities), null, 2))}</pre>
        </div>
      </div>
      <div class="biomed-label">Redactions</div>
      ${renderList(graph.redactions)}
      ${graph.warnings.length ? `<div class="biomed-label">Warnings</div>${renderList(graph.warnings)}` : ""}
      <details class="biomed-logic-frames">
        <summary>Raw Provenance JSON</summary>
        <pre class="biomed-json">${escapeHtml(JSON.stringify(graph, null, 2))}</pre>
      </details>
    </div>
  `;
}

function renderReleaseError(envelope: ReleaseToolEnvelope<unknown>): string {
  return `
    <div class="biomed-error">
      ${escapeHtml(envelope.error_code || "release_tool_error")}: ${escapeHtml(envelope.message || "The tool call did not complete.")}
    </div>
    ${envelope.warnings?.length ? renderList(envelope.warnings) : ""}
    ${envelope.trace && Object.keys(envelope.trace).length ? `<pre class="biomed-json">${escapeHtml(JSON.stringify(envelope.trace, null, 2))}</pre>` : ""}
  `;
}

function renderManifest(manifest: RetrievalManifest | null | undefined): string {
  if (!manifest) return '<div class="biomed-muted">No retrieval manifest recorded.</div>';
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Retrieval</span><code>${escapeHtml(manifest.retrieval_id)}</code></div>
        <div><span>Source</span><strong>${escapeHtml(manifest.source)}</strong></div>
        <div><span>Results</span><strong>${manifest.deduped_result_count}/${manifest.raw_result_count}</strong></div>
        <div><span>Pages</span><strong>${manifest.pages_completed}/${manifest.pages_requested}</strong></div>
      </div>
      <div class="biomed-label">Compiled Query</div>
      <code class="biomed-query">${escapeHtml(manifest.compiled_query || manifest.original_query)}</code>
      ${manifest.warnings?.length ? `<div class="biomed-label">Warnings</div>${renderList(manifest.warnings)}` : ""}
      ${manifest.errors?.length ? `<div class="biomed-label">Errors</div>${renderList(manifest.errors)}` : ""}
      ${manifest.unsupported_filters?.length ? `<div class="biomed-label">Unsupported Filters</div>${renderList(manifest.unsupported_filters)}` : ""}
    </div>
  `;
}

function renderLoading(message: string): string {
  return `<div class="biomed-loading">${escapeHtml(message)}</div>`;
}

function renderWorkflowTemplateSummary(template: SavedToolChainTemplate | undefined): string {
  if (!template) return "Select a workflow template to apply saved retrieval, LLM, audit, and provenance settings.";
  const flags = [
    template.use_llm_planner ? "planner" : "",
    template.use_llm_extractor ? "extractor" : "",
    template.use_llm_synthesis ? "synthesis" : "",
    template.use_llm_verifier ? "verifier" : "",
    template.use_llm_revision ? "revision" : "",
    template.use_llm_claim_logic ? "logic" : "",
    template.export_logic_facts ? "facts" : "",
  ].filter(Boolean);
  return `${template.builtin ? "built-in" : "custom"} | ${template.source} | max ${template.max_papers} papers | ${flags.join(", ") || "deterministic"}`;
}

function selectedWorkflowTemplate(container: HTMLElement): SavedToolChainTemplate | undefined {
  const templateId = container.querySelector<HTMLSelectElement>("#biomed-template-select")?.value || "";
  return biomedWorkflowTemplates.find((item) => item.template_id === templateId);
}

function setChecked(container: HTMLElement, selector: string, checked: boolean): void {
  const input = container.querySelector<HTMLInputElement>(selector);
  if (input) input.checked = checked;
}

function applyWorkflowTemplate(container: HTMLElement, template: SavedToolChainTemplate): void {
  const source = container.querySelector<HTMLSelectElement>("#biomed-source");
  const maxPapers = container.querySelector<HTMLInputElement>("#biomed-max-papers");
  const summary = container.querySelector<HTMLElement>("#biomed-template-summary");
  if (source) source.value = template.source;
  if (maxPapers) maxPapers.value = String(template.max_papers);
  setChecked(container, "#biomed-include-rejected", template.include_rejected_papers);
  setChecked(container, "#biomed-execute-support-refute", template.execute_support_refute);
  setChecked(container, "#biomed-use-planner", template.use_llm_planner);
  setChecked(container, "#biomed-use-extractor", template.use_llm_extractor);
  setChecked(container, "#biomed-use-synthesis", template.use_llm_synthesis);
  setChecked(container, "#biomed-use-verifier", template.use_llm_verifier);
  setChecked(container, "#biomed-use-revision", template.use_llm_revision);
  setChecked(container, "#biomed-use-claim-logic", template.use_llm_claim_logic);
  setChecked(container, "#biomed-export-logic-facts", template.export_logic_facts);
  if (summary) summary.textContent = renderWorkflowTemplateSummary(template);
}

function currentWorkflowTemplatePayload(container: HTMLElement): Record<string, unknown> {
  const name = container.querySelector<HTMLInputElement>("#biomed-template-name")?.value || "";
  const source = container.querySelector<HTMLSelectElement>("#biomed-source")?.value || "mock";
  const maxPapers = Number(container.querySelector<HTMLInputElement>("#biomed-max-papers")?.value || 5);
  return {
    name,
    description: "Saved from the Biomedical Evidence dashboard.",
    source,
    max_papers: maxPapers,
    include_rejected_papers: Boolean(container.querySelector<HTMLInputElement>("#biomed-include-rejected")?.checked),
    execute_support_refute: Boolean(container.querySelector<HTMLInputElement>("#biomed-execute-support-refute")?.checked),
    use_llm_planner: Boolean(container.querySelector<HTMLInputElement>("#biomed-use-planner")?.checked),
    use_llm_extractor: Boolean(container.querySelector<HTMLInputElement>("#biomed-use-extractor")?.checked),
    use_llm_synthesis: Boolean(container.querySelector<HTMLInputElement>("#biomed-use-synthesis")?.checked),
    use_llm_verifier: Boolean(container.querySelector<HTMLInputElement>("#biomed-use-verifier")?.checked),
    use_llm_revision: Boolean(container.querySelector<HTMLInputElement>("#biomed-use-revision")?.checked),
    use_llm_claim_logic: Boolean(container.querySelector<HTMLInputElement>("#biomed-use-claim-logic")?.checked),
    export_logic_facts: Boolean(container.querySelector<HTMLInputElement>("#biomed-export-logic-facts")?.checked),
    export_provenance: true,
    clinical_guard_required: true,
    required_skills: ["biomed-evidence-review", "biomed-clinical-boundary"],
    stop_conditions: ["clinical_boundary", "source_policy_blocked", "empty_evidence"],
  };
}

async function loadWorkflowTemplates(container: HTMLElement): Promise<void> {
  const select = container.querySelector<HTMLSelectElement>("#biomed-template-select");
  const summary = container.querySelector<HTMLElement>("#biomed-template-summary");
  if (!select) return;
  try {
    const data = await api<SavedToolChainTemplateListResult>("/api/biomed/workflow/templates");
    biomedWorkflowTemplates = data.items || [];
    select.innerHTML = biomedWorkflowTemplates.map((template) => `
      <option value="${escapeHtml(template.template_id)}">${escapeHtml(template.name)}</option>
    `).join("");
    const first = biomedWorkflowTemplates[0];
    if (first) {
      select.value = first.template_id;
      applyWorkflowTemplate(container, first);
      if (summary) summary.textContent = renderWorkflowTemplateSummary(first);
    } else {
      select.innerHTML = '<option value="">no templates</option>';
      if (summary) summary.textContent = "No workflow templates available.";
    }
  } catch (error) {
    select.innerHTML = '<option value="">template load failed</option>';
    if (summary) summary.textContent = String(error);
  }
}

async function hydrateRetrievalBlocks(container: HTMLElement): Promise<void> {
  const blocks = Array.from(container.querySelectorAll<HTMLElement>("[data-biomed-retrieval-id]"));
  await Promise.all(blocks.map(async (block) => {
    const retrievalId = block.dataset.biomedRetrievalId || "";
    if (!retrievalId) return;
    try {
      const manifest = await api<RetrievalManifest>(`/api/biomed/retrievals/${encodeURIComponent(retrievalId)}`);
      block.innerHTML = renderManifest(manifest);
    } catch (error) {
      block.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  }));
}

function renderEvidenceDetail(item: EvidenceRow): string {
  const entities = (item.entities || []).map((entity) => `${entity.name} (${entity.entity_type})`);
  return `
    <div class="biomed-section">
      <div class="biomed-title">Evidence Detail</div>
      <div class="biomed-subtitle">${escapeHtml(item.paper_title || item.paper_id)}</div>
      ${renderEvidenceItem(item)}
      <div class="biomed-two-col">
        <div>
          <div class="biomed-label">Entities</div>
          ${renderList(entities)}
        </div>
        <div>
          <div class="biomed-label">Methods</div>
          ${renderList(item.methods)}
        </div>
      </div>
      <div class="biomed-label">Limitations</div>
      ${renderList(item.limitations)}
      <div class="biomed-label">Retrieval Provenance</div>
      ${
        item.retrieval_id
          ? `<div data-biomed-retrieval-id="${escapeHtml(item.retrieval_id)}"><div class="biomed-muted">Loading retrieval manifest...</div></div>`
          : '<div class="biomed-muted">No retrieval ID recorded for this evidence item.</div>'
      }
    </div>
  `;
}

function renderLogicAudit(logic: LogicAuditResult | null | undefined): string {
  if (!logic) return "";
  const factExport = logic.logic_fact_export;
  const claimFrame = logic.claim_frame || null;
  const evidenceFrames = logic.evidence_frames || [];
  const parserFrames = [claimFrame, ...evidenceFrames].filter(Boolean) as LogicParserFrame[];
  const parserModes = Array.from(new Set(parserFrames.map((frame) => frame.parser_mode).filter(Boolean)));
  const parserModels = Array.from(new Set(parserFrames.map((frame) => frame.parser_model).filter(Boolean)));
  const parserPromptHashes = Array.from(new Set(parserFrames.map((frame) => frame.parser_prompt_hash).filter(Boolean)));
  const parserWarnings = Array.from(new Set(parserFrames.flatMap((frame) => frame.parser_warnings || [])));
  const mismatchLines = [
    ...(logic.predicate_mismatches || []).map((item) => `predicate: ${JSON.stringify(item)}`),
    ...(logic.scope_mismatches || []).map((item) => `scope: ${JSON.stringify(item)}`),
    ...(logic.modality_mismatches || []).map((item) => `modality: ${JSON.stringify(item)}`),
    ...(logic.population_mismatches || []).map((item) => `population: ${JSON.stringify(item)}`),
  ];
  return `
    <div class="biomed-label">Logic Audit</div>
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Verdict</span><strong>${escapeHtml(logic.logic_verdict)}</strong></div>
        <div><span>Score</span><strong>${Math.round(logic.entailment_score * 100)}%</strong></div>
        <div><span>Evidence</span><strong>${escapeHtml(logic.evidence_ids.join(", ") || "-")}</strong></div>
        <div><span>Facts</span><strong>${factExport ? factExport.facts.length : 0}</strong></div>
        <div><span>Parser</span><strong>${escapeHtml(parserModes.join(", ") || "-")}</strong></div>
        <div><span>Model</span><strong>${escapeHtml(parserModels.join(", ") || "-")}</strong></div>
        <div><span>Prompt</span><strong>${escapeHtml(parserPromptHashes.join(", ") || "-")}</strong></div>
      </div>
      <div class="biomed-evidence-finding">${escapeHtml(logic.reason)}</div>
      <div class="biomed-label">Triggered Rules</div>
      ${renderList(logic.rules_triggered)}
      ${mismatchLines.length ? `<div class="biomed-label">Mismatches</div>${renderList(mismatchLines)}` : ""}
      ${parserWarnings.length ? `<div class="biomed-label">Parser Warnings</div>${renderList(parserWarnings)}` : ""}
      ${logic.warnings.length ? `<div class="biomed-label">Logic Warnings</div>${renderList(logic.warnings)}` : ""}
      ${
        parserFrames.length
          ? `
            <details class="biomed-logic-frames">
              <summary>Parsed Logic Frames</summary>
              <pre class="biomed-json">${escapeHtml(JSON.stringify({ claim_frame: claimFrame, evidence_frames: evidenceFrames }, null, 2))}</pre>
            </details>
          `
          : ""
      }
      ${
        factExport
          ? `
            <div class="biomed-label">Logic Fact Export</div>
            <div class="biomed-watch-meta">
              <code>${escapeHtml(factExport.export_id)}</code> · ${escapeHtml(factExport.format)} · ${escapeHtml(factExport.exporter_version)}
            </div>
            ${factExport.warnings.length ? renderList(factExport.warnings) : ""}
            ${factExport.text ? `<pre class="biomed-json">${escapeHtml(factExport.text)}</pre>` : ""}
          `
          : ""
      }
    </div>
  `;
}

function renderAuditResult(result: CitationAuditResult): string {
  const failed = result.failed_claims || [];
  const rows = (result.claim_audits || []).map((item) => `
    <div class="biomed-audit-row ${failed.some((failedItem) => failedItem.claim_id === item.claim_id) ? "is-failed" : ""}">
      <div class="biomed-audit-row-head">
        ${pill(item.verdict)}
        ${pill(item.claim_type)}
        <span>${Math.round(item.support_score * 100)}%</span>
      </div>
      <div class="biomed-evidence-claim">${escapeHtml(item.claim)}</div>
      <div class="biomed-evidence-finding">${escapeHtml(item.reason)}</div>
      <div class="biomed-watch-meta">
        citations ${escapeHtml(item.cited_paper_ids.join(", ") || "-")} · evidence ${escapeHtml(item.evidence_ids.join(", ") || "-")}
      </div>
      ${item.evidence_span ? `<code class="biomed-query">${escapeHtml(item.evidence_span)}</code>` : ""}
      ${renderLogicAudit(item.logic_audit)}
    </div>
  `).join("");
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Audit</span><code>${escapeHtml(result.audit_id)}</code></div>
        <div><span>Action</span><strong>${escapeHtml(result.recommended_action)}</strong></div>
        <div><span>Claim Support</span><strong>${Math.round(result.claim_support_rate * 100)}%</strong></div>
        <div><span>Citation Precision</span><strong>${Math.round(result.citation_precision * 100)}%</strong></div>
        <div><span>Packet Use</span><strong>${Math.round((result.packet_citation_utilization ?? result.citation_precision) * 100)}%</strong></div>
        <div><span>Unsupported</span><strong>${Math.round(result.unsupported_claim_rate * 100)}%</strong></div>
        <div><span>Overclaim</span><strong>${Math.round(result.overclaim_rate * 100)}%</strong></div>
        <div><span>Conflict Aware</span><strong>${result.conflict_awareness ? "yes" : "no"}</strong></div>
        <div><span>Uncertainty</span><strong>${result.uncertainty_calibrated ? "calibrated" : "mismatch"}</strong></div>
      </div>
    </div>
    <div class="biomed-label">Claim Audit</div>
    <div class="biomed-audit-table">
      ${rows || '<div class="biomed-muted">No claims audited.</div>'}
    </div>
  `;
}

function renderAdvisoryVerifier(result: AdvisoryVerifierResult | null | undefined): string {
  if (!result) return '<div class="biomed-muted">No advisory verifier recorded.</div>';
  const rows = (result.disagreements || []).map((item) => `
    <div class="biomed-audit-row ${item.high_risk ? "is-failed" : ""}">
      <div class="biomed-audit-row-head">
        ${pill(item.risk_level)}
        ${pill(item.advisory_action)}
        ${item.high_risk ? pill("high-risk") : ""}
      </div>
      <div class="biomed-evidence-claim">${escapeHtml(item.claim)}</div>
      <div class="biomed-evidence-finding">${escapeHtml(item.reason)}</div>
      <div class="biomed-watch-meta">
        deterministic ${escapeHtml(item.deterministic_verdict || item.deterministic_action)} · advisory ${escapeHtml(item.advisory_verdict)}
      </div>
    </div>
  `).join("");
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Verifier</span><code>${escapeHtml(result.verifier_id)}</code></div>
        <div><span>Mode</span><strong>${escapeHtml(result.verifier_mode)}</strong></div>
        <div><span>Model</span><strong>${escapeHtml(result.llm_model || "-")}</strong></div>
        <div><span>Deterministic</span><strong>${escapeHtml(result.deterministic_action)}</strong></div>
        <div><span>Advisory</span><strong>${escapeHtml(result.advisory_action)}</strong></div>
        <div><span>High Risk</span><strong>${result.high_risk_disagreement_count}</strong></div>
      </div>
      ${result.fallback_reason ? `<div class="biomed-label">Fallback</div><div class="biomed-muted">${escapeHtml(result.fallback_reason)}</div>` : ""}
      ${result.warnings?.length ? `<div class="biomed-label">Warnings</div>${renderList(result.warnings)}` : ""}
    </div>
    <div class="biomed-label">Advisory Disagreements</div>
    <div class="biomed-audit-table">
      ${rows || '<div class="biomed-muted">No disagreements recorded.</div>'}
    </div>
  `;
}

function renderTraceResult(payload: TracePayload): string {
  const revision = payload.revision;
  const audit = payload.latest_citation_audit;
  const advisory = payload.latest_advisory_verifier;
  const budgetSnapshots = payload.trace
    .map((step) => step.metadata?.budget)
    .filter((item) => item && typeof item === "object");
  const observability = payload.observability || {};
  const obs = (key: string): string => {
    const value = observability[key];
    return escapeHtml(value === null || value === undefined ? "-" : String(value));
  };
  const memory = payload.memory || payload.answer_run.project_context_trace || {};
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Run</span><code>${escapeHtml(payload.run_id)}</code></div>
        <div><span>Action</span><strong>${escapeHtml(revision?.revision_action || "-")}</strong></div>
        <div><span>Mode</span><strong>${escapeHtml(revision?.revision_mode || "-")}</strong></div>
        <div><span>Audit</span><code>${escapeHtml(audit?.audit_id || "-")}</code></div>
        <div><span>Verifier</span><strong>${escapeHtml(advisory?.verifier_mode || "-")}</strong></div>
        <div><span>Trace</span><strong>${payload.trace.length}</strong></div>
      </div>
    </div>
    <div class="biomed-label">Run Observability</div>
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Prompt tokens</span><strong>${obs("prompt_tokens")}</strong></div>
        <div><span>LLM calls</span><strong>${obs("llm_call_count")}</strong></div>
        <div><span>Source calls</span><strong>${obs("source_call_count")}</strong></div>
        <div><span>Latency seconds</span><strong>${obs("latency_seconds")}</strong></div>
        <div><span>Cache hit tokens</span><strong>${obs("cache_hit_tokens")}</strong></div>
        <div><span>Estimated cost USD</span><strong>${obs("estimated_cost_usd")}</strong></div>
      </div>
    </div>
    <div class="biomed-two-col">
      <div>
        <div class="biomed-label">Memory Effects</div>
        <pre class="biomed-json">${escapeHtml(JSON.stringify(memory, null, 2))}</pre>
      </div>
      <div>
        <div class="biomed-label">Budget Snapshots</div>
        <pre class="biomed-json">${escapeHtml(JSON.stringify(budgetSnapshots, null, 2))}</pre>
      </div>
    </div>
    <div class="biomed-label">Step Telemetry</div>
    ${renderStepTelemetry(payload.step_telemetry)}
    <div class="biomed-label">Advisory Verifier</div>
    ${renderAdvisoryVerifier(advisory)}
    ${
      revision
        ? `
          <div class="biomed-two-col">
            <div>
              <div class="biomed-label">Draft Answer</div>
              <div class="biomed-answer">${renderMarkdown(revision.draft_answer)}</div>
            </div>
            <div>
              <div class="biomed-label">Final Answer</div>
              <div class="biomed-answer">${renderMarkdown(revision.final_answer)}</div>
            </div>
          </div>
          <div class="biomed-two-col">
            <div>
              <div class="biomed-label">Removed Claims</div>
              ${renderList(revision.removed_claims)}
            </div>
            <div>
              <div class="biomed-label">Softened Claims</div>
              ${renderList(revision.softened_claims)}
            </div>
          </div>
          <div class="biomed-label">Added Limitations</div>
          ${renderList(revision.added_limitations)}
          ${revision.fallback_reason ? `<div class="biomed-label">Fallback</div><div class="biomed-muted">${escapeHtml(revision.fallback_reason)}</div>` : ""}
        `
        : '<div class="biomed-muted">No revision recorded. Use Answer + Audit to create a trace.</div>'
    }
    <div class="biomed-label">Trace</div>
    <div class="biomed-trace-list">
      ${payload.trace.map((step) => `
        <div class="biomed-trace-step">
          <div class="biomed-audit-row-head">
            ${pill(step.step)}
            ${pill(step.status)}
            <span>${escapeHtml(step.created_at)}</span>
          </div>
          <div class="biomed-evidence-claim">${escapeHtml(step.output_summary || "-")}</div>
          <div class="biomed-evidence-finding">${escapeHtml(step.input_summary || "")}</div>
          ${step.warnings?.length ? `<div class="biomed-label">Warnings</div>${renderList(step.warnings)}` : ""}
          ${step.metadata && Object.keys(step.metadata).length ? `<pre class="biomed-json">${escapeHtml(JSON.stringify(step.metadata, null, 2))}</pre>` : ""}
        </div>
      `).join("") || '<div class="biomed-muted">No trace steps recorded.</div>'}
    </div>
  `;
}

function currentAuditFromContext(context: WorkspaceRunContext): CitationAuditResult | null {
  return (
    context.audited?.audit ||
    context.trace?.latest_citation_audit ||
    null
  );
}

function currentRevisionFromContext(context: WorkspaceRunContext): AnswerRevision | null {
  return (
    context.audited?.revision ||
    context.trace?.revision ||
    null
  );
}

function currentFinalAnswer(context: WorkspaceRunContext): string {
  return (
    context.fullTextReanalysis?.final_answer ||
    context.audited?.final_answer ||
    context.trace?.revision?.final_answer ||
    context.answer.answer ||
    ""
  );
}

function answerSourceScopeLabel(answer: AnswerResult): string {
  const scopes = answer.evidence_summary.map((item) => item.source_scope || "abstract");
  if (!scopes.length) return "no evidence";
  const hasFullText = scopes.some((scope) => scope === "full_text" || scope === "pdf");
  const hasAbstract = scopes.some((scope) => scope === "abstract");
  if (hasFullText && !hasAbstract) return "full-text-derived";
  if (hasFullText && hasAbstract) return "mixed abstract/full-text";
  return "abstract-derived";
}

function answerStatusLabel(
  audit: CitationAuditResult | null,
  revision: AnswerRevision | null | undefined,
): string {
  if (auditAcceptsDisplayedClaims(audit)) return "Answer accepted by audit";
  if (revision?.final_answer && revision.revision_action === "pass") return "Answer accepted by audit";
  if (revision?.final_answer && revision.revision_action === "revise") return "Answer revised after audit";
  if (revision?.revision_action === "refuse" || revision?.revision_action === "abstain") return "No supported answer";
  const action = audit?.recommended_action || revision?.revision_action || "answer";
  if (action === "pass") return "Answer accepted by audit";
  if (action === "pass_with_limitations") return "Answer passed; inspect packet limits";
  if (action === "revise") return revision?.final_answer ? "Answer revised after audit" : "Revision needed";
  if (action === "refuse_or_abstain" || action === "refuse" || action === "abstain") return "No supported answer";
  return "Answer generated";
}

function auditAcceptsDisplayedClaims(audit: CitationAuditResult | null): boolean {
  if (!audit) return false;
  return (
    audit.claim_support_rate >= 0.995 &&
    audit.citation_precision >= 0.995 &&
    audit.overclaim_rate <= 0 &&
    audit.failed_claims.length === 0
  );
}

function answerTraceStringArray(answer: AnswerResult, key: string): string[] {
  const value = answer.project_context_trace?.[key];
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function directAnswerEvidenceRows(answer: AnswerResult): EvidenceRow[] {
  const directEvidenceIds = new Set(answerTraceStringArray(answer, "direct_answer_evidence_ids"));
  if (directEvidenceIds.size) {
    const rows = answer.evidence_summary.filter((item) => directEvidenceIds.has(item.evidence_id));
    if (rows.length) return rows;
  }
  const offScopeEvidenceIds = new Set(answerTraceStringArray(answer, "off_scope_evidence_ids"));
  if (offScopeEvidenceIds.size) {
    const rows = answer.evidence_summary.filter((item) => !offScopeEvidenceIds.has(item.evidence_id));
    if (rows.length) return rows;
  }
  return answer.evidence_summary;
}

function evidenceConclusionLabel(answer: AnswerResult): string {
  const rows = directAnswerEvidenceRows(answer);
  const counts = rows.reduce<Record<string, number>>((acc, item) => {
    const key = item.evidence_direction || "unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  if ((counts.supports || 0) > 0 && (counts.contradicts || 0) > 0) return "mixed evidence";
  if ((counts.contradicts || 0) > 0) return "evidence does not support the hypothesis";
  if ((counts.supports || 0) > 0) return "evidence supports the hypothesis";
  if ((counts.inconclusive || 0) > 0) return "inconclusive evidence";
  if ((counts.background || 0) > 0) return "contextual evidence only";
  return "no extracted evidence";
}

function renderBoundaryNotice(answer: AnswerResult): string {
  const disclaimer = answer.disclaimer || "Research-only biomedical evidence support. Not medical advice.";
  return `
    <div class="biomed-boundary-notice" title="${escapeHtml(disclaimer)}">
      <span>Boundary</span>
      <strong>${answer.not_medical_advice ? "research-only · not medical advice" : "review required"}</strong>
    </div>
  `;
}

function percent(value: number | undefined): string {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function runQuestion(answer: AnswerResult): string {
  return answer.evidence_packet?.question || answer.retrieval_manifest?.original_query || "Biomedical evidence answer";
}

function retrievedPaperCount(answer: AnswerResult): number {
  const ids = new Set<string>();
  answer.retrieval_bundle?.records.forEach((record) => {
    record.returned_paper_ids.forEach((paperId) => ids.add(paperId));
  });
  answer.retrieval_manifest?.returned_paper_ids.forEach((paperId) => ids.add(paperId));
  return ids.size;
}

function usedCitationPaperCount(answer: AnswerResult): number {
  return new Set(answer.citations.map((citation) => citation.paper_id)).size;
}

function answerTraceNumber(answer: AnswerResult, key: string): number | null {
  const value = answer.project_context_trace?.[key];
  return typeof value === "number" ? value : null;
}

function answerTraceString(answer: AnswerResult, key: string): string {
  const value = answer.project_context_trace?.[key];
  return typeof value === "string" ? value : "";
}

function fullTextReanalysisCoverageWarning(answer: AnswerResult): string {
  return answerTraceString(answer, "full_text_reanalysis_coverage_warning");
}

function renderTrustSignals(answer: AnswerResult, audit: CitationAuditResult | null): string {
  return `
    <section class="biomed-trust-panel">
      <div class="biomed-section-title">Audit checks</div>
      <div class="biomed-trust-copy">
        <div><strong>${audit ? percent(audit.claim_support_rate) : "Pending"} of displayed claims are citation-supported.</strong><span>This is claim-level grounding, not hypothesis support.</span></div>
        <div><strong>${audit ? percent(audit.citation_precision) : "Pending"} citation alignment.</strong><span>Citations are checked against the displayed answer.</span></div>
        <div><strong>${answer.conflicting_evidence.length} conflicts surfaced.</strong><span>Packet limits stay separate from scientific confidence.</span></div>
      </div>
    </section>
  `;
}

function renderEvidenceThatMatters(answer: AnswerResult): string {
  const rows = directAnswerEvidenceRows(answer);
  const items = rows
    .filter((item) => item.evidence_direction !== "inconclusive")
    .slice(0, 4);
  const fallback = rows.slice(0, 4);
  const selected = items.length ? items : fallback;
  return `
    <section class="biomed-output-band">
      <div class="biomed-section-title">Evidence that matters</div>
      <div class="biomed-important-evidence-list">
        ${selected.map((item) => `
          <article>
            <code>${escapeHtml(item.paper_id)}</code>
            <strong>${escapeHtml(item.claim)}</strong>
            <span class="${item.evidence_direction === "contradicts" ? "is-contradicting" : ""}">${escapeHtml(item.evidence_direction)}</span>
          </article>
        `).join("") || '<div class="biomed-muted">No evidence extracted yet.</div>'}
      </div>
    </section>
  `;
}

function renderWorkspaceRunSummary(context: WorkspaceRunContext): string {
  const answer = context.answer;
  const revision = currentRevisionFromContext(context);
  const audit = currentAuditFromContext(context);
  const answerStatus = answerStatusLabel(audit, revision);
  const evidenceConclusion = evidenceConclusionLabel(answer);
  return `
    <section class="biomed-run-hero biomed-cockpit-hero">
      <div>
        <div class="biomed-label">Answer status</div>
        <h2>${escapeHtml(answerStatus)}</h2>
        <p><strong>Evidence conclusion:</strong> ${escapeHtml(evidenceConclusion)}</p>
        <p>${escapeHtml(runQuestion(answer))}</p>
      </div>
      <div class="biomed-run-kicker">
        ${audit ? pill(`claim citation support ${percent(audit.claim_support_rate)}`) : pill("audit pending")}
        ${audit ? pill(`citation alignment ${percent(audit.citation_precision)}`) : ""}
        ${pill(answerSourceScopeLabel(answer))}
        ${answerQualityPills(answer)}
      </div>
    </section>
    <div class="biomed-answer-trust-layout">
      <section class="biomed-output-band biomed-final-answer-panel">
        <div class="biomed-answer-head">
          <div class="biomed-section-title">Final Answer</div>
          ${pill("final-audited")}
        </div>
        <div class="biomed-answer biomed-answer-large">${renderMarkdown(currentFinalAnswer(context))}</div>
        ${renderBoundaryNotice(answer)}
      </section>
      ${renderTrustSignals(answer, audit)}
    </div>
    <section class="biomed-stat-strip">
      <div><span>Retrieved papers</span><strong>${retrievedPaperCount(answer) || "-"}</strong><small>unique search results</small></div>
      <div><span>Extracted evidence</span><strong>${answer.evidence_summary.length}</strong><small>packet items</small></div>
      <div><span>Used citations</span><strong>${answer.citations.length}</strong><small>${usedCitationPaperCount(answer)} papers cited</small></div>
      <div><span>Audit action</span><strong>${escapeHtml(audit?.recommended_action || "pending")}</strong><small>${audit ? percent(audit.packet_citation_utilization ?? audit.citation_precision) : "0%"} packet use</small></div>
    </section>
    ${renderEvidenceThatMatters(answer)}
    <section class="biomed-output-band">
      <div class="biomed-section-title">Main limitations</div>
      <div class="biomed-mini-grid">
        <div><span>Packet</span><strong>${escapeHtml(answer.evidence_packet?.packet_id || "-")}</strong></div>
        <div><span>Retrieval</span><strong>${escapeHtml(answer.retrieval_id || "-")}</strong></div>
        <div><span>Conflicts</span><strong>${answer.conflicting_evidence.length}</strong></div>
        <div><span>Limitations</span><strong>${answer.limitations.length}</strong></div>
      </div>
      ${answer.limitations.length ? renderList(answer.limitations.slice(0, 5)) : '<div class="biomed-muted">No explicit limitations recorded.</div>'}
    </section>
  `;
}

function renderInspectorTabs(active: string): string {
  const tabs = [
    ["overview", "Summary"],
    ["evidence", "Evidence"],
    ["fulltext", "Full Text"],
    ["review", "Review"],
    ["advanced", "Advanced"],
  ];
  return `
    <div class="biomed-inspector-tabs">
      ${tabs.map(([id, label]) => `
        <button class="biomed-inspector-tab ${id === active ? "is-active" : ""}" data-biomed-inspector="${id}">
          ${escapeHtml(label)}
        </button>
      `).join("")}
    </div>
  `;
}

function renderAdvancedInspector(): string {
  const artifacts = [
    ["audit", "Audit"],
    ["logic", "Logic facts"],
    ["argument", "Argument graph"],
    ["math", "Math signals"],
    ["trace", "Trace"],
    ["provenance", "Provenance"],
    ["diff", "Snapshot diff"],
    ["pilot", "Pilot report"],
    ["raw", "Raw JSON"],
  ];
  return `
    <div class="biomed-inspector-stack">
      <div class="biomed-label">Advanced</div>
      <div class="biomed-muted">Debugging and provenance artifacts are still available, but kept out of the default reading path.</div>
      <div class="biomed-advanced-artifacts">
        ${artifacts.map(([id, label]) => `
          <button type="button" data-biomed-deep-tab="${escapeHtml(id)}">${escapeHtml(label)}</button>
        `).join("")}
      </div>
    </div>
  `;
}

function renderRunLiteratureSet(literature: RunLiteratureSet): string {
  const summary = literature.summary;
  return `
    <div class="biomed-inspector-stack">
      <div class="biomed-label">Literature Set</div>
      <div class="biomed-mini-grid">
        <div><span>Papers</span><strong>${summary.total_papers}</strong></div>
        <div><span>Used</span><strong>${summary.used_in_answer_count}</strong></div>
        <div><span>Packet</span><strong>${summary.packet_included_count}</strong></div>
        <div><span>Full Text</span><strong>${summary.full_text_count}</strong></div>
        <div><span>Needs Review</span><strong>${summary.needs_review_count}</strong></div>
        <div><span>Rejected</span><strong>${summary.rejected_count}</strong></div>
      </div>
      <div class="biomed-literature-list">
        ${literature.papers.map((paper) => `
          <article class="biomed-literature-row">
            <div>
              <div class="biomed-review-claim-head">
                ${paper.used_in_answer ? pill("used") : pill("retrieved")}
                ${paper.packet_included ? pill("packet") : ""}
                ${paper.has_full_text ? pill("full_text") : ""}
                ${paper.decision ? pill(paper.decision) : pill(paper.review_status)}
              </div>
              <h3>${escapeHtml(paper.title || paper.paper_id)}</h3>
              <div class="biomed-watch-meta">
                ${escapeHtml(paper.journal || paper.source)} · ${escapeHtml(paper.publication_date || "-")} · rank ${paper.retrieval_rank || "-"}
              </div>
              ${paper.decision_reason ? `<p>${escapeHtml(paper.decision_reason)}</p>` : ""}
            </div>
            <code>${escapeHtml(paper.paper_id)}</code>
          </article>
        `).join("") || '<div class="biomed-muted">No papers recorded for this run.</div>'}
      </div>
    </div>
  `;
}

function renderFullTextEnhancement(envelope: ReleaseToolEnvelope<FullTextEnhancementResult>): string {
  if (!envelope.ok) return renderReleaseError(envelope);
  const result = envelope.result;
  const hasFullTextEvidence = Boolean(
    result.extracted_evidence_ids.length ||
    result.paper_statuses.some((paper) => paper.evidence_ids.length),
  );
  return `
    <div class="biomed-inspector-stack">
      <div class="biomed-label">Full Text Enhancement</div>
      <div class="biomed-mini-grid">
        <div><span>Processed</span><strong>${result.processed_paper_ids.length}</strong></div>
        <div><span>Documents</span><strong>${result.document_ids.length}</strong></div>
        <div><span>Extracted Evidence</span><strong>${result.extracted_evidence_ids.length}</strong></div>
        <div><span>Unavailable</span><strong>${result.unavailable_paper_ids.length}</strong></div>
        <div><span>Packet</span><strong>${escapeHtml(result.packet_id || "-")}</strong></div>
        <div><span>Review</span><strong>${result.review_available ? "available" : "pending"}</strong></div>
      </div>
      ${result.warnings.length ? `<div class="biomed-label">Warnings</div>${renderBreakableList(result.warnings)}` : ""}
      ${
        hasFullTextEvidence
          ? '<button id="biomed-run-reanalyze-fulltext" class="biomed-secondary-button" type="button">Re-analyze with Full Text</button>'
          : ""
      }
      <div class="biomed-label">Paper Status</div>
      <div class="biomed-literature-list">
        ${result.paper_statuses.map((paper) => `
          <article class="biomed-literature-row">
            <div>
              <div class="biomed-review-claim-head">
                ${pill(paper.status)}
                ${paper.document_id ? pill("document") : ""}
                ${paper.evidence_ids.length ? pill(`${paper.evidence_ids.length} evidence`) : ""}
              </div>
              <h3>${escapeHtml(paper.paper_id)}</h3>
              <div class="biomed-watch-meta">
                sections ${paper.section_count} · ${escapeHtml(paper.source)}
                ${paper.provider_status ? ` · ${escapeHtml(paper.provider_status)}` : ""}
                ${paper.provider ? ` · ${escapeHtml(paper.provider)}` : ""}
                ${paper.lookup_id_type ? ` · ${escapeHtml(paper.lookup_id_type)}` : ""}
              </div>
              ${paper.source_locator ? `<p>${breakableText(paper.source_locator)}</p>` : ""}
              ${paper.license_or_rights ? `<p>${breakableText(paper.license_or_rights)}</p>` : ""}
              ${paper.warning ? `<p>${breakableText(paper.warning)}</p>` : ""}
              ${paper.error ? `<p>${breakableText(paper.error)}</p>` : ""}
            </div>
            <code>${escapeHtml(paper.document_id || "-")}</code>
          </article>
        `).join("") || '<div class="biomed-muted">No paper statuses returned.</div>'}
      </div>
    </div>
  `;
}

function renderFullTextReanalysis(result: AuditedAnswerResult): string {
  const answer = result.answer_result;
  const availableEvidence = answerTraceNumber(answer, "full_text_reanalysis_available_evidence_count");
  const usedEvidence = answerTraceNumber(answer, "full_text_reanalysis_used_evidence_count") ?? answer.evidence_summary.length;
  const availablePapers = answerTraceNumber(answer, "full_text_reanalysis_available_paper_count");
  const usedPapers = answerTraceNumber(answer, "full_text_reanalysis_used_paper_count") ?? new Set(answer.evidence_summary.map((item) => item.paper_id)).size;
  const warning = fullTextReanalysisCoverageWarning(answer);
  return `
    <div class="biomed-label">Full Text Re-analysis</div>
    <div class="biomed-mini-grid">
      <div><span>Full-text coverage</span><strong>${usedPapers}/${availablePapers ?? usedPapers}</strong></div>
      <div><span>Used evidence</span><strong>${usedEvidence}/${availableEvidence ?? usedEvidence}</strong></div>
      <div><span>Used citations</span><strong>${answer.citations.length}</strong></div>
    </div>
    ${warning ? `<div class="biomed-warning">${escapeHtml(warning)}</div>` : ""}
    <div class="biomed-answer">${renderMarkdown(result.final_answer)}</div>
  `;
}

function renderFullTextRunPanel(context: WorkspaceRunContext): string {
  const literature = context.literature;
  return `
    <div class="biomed-inspector-stack">
      <div class="biomed-label">Full Text</div>
      ${
        literature
          ? renderRunLiteratureSet(literature)
          : '<div class="biomed-muted">Load the Literature Set tab first to inspect current full-text coverage.</div>'
      }
      <div class="biomed-primary-actions">
        <button id="biomed-run-enhance-fulltext" class="biomed-primary-button" type="button">Enhance Full Text</button>
      </div>
      <div id="biomed-run-fulltext-result">
        ${
          context.fullTextEnhancement
            ? renderFullTextEnhancement(context.fullTextEnhancement)
            : '<div class="biomed-muted">Run enhancement to reuse stored full text or attempt provider-backed full-text lookup.</div>'
        }
      </div>
      <div id="biomed-run-fulltext-reanalysis">
        ${
          context.fullTextReanalysis
            ? renderFullTextReanalysis(context.fullTextReanalysis)
            : ""
        }
      </div>
    </div>
  `;
}

function renderPilotReportMarkdown(markdown: string): string {
  return `
    <div class="biomed-inspector-stack">
      <div class="biomed-label">Pilot Report</div>
      <div class="biomed-answer">${renderMarkdown(markdown)}</div>
    </div>
  `;
}

function renderLogicFactsPanel(audit: CitationAuditResult | null): string {
  if (!audit) return '<div class="biomed-muted">No citation audit with logic facts is loaded.</div>';
  const logicItems = audit.claim_audits.filter((item) => item.logic_audit);
  if (!logicItems.length) return '<div class="biomed-muted">No logic audit artifacts were attached to this run.</div>';
  return logicItems.map((item) => `
    <div class="biomed-audit-row">
      <div class="biomed-audit-row-head">
        ${pill(item.logic_audit?.logic_verdict || "not_assessed")}
        ${pill(item.verdict)}
        <code>${escapeHtml(item.claim_id)}</code>
      </div>
      <div class="biomed-evidence-claim">${escapeHtml(item.claim)}</div>
      ${renderLogicAudit(item.logic_audit)}
    </div>
  `).join("");
}

function renderInspectorEvidenceReview(review: RunEvidenceReview): string {
  return `
    <div class="biomed-inspector-stack">
      <div class="biomed-label">Snapshot Review</div>
      <div class="biomed-mini-grid">
        <div><span>Snapshot</span><strong>${escapeHtml(review.snapshot.status)}</strong></div>
        <div><span>Stale</span><strong>${review.snapshot.stale ? "yes" : "no"}</strong></div>
        <div><span>Claims</span><strong>${review.summary.total_claims}</strong></div>
        <div><span>Needs Review</span><strong>${review.claims.filter((claim) => claim.review_action !== "accept").length}</strong></div>
        <div><span>Validation</span><strong>${review.summary.validation_ok ? "valid" : "invalid"}</strong></div>
        <div><span>Audit</span><strong>${escapeHtml(review.summary.recommended_audit_action || "pending")}</strong></div>
      </div>
      ${review.snapshot.graph_hash ? `<div class="biomed-watch-meta">graph hash ${compactCode(review.snapshot.graph_hash)}</div>` : ""}
      ${review.snapshot.previous_snapshot_id ? `<div class="biomed-watch-meta">previous snapshot ${compactCode(review.snapshot.previous_snapshot_id)}</div>` : ""}
      ${review.snapshot.stale_reasons?.length ? `<div class="biomed-label">Stale Reasons</div>${renderList(review.snapshot.stale_reasons)}` : ""}
      ${review.warnings.length ? `<div class="biomed-label">Warnings</div>${renderList(review.warnings)}` : ""}
      ${renderGraphValidation(review.validation)}
      <div class="biomed-label">Claims</div>
      ${review.claims.map((claim) => `
        <article class="biomed-review-claim-card ${claim.review_action !== "accept" ? "is-failed" : ""}">
          <div class="biomed-review-claim-head">
            ${pill(claim.review_action)}
            ${pill(claim.support_status)}
            ${claim.audit_verdict ? pill(claim.audit_verdict) : ""}
          </div>
          <h3>${escapeHtml(claim.claim_text)}</h3>
          <div class="biomed-watch-meta">${claim.paper_ids.map(escapeHtml).join(" · ") || "no papers"}</div>
          ${claim.support_status_reason ? `<p>${escapeHtml(claim.support_status_reason)}</p>` : ""}
        </article>
      `).join("") || '<div class="biomed-muted">No claims in this review.</div>'}
    </div>
  `;
}

function renderSnapshotDiff(diff: EvidenceGraphSnapshotDiff): string {
  if (!diff.available) {
    return `
      <div class="biomed-inspector-stack">
        <div class="biomed-label">Snapshot Diff</div>
        <div class="biomed-muted">${escapeHtml(diff.reason || "No snapshot diff is available.")}</div>
      </div>
    `;
  }
  const entries = Object.entries(diff.changes || {});
  return `
    <div class="biomed-inspector-stack">
      <div class="biomed-label">Snapshot Diff</div>
      <div class="biomed-mini-grid">
        <div><span>Base</span><strong>${escapeHtml(compactCode(diff.base_snapshot_id || "-"))}</strong></div>
        <div><span>Compare</span><strong>${escapeHtml(compactCode(diff.compare_snapshot_id || "-"))}</strong></div>
        <div><span>Base Audit</span><strong>${escapeHtml(compactCode(diff.base_audit_id || "-"))}</strong></div>
        <div><span>Compare Audit</span><strong>${escapeHtml(compactCode(diff.compare_audit_id || "-"))}</strong></div>
      </div>
      ${entries.map(([key, value]) => {
        const items = Array.isArray(value) ? value : [];
        return `
          <div class="biomed-audit-row">
            <div class="biomed-audit-row-head">${pill(key)}<strong>${items.length}</strong></div>
            ${items.length ? renderList(items.map((item) => typeof item === "string" ? item : JSON.stringify(item))) : '<div class="biomed-muted">No changes.</div>'}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

async function loadWorkspaceTrace(runId: string): Promise<TracePayload> {
  return api<TracePayload>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/trace`);
}

async function loadWorkspaceRun(runId: string): Promise<WorkspaceRunContext> {
  const trace = await loadWorkspaceTrace(runId);
  let activeTrace = trace;
  if (!runId.endsWith("-fulltext")) {
    try {
      activeTrace = await loadWorkspaceTrace(`${runId}-fulltext`);
    } catch {
      activeTrace = trace;
    }
  }
  const context: WorkspaceRunContext = {
    answer: activeTrace.answer_run,
    trace: activeTrace,
    raw: activeTrace,
  };
  if (activeTrace.run_id !== trace.run_id && activeTrace.latest_citation_audit && activeTrace.revision) {
    context.fullTextReanalysis = {
      answer_result: activeTrace.answer_run,
      draft_answer: activeTrace.answer_run.answer,
      final_answer: activeTrace.revision.final_answer || activeTrace.answer_run.answer,
      audit: activeTrace.latest_citation_audit,
      revision: activeTrace.revision,
      trace: activeTrace.trace || [],
      final_action: activeTrace.latest_citation_audit.recommended_action || activeTrace.revision.revision_action || "pass",
    };
  }
  syncFullTextCacheToContext(context);
  return context;
}

async function loadRunLiteratureSet(context: WorkspaceRunContext): Promise<RunLiteratureSet> {
  if (context.literature) return context.literature;
  const params = new URLSearchParams();
  if (context.answer.project_id) params.set("project_id", context.answer.project_id);
  const query = params.toString();
  const literature = await api<RunLiteratureSet>(
    `/api/biomed/answer-runs/${encodeURIComponent(context.answer.run_id)}/papers${query ? `?${query}` : ""}`,
  );
  context.literature = literature;
  rememberFullTextContext(context);
  return literature;
}

function syncFullTextCacheToContext(context: WorkspaceRunContext): void {
  const cached = fullTextRunCache.get(context.answer.run_id);
  if (!cached) return;
  context.literature = context.literature ?? cached.literature ?? null;
  context.fullTextEnhancement = context.fullTextEnhancement ?? cached.fullTextEnhancement ?? null;
  context.fullTextReanalysis = context.fullTextReanalysis ?? cached.fullTextReanalysis ?? null;
}

function rememberFullTextContext(context: WorkspaceRunContext, aliasRunId?: string): void {
  const entry: FullTextRunCacheEntry = {
    literature: context.literature ?? null,
    fullTextEnhancement: context.fullTextEnhancement ?? null,
    fullTextReanalysis: context.fullTextReanalysis ?? null,
  };
  fullTextRunCache.set(context.answer.run_id, entry);
  if (aliasRunId && aliasRunId !== context.answer.run_id) {
    fullTextRunCache.set(aliasRunId, entry);
  }
}

async function loadRecentRuns(container: HTMLElement): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-recent-runs");
  if (!target) return;
  target.innerHTML = '<div class="biomed-muted">Loading recent runs...</div>';
  try {
    const data = await api<{ items: AnswerRunListItem[] }>("/api/biomed/answer-runs?page_size=8");
    target.innerHTML = data.items.map((item) => `
      <button class="biomed-run-link" data-biomed-run-id="${escapeHtml(item.run_id)}">
        <span>${escapeHtml(item.question || item.run_id)}</span>
        <code>${escapeHtml(item.created_at || item.run_id)}</code>
      </button>
    `).join("") || '<div class="biomed-muted">No runs yet.</div>';
    target.querySelectorAll<HTMLButtonElement>("[data-biomed-run-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        const runId = button.dataset.biomedRunId || "";
        const center = container.querySelector<HTMLElement>("#biomed-ask-result");
        if (center) center.innerHTML = renderLoading("Loading saved run...");
        try {
          const context = await loadWorkspaceRun(runId);
          hydrateWorkspaceRun(container, context);
        } catch (error) {
          if (center) center.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
        }
      });
    });
  } catch (error) {
    target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

function renderInspectorOverview(context: WorkspaceRunContext): string {
  const answer = context.answer;
  const audit = currentAuditFromContext(context);
  return `
    <div class="biomed-inspector-stack">
      <div class="biomed-label">Run Snapshot</div>
      <div class="biomed-mini-grid">
        <div><span>Run</span><strong>${escapeHtml(answer.run_id)}</strong></div>
        <div><span>Source</span><strong>${escapeHtml(answer.retrieval_manifest?.source || "-")}</strong></div>
        <div><span>Retrieved papers</span><strong>${retrievedPaperCount(answer) || "-"}</strong></div>
        <div><span>Extracted evidence</span><strong>${answer.evidence_summary.length}</strong></div>
        <div><span>Used citations</span><strong>${answer.citations.length}</strong></div>
        <div><span>Audit</span><strong>${escapeHtml(audit?.recommended_action || "pending")}</strong></div>
        <div><span>Packet</span><strong>${escapeHtml(answer.evidence_packet?.stop_reason || "-")}</strong></div>
      </div>
      ${fullTextReanalysisCoverageWarning(answer) ? `<div class="biomed-warning">${escapeHtml(fullTextReanalysisCoverageWarning(answer))}</div>` : ""}
      <div class="biomed-label">Retrieval Manifest</div>
      ${renderManifest(answer.retrieval_manifest)}
      <div class="biomed-label">Citations</div>
      ${renderList(answer.citations.map((citation) => `${citation.title} | ${citation.paper_id}`))}
    </div>
  `;
}

async function loadInspectorTab(
  container: HTMLElement,
  context: WorkspaceRunContext,
  tab: string,
): Promise<void> {
  const content = container.querySelector<HTMLElement>("#biomed-inspector-content");
  const runId = context.answer.run_id;
  if (!content) return;
  const deepTabs = new Set(["audit", "logic", "argument", "math", "trace", "provenance", "diff", "pilot", "raw", "literature"]);
  const activeTab = deepTabs.has(tab) ? "advanced" : tab;
  container.querySelectorAll<HTMLButtonElement>("[data-biomed-inspector]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.biomedInspector === activeTab);
  });
  content.innerHTML = renderLoading(`Loading ${tab}...`);
  try {
    if (tab === "overview") {
      content.innerHTML = renderInspectorOverview(context);
    } else if (tab === "literature") {
      const literature = await loadRunLiteratureSet(context);
      content.innerHTML = renderRunLiteratureSet(literature);
    } else if (tab === "advanced") {
      content.innerHTML = renderAdvancedInspector();
      content.querySelectorAll<HTMLButtonElement>("[data-biomed-deep-tab]").forEach((button) => {
        button.addEventListener("click", () => {
          void loadInspectorTab(container, context, button.dataset.biomedDeepTab || "audit");
        });
      });
    } else if (tab === "fulltext") {
      if (!context.literature) {
        context.literature = await loadRunLiteratureSet(context).catch(() => null);
      }
      content.innerHTML = renderFullTextRunPanel(context);
      const bindReanalysis = () => {
        content.querySelector<HTMLButtonElement>("#biomed-run-reanalyze-fulltext")?.addEventListener("click", async () => {
          const target = content.querySelector<HTMLElement>("#biomed-run-fulltext-reanalysis");
          const button = content.querySelector<HTMLButtonElement>("#biomed-run-reanalyze-fulltext");
          if (!target) return;
          target.innerHTML = renderLoading("Re-analyzing with full text...");
          if (button) button.disabled = true;
          try {
            const result = await api<AuditedAnswerResult>(
              `/api/biomed/answer-runs/${encodeURIComponent(runId)}/full-text-reanalysis`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  run_id: runId,
                  use_llm_claim_logic: Boolean(container.querySelector<HTMLInputElement>("#biomed-use-claim-logic")?.checked),
                  export_logic_facts: Boolean(container.querySelector<HTMLInputElement>("#biomed-export-logic-facts")?.checked),
                }),
              },
            );
            context.fullTextReanalysis = result;
            context.answer = result.answer_result;
            context.audited = result;
            context.trace = null;
            context.raw = result;
            rememberFullTextContext(context, runId);
            const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
            if (resultNode) resultNode.innerHTML = renderWorkspaceRunSummary(context);
            const title = container.querySelector<HTMLElement>(".biomed-inspector-title");
            if (title) title.textContent = context.answer.run_id;
            target.innerHTML = renderFullTextReanalysis(result);
          } catch (error) {
            target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
          } finally {
            if (button) button.disabled = false;
          }
        });
      };
      bindReanalysis();
      content.querySelector<HTMLButtonElement>("#biomed-run-enhance-fulltext")?.addEventListener("click", async () => {
        const target = content.querySelector<HTMLElement>("#biomed-run-fulltext-result");
        const button = content.querySelector<HTMLButtonElement>("#biomed-run-enhance-fulltext");
        if (!target) return;
        target.innerHTML = renderLoading("Enhancing full text...");
        if (button) button.disabled = true;
        try {
          const envelope = await api<ReleaseToolEnvelope<FullTextEnhancementResult>>(
            `/api/biomed/answer-runs/${encodeURIComponent(runId)}/full-text-enhance`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                run_id: runId,
                source: context.answer.retrieval_manifest?.source || "mock",
                max_papers: 10,
                use_open_provider: true,
              }),
            },
          );
          context.fullTextEnhancement = envelope;
          context.literature = null;
          rememberFullTextContext(context);
          target.innerHTML = renderFullTextEnhancement(envelope);
          bindReanalysis();
        } catch (error) {
          target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
        } finally {
          if (button) button.disabled = false;
        }
      });
    } else if (tab === "review") {
      const review = await api<RunEvidenceReview>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/evidence-review`);
      content.innerHTML = renderInspectorEvidenceReview(review);
    } else if (tab === "pilot") {
      let markdown = context.pilotReportMarkdown;
      if (!markdown) {
        const response = await fetch(`/api/biomed/export?run_id=${encodeURIComponent(runId)}&report_type=pilot&format=markdown`);
        if (!response.ok) {
          throw new Error(await response.text());
        }
        markdown = await response.text();
      }
      context.pilotReportMarkdown = markdown;
      content.innerHTML = renderPilotReportMarkdown(markdown);
    } else if (tab === "diff") {
      const diff = await api<EvidenceGraphSnapshotDiff>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/evidence-review/snapshot-diff`);
      content.innerHTML = renderSnapshotDiff(diff);
    } else if (tab === "trace") {
      const trace = context.trace || await loadWorkspaceTrace(runId);
      context.trace = trace;
      content.innerHTML = renderTraceResult(trace);
    } else if (tab === "evidence") {
      content.innerHTML = `
        ${renderEvidencePacket(context.answer.evidence_packet)}
        <div class="biomed-label">Evidence Items</div>
        ${context.answer.evidence_summary.map(renderEvidenceItem).join("") || '<div class="biomed-muted">No evidence extracted.</div>'}
      `;
    } else if (tab === "audit") {
      const audit = currentAuditFromContext(context);
      content.innerHTML = audit ? renderAuditResult(audit) : '<div class="biomed-muted">No audit loaded for this run.</div>';
    } else if (tab === "logic") {
      content.innerHTML = renderLogicFactsPanel(currentAuditFromContext(context));
    } else if (tab === "argument") {
      const graph = await api<ArgumentGraphResult>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/argument-graph`);
      content.innerHTML = renderArgumentGraph(graph);
    } else if (tab === "math") {
      const signals = await api<MathSignalsResult>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/math-signals`);
      content.innerHTML = renderMathSignals(signals);
    } else if (tab === "provenance") {
      const provenance = context.provenance || await api<ReleaseToolEnvelope<ProvenanceGraphResult>>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/provenance`);
      context.provenance = provenance;
      content.innerHTML = renderProvenanceResult(provenance);
    } else {
      content.innerHTML = `<pre class="biomed-json biomed-json-tall">${escapeHtml(JSON.stringify(context.raw || context, null, 2))}</pre>`;
    }
  } catch (error) {
    content.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

function hydrateWorkspaceRun(container: HTMLElement, context: WorkspaceRunContext): void {
  const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
  const inspector = container.querySelector<HTMLElement>("#biomed-inspector");
  if (resultNode) {
    resultNode.innerHTML = renderWorkspaceRunSummary(context);
  }
  if (inspector) {
    inspector.innerHTML = `
      <div class="biomed-inspector-head">
        <div>
          <div class="biomed-label">Inspector</div>
          <div class="biomed-inspector-title">${escapeHtml(context.answer.run_id)}</div>
        </div>
        <div>${answerQualityPills(context.answer)}</div>
      </div>
      ${renderInspectorTabs("overview")}
      <div id="biomed-inspector-content" class="biomed-inspector-content"></div>
    `;
    inspector.querySelectorAll<HTMLButtonElement>("[data-biomed-inspector]").forEach((button) => {
      button.addEventListener("click", () => {
        void loadInspectorTab(container, context, button.dataset.biomedInspector || "overview");
      });
    });
    void loadInspectorTab(container, context, "overview");
  }
  void loadRecentRuns(container);
}

async function loadProjectOptions(container: HTMLElement): Promise<void> {
  const select = container.querySelector<HTMLSelectElement>("#biomed-project-select");
  if (!select) return;
  try {
    const data = await api<{ items: BiomedProject[] }>("/api/biomed/projects");
    const current = select.value;
    select.innerHTML = `
      <option value="">no project</option>
      ${data.items.map((project) => `
        <option value="${escapeHtml(project.project_id)}">${escapeHtml(project.name)}</option>
      `).join("")}
    `;
    if (current) select.value = current;
  } catch {
    select.innerHTML = '<option value="">projects unavailable</option>';
  }
}

function renderProjectList(projects: BiomedProject[]): string {
  if (!projects.length) return '<div class="biomed-muted">No projects yet.</div>';
  return projects.map((project) => `
    <div class="biomed-decision">
      <div>
        <strong>${escapeHtml(project.name)}</strong>
        <code>${escapeHtml(project.project_id)}</code>
      </div>
      <div class="biomed-watch-meta">
        ${escapeHtml(project.research_question || "no research question")} · updated ${escapeHtml(project.updated_at)}
      </div>
      <div class="biomed-watch-meta">
        include ${escapeHtml(project.include_keywords.join(", ") || "-")} · exclude ${escapeHtml(project.exclude_keywords.join(", ") || "-")}
      </div>
      <button data-biomed-load-project="${escapeHtml(project.project_id)}">Load</button>
    </div>
  `).join("");
}

async function loadProjectDetail(container: HTMLElement, projectId: string): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-project-detail");
  if (!target || !projectId) return;
  target.textContent = "Loading project...";
  try {
    const [papers, claims, queue, briefs] = await Promise.all([
      api<{ items: ProjectPaperDecision[] }>(`/api/biomed/projects/${encodeURIComponent(projectId)}/papers`),
      api<{ items: ProjectClaimRecord[] }>(`/api/biomed/projects/${encodeURIComponent(projectId)}/claims`),
      api<{ items: ProjectReviewQueueItem[] }>(`/api/biomed/projects/${encodeURIComponent(projectId)}/review-queue`),
      api<{ items: ProjectEvidenceBrief[] }>(`/api/biomed/projects/${encodeURIComponent(projectId)}/briefs`),
    ]);
    target.innerHTML = `
      <div class="biomed-two-col">
        <div>
          <div class="biomed-label">Paper Decisions</div>
          ${papers.items.map((item) => `
            <div class="biomed-decision">
              <div>${pill(item.decision)} <code>${escapeHtml(item.paper_id)}</code></div>
              <div class="biomed-watch-meta">${escapeHtml(item.reason || "")}</div>
            </div>
          `).join("") || '<div class="biomed-muted">No paper decisions.</div>'}
        </div>
        <div>
          <div class="biomed-label">Project Claims</div>
          ${claims.items.map((item) => `
            <div class="biomed-decision">
              <div>${pill(item.status)} ${escapeHtml(item.claim)}</div>
              <div class="biomed-watch-meta">audits ${escapeHtml(item.audit_ids.join(", ") || "-")} · evidence ${escapeHtml(item.evidence_ids.join(", ") || "-")}</div>
            </div>
          `).join("") || '<div class="biomed-muted">No project claims.</div>'}
        </div>
      </div>
      <div class="biomed-label">Review Queue</div>
      ${queue.items.map((item) => `
        <div class="biomed-audit-row ${item.risk_level === "high" ? "is-failed" : ""}">
          <div class="biomed-audit-row-head">${pill(item.risk_level)} ${pill(item.item_type)} <span>${escapeHtml(item.created_at)}</span></div>
          <div class="biomed-evidence-claim">${escapeHtml(item.title)}</div>
          <div class="biomed-evidence-finding">${escapeHtml(item.reason)}</div>
        </div>
      `).join("") || '<div class="biomed-muted">No review items.</div>'}
      <div class="biomed-label">Evidence Briefs</div>
      ${briefs.items.map((item) => `
        <div class="biomed-decision">
          <div>${pill(item.format)} <code>${escapeHtml(item.brief_id)}</code> ${escapeHtml(item.title)}</div>
          <pre class="biomed-json">${escapeHtml(item.content)}</pre>
        </div>
      `).join("") || '<div class="biomed-muted">No briefs generated.</div>'}
    `;
  } catch (error) {
    target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

async function loadProjects(container: HTMLElement): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-project-list");
  if (!target) return;
  target.textContent = "Loading projects...";
  try {
    const data = await api<{ items: BiomedProject[] }>("/api/biomed/projects");
    target.innerHTML = renderProjectList(data.items);
    target.querySelectorAll<HTMLButtonElement>("[data-biomed-load-project]").forEach((button) => {
      button.addEventListener("click", async () => {
        const projectId = button.dataset.biomedLoadProject || "";
        const current = container.querySelector<HTMLInputElement>("#biomed-current-project");
        if (current) current.value = projectId;
        await loadProjectDetail(container, projectId);
      });
    });
  } catch (error) {
    target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

function renderProjects(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-section">
      <div class="biomed-title">Project Evidence Workspace</div>
      <div class="biomed-form">
        <input id="biomed-project-name" value="Microglia AD progression" />
        <input id="biomed-project-question" value="Evidence linking microglial activation to Alzheimer's disease progression" />
        <input id="biomed-project-include" value="microglial activation,Alzheimer's disease,progression" />
        <input id="biomed-project-exclude" placeholder="exclude keywords" />
        <input id="biomed-project-methods" placeholder="preferred methods" />
        <div class="biomed-row">
          <button id="biomed-project-create">Create Project</button>
          <input id="biomed-current-project" placeholder="project id" />
          <button id="biomed-project-load">Load Project</button>
        </div>
      </div>
      <div class="biomed-label">Projects</div>
      <div id="biomed-project-list" class="biomed-result"></div>
      <div class="biomed-label">Paper Decision</div>
      <div class="biomed-row">
        <input id="biomed-project-paper-id" placeholder="paper id" />
        <select id="biomed-project-paper-source"><option value="mock">mock</option><option value="pubmed">pubmed</option></select>
        <select id="biomed-project-paper-decision"><option value="saved">saved</option><option value="rejected">rejected</option><option value="needs_review">needs_review</option></select>
        <input id="biomed-project-paper-reason" placeholder="reason" />
        <button id="biomed-project-paper-save">Record</button>
      </div>
      <div class="biomed-label">Claim Record</div>
      <div class="biomed-row">
        <input id="biomed-project-claim" placeholder="claim" />
        <select id="biomed-project-claim-status"><option value="needs_review">needs_review</option><option value="supported">supported</option><option value="mixed">mixed</option><option value="uncertain">uncertain</option><option value="rejected">rejected</option></select>
        <input id="biomed-project-claim-evidence" placeholder="evidence ids" />
        <input id="biomed-project-claim-audits" placeholder="audit ids" />
        <button id="biomed-project-claim-save">Record Claim</button>
      </div>
      <div class="biomed-row">
        <button id="biomed-project-brief">Generate Brief</button>
      </div>
      <div id="biomed-project-detail" class="biomed-result"></div>
    </div>
  `;
  container.querySelector<HTMLButtonElement>("#biomed-project-create")?.addEventListener("click", async () => {
    const name = container.querySelector<HTMLInputElement>("#biomed-project-name")?.value || "";
    const research_question = container.querySelector<HTMLInputElement>("#biomed-project-question")?.value || "";
    const include_keywords = csv(container.querySelector<HTMLInputElement>("#biomed-project-include")?.value || "");
    const exclude_keywords = csv(container.querySelector<HTMLInputElement>("#biomed-project-exclude")?.value || "");
    const preferred_methods = csv(container.querySelector<HTMLInputElement>("#biomed-project-methods")?.value || "");
    const project = await api<BiomedProject>("/api/biomed/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, research_question, include_keywords, exclude_keywords, preferred_methods }),
    });
    const current = container.querySelector<HTMLInputElement>("#biomed-current-project");
    if (current) current.value = project.project_id;
    await loadProjects(container);
    await loadProjectDetail(container, project.project_id);
  });
  container.querySelector<HTMLButtonElement>("#biomed-project-load")?.addEventListener("click", async () => {
    const projectId = container.querySelector<HTMLInputElement>("#biomed-current-project")?.value || "";
    await loadProjectDetail(container, projectId);
  });
  container.querySelector<HTMLButtonElement>("#biomed-project-paper-save")?.addEventListener("click", async () => {
    const projectId = container.querySelector<HTMLInputElement>("#biomed-current-project")?.value || "";
    const paper_id = container.querySelector<HTMLInputElement>("#biomed-project-paper-id")?.value || "";
    const source = container.querySelector<HTMLSelectElement>("#biomed-project-paper-source")?.value || "mock";
    const decision = container.querySelector<HTMLSelectElement>("#biomed-project-paper-decision")?.value || "saved";
    const reason = container.querySelector<HTMLInputElement>("#biomed-project-paper-reason")?.value || "";
    if (!projectId || !paper_id) return;
    await api(`/api/biomed/projects/${encodeURIComponent(projectId)}/papers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_id, source, decision, reason }),
    });
    await loadProjectDetail(container, projectId);
  });
  container.querySelector<HTMLButtonElement>("#biomed-project-claim-save")?.addEventListener("click", async () => {
    const projectId = container.querySelector<HTMLInputElement>("#biomed-current-project")?.value || "";
    const claim = container.querySelector<HTMLInputElement>("#biomed-project-claim")?.value || "";
    const status = container.querySelector<HTMLSelectElement>("#biomed-project-claim-status")?.value || "needs_review";
    const evidence_ids = csv(container.querySelector<HTMLInputElement>("#biomed-project-claim-evidence")?.value || "");
    const audit_ids = csv(container.querySelector<HTMLInputElement>("#biomed-project-claim-audits")?.value || "");
    if (!projectId || !claim) return;
    await api(`/api/biomed/projects/${encodeURIComponent(projectId)}/claims`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim, status, evidence_ids, audit_ids }),
    });
    await loadProjectDetail(container, projectId);
  });
  container.querySelector<HTMLButtonElement>("#biomed-project-brief")?.addEventListener("click", async () => {
    const projectId = container.querySelector<HTMLInputElement>("#biomed-current-project")?.value || "";
    if (!projectId) return;
    await api(`/api/biomed/projects/${encodeURIComponent(projectId)}/briefs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format: "markdown" }),
    });
    await loadProjectDetail(container, projectId);
  });
  void loadProjects(container);
}

function renderTabs(view: BiomedView): string {
  return `
    <div class="biomed-tabs">
      ${BIOMED_VIEW_ITEMS.map((tab) => `
        <button class="biomed-tab ${tab.id === view ? "is-active" : ""}" data-biomed-view="${tab.id}">
          ${escapeHtml(tab.label)}
        </button>
      `).join("")}
    </div>
  `;
}

function renderBiomedWorkbenchPage(
  root: HTMLElement,
  title: string,
  subtitle: string,
  renderBody: (body: HTMLElement) => void,
): void {
  root.innerHTML = `
    <div class="biomed-workbench-page">
      <header class="biomed-workbench-page-head">
        <div>
          <div class="biomed-label">Biomedical Evidence Agent</div>
          <h2>${escapeHtml(title)}</h2>
          <p>${escapeHtml(subtitle)}</p>
        </div>
      </header>
      <section class="biomed-workbench-page-body"></section>
    </div>
  `;
  const body = root.querySelector<HTMLElement>(".biomed-workbench-page-body");
  if (body) renderBody(body);
}

function renderBiomedChatWorkspace(container: HTMLElement, dispatch?: PluginDispatch): void {
  container.innerHTML = `
    <div class="biomed-chat-workspace">
      <aside class="biomed-agent-rail">
        <div class="biomed-agent-brand">
          <div class="biomed-agent-mark">BE</div>
          <div>
            <div class="biomed-agent-title">Evidence Workbench</div>
            <div class="biomed-agent-subtitle">Research-only agent</div>
          </div>
        </div>
        <div class="biomed-rail-section">
          <div class="biomed-label">Start here</div>
          <button class="biomed-run-link" data-biomed-target-view="runs" data-biomed-chat-prompt="Run a biomedical evidence audit for this research question: "><span>Ask a question</span><code>search, answer, audit</code></button>
          <button class="biomed-run-link" data-biomed-artifact="review" data-biomed-chat-prompt="Open the latest audited biomedical run and summarize the evidence packet, audit result, reviewer state, and next actions."><span>Review evidence</span><code>packet, audit, review</code></button>
          <button class="biomed-run-link" data-biomed-artifact="pilot" data-biomed-chat-prompt="Create a Pilot Report for the latest completed audited run using available ROI and observability fields."><span>Build pilot report</span><code>handoff, ROI, policy</code></button>
        </div>
        <div class="biomed-rail-section">
          <div class="biomed-label">Queues</div>
          <button class="biomed-run-link" data-biomed-target-view="queue" data-biomed-chat-prompt="List unresolved biomedical review queue risks and the run IDs I should inspect first."><span>Check review queue</span><code>triage risks</code></button>
          <button class="biomed-run-link" data-biomed-target-view="library" data-biomed-chat-prompt="Summarize the current literature sets and explain which papers need review."><span>Manage papers</span><code>literature sets</code></button>
          <button class="biomed-run-link" data-biomed-chat-prompt="Summarize the latest biomedical harness result and list release blockers."><span>Check harness</span><code>eval gates</code></button>
        </div>
      </aside>
      <main class="biomed-artifact-workspace">
        <section class="biomed-artifact-hero">
          <div>
            <div class="biomed-label">Current workspace</div>
            <h2>Run-aware evidence review</h2>
            <p>Pick a task on the left, then use the agent on the right. The middle stays focused on artifacts: runs, packets, reviews, reports, and harness results.</p>
          </div>
          <span class="biomed-safety-chip">research only</span>
        </section>
        <section class="biomed-workflow-steps" aria-label="Evidence review workflow">
          <article>
            <strong>1. Audit</strong>
            <span>Search papers, answer with citations, and check support.</span>
          </article>
          <article>
            <strong>2. Review</strong>
            <span>Open packet, provenance, trace, and reviewer decisions.</span>
          </article>
          <article>
            <strong>3. Report</strong>
            <span>Export Pilot Report with ROI, policy, and observability.</span>
          </article>
        </section>
        <section id="biomed-latest-run-actions" class="biomed-latest-run-actions">
          <div class="biomed-muted">Loading latest run...</div>
        </section>
        <section class="biomed-artifact-grid">
          <button class="biomed-artifact-action" data-biomed-target-view="runs" data-biomed-chat-prompt="Show me the latest biomedical answer runs with run IDs, source, paper count, review status, and artifact links.">
            <strong>Runs</strong>
            <span>Find the run to inspect.</span>
          </button>
          <button class="biomed-artifact-action" data-biomed-artifact="packet" data-biomed-chat-prompt="Open the evidence packet and provenance links for the latest audited run.">
            <strong>Evidence Packet</strong>
            <span>Check what supports the answer.</span>
          </button>
          <button class="biomed-artifact-action" data-biomed-artifact="review" data-biomed-chat-prompt="List reviewer decisions and unresolved issues for the latest audited run.">
            <strong>Run Evidence Review</strong>
            <span>See reviewer state and blockers.</span>
          </button>
          <button class="biomed-artifact-action" data-biomed-artifact="trace" data-biomed-chat-prompt="Show cost, cache, latency, source calls, and trace status for the latest audited run.">
            <strong>Trace</strong>
            <span>Inspect cost and execution.</span>
          </button>
        </section>
        <section class="biomed-policy-strip">
          <strong>Evidence boundary</strong>
          <span>Biomedical support comes from retrieved papers, evidence spans, manifests, audits, logic audit, and evidence packets. Chat, memory, reviewer notes, and model output are context only.</span>
        </section>
      </main>
      <aside class="biomed-chat-main biomed-agent-cockpit">
        <div class="biomed-cockpit-head">
          <div>
            <div class="biomed-label">Agent cockpit</div>
            <strong>Ask, approve, inspect</strong>
          </div>
          <details class="biomed-session-details">
            <summary>Session</summary>
            <input id="biomed-chat-session" class="biomed-rail-input" value="dashboard:biomed" />
            <button id="biomed-chat-load" type="button">Load</button>
          </details>
        </div>
        <div id="biomed-chat-history" class="biomed-chat-history">
          <div class="biomed-empty-state">
            <div class="biomed-empty-title">No messages loaded.</div>
            <div class="biomed-empty-copy">Session history appears here after loading or sending a message.</div>
          </div>
        </div>
        <form id="biomed-chat-form" class="biomed-chat-composer">
          <textarea id="biomed-chat-input" rows="4" placeholder="Ask about a run, evidence packet, review queue, or pilot report..."></textarea>
          <button id="biomed-chat-send" class="biomed-primary-button" type="submit">Send</button>
        </form>
      </aside>
    </div>
  `;

  const sessionKey = (): string => (
    container.querySelector<HTMLInputElement>("#biomed-chat-session")?.value.trim()
    || "dashboard:biomed"
  );
  let latestRunId = "";
  const artifactUrl = (kind: string, runId: string): string => {
    const encoded = encodeURIComponent(runId);
    if (kind === "review") return `/api/biomed/answer-runs/${encoded}/evidence-review`;
    if (kind === "packet") return `/api/biomed/answer-runs/${encoded}/evidence-packet`;
    if (kind === "trace") return `/api/biomed/answer-runs/${encoded}/trace`;
    if (kind === "pilot") return `/api/biomed/export?run_id=${encoded}&report_type=pilot&format=markdown`;
    return `/api/biomed/answer-runs/${encoded}/provenance`;
  };
  const openLatestArtifact = (kind: string): void => {
    if (!latestRunId) {
      const target = container.querySelector<HTMLElement>("#biomed-latest-run-actions");
      if (target) target.innerHTML = '<div class="biomed-muted">No run is available yet. Start with Ask a question.</div>';
      return;
    }
    window.open(artifactUrl(kind, latestRunId), "_blank", "noopener,noreferrer");
  };
  const openView = (view: BiomedView): void => {
    dispatch?.setFilter("_view", view);
    dispatch?.activate();
    if (!dispatch) renderBiomedWorkbench(container, view);
  };
  const chatState = {
    events: [] as DashboardChatMessage[],
    latestSeq: 0,
    streamSeq: 0,
    streamedContent: "",
    streamAbort: null as AbortController | null,
    optimisticEvents: [] as DashboardChatMessage[],
    liveNotices: [] as BiomedChatLiveNotice[],
  };
  const renderAssistantMarkdown = (content: string): string => renderMarkdown(content || "");
  const renderChatEvent = (event: DashboardChatMessage | BiomedChatLiveNotice): string => {
    if ("role" in event && event.role === "assistant") {
      return `
        <div class="biomed-chat-message is-agent">
          <div class="biomed-chat-bubble">
            <div class="biomed-watch-meta">assistant · #${event.seq}</div>
            <div>${renderAssistantMarkdown(event.content || "")}</div>
          </div>
        </div>
      `;
    }
    if ("kind" in event && event.kind === "system") {
      return `
        <div class="biomed-chat-system">
          <span class="biomed-watch-meta">progress · #${event.seq}</span>
          <span>${escapeHtml(event.summary)}</span>
          ${event.detail ? `<details><summary>Technical details</summary><pre>${escapeHtml(event.detail)}</pre></details>` : ""}
        </div>
      `;
    }
    const message = event as DashboardChatMessage;
    return `
      <div class="biomed-chat-message is-user">
        <div class="biomed-chat-bubble">
          <div class="biomed-watch-meta">user · #${message.seq}</div>
          <div>${escapeHtml(message.content)}</div>
        </div>
      </div>
    `;
  };
  const renderHistory = (messages: DashboardChatMessage[]): string => (
    messages.map((message) => `
      <div class="biomed-chat-message ${message.role === "user" ? "is-user" : "is-agent"}">
        <div class="biomed-chat-bubble">
          <div class="biomed-watch-meta">${escapeHtml(message.role)} · #${message.seq}</div>
          <div>${message.role === "assistant" ? renderMarkdown(message.content || "") : escapeHtml(message.content || "")}</div>
        </div>
      </div>
    `).join("") || '<div class="biomed-muted">No messages in this session.</div>'
  );
  const syncHistory = async (): Promise<void> => {
    const target = container.querySelector<HTMLElement>("#biomed-chat-history");
    if (!target) return;
    try {
      const params = new URLSearchParams();
      params.set("session_key", sessionKey());
      params.set("page_size", "80");
      const data = await api<{ items: DashboardChatMessage[]; session_key?: string }>(`/api/dashboard/chat/history?${params.toString()}`);
      const history = data.items || [];
      chatState.optimisticEvents = chatState.optimisticEvents.filter((item) => (
        !history.some((row) => (
          row.role === item.role
          && row.content === item.content
          && (row.seq === item.seq || row.seq >= item.seq)
        ))
      ));
      chatState.events = [...history, ...chatState.optimisticEvents];
      chatState.latestSeq = Math.max(
        chatState.latestSeq,
        ...chatState.events.map((item) => item.seq).filter((seq) => Number.isFinite(seq)) as number[],
      );
      if (target.querySelector(".biomed-chat-message.is-agent.is-pending")) {
        return;
      }
      target.innerHTML = `${renderHistory(chatState.events)}${chatState.liveNotices.map(renderChatEvent).join("")}`;
      target.scrollTo({ top: target.scrollHeight });
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  };
  const appendLiveNotice = (notice: BiomedChatLiveNotice): void => {
    const target = container.querySelector<HTMLElement>("#biomed-chat-history");
    if (!target) return;
    chatState.liveNotices = [...chatState.liveNotices.filter((item) => item.seq !== notice.seq), notice].slice(-80);
    target.insertAdjacentHTML("beforeend", renderChatEvent(notice));
    target.scrollTo({ top: target.scrollHeight });
  };
  const presentLiveEvent = (event: string, data: DashboardChatSseMessage): BiomedChatLiveNotice => {
    const seq = typeof data.seq === "number" ? data.seq : Number(data.seq || chatState.latestSeq || 0);
    return {
      kind: "system",
      seq: Number.isFinite(seq) && seq > 0 ? seq : chatState.latestSeq,
      summary: biomedChatProgressSummary(event, data),
      detail: compactBiomedChatDetail(event, data),
    };
  };
  const applyLivePayload = (event: string, data: DashboardChatSseMessage): void => {
    const target = container.querySelector<HTMLElement>("#biomed-chat-history");
    if (!target) return;
    const seq = typeof data.seq === "number" ? data.seq : Number(data.seq || 0);
    if (Number.isFinite(seq) && seq > chatState.streamSeq) {
      chatState.streamSeq = seq;
    }
    if (event === "user_message_accepted") {
      appendLiveNotice(presentLiveEvent(event, data));
      return;
    }
    if (event === "turn_started") {
      appendLiveNotice(presentLiveEvent(event, data));
      return;
    }
    if (event === "assistant_delta") {
      const content = String(data.content_delta || data.thinking_delta || "");
      if (!content) return;
      chatState.streamedContent += content;
      const bubble = target.querySelector<HTMLElement>(".biomed-chat-message.is-agent.is-pending .biomed-chat-markdown");
      if (bubble?.parentElement) {
        bubble.innerHTML = renderAssistantMarkdown(chatState.streamedContent);
        target.scrollTo({ top: target.scrollHeight });
        return;
      }
      target.insertAdjacentHTML("beforeend", `
        <div class="biomed-chat-message is-agent is-pending">
          <div class="biomed-chat-bubble">
            <div class="biomed-watch-meta">assistant · #${seq || chatState.latestSeq}</div>
            <div class="biomed-chat-markdown">${renderAssistantMarkdown(chatState.streamedContent)}</div>
          </div>
        </div>
      `);
      target.scrollTo({ top: target.scrollHeight });
      return;
    }
    if (event === "assistant_message") {
      const content = String(data.content || "");
      const pending = target.querySelector<HTMLElement>(".biomed-chat-message.is-agent.is-pending");
      if (pending) {
        pending.outerHTML = renderChatEvent({ id: "", session_key: String(data.session_key || sessionKey()), seq: seq || chatState.latestSeq, role: "assistant", content, ts: new Date().toISOString() });
      } else {
        target.insertAdjacentHTML("beforeend", renderChatEvent({ id: "", session_key: String(data.session_key || sessionKey()), seq: seq || chatState.latestSeq, role: "assistant", content, ts: new Date().toISOString() }));
      }
      chatState.streamedContent = "";
      target.scrollTo({ top: target.scrollHeight });
      return;
    }
    if (event === "tool_started" || event === "tool_completed" || event === "step") {
      appendLiveNotice(presentLiveEvent(event, data));
      return;
    }
    if (event === "error") {
      target.insertAdjacentHTML("beforeend", `<div class="biomed-error">${escapeHtml(String(data.detail || data.message || "Error"))}</div>`);
      target.scrollTo({ top: target.scrollHeight });
    }
  };
  const startLiveStream = async (sinceSeq?: number): Promise<void> => {
    chatState.streamAbort?.abort();
    const controller = new AbortController();
    chatState.streamAbort = controller;
    try {
      const params = new URLSearchParams();
      params.set("session_key", sessionKey());
      if (typeof sinceSeq === "number" && sinceSeq > 0) {
        params.set("since_seq", String(sinceSeq));
      }
      const response = await fetch(`/api/dashboard/chat/stream?${params.toString()}`, {
        headers: { Accept: "text/event-stream" },
        signal: controller.signal,
      });
      if (!response.ok || !response.body) return;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        for (const chunk of chunks) {
          let event = "";
          const dataLines: string[] = [];
          for (const line of chunk.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!event || !dataLines.length) continue;
          if (event === "connected") {
            const payload = JSON.parse(dataLines.join("\n")) as DashboardChatSseMessage;
            const latest = Number(payload.latest_seq || payload.seq || 0);
            if (Number.isFinite(latest) && latest > chatState.streamSeq) {
              chatState.streamSeq = latest;
            }
            continue;
          }
          const payload = JSON.parse(dataLines.join("\n")) as DashboardChatSseMessage;
          applyLivePayload(event, payload);
        }
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      const target = container.querySelector<HTMLElement>("#biomed-chat-history");
      if (target) {
        target.insertAdjacentHTML("beforeend", `<div class="biomed-error">${escapeHtml(String(error))}</div>`);
      }
    }
  };
  const ensureLiveStream = (): void => {
    if (!chatState.streamAbort || chatState.streamAbort.signal.aborted) {
      void startLiveStream(chatState.streamSeq);
    }
  };
  const refreshHistoryAndStream = async (): Promise<void> => {
    await syncHistory();
    ensureLiveStream();
  };
  const loadHistory = async (): Promise<void> => {
    const target = container.querySelector<HTMLElement>("#biomed-chat-history");
    if (!target) return;
    chatState.streamSeq = 0;
    chatState.streamedContent = "";
    chatState.liveNotices = [];
    target.innerHTML = renderLoading("Loading chat history...");
    await refreshHistoryAndStream();
  };

  container.querySelector<HTMLButtonElement>("#biomed-chat-load")?.addEventListener("click", () => {
    void loadHistory();
  });
  container.querySelectorAll<HTMLButtonElement>("[data-biomed-chat-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = container.querySelector<HTMLTextAreaElement>("#biomed-chat-input");
      if (input) input.value = button.dataset.biomedChatPrompt || "";
    });
  });
  container.querySelectorAll<HTMLButtonElement>("[data-biomed-target-view]").forEach((button) => {
    button.addEventListener("click", () => openView((button.dataset.biomedTargetView || "chat") as BiomedView));
  });
  container.querySelectorAll<HTMLButtonElement>("[data-biomed-artifact]").forEach((button) => {
    button.addEventListener("click", () => openLatestArtifact(button.dataset.biomedArtifact || ""));
  });
  container.querySelector<HTMLFormElement>("#biomed-chat-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = container.querySelector<HTMLTextAreaElement>("#biomed-chat-input");
    const send = container.querySelector<HTMLButtonElement>("#biomed-chat-send");
    const content = input?.value.trim() || "";
    if (!content) return;
    if (send) send.disabled = true;
    const nextSeq = chatState.latestSeq + 1;
    const optimistic: DashboardChatMessage = {
      id: `local-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      session_key: sessionKey(),
      seq: nextSeq,
      role: "user",
      content,
      ts: new Date().toISOString(),
    };
    try {
      ensureLiveStream();
      chatState.optimisticEvents = [...chatState.optimisticEvents, optimistic];
      chatState.events = [...chatState.events, optimistic];
      chatState.latestSeq = nextSeq;
      const target = container.querySelector<HTMLElement>("#biomed-chat-history");
      if (target) {
        target.insertAdjacentHTML("beforeend", renderChatEvent(optimistic));
        target.scrollTo({ top: target.scrollHeight });
      }
      await api("/api/dashboard/chat/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_key: sessionKey(), content }),
      });
      if (input) input.value = "";
      window.setTimeout(() => void syncHistory(), 1400);
    } catch (error) {
      chatState.optimisticEvents = chatState.optimisticEvents.filter((item) => item.id !== optimistic.id);
      chatState.events = chatState.events.filter((item) => item.id !== optimistic.id);
      const target = container.querySelector<HTMLElement>("#biomed-chat-history");
      if (target) target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    } finally {
      if (send) send.disabled = false;
    }
  });
  const loadLatestRunActions = async (): Promise<void> => {
    const target = container.querySelector<HTMLElement>("#biomed-latest-run-actions");
    if (!target) return;
    try {
      const data = await api<{ items: AnswerRunListItem[] }>("/api/biomed/answer-runs?page_size=1");
      latestRunId = data.items[0]?.run_id || "";
      if (!latestRunId) {
        target.innerHTML = '<div class="biomed-muted">No runs yet. Start with Ask a question.</div>';
        return;
      }
      target.innerHTML = `
        <div>
          <div class="biomed-label">Latest run</div>
          <strong>${escapeHtml(data.items[0]?.question || latestRunId)}</strong>
          <code>${escapeHtml(latestRunId)}</code>
        </div>
        <div class="biomed-latest-run-buttons">
          <button data-biomed-artifact-open="review">Review</button>
          <button data-biomed-artifact-open="packet">Packet</button>
          <button data-biomed-artifact-open="trace">Trace</button>
          <button data-biomed-artifact-open="pilot">Pilot Report</button>
        </div>
      `;
      target.querySelectorAll<HTMLButtonElement>("[data-biomed-artifact-open]").forEach((button) => {
        button.addEventListener("click", () => openLatestArtifact(button.dataset.biomedArtifactOpen || ""));
      });
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  };
  void loadLatestRunActions();
  void loadHistory();
}

function renderLibrary(container: HTMLElement): void {
  container.innerHTML = `
    <div class="biomed-advanced-workspace">
      <div class="biomed-advanced-switcher">
        <button class="is-active" data-biomed-library="projects">Projects</button>
        <button data-biomed-library="watch">Watch</button>
        <button data-biomed-library="evidence">Evidence</button>
        <button data-biomed-library="fulltext">Full Text</button>
        <button data-biomed-library="graph">Graph</button>
      </div>
      <div id="biomed-library-body"></div>
    </div>
  `;
  const body = container.querySelector<HTMLElement>("#biomed-library-body");
  const renderMode = (mode: string): void => {
    container.querySelectorAll<HTMLButtonElement>("[data-biomed-library]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.biomedLibrary === mode);
    });
    if (!body) return;
    if (mode === "watch") {
      renderWatch(body);
    } else if (mode === "evidence") {
      renderEvidenceBrowser(body);
    } else if (mode === "fulltext") {
      renderFullTextWorkspace(body);
    } else if (mode === "graph") {
      renderGraph(body);
    } else {
      renderProjects(body);
    }
  };
  container.querySelectorAll<HTMLButtonElement>("[data-biomed-library]").forEach((button) => {
    button.addEventListener("click", () => renderMode(button.dataset.biomedLibrary || "projects"));
  });
  renderMode("projects");
}

function renderFullTextWorkspace(container: HTMLElement): void {
  container.innerHTML = `
    <div class="biomed-section">
      <div class="biomed-title">Full-Text And PDF Ingestion</div>
      <div class="biomed-subtitle">Parser output is stored as sections and locators. It becomes evidence only after extraction and downstream audit/review.</div>
      <div class="biomed-form">
        <div class="biomed-row">
          <input id="biomed-fulltext-paper-id" placeholder="paper id" />
          <select id="biomed-fulltext-source"><option value="mock">mock</option><option value="pubmed">pubmed</option></select>
          <select id="biomed-fulltext-content-type"><option value="text/plain">text/plain</option><option value="application/pdf">application/pdf</option></select>
        </div>
        <input id="biomed-fulltext-filename" placeholder="source filename" />
        <textarea id="biomed-fulltext-content" rows="9" placeholder="Paste deterministic fixture text or extracted PDF text here...">## Results
Microglial activation was associated with Alzheimer's disease progression in a human cohort. This cohort study requires validation.</textarea>
        <div class="biomed-row">
          <button id="biomed-fulltext-ingest">Ingest</button>
          <button id="biomed-fulltext-load">Load Stored</button>
          <button id="biomed-fulltext-extract">Extract Evidence</button>
        </div>
      </div>
      <div id="biomed-fulltext-result" class="biomed-result"></div>
    </div>
  `;
  const paperId = (): string => container.querySelector<HTMLInputElement>("#biomed-fulltext-paper-id")?.value.trim() || "";
  const source = (): string => container.querySelector<HTMLSelectElement>("#biomed-fulltext-source")?.value || "mock";
  const resultNode = (): HTMLElement | null => container.querySelector<HTMLElement>("#biomed-fulltext-result");
  container.querySelector<HTMLButtonElement>("#biomed-fulltext-ingest")?.addEventListener("click", async () => {
    const target = resultNode();
    if (!target || !paperId()) return;
    target.innerHTML = renderLoading("Ingesting full text...");
    try {
      const result = await api<FullTextIngestionResult>(`/api/biomed/papers/${encodeURIComponent(paperId())}/full-text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paper_id: paperId(),
          source: source(),
          content_type: container.querySelector<HTMLSelectElement>("#biomed-fulltext-content-type")?.value || "text/plain",
          source_filename: container.querySelector<HTMLInputElement>("#biomed-fulltext-filename")?.value || null,
          content: container.querySelector<HTMLTextAreaElement>("#biomed-fulltext-content")?.value || "",
          overwrite: true,
        }),
      });
      target.innerHTML = renderFullTextResult(result);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-fulltext-load")?.addEventListener("click", async () => {
    const target = resultNode();
    if (!target || !paperId()) return;
    target.innerHTML = renderLoading("Loading full text...");
    try {
      const result = await api<FullTextIngestionResult>(`/api/biomed/papers/${encodeURIComponent(paperId())}/full-text?source=${encodeURIComponent(source())}`);
      target.innerHTML = renderFullTextResult(result);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-fulltext-extract")?.addEventListener("click", async () => {
    const target = resultNode();
    if (!target || !paperId()) return;
    target.innerHTML = renderLoading("Extracting evidence from stored full text...");
    try {
      const result = await api<{ evidence?: EvidenceRow[]; reason?: string | null }>(`/api/biomed/papers/${encodeURIComponent(paperId())}/full-text/evidence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: source(),
          research_question: container.querySelector<HTMLTextAreaElement>("#biomed-fulltext-content")?.value.slice(0, 240) || null,
        }),
      });
      target.innerHTML = renderFullTextEvidenceResult(result);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
}

function renderBiomedWorkbench(root: HTMLElement, view: BiomedView, dispatch?: PluginDispatch): void {
  root.innerHTML = "";
  if (view === "chat") {
    renderBiomedChatWorkspace(root, dispatch);
    return;
  }
  if (view === "runs") {
    renderAskWorkspace(root);
    return;
  }
  if (view === "queue") {
    renderBiomedWorkbenchPage(root, "Review Queue", "Triage project-scoped graph, audit, verifier, and reviewer risks.", renderProjects);
  } else if (view === "library") {
    renderBiomedWorkbenchPage(root, "Library", "Manage project context, research watch topics, evidence records, and graph lookup.", renderLibrary);
  } else if (view === "settings") {
    renderBiomedWorkbenchPage(root, "Responsible AI boundary", "Review the research-only safety contract enforced before tool execution.", renderResponsible);
  } else {
    renderBiomedChatWorkspace(root, dispatch);
  }
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars -- legacy renderer kept for fallback/debug workbench routes.
function renderAdvanced(container: HTMLElement): void {
  container.innerHTML = `
    <div class="biomed-advanced-workspace">
      <div class="biomed-advanced-switcher">
        <button class="is-active" data-biomed-advanced="graph">Raw Graph</button>
        <button data-biomed-advanced="evidence">Evidence</button>
        <button data-biomed-advanced="audit">Audit</button>
        <button data-biomed-advanced="trace">Trace</button>
      </div>
      <div id="biomed-advanced-panel"></div>
    </div>
  `;
  const panel = container.querySelector<HTMLElement>("#biomed-advanced-panel");
  const renderMode = (mode: string): void => {
    if (!panel) return;
    panel.replaceChildren();
    if (mode === "evidence") renderEvidenceBrowser(panel);
    else if (mode === "audit") renderAudit(panel);
    else if (mode === "trace") renderTrace(panel);
    else renderGraph(panel);
  };
  container.querySelectorAll<HTMLButtonElement>("[data-biomed-advanced]").forEach((button) => {
    button.addEventListener("click", () => {
      container.querySelectorAll<HTMLButtonElement>("[data-biomed-advanced]").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      renderMode(button.dataset.biomedAdvanced || "graph");
    });
  });
  renderMode("graph");
}

function renderEvidenceBrowser(container: HTMLElement): void {
  container.innerHTML = `
    <div class="biomed-evidence-browser">
      <section class="biomed-evidence-toolbar">
        <label>
          <span>Search</span>
          <input id="biomed-evidence-q" type="text" value="microglia" placeholder="claim, paper, entity, finding" />
        </label>
        <label>
          <span>Direction</span>
          <select id="biomed-evidence-direction">
            <option value="">all</option>
            <option value="supports">supports</option>
            <option value="contradicts">contradicts</option>
            <option value="inconclusive">inconclusive</option>
            <option value="background">background</option>
          </select>
        </label>
        <label>
          <span>Entity</span>
          <input id="biomed-evidence-entity" type="text" placeholder="Microglia" />
        </label>
        <button id="biomed-evidence-load-btn" type="button">Load Evidence</button>
      </section>
      <section id="biomed-evidence-browser-summary" class="biomed-evidence-summary"></section>
      <section id="biomed-evidence-browser-results" class="biomed-evidence-grid"></section>
    </div>
  `;
  container.querySelector<HTMLButtonElement>("#biomed-evidence-load-btn")?.addEventListener("click", () => {
    void loadEvidenceBrowser(container);
  });
  container.querySelectorAll<HTMLInputElement | HTMLSelectElement>("#biomed-evidence-q, #biomed-evidence-direction, #biomed-evidence-entity").forEach((node) => {
    node.addEventListener("keydown", (event) => {
      if (event instanceof KeyboardEvent && event.key === "Enter") void loadEvidenceBrowser(container);
    });
    node.addEventListener("change", () => {
      if (node instanceof HTMLSelectElement) void loadEvidenceBrowser(container);
    });
  });
  void loadEvidenceBrowser(container);
}

async function loadEvidenceBrowser(container: HTMLElement): Promise<void> {
  const summary = container.querySelector<HTMLElement>("#biomed-evidence-browser-summary");
  const results = container.querySelector<HTMLElement>("#biomed-evidence-browser-results");
  if (!summary || !results) return;
  const params = new URLSearchParams();
  params.set("page", "1");
  params.set("page_size", "25");
  const query = container.querySelector<HTMLInputElement>("#biomed-evidence-q")?.value.trim() || "";
  const direction = container.querySelector<HTMLSelectElement>("#biomed-evidence-direction")?.value || "";
  const entity = container.querySelector<HTMLInputElement>("#biomed-evidence-entity")?.value.trim() || "";
  if (query) params.set("q", query);
  if (direction) params.set("direction", direction);
  if (entity) params.set("entity", entity);
  summary.innerHTML = renderLoading("Loading evidence...");
  results.innerHTML = "";
  try {
    const data = await api<{ items: EvidenceRow[]; total: number }>(`/api/biomed/evidence?${params.toString()}`);
    const items = data.items || [];
    const retrievalIds = new Set(items.map((item) => item.retrieval_id).filter(Boolean));
    const directions = items.reduce<Record<string, number>>((acc, item) => {
      const key = item.evidence_direction || "unknown";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
    summary.innerHTML = `
      <div class="biomed-mini-grid">
        <div><span>Total Matches</span><strong>${data.total || 0}</strong></div>
        <div><span>Shown</span><strong>${items.length}</strong></div>
        <div><span>Retrievals</span><strong>${retrievalIds.size}</strong></div>
        <div><span>Directions</span><strong>${escapeHtml(Object.entries(directions).map(([key, count]) => `${key} ${count}`).join(" · ") || "-")}</strong></div>
      </div>
    `;
    results.innerHTML = items.map(renderEvidenceBrowserCard).join("") || `
      <div class="biomed-empty-state">
        <div class="biomed-empty-title">No evidence matched.</div>
        <div class="biomed-empty-copy">Try a broader query or run a workflow to populate the evidence store.</div>
      </div>
    `;
  } catch (error) {
    summary.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

function renderEvidenceBrowserCard(item: EvidenceRow): string {
  const entities = (item.entities || []).slice(0, 4).map((entity) => `${entity.name} (${entity.entity_type})`);
  return `
    <article class="biomed-evidence-card">
      <div class="biomed-evidence-head">
        ${pill(item.evidence_direction)}
        ${pill(item.confidence)}
        ${item.retrieval_intent ? pill(item.retrieval_intent) : ""}
        ${item.extraction_mode ? pill(item.extraction_mode) : ""}
        ${item.source_scope && item.source_scope !== "abstract" ? pill(item.source_scope) : ""}
      </div>
      <div class="biomed-evidence-card-title">${escapeHtml(item.claim)}</div>
      <div class="biomed-evidence-card-finding">${escapeHtml(item.finding)}</div>
      <div class="biomed-evidence-card-meta">
        <code>${escapeHtml(item.paper_id)}</code>
        ${item.retrieval_id ? `<code>${escapeHtml(item.retrieval_id)}</code>` : ""}
      </div>
      ${renderEvidenceLocator(item)}
      <div class="biomed-evidence-card-detail">
        <div>
          <span>Entities</span>
          ${renderList(entities)}
        </div>
        <div>
          <span>Methods</span>
          ${renderList((item.methods || []).slice(0, 4))}
        </div>
      </div>
      ${item.limitations?.length ? `
        <div class="biomed-evidence-card-limit">
          <span>Limitations</span>
          ${renderList(item.limitations.slice(0, 3))}
        </div>
      ` : ""}
    </article>
  `;
}

function renderFullTextResult(result: FullTextIngestionResult): string {
  if (!result.ok || !result.document) {
    return `
      <div class="biomed-error">
        ${escapeHtml((result.errors || []).join("; ") || "Full-text operation failed.")}
      </div>
    `;
  }
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Document</span><code>${escapeHtml(result.document.document_id)}</code></div>
        <div><span>Paper</span><code>${escapeHtml(result.document.paper_id)}</code></div>
        <div><span>Type</span><strong>${escapeHtml(result.document.content_type)}</strong></div>
        <div><span>Sections</span><strong>${result.sections.length}</strong></div>
        <div><span>Bytes</span><strong>${result.document.byte_size}</strong></div>
        <div><span>Parser</span><strong>${escapeHtml(result.document.parser)}</strong></div>
      </div>
      <div class="biomed-watch-meta">
        source hash ${escapeHtml(compactId(result.document.source_hash))} · updated ${escapeHtml(result.document.updated_at)}
      </div>
      ${result.warnings.length ? `<div class="biomed-label">Warnings</div>${renderList(result.warnings)}` : ""}
      <div class="biomed-label">Sections</div>
      <div class="biomed-audit-table">
        ${result.sections.map((section) => `
          <div class="biomed-audit-row">
            <div class="biomed-audit-row-head">
              ${pill(section.label)}
              <code>${escapeHtml(section.section_id)}</code>
              <span>pages ${escapeHtml(String(section.page_start ?? "-"))}-${escapeHtml(String(section.page_end ?? "-"))}</span>
            </div>
            <div class="biomed-watch-meta">hash ${escapeHtml(compactId(section.source_hash))}</div>
            <div class="biomed-evidence-finding">${escapeHtml(section.text.slice(0, 420))}${section.text.length > 420 ? "..." : ""}</div>
          </div>
        `).join("") || '<div class="biomed-muted">No sections stored.</div>'}
      </div>
    </div>
  `;
}

function renderFullTextEvidenceResult(result: { evidence?: EvidenceRow[]; reason?: string | null }): string {
  const evidence = result.evidence || [];
  return `
    <div class="biomed-section">
      <div class="biomed-label">Extracted Full-Text Evidence</div>
      ${result.reason ? `<div class="biomed-muted">${escapeHtml(result.reason)}</div>` : ""}
      ${evidence.map(renderEvidenceItem).join("") || '<div class="biomed-muted">No full-text evidence extracted.</div>'}
    </div>
  `;
}

function bindInspectorResize(container: HTMLElement): void {
  const workspace = container.querySelector<HTMLElement>(".biomed-workspace");
  const handle = container.querySelector<HTMLButtonElement>(".biomed-inspector-resizer");
  if (!workspace || !handle) return;
  const stored = window.localStorage.getItem("biomed.inspector.width");
  if (stored) workspace.style.setProperty("--biomed-inspector-width", stored);
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    const onMove = (moveEvent: PointerEvent) => {
      const rect = workspace.getBoundingClientRect();
      const width = Math.max(300, Math.min(760, rect.right - moveEvent.clientX));
      const value = `${Math.round(width)}px`;
      workspace.style.setProperty("--biomed-inspector-width", value);
      window.localStorage.setItem("biomed.inspector.width", value);
    };
    const onUp = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onUp);
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onUp);
  });
}

function renderAskWorkspace(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-workspace">
      <main class="biomed-agent-main">
        <details class="biomed-composer" open>
          <summary class="biomed-composer-head">
            <div>
              <div class="biomed-label">Task</div>
              <div class="biomed-composer-title">Evidence-backed biomedical research answer</div>
            </div>
            <div class="biomed-safety-chip">research-only</div>
          </summary>
          <div class="biomed-composer-body">
            <div class="biomed-run-setup-bar">
              <label>
                <span>Preset</span>
                <select id="biomed-template-select" class="biomed-rail-select">
                  <option value="">loading templates...</option>
                </select>
              </label>
              <button id="biomed-template-apply-btn" type="button">Apply</button>
              <button id="biomed-template-save-btn" type="button">Save</button>
              <input id="biomed-template-name" class="biomed-rail-input" placeholder="custom template name" />
              <label class="biomed-live-toggle">
                <input id="biomed-allow-live-pubmed" type="checkbox" />
                <span>Live PubMed</span>
              </label>
            </div>
            <div id="biomed-template-summary" class="biomed-template-summary"></div>
            <textarea id="biomed-question" rows="5">What recent evidence links microglial activation to Alzheimer's disease progression?</textarea>
            <div class="biomed-command-row">
              <label>
                <span>Project</span>
                <select id="biomed-project-select">
                  <option value="">no project</option>
                </select>
              </label>
              <label>
                <span>Source</span>
                <select id="biomed-source">
                  <option value="mock">mock</option>
                  <option value="pubmed">pubmed</option>
                </select>
              </label>
              <label>
                <span>Papers</span>
                <input id="biomed-max-papers" type="number" min="1" max="20" value="5" />
              </label>
            </div>
            <details class="biomed-advanced-drawer">
              <summary>Advanced workflow controls</summary>
              <div class="biomed-advanced-grid">
                <div>
                  <div class="biomed-label">Retrieval</div>
                  <div class="biomed-toggle-grid">
                    <label class="biomed-check"><input id="biomed-include-rejected" type="checkbox" /> Include rejected</label>
                    <label class="biomed-check"><input id="biomed-execute-support-refute" type="checkbox" /> Support/refute retrieval</label>
                  </div>
                </div>
                <div>
                  <div class="biomed-label">LLM + Audit</div>
                  <div class="biomed-toggle-grid">
                    <label class="biomed-check"><input id="biomed-use-planner" type="checkbox" /> Planner</label>
                    <label class="biomed-check"><input id="biomed-use-extractor" type="checkbox" /> Extractor</label>
                    <label class="biomed-check"><input id="biomed-use-synthesis" type="checkbox" /> Synthesis</label>
                    <label class="biomed-check"><input id="biomed-use-verifier" type="checkbox" /> Verifier</label>
                    <label class="biomed-check"><input id="biomed-use-revision" type="checkbox" /> Revision</label>
                    <label class="biomed-check"><input id="biomed-use-claim-logic" type="checkbox" /> Claim logic</label>
                    <label class="biomed-check"><input id="biomed-export-logic-facts" type="checkbox" /> Logic facts</label>
                  </div>
                </div>
              </div>
            </details>
            <div class="biomed-primary-actions">
              <button id="biomed-template-run-btn" class="biomed-primary-button">Run Workflow</button>
              <button id="biomed-audited-btn">Direct Audit Run</button>
              <button id="biomed-ask-btn">Draft Only</button>
            </div>
            <details class="biomed-recent-drawer">
              <summary>Recent runs</summary>
              <div id="biomed-recent-runs" class="biomed-recent-runs"></div>
            </details>
          </div>
        </details>
        <div id="biomed-ask-result" class="biomed-agent-output">
          <div class="biomed-empty-state">
            <div class="biomed-empty-title">Ask a biomedical evidence question.</div>
            <div class="biomed-empty-copy">The first result focuses on the answer, trust signals, important evidence, and review actions. Deeper artifacts live under Advanced.</div>
          </div>
        </div>
      </main>
      <aside id="biomed-inspector" class="biomed-agent-inspector">
        <button class="biomed-inspector-resizer" type="button" aria-label="Resize inspector"></button>
        <div class="biomed-inspector-empty">
          <div class="biomed-label">Inspector</div>
          <div class="biomed-inspector-title">No active run</div>
          <div class="biomed-muted">Run a workflow or open a recent run to inspect trace, evidence, audit, logic facts, argument graph, math signals, and provenance.</div>
        </div>
      </aside>
    </div>
  `;

  bindInspectorResize(container);
  container.querySelector<HTMLSelectElement>("#biomed-template-select")?.addEventListener("change", () => {
    const template = selectedWorkflowTemplate(container);
    const summary = container.querySelector<HTMLElement>("#biomed-template-summary");
    if (summary) summary.textContent = renderWorkflowTemplateSummary(template);
    if (template) applyWorkflowTemplate(container, template);
  });
  container.querySelector<HTMLButtonElement>("#biomed-template-apply-btn")?.addEventListener("click", () => {
    const template = selectedWorkflowTemplate(container);
    if (template) applyWorkflowTemplate(container, template);
  });
  container.querySelector<HTMLButtonElement>("#biomed-template-save-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    const name = container.querySelector<HTMLInputElement>("#biomed-template-name")?.value.trim() || "";
    if (!resultNode || !name) {
      if (resultNode) resultNode.innerHTML = '<div class="biomed-error">Template name is required.</div>';
      return;
    }
    resultNode.innerHTML = renderLoading("Saving workflow template...");
    try {
      const template = await api<SavedToolChainTemplate>("/api/biomed/workflow/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentWorkflowTemplatePayload(container)),
      });
      await loadWorkflowTemplates(container);
      const select = container.querySelector<HTMLSelectElement>("#biomed-template-select");
      if (select) select.value = template.template_id;
      resultNode.innerHTML = `<div class="biomed-empty-state"><div class="biomed-empty-title">Saved template</div><div class="biomed-empty-copy">${escapeHtml(template.name)}</div></div>`;
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-template-run-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    const button = container.querySelector<HTMLButtonElement>("#biomed-template-run-btn");
    const template = selectedWorkflowTemplate(container);
    if (!resultNode || !template) return;
    resultNode.innerHTML = renderLoading("Running workflow template...");
    if (button) button.disabled = true;
    try {
      const question = container.querySelector<HTMLTextAreaElement>("#biomed-question")?.value || "";
      const projectId = container.querySelector<HTMLSelectElement>("#biomed-project-select")?.value || "";
      const source = container.querySelector<HTMLSelectElement>("#biomed-source")?.value || template.source;
      const maxPapers = Number(container.querySelector<HTMLInputElement>("#biomed-max-papers")?.value || template.max_papers);
      const allowLivePubmed = Boolean(container.querySelector<HTMLInputElement>("#biomed-allow-live-pubmed")?.checked);
      const envelope = await api<ReleaseToolEnvelope<SavedToolChainTemplateRunResult>>(
        `/api/biomed/workflow/templates/${encodeURIComponent(template.template_id)}/run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question,
            project_id: projectId || null,
            source_override: source !== template.source ? source : null,
            max_papers_override: maxPapers !== template.max_papers ? maxPapers : null,
            allow_live_pubmed: allowLivePubmed,
          }),
        },
      );
      if (!envelope.ok) {
        resultNode.innerHTML = renderReleaseError(envelope);
        return;
      }
      hydrateWorkspaceRun(container, {
        answer: envelope.result.audited_answer.answer_result,
        audited: envelope.result.audited_answer,
        provenance: envelope.result.provenance || null,
        raw: envelope,
      });
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-audited-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    const button = container.querySelector<HTMLButtonElement>("#biomed-audited-btn");
    if (!resultNode) return;
    resultNode.innerHTML = renderLoading("Running audited answer chain...");
    if (button) button.disabled = true;
    try {
      const result = await api<AuditedAnswerResult>("/api/biomed/answer/audited", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(workspaceAnswerPayload(container, true)),
      });
      hydrateWorkspaceRun(container, {
        answer: result.answer_result,
        audited: result,
        raw: result,
      });
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-ask-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    const button = container.querySelector<HTMLButtonElement>("#biomed-ask-btn");
    if (!resultNode) return;
    resultNode.innerHTML = renderLoading("Drafting citation-backed answer...");
    if (button) button.disabled = true;
    try {
      const result = await api<AnswerResult>("/api/biomed/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(workspaceAnswerPayload(container, false)),
      });
      hydrateWorkspaceRun(container, {
        answer: result,
        raw: result,
      });
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  });
  void loadProjectOptions(container);
  void loadWorkflowTemplates(container);
  void loadRecentRuns(container);
}

function workspaceAnswerPayload(container: HTMLElement, audited: boolean): Record<string, unknown> {
  const source = container.querySelector<HTMLSelectElement>("#biomed-source")?.value || "mock";
  const usePlanner = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-planner")?.checked);
  const useAssistedPubmedAudit = audited && source === "pubmed" && usePlanner;
  return {
    question: container.querySelector<HTMLTextAreaElement>("#biomed-question")?.value || "",
    project_id: container.querySelector<HTMLSelectElement>("#biomed-project-select")?.value || null,
    source,
    max_papers: Number(container.querySelector<HTMLInputElement>("#biomed-max-papers")?.value || 5),
    include_rejected_papers: Boolean(container.querySelector<HTMLInputElement>("#biomed-include-rejected")?.checked),
    use_llm_planner: usePlanner,
    execute_support_refute: Boolean(container.querySelector<HTMLInputElement>("#biomed-execute-support-refute")?.checked),
    use_llm_extractor: useAssistedPubmedAudit || Boolean(container.querySelector<HTMLInputElement>("#biomed-use-extractor")?.checked),
    use_llm_synthesis: useAssistedPubmedAudit || Boolean(container.querySelector<HTMLInputElement>("#biomed-use-synthesis")?.checked),
    use_llm_verifier: audited && Boolean(container.querySelector<HTMLInputElement>("#biomed-use-verifier")?.checked),
    use_llm_revision: useAssistedPubmedAudit || (audited && Boolean(container.querySelector<HTMLInputElement>("#biomed-use-revision")?.checked)),
    use_llm_claim_logic: useAssistedPubmedAudit || (audited && Boolean(container.querySelector<HTMLInputElement>("#biomed-use-claim-logic")?.checked)),
    export_logic_facts: audited && Boolean(container.querySelector<HTMLInputElement>("#biomed-export-logic-facts")?.checked),
  };
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars -- legacy renderer kept for fallback/debug workbench routes.
function renderReview(container: HTMLElement): void {
  container.innerHTML = `
    <div class="biomed-review-workspace">
      <aside class="biomed-review-rail">
        <div>
          <div class="biomed-label">Evidence Review</div>
          <h2>Run review</h2>
          <p>Open a recent run, inspect claim cards, and jump to trace, provenance, or redacted graph export.</p>
        </div>
        <label class="biomed-field">
          <span>Run ID</span>
          <input id="biomed-review-run-id" placeholder="answer run id" />
        </label>
        <label class="biomed-field">
          <span>Claim Filter</span>
          <select id="biomed-review-filter">
            <option value="needs_review">needs review</option>
            <option value="all">all claims</option>
            <option value="mixed">mixed</option>
            <option value="contradicted">contradicted</option>
            <option value="unsupported">unsupported/qualified</option>
            <option value="supported">supported</option>
          </select>
        </label>
        <div class="biomed-review-rail-actions">
          <button id="biomed-review-load-btn">Load Review</button>
          <button id="biomed-review-snapshot-btn">Snapshot</button>
        </div>
        <div class="biomed-label">Recent Runs</div>
        <div id="biomed-review-recent-runs" class="biomed-review-run-list"></div>
      </aside>
      <main id="biomed-review-result" class="biomed-review-main">
        <div class="biomed-empty-state">
          <div class="biomed-label">No run selected</div>
          <h2>Select a recent run</h2>
          <p>The review loads snapshot status, graph validation, claim cards, evidence methods, limitations, and audit action.</p>
        </div>
      </main>
      <aside id="biomed-review-inspector" class="biomed-review-inspector">
        ${renderReviewInspectorEmpty()}
      </aside>
    </div>
  `;
  let currentReview: RunEvidenceReview | null = null;
  let currentTrace: TracePayload | null = null;

  const currentFilter = (): string => (
    container.querySelector<HTMLSelectElement>("#biomed-review-filter")?.value || "all"
  );

  const attachReviewActions = (): void => {
    container.querySelectorAll<HTMLButtonElement>("[data-review-related]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!currentReview) return;
        const target = container.querySelector<HTMLElement>("#biomed-review-inspector");
        if (!target) return;
        const kind = button.dataset.reviewRelated || "";
        target.innerHTML = renderLoading(`Loading ${kind}...`);
        try {
          if (kind === "graph") {
            const graph = await api<BiomedEvidenceGraphV1>(`/api/biomed/answer-runs/${encodeURIComponent(currentReview.run_id)}/evidence-graph?validate=true`);
            target.innerHTML = `<div class="biomed-label">Evidence Graph</div>${renderBiomedEvidenceGraph(graph)}`;
          } else if (kind === "trace") {
            const trace = await api<TracePayload>(`/api/biomed/answer-runs/${encodeURIComponent(currentReview.run_id)}/trace`);
            target.innerHTML = `<div class="biomed-label">Trace</div>${renderTraceResult(trace)}`;
          } else if (kind === "provenance") {
            const envelope = await api<ReleaseToolEnvelope<ProvenanceGraphResult>>(`/api/biomed/answer-runs/${encodeURIComponent(currentReview.run_id)}/provenance`);
            target.innerHTML = `<div class="biomed-label">Provenance</div>${renderProvenanceResult(envelope)}`;
          } else if (kind === "packet") {
            const packet = await api<Record<string, unknown>>(`/api/biomed/answer-runs/${encodeURIComponent(currentReview.run_id)}/evidence-review/packet`);
            target.innerHTML = `
              <div class="biomed-label">Review Packet</div>
              <pre class="biomed-json biomed-json-tall">${escapeHtml(JSON.stringify(packet, null, 2))}</pre>
            `;
          } else {
            const graph = await api<BiomedEvidenceGraphV1>(`/api/biomed/graph/v1/export/json?run_id=${encodeURIComponent(currentReview.run_id)}&validate=true`);
            target.innerHTML = `
              <div class="biomed-label">Evidence Graph JSON</div>
              <pre class="biomed-json biomed-json-tall">${escapeHtml(JSON.stringify(graph, null, 2))}</pre>
            `;
          }
        } catch (error) {
          target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
        }
      });
    });
    container.querySelectorAll<HTMLButtonElement>("[data-review-inspect-claim]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!currentReview) return;
        const target = container.querySelector<HTMLElement>("#biomed-review-inspector");
        const claimNodeId = button.dataset.reviewInspectClaim || "";
        const claim = currentReview.claims.find((item) => item.claim_node_id === claimNodeId);
        if (!target || !claim) return;
        target.innerHTML = `
          <div class="biomed-label">Claim Inspector</div>
          ${renderBiomedEvidenceCard(claim.evidence_card)}
        `;
      });
    });
    container.querySelectorAll<HTMLButtonElement>("[data-review-json-claim]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!currentReview) return;
        const target = container.querySelector<HTMLElement>("#biomed-review-inspector");
        const claimNodeId = button.dataset.reviewJsonClaim || "";
        const claim = currentReview.claims.find((item) => item.claim_node_id === claimNodeId);
        if (!target || !claim) return;
        target.innerHTML = `
          <div class="biomed-label">Claim JSON</div>
          <pre class="biomed-json biomed-json-tall">${escapeHtml(JSON.stringify(claim, null, 2))}</pre>
        `;
      });
    });
    container.querySelectorAll<HTMLButtonElement>("[data-review-decision]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!currentReview) return;
        const claimNodeId = button.dataset.reviewDecisionClaim || "";
        const decision = button.dataset.reviewDecision as RunReviewDecisionValue | undefined;
        const claim = currentReview.claims.find((item) => item.claim_node_id === claimNodeId);
        const target = container.querySelector<HTMLElement>("#biomed-review-inspector");
        if (!claim || !decision || !target) return;
        const card = button.closest<HTMLElement>("[data-review-claim-card]");
        const note = card?.querySelector<HTMLTextAreaElement>("[data-review-note]")?.value.trim() || "";
        target.innerHTML = renderLoading("Recording review decision...");
        try {
          const saved = await api<RunReviewDecision>(`/api/biomed/answer-runs/${encodeURIComponent(currentReview.run_id)}/evidence-review/decisions`, {
            method: "POST",
            body: JSON.stringify({
              claim_id: claim.claim_id,
              claim_node_id: claim.claim_node_id,
              decision,
              reviewer_note: note || null,
              decision_source: "dashboard",
            }),
          });
          await loadReview(currentReview.run_id);
          const refreshedInspector = container.querySelector<HTMLElement>("#biomed-review-inspector");
          if (refreshedInspector) {
            refreshedInspector.innerHTML = `
              <div class="biomed-label">Review Decision</div>
              <h3>${escapeHtml(saved.decision)}</h3>
              <p>${escapeHtml(saved.claim_id)}</p>
              <pre class="biomed-json">${escapeHtml(JSON.stringify(saved, null, 2))}</pre>
            `;
          }
        } catch (error) {
          target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
        }
      });
    });
  };

  const paintReview = (review: RunEvidenceReview, trace: TracePayload | null): void => {
    currentReview = review;
    currentTrace = trace;
    const target = container.querySelector<HTMLElement>("#biomed-review-result");
    if (!target) return;
    target.innerHTML = renderReviewMainPanel(review, trace, currentFilter());
    const inspector = container.querySelector<HTMLElement>("#biomed-review-inspector");
    if (inspector) inspector.innerHTML = renderReviewInspectorEmpty();
    attachReviewActions();
  };

  const loadReview = async (runId: string): Promise<void> => {
    const target = container.querySelector<HTMLElement>("#biomed-review-result");
    const inspector = container.querySelector<HTMLElement>("#biomed-review-inspector");
    if (!target || !runId) return;
    if (inspector) inspector.innerHTML = renderReviewInspectorEmpty();
    target.innerHTML = renderLoading("Loading evidence review...");
    try {
      let review = await api<RunEvidenceReview>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/evidence-review`);
      if (review.snapshot.status === "missing") {
        target.innerHTML = renderLoading("Creating evidence graph snapshot...");
        await api(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/evidence-review/snapshot`, { method: "POST" });
        review = await api<RunEvidenceReview>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/evidence-review`);
      }
      const trace = await api<TracePayload>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/trace`).catch(() => null);
      paintReview(review, trace);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  };

  container.querySelector<HTMLButtonElement>("#biomed-review-load-btn")?.addEventListener("click", async () => {
    const runId = container.querySelector<HTMLInputElement>("#biomed-review-run-id")?.value.trim() || "";
    await loadReview(runId);
  });
  container.querySelector<HTMLButtonElement>("#biomed-review-snapshot-btn")?.addEventListener("click", async () => {
    const runId = container.querySelector<HTMLInputElement>("#biomed-review-run-id")?.value.trim() || "";
    const target = container.querySelector<HTMLElement>("#biomed-review-result");
    if (!target || !runId) return;
    target.innerHTML = renderLoading("Creating evidence graph snapshot...");
    try {
      await api(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/evidence-review/snapshot`, { method: "POST" });
      await loadReview(runId);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
  container.querySelector<HTMLSelectElement>("#biomed-review-filter")?.addEventListener("change", () => {
    if (currentReview) paintReview(currentReview, currentTrace);
  });
  void loadReviewRecentRuns(container, loadReview);
}

async function loadReviewRecentRuns(
  container: HTMLElement,
  onSelect: (runId: string) => Promise<void>,
): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-review-recent-runs");
  if (!target) return;
  target.innerHTML = '<div class="biomed-muted">Loading recent runs...</div>';
  try {
    const data = await api<{ items: AnswerRunListItem[] }>("/api/biomed/answer-runs?page_size=8");
    target.innerHTML = data.items.map((item) => `
      <button class="biomed-run-link" data-review-run-id="${escapeHtml(item.run_id)}">
        <span>${escapeHtml(item.question || item.run_id)}</span>
        <code>${escapeHtml(item.created_at || item.run_id)}</code>
      </button>
    `).join("") || '<div class="biomed-muted">No runs yet.</div>';
    target.querySelectorAll<HTMLButtonElement>("[data-review-run-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        const runId = button.dataset.reviewRunId || "";
        const input = container.querySelector<HTMLInputElement>("#biomed-review-run-id");
        if (input) input.value = runId;
        await onSelect(runId);
      });
    });
    const firstRunId = data.items[0]?.run_id || "";
    if (firstRunId) {
      const input = container.querySelector<HTMLInputElement>("#biomed-review-run-id");
      if (input && !input.value) input.value = firstRunId;
      if (input?.value === firstRunId) await onSelect(firstRunId);
    }
  } catch (error) {
    target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

function renderGraph(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-section">
      <div class="biomed-title">Evidence Graph</div>
      <div class="biomed-form">
        <div class="biomed-control-grid">
          <label class="biomed-field">
            <span>Topic</span>
            <input id="biomed-graph-topic" value="microglial activation Alzheimer's disease" />
          </label>
          <label class="biomed-field">
            <span>Entity</span>
            <input id="biomed-graph-entity" />
          </label>
          <label class="biomed-field">
            <span>Paper ID</span>
            <input id="biomed-graph-paper" />
          </label>
          <label class="biomed-field">
            <span>Run ID</span>
            <input id="biomed-graph-run" />
          </label>
          <label class="biomed-field">
            <span>Direction</span>
            <select id="biomed-graph-direction">
              <option value="">any</option>
              <option value="supports">supports</option>
              <option value="contradicts">contradicts</option>
              <option value="inconclusive">inconclusive</option>
              <option value="background">background</option>
            </select>
          </label>
          <label class="biomed-check">
            <input id="biomed-graph-validate" type="checkbox" checked />
            <span>Validate</span>
          </label>
        </div>
        <div class="biomed-action-row">
          <button id="biomed-graph-btn">Load</button>
          <button id="biomed-graph-export-btn">Export JSON</button>
        </div>
      </div>
      <div class="biomed-two-col">
        <label class="biomed-field">
          <span>Source Node</span>
          <input id="biomed-graph-path-source" />
        </label>
        <label class="biomed-field">
          <span>Target Node</span>
          <input id="biomed-graph-path-target" />
        </label>
      </div>
      <div class="biomed-action-row">
        <label class="biomed-check">
          <input id="biomed-graph-path-directed" type="checkbox" />
          <span>Directed path</span>
        </label>
        <button id="biomed-graph-path-btn">Related Path</button>
      </div>
      <div id="biomed-graph-result" class="biomed-result"></div>
      <div id="biomed-graph-inspector" class="biomed-result"></div>
      <div id="biomed-graph-card" class="biomed-result"></div>
      <div id="biomed-graph-path" class="biomed-result"></div>
      <div id="biomed-graph-export" class="biomed-result"></div>
    </div>
  `;
  let currentGraph: BiomedEvidenceGraphV1 | null = null;

  const paramsFromControls = (includeValidate = true): URLSearchParams => {
    const params = new URLSearchParams();
    const topic = container.querySelector<HTMLInputElement>("#biomed-graph-topic")?.value.trim() || "";
    const entity = container.querySelector<HTMLInputElement>("#biomed-graph-entity")?.value.trim() || "";
    const paper = container.querySelector<HTMLInputElement>("#biomed-graph-paper")?.value.trim() || "";
    const run = container.querySelector<HTMLInputElement>("#biomed-graph-run")?.value.trim() || "";
    const direction = container.querySelector<HTMLSelectElement>("#biomed-graph-direction")?.value || "";
    if (topic) params.set("topic", topic);
    if (entity) params.set("entity", entity);
    if (paper) params.set("paper_id", paper);
    if (run) params.set("run_id", run);
    if (direction) params.set("direction", direction);
    if (includeValidate && container.querySelector<HTMLInputElement>("#biomed-graph-validate")?.checked) {
      params.set("validate", "true");
    }
    return params;
  };

  const attachGraphActions = (): void => {
    const inspector = container.querySelector<HTMLElement>("#biomed-graph-inspector");
    const cardTarget = container.querySelector<HTMLElement>("#biomed-graph-card");
    const sourceInput = container.querySelector<HTMLInputElement>("#biomed-graph-path-source");
    const targetInput = container.querySelector<HTMLInputElement>("#biomed-graph-path-target");
    container.querySelectorAll<HTMLButtonElement>("[data-graph-node-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const nodeId = button.getAttribute("data-graph-node-id") || "";
        if (!currentGraph || !inspector) return;
        inspector.innerHTML = `<div class="biomed-label">Inspector</div>${renderGraphNodeInspector(currentGraph, nodeId)}`;
        if (sourceInput && !sourceInput.value) sourceInput.value = nodeId;
        else if (targetInput && !targetInput.value) targetInput.value = nodeId;
      });
    });
    container.querySelectorAll<HTMLButtonElement>("[data-graph-card-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        const claimId = button.getAttribute("data-graph-card-id") || "";
        if (!cardTarget) return;
        cardTarget.innerHTML = '<div class="biomed-loading">Loading evidence card...</div>';
        try {
          const params = paramsFromControls(false);
          const card = await api<BiomedEvidenceCard>(`/api/biomed/graph/v1/evidence-card/${encodeURIComponent(claimId)}?${params.toString()}`);
          cardTarget.innerHTML = `<div class="biomed-label">Evidence Card</div>${renderBiomedEvidenceCard(card)}`;
        } catch (error) {
          cardTarget.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
        }
      });
    });
  };

  container.querySelector<HTMLButtonElement>("#biomed-graph-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-graph-result");
    if (!resultNode) return;
    resultNode.innerHTML = '<div class="biomed-loading">Loading graph...</div>';
    container.querySelector<HTMLElement>("#biomed-graph-inspector")?.replaceChildren();
    container.querySelector<HTMLElement>("#biomed-graph-card")?.replaceChildren();
    container.querySelector<HTMLElement>("#biomed-graph-path")?.replaceChildren();
    container.querySelector<HTMLElement>("#biomed-graph-export")?.replaceChildren();
    try {
      const params = paramsFromControls(true);
      const graph = await api<BiomedEvidenceGraphV1>(`/api/biomed/graph/v1?${params.toString()}`);
      currentGraph = graph;
      resultNode.innerHTML = renderBiomedEvidenceGraph(graph);
      attachGraphActions();
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });

  container.querySelector<HTMLButtonElement>("#biomed-graph-path-btn")?.addEventListener("click", async () => {
    const target = container.querySelector<HTMLElement>("#biomed-graph-path");
    if (!target) return;
    const source = container.querySelector<HTMLInputElement>("#biomed-graph-path-source")?.value.trim() || "";
    const dest = container.querySelector<HTMLInputElement>("#biomed-graph-path-target")?.value.trim() || "";
    if (!source || !dest) {
      target.innerHTML = '<div class="biomed-error">Source and target node IDs are required.</div>';
      return;
    }
    target.innerHTML = '<div class="biomed-loading">Loading path...</div>';
    try {
      const params = paramsFromControls(false);
      params.set("source", source);
      params.set("target", dest);
      if (container.querySelector<HTMLInputElement>("#biomed-graph-path-directed")?.checked) {
        params.set("directed", "true");
      }
      const path = await api<{ schema_version: string; path_mode: string; path: string[]; nodes: BiomedEvidenceGraphNode[]; edges: BiomedEvidenceGraphEdge[] }>(`/api/biomed/graph/v1/path?${params.toString()}`);
      target.innerHTML = `
        <div class="biomed-label">${path.path_mode === "directed" ? "Directed Path" : "Related Path"}</div>
        <div class="biomed-provenance">
          <div class="biomed-provenance-grid">
            <div><span>Schema</span><strong>${escapeHtml(path.schema_version)}</strong></div>
            <div><span>Mode</span><strong>${escapeHtml(path.path_mode)}</strong></div>
            <div><span>Nodes</span><strong>${path.nodes.length}</strong></div>
            <div><span>Edges</span><strong>${path.edges.length}</strong></div>
          </div>
          ${renderList(path.path)}
          <div class="biomed-label">Edges</div>
          ${renderList(path.edges.map((edge) => `${edge.source} -> ${edge.type} -> ${edge.target}`))}
        </div>
      `;
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });

  container.querySelector<HTMLButtonElement>("#biomed-graph-export-btn")?.addEventListener("click", async () => {
    const target = container.querySelector<HTMLElement>("#biomed-graph-export");
    if (!target) return;
    target.innerHTML = '<div class="biomed-loading">Exporting graph...</div>';
    try {
      const params = paramsFromControls(true);
      const graph = await api<BiomedEvidenceGraphV1>(`/api/biomed/graph/v1/export/json?${params.toString()}`);
      target.innerHTML = `
        <div class="biomed-label">JSON Export</div>
        <pre class="biomed-json biomed-json-tall">${escapeHtml(JSON.stringify(graph, null, 2))}</pre>
      `;
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
}

async function loadWatchList(container: HTMLElement): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-watch-list");
  if (!target) return;
  target.textContent = "Loading watches...";
  const data = await api<{ items: WatchTopic[] }>("/api/biomed/watch");
  if (!data.items.length) {
    target.innerHTML = '<div class="biomed-muted">No watch topics yet.</div>';
    return;
  }
  target.innerHTML = data.items.map((watch) => `
    <div class="biomed-watch-row">
      <div>
        <div class="biomed-watch-title">${escapeHtml(watch.topic)}</div>
        <div class="biomed-watch-meta">
          ${escapeHtml(watch.schedule)} · ${watch.enabled ? "enabled" : "paused"} · threshold ${watch.min_relevance_score}
        </div>
        <div class="biomed-watch-meta">
          last ${escapeHtml(watch.last_checked_at || "-")} · next ${escapeHtml(watch.next_check_at || "-")}
        </div>
      </div>
      <div class="biomed-row">
        <button data-biomed-check="${escapeHtml(watch.watch_id)}">Check</button>
        <button data-biomed-drift="${escapeHtml(watch.watch_id)}">Drift</button>
      </div>
    </div>
  `).join("");
  target.querySelectorAll<HTMLButtonElement>("[data-biomed-check]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.getAttribute("data-biomed-check") || "";
      button.disabled = true;
      button.textContent = "Checking...";
      const result = await api<WatchCheckResult>(`/api/biomed/watch/${encodeURIComponent(id)}/check`, { method: "POST" });
      const checkTarget = container.querySelector<HTMLElement>("#biomed-watch-check-result");
      if (checkTarget) {
        checkTarget.innerHTML = renderWatchCheckResult(result);
      }
      await loadWatchList(container);
      await loadWatchEvents(container, id);
    });
  });
  target.querySelectorAll<HTMLButtonElement>("[data-biomed-drift]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.getAttribute("data-biomed-drift") || "";
      button.disabled = true;
      button.textContent = "Loading...";
      const driftTarget = container.querySelector<HTMLElement>("#biomed-watch-drift-result");
      if (driftTarget) driftTarget.innerHTML = renderLoading("Loading Watch graph drift...");
      try {
        const result = await api<WatchGraphDriftResult>(`/api/biomed/watch/${encodeURIComponent(id)}/drift`);
        if (driftTarget) driftTarget.innerHTML = renderWatchDrift(result);
      } catch (error) {
        if (driftTarget) driftTarget.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
      } finally {
        button.disabled = false;
        button.textContent = "Drift";
      }
    });
  });
}

async function loadWatchEvents(container: HTMLElement, watchId = ""): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-watch-events");
  if (!target) return;
  const url = watchId ? `/api/biomed/watch/${encodeURIComponent(watchId)}/events` : "/api/biomed/watch//events";
  if (!watchId) {
    target.innerHTML = '<div class="biomed-muted">Check a watch to inspect its decisions.</div>';
    return;
  }
  const data = await api<{ items: WatchDecision[] }>(url);
  target.innerHTML = data.items.map((item) => `
    <div class="biomed-decision">
      <div>${pill(item.decision || "")} ${escapeHtml(item.title || item.paper_id || "")}</div>
      <div class="biomed-watch-meta">score ${escapeHtml(String(item.relevance_score || ""))} · ${escapeHtml(item.rationale || "")}</div>
      <div class="biomed-watch-meta">
        retrieval ${escapeHtml(item.retrieval_id || "-")} · snapshot ${escapeHtml(item.snapshot_id || "-")}
      </div>
    </div>
  `).join("") || '<div class="biomed-muted">No decisions.</div>';
}

function renderWatchCheckResult(result: WatchCheckResult): string {
  const snapshot = result.snapshot;
  return `
    <div class="biomed-section">
      <div class="biomed-title">Latest Check</div>
      ${renderManifest(result.retrieval_manifest)}
      ${
        snapshot
          ? `
            <div class="biomed-provenance">
              <div class="biomed-provenance-grid">
                <div><span>Snapshot</span><code>${escapeHtml(snapshot.snapshot_id)}</code></div>
                <div><span>New Papers</span><strong>${snapshot.new_paper_ids.length}</strong></div>
                <div><span>Total Papers</span><strong>${snapshot.paper_ids.length}</strong></div>
                <div><span>Decisions</span><strong>${result.decisions.length}</strong></div>
              </div>
              <div class="biomed-label">New Paper IDs</div>
              ${renderList(snapshot.new_paper_ids)}
            </div>
          `
          : '<div class="biomed-muted">No snapshot recorded.</div>'
      }
    </div>
  `;
}

function renderWatchDrift(result: WatchGraphDriftResult): string {
  const changesByType = result.changes.reduce<Record<string, WatchDriftChange[]>>((acc, change) => {
    const key = change.change_type || "unknown";
    if (!acc[key]) acc[key] = [];
    acc[key].push(change);
    return acc;
  }, {});
  return `
    <div class="biomed-section">
      <div class="biomed-title">Watch Graph Drift</div>
      <div class="biomed-provenance">
        <div class="biomed-provenance-grid">
          <div><span>Status</span><strong>${escapeHtml(result.status)}</strong></div>
          <div><span>Schema</span><strong>${escapeHtml(result.schema_version)}</strong></div>
          <div><span>Changes</span><strong>${result.change_count}</strong></div>
          <div><span>Advisory</span><strong>${result.advisory_only ? "yes" : "no"}</strong></div>
          <div><span>Base</span>${compactCode(result.base_snapshot_id || "-")}</div>
          <div><span>Compare</span>${compactCode(result.compare_snapshot_id || "-")}</div>
        </div>
        <div class="biomed-muted">Drift is reviewer QA context. It is not biomedical evidence and does not control runtime behavior.</div>
        ${Object.keys(result.summary || {}).length ? `<div class="biomed-label">Summary</div><pre class="biomed-json">${escapeHtml(JSON.stringify(result.summary, null, 2))}</pre>` : ""}
        ${result.warnings.length ? `<div class="biomed-label">Warnings</div>${renderList(result.warnings)}` : ""}
      </div>
      <div class="biomed-audit-table">
        ${Object.entries(changesByType).map(([type, changes]) => `
          <div class="biomed-audit-row">
            <div class="biomed-audit-row-head">${pill(type)} <strong>${changes.length}</strong></div>
            ${changes.slice(0, 8).map((change) => `
              <div class="biomed-decision">
                <div><code>${escapeHtml(change.item_id)}</code> ${escapeHtml(change.label)}</div>
                <div class="biomed-watch-meta">
                  papers ${escapeHtml(change.paper_ids.join(", ") || "-")} · evidence ${escapeHtml(change.evidence_ids.join(", ") || "-")}
                </div>
              </div>
            `).join("")}
          </div>
        `).join("") || '<div class="biomed-muted">No graph drift changes available.</div>'}
      </div>
    </div>
  `;
}

function renderWatch(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-section">
      <div class="biomed-title">Research Watch</div>
      <div class="biomed-form biomed-watch-form">
        <input id="biomed-watch-topic" value="spatial transcriptomics in tumor microenvironment" />
        <input id="biomed-watch-include" value="spatial transcriptomics,tumor microenvironment" />
        <input id="biomed-watch-methods" value="spatial transcriptomics" />
        <div class="biomed-row">
          <input id="biomed-watch-threshold" type="number" min="0" max="1" step="0.05" value="0.7" />
          <select id="biomed-watch-schedule"><option>daily</option><option>weekly</option><option>manual</option></select>
          <button id="biomed-watch-create">Create Watch</button>
        </div>
      </div>
      <div class="biomed-label">Topics</div>
      <div id="biomed-watch-list" class="biomed-result"></div>
      <div id="biomed-watch-check-result" class="biomed-result"></div>
      <div id="biomed-watch-drift-result" class="biomed-result"></div>
      <div class="biomed-label">Decision Log</div>
      <div id="biomed-watch-events" class="biomed-result"></div>
    </div>
  `;
  container.querySelector<HTMLButtonElement>("#biomed-watch-create")?.addEventListener("click", async () => {
    const topic = container.querySelector<HTMLInputElement>("#biomed-watch-topic")?.value || "";
    const include = csv(container.querySelector<HTMLInputElement>("#biomed-watch-include")?.value || "");
    const methods = csv(container.querySelector<HTMLInputElement>("#biomed-watch-methods")?.value || "");
    const min_relevance_score = Number(container.querySelector<HTMLInputElement>("#biomed-watch-threshold")?.value || 0.7);
    const schedule = container.querySelector<HTMLSelectElement>("#biomed-watch-schedule")?.value || "daily";
    await api("/api/biomed/watch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic, include_keywords: include, preferred_methods: methods, min_relevance_score, schedule }),
    });
    await loadWatchList(container);
  });
  void loadWatchList(container);
  void loadWatchEvents(container);
}

function renderAudit(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-audit-workspace">
      <aside class="biomed-audit-rail">
        <div>
          <div class="biomed-label">Audit</div>
          <h2>Citation review</h2>
          <p>Run or inspect claim-level citation audit, then jump to trace, packet, or provenance for the same answer run.</p>
        </div>
        <label class="biomed-field">
          <span>Run ID</span>
          <input id="biomed-audit-run-id" placeholder="answer run id" />
        </label>
        <div class="biomed-review-rail-actions">
          <button id="biomed-audit-run-btn">Run Audit</button>
          <button id="biomed-audit-trace-btn">Trace</button>
        </div>
        <div class="biomed-review-rail-actions">
          <button id="biomed-audit-packet-btn">Packet</button>
          <button id="biomed-audit-provenance-btn">Provenance</button>
        </div>
        <div class="biomed-label">Recent Runs</div>
        <div id="biomed-audit-recent-runs" class="biomed-review-run-list"></div>
      </aside>
      <main id="biomed-audit-result" class="biomed-audit-main">
        <div class="biomed-empty-state">
          <div class="biomed-label">No audit selected</div>
          <h2>Select a recent run</h2>
          <p>The audit view loads citation alignment, claim citation support, overclaim risk, claim verdicts, and logic-audit artifacts when present.</p>
        </div>
      </main>
      <aside id="biomed-audit-inspector" class="biomed-audit-inspector">
        <div class="biomed-review-inspector-empty">
          <div class="biomed-label">Run Artifacts</div>
          <h3>Trace, packet, provenance</h3>
          <p>Use the selected run to inspect supporting release artifacts without leaving the audit workflow.</p>
        </div>
      </aside>
    </div>
  `;

  const selectedRunId = (): string => (
    container.querySelector<HTMLInputElement>("#biomed-audit-run-id")?.value.trim() || ""
  );

  const setSelectedRun = (runId: string): void => {
    const input = container.querySelector<HTMLInputElement>("#biomed-audit-run-id");
    if (input) input.value = runId;
  };

  const loadAudit = async (runId: string, runAudit = false): Promise<void> => {
    const target = container.querySelector<HTMLElement>("#biomed-audit-result");
    if (!target || !runId) return;
    setSelectedRun(runId);
    target.innerHTML = renderLoading(runAudit ? "Running citation audit..." : "Loading citation audit...");
    try {
      const audit = runAudit
        ? await api<CitationAuditResult>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/audit`, { method: "POST" })
        : (await api<AuditRunPayload>(`/api/biomed/audit/${encodeURIComponent(runId)}`)).latest_citation_audit;
      if (!audit) {
        target.innerHTML = `
          <div class="biomed-empty-state">
            <div class="biomed-label">No citation audit</div>
            <h2>${escapeHtml(runId)}</h2>
            <p>This run has no saved audit yet. Run Audit will create the citation audit and logic-audit artifact for this answer run.</p>
          </div>
        `;
        return;
      }
      target.innerHTML = `
        <section class="biomed-run-hero">
          <div class="biomed-run-kicker">
            ${pill(audit.recommended_action)}
            ${pill(`claim citation support ${Math.round(audit.claim_support_rate * 100)}%`)}
            ${pill(`citation alignment ${Math.round(audit.citation_precision * 100)}%`)}
            ${pill(`packet use ${Math.round((audit.packet_citation_utilization ?? audit.citation_precision) * 100)}%`)}
          </div>
          <div class="biomed-run-title">${escapeHtml(runId)}</div>
          <div class="biomed-run-stats">
            <span>${audit.claim_audits.length} claims</span>
            <span>${audit.failed_claims.length} failed</span>
            <span>${Math.round(audit.unsupported_claim_rate * 100)}% unsupported</span>
            <span>${Math.round(audit.overclaim_rate * 100)}% overclaim</span>
          </div>
        </section>
        ${renderAuditResult(audit)}
      `;
      await loadAuditList(container);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  };

  const loadInspector = async (label: string, loader: () => Promise<string>): Promise<void> => {
    const target = container.querySelector<HTMLElement>("#biomed-audit-inspector");
    if (!target) return;
    target.innerHTML = renderLoading(label);
    try {
      target.innerHTML = await loader();
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  };

  container.querySelector<HTMLButtonElement>("#biomed-audit-run-btn")?.addEventListener("click", async () => {
    await loadAudit(selectedRunId(), true);
  });
  container.querySelector<HTMLButtonElement>("#biomed-audit-trace-btn")?.addEventListener("click", async () => {
    const runId = selectedRunId();
    if (!runId) return;
    await loadInspector("Loading trace...", async () => {
      const trace = await api<TracePayload>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/trace`);
      return renderTraceResult(trace);
    });
  });
  container.querySelector<HTMLButtonElement>("#biomed-audit-packet-btn")?.addEventListener("click", async () => {
    const runId = selectedRunId();
    if (!runId) return;
    await loadInspector("Building evidence packet...", async () => {
      const envelope = await api<ReleaseToolEnvelope<EvidencePacketBuildResult>>("/api/biomed/evidence/packet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, max_evidence_items: 12, selection_strategy: "submodular_greedy" }),
      });
      return renderPacketBuildResult(envelope);
    });
  });
  container.querySelector<HTMLButtonElement>("#biomed-audit-provenance-btn")?.addEventListener("click", async () => {
    const runId = selectedRunId();
    if (!runId) return;
    await loadInspector("Loading provenance graph...", async () => {
      const envelope = await api<ReleaseToolEnvelope<ProvenanceGraphResult>>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/provenance`);
      return renderProvenanceResult(envelope);
    });
  });
  void loadAuditList(container);
  void loadAuditRecentRuns(container, loadAudit);
}

async function loadAuditList(container: HTMLElement): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-audit-inspector");
  if (!target) return;
  try {
    const data = await api<{ items: { audit_id: string; run_id?: string | null; recommended_action: string; metrics?: Record<string, unknown>; created_at: string }[] }>("/api/biomed/audits");
    const rows = data.items.slice(0, 5).map((item) => `
      <button class="biomed-run-link" data-audit-history-run-id="${escapeHtml(item.run_id || "")}">
        <span>${escapeHtml(item.run_id || item.audit_id)}</span>
        <code>${escapeHtml(item.recommended_action)} · ${escapeHtml(item.created_at || "")}</code>
      </button>
    `).join("");
    target.innerHTML = `
      <div class="biomed-label">Recent Audits</div>
      <div class="biomed-review-run-list">
        ${rows || '<div class="biomed-muted">No audits yet.</div>'}
      </div>
    `;
    target.querySelectorAll<HTMLButtonElement>("[data-audit-history-run-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const runId = button.dataset.auditHistoryRunId || "";
        const input = container.querySelector<HTMLInputElement>("#biomed-audit-run-id");
        if (input && runId) input.value = runId;
      });
    });
  } catch (error) {
    target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

async function loadAuditRecentRuns(
  container: HTMLElement,
  onSelect: (runId: string, runAudit?: boolean) => Promise<void>,
): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-audit-recent-runs");
  if (!target) return;
  target.innerHTML = '<div class="biomed-muted">Loading recent runs...</div>';
  try {
    const data = await api<{ items: AnswerRunListItem[] }>("/api/biomed/answer-runs?page_size=8");
    target.innerHTML = data.items.map((item) => `
      <button class="biomed-run-link" data-audit-run-id="${escapeHtml(item.run_id)}">
        <span>${escapeHtml(item.question || item.run_id)}</span>
        <code>${escapeHtml(item.created_at || item.run_id)}</code>
      </button>
    `).join("") || '<div class="biomed-muted">No runs yet.</div>';
    target.querySelectorAll<HTMLButtonElement>("[data-audit-run-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        const runId = button.dataset.auditRunId || "";
        await onSelect(runId, false);
      });
    });
    const firstRunId = data.items[0]?.run_id || "";
    if (firstRunId) {
      await onSelect(firstRunId, false);
    }
  } catch (error) {
    target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

function renderTrace(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-trace-workspace">
      <aside class="biomed-trace-rail">
        <div>
          <div class="biomed-label">Trace</div>
          <h2>Run exports</h2>
          <p>Open a saved answer run, inspect tool steps, then build packet, provenance, or one-way Obsidian export artifacts.</p>
        </div>
        <label class="biomed-field">
          <span>Run ID</span>
          <input id="biomed-trace-run-id" placeholder="answer run id" />
        </label>
        <div class="biomed-review-rail-actions">
          <button id="biomed-trace-load-btn">Load Trace</button>
          <button id="biomed-packet-build-btn">Build Packet</button>
        </div>
        <div class="biomed-review-rail-actions">
          <button id="biomed-provenance-load-btn">Provenance</button>
          <button id="biomed-obsidian-export-btn">Export Packet</button>
        </div>
        <label class="biomed-field">
          <span>Obsidian Export Dir</span>
          <input id="biomed-obsidian-dir" placeholder="workspace-relative export dir" value="obsidian-export" />
        </label>
        <label class="biomed-check">
          <input id="biomed-obsidian-enabled" type="checkbox" />
          <span>Enable one-way export</span>
        </label>
        <div class="biomed-label">Recent Runs</div>
        <div id="biomed-trace-recent-runs" class="biomed-review-run-list"></div>
      </aside>
      <main id="biomed-trace-result" class="biomed-trace-main">
        <div class="biomed-empty-state">
          <div class="biomed-label">No run selected</div>
          <h2>Select a recent run</h2>
          <p>The trace view loads tool-chain steps, memory effects, budget snapshots, telemetry, audit state, and answer revision details.</p>
        </div>
      </main>
      <aside id="biomed-release-tool-result" class="biomed-trace-inspector">
        <div class="biomed-review-inspector-empty">
          <div class="biomed-label">Release Artifacts</div>
          <h3>Packet, provenance, export</h3>
          <p>Use a selected run to build or inspect release artifacts. Obsidian export remains disabled unless explicitly enabled.</p>
        </div>
      </aside>
    </div>
  `;

  let currentTrace: TracePayload | null = null;

  const selectedRunId = (): string => (
    container.querySelector<HTMLInputElement>("#biomed-trace-run-id")?.value.trim() || currentTrace?.run_id || ""
  );

  const setSelectedRun = (runId: string): void => {
    const input = container.querySelector<HTMLInputElement>("#biomed-trace-run-id");
    if (input) input.value = runId;
  };

  const renderTraceSummary = (trace: TracePayload): string => {
    const answer = trace.answer_run;
    const audit = trace.latest_citation_audit;
    const revision = trace.revision;
    return `
      <section class="biomed-run-hero">
        <div class="biomed-run-kicker">
          ${pill(revision?.revision_action || "trace")}
          ${answerQualityPills(answer)}
          ${answer.synthesis_mode ? pill(answer.synthesis_mode) : ""}
          ${answer.retrieval_manifest?.source ? pill(answer.retrieval_manifest.source) : ""}
        </div>
        <div class="biomed-run-title">${escapeHtml(trace.run_id)}</div>
        <div class="biomed-run-stats">
          <span>${trace.trace.length} steps</span>
          <span>${answer.evidence_summary.length} evidence items</span>
          <span>${answer.citations.length} citations</span>
          <span>${audit ? audit.recommended_action : "audit pending"}</span>
        </div>
      </section>
      ${renderTraceResult(trace)}
    `;
  };

  const loadTrace = async (runId: string): Promise<void> => {
    const target = container.querySelector<HTMLElement>("#biomed-trace-result");
    const artifactTarget = container.querySelector<HTMLElement>("#biomed-release-tool-result");
    if (!target || !runId) return;
    setSelectedRun(runId);
    target.innerHTML = renderLoading("Loading answer trace...");
    if (artifactTarget) {
      artifactTarget.innerHTML = `
        <div class="biomed-review-inspector-empty">
          <div class="biomed-label">Release Artifacts</div>
          <h3>${escapeHtml(runId)}</h3>
          <p>Build packet, load provenance, or export one-way Obsidian notes for this run.</p>
        </div>
      `;
    }
    try {
      const trace = await api<TracePayload>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/trace`);
      currentTrace = trace;
      target.innerHTML = renderTraceSummary(trace);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  };

  const loadReleaseArtifact = async (label: string, loader: () => Promise<string>): Promise<void> => {
    const target = container.querySelector<HTMLElement>("#biomed-release-tool-result");
    if (!target) return;
    target.innerHTML = renderLoading(label);
    try {
      target.innerHTML = await loader();
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  };

  container.querySelector<HTMLButtonElement>("#biomed-trace-load-btn")?.addEventListener("click", async () => {
    await loadTrace(selectedRunId());
  });
  container.querySelector<HTMLButtonElement>("#biomed-packet-build-btn")?.addEventListener("click", async () => {
    const runId = selectedRunId();
    if (!runId) return;
    await loadReleaseArtifact("Building evidence packet...", async () => {
      const envelope = await api<ReleaseToolEnvelope<EvidencePacketBuildResult>>("/api/biomed/evidence/packet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, max_evidence_items: 12, selection_strategy: "submodular_greedy" }),
      });
      return renderPacketBuildResult(envelope);
    });
  });
  container.querySelector<HTMLButtonElement>("#biomed-provenance-load-btn")?.addEventListener("click", async () => {
    const runId = selectedRunId();
    if (!runId) return;
    await loadReleaseArtifact("Loading provenance graph...", async () => {
      const envelope = await api<ReleaseToolEnvelope<ProvenanceGraphResult>>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/provenance`);
      return renderProvenanceResult(envelope);
    });
  });
  container.querySelector<HTMLButtonElement>("#biomed-obsidian-export-btn")?.addEventListener("click", async () => {
    const runId = selectedRunId();
    const exportDir = container.querySelector<HTMLInputElement>("#biomed-obsidian-dir")?.value.trim() || "";
    const enabled = Boolean(container.querySelector<HTMLInputElement>("#biomed-obsidian-enabled")?.checked);
    if (!runId) return;
    await loadReleaseArtifact("Exporting one-way Obsidian note...", async () => {
      const envelope = await api<ReleaseToolEnvelope<ObsidianExportResult>>("/api/biomed/export/obsidian/evidence-packet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, export_dir: exportDir, enabled }),
      });
      return renderObsidianExportResult(envelope);
    });
  });
  void loadTraceRecentRuns(container, loadTrace);
}

async function loadTraceRecentRuns(
  container: HTMLElement,
  onSelect: (runId: string) => Promise<void>,
): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-trace-recent-runs");
  if (!target) return;
  target.innerHTML = '<div class="biomed-muted">Loading recent runs...</div>';
  try {
    const data = await api<{ items: AnswerRunListItem[] }>("/api/biomed/answer-runs?page_size=8");
    target.innerHTML = data.items.map((item) => `
      <button class="biomed-run-link" data-trace-run-id="${escapeHtml(item.run_id)}">
        <span>${escapeHtml(item.question || item.run_id)}</span>
        <code>${escapeHtml(item.created_at || item.run_id)}</code>
      </button>
    `).join("") || '<div class="biomed-muted">No runs yet.</div>';
    target.querySelectorAll<HTMLButtonElement>("[data-trace-run-id]").forEach((button) => {
      button.addEventListener("click", async () => {
        const runId = button.dataset.traceRunId || "";
        await onSelect(runId);
      });
    });
    const firstRunId = data.items[0]?.run_id || "";
    if (firstRunId) await onSelect(firstRunId);
  } catch (error) {
    target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

function csv(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function renderResponsible(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-section">
      <div class="biomed-title">Responsible AI Boundary</div>
      <div class="biomed-policy">
        This system is intended for biomedical research support only. It does not provide clinical diagnosis,
        treatment recommendations, or patient-specific medical advice. Outputs require expert review.
      </div>
      <div class="biomed-label">Policy</div>
      <ul class="biomed-list">
        <li>Biomedical factual claims must be grounded in retrieved citations.</li>
        <li>Project memory is treated as user context, not biomedical fact.</li>
        <li>Clinical diagnosis, patient-specific treatment, and private medical-record interpretation are refused.</li>
        <li>Uncertainty is elevated when evidence is conflicting, observational, abstract-only, or missing citations.</li>
        <li>Retrieval manifests expose source, compiled query, result counts, warnings, and repeatability limits.</li>
        <li>Release 1.0 tool outputs use structured envelopes, fail fast on policy errors, and preserve partial traces.</li>
        <li>Toolized retrieval, extraction, packet building, audit, revision, export, and provenance stay inspectable through trace.</li>
        <li>Obsidian export is one-way reviewer output; exported notes are never imported as biomedical evidence.</li>
        <li>Packet selection and retrieval advisories are deterministic or advisory-only and cannot override clinical/source policy.</li>
        <li>Provenance graphs redact prompts, provider raw responses, API keys, and secrets.</li>
      </ul>
    </div>
  `;
}

function attachDetailTabs(
  root: HTMLElement,
  item: Record<string, unknown> | null,
  dispatch?: PluginDispatch,
): void {
  root.querySelectorAll<HTMLButtonElement>("[data-biomed-view]").forEach((button) => {
    button.addEventListener("click", () => {
      const view = (button.dataset.biomedView || "chat") as BiomedView;
      dispatch?.setFilter("_view", view);
      renderBiomedDetail(root, item, view, dispatch);
    });
  });
}

function renderBiomedDetail(
  root: HTMLElement,
  item: Record<string, unknown> | null,
  view: BiomedView,
  dispatch?: PluginDispatch,
): void {
  root.innerHTML = renderTabs(view);
  if (item && view === "library") {
    root.innerHTML += renderEvidenceDetail(item as unknown as EvidenceRow);
    attachDetailTabs(root, item, dispatch);
    void hydrateRetrievalBlocks(root);
    return;
  }
  if (view === "chat") {
    renderBiomedChatWorkspace(root, dispatch);
  } else if (view === "runs") {
    renderAskWorkspace(root);
  } else if (view === "queue") {
    renderProjects(root);
  } else if (view === "library") {
    renderLibrary(root);
  } else if (view === "settings") {
    renderResponsible(root);
  } else {
    renderBiomedChatWorkspace(root, dispatch);
  }
  attachDetailTabs(root, item, dispatch);
}

window.AkashicDashboard.registerPlugin({
  id: "biomed_evidence",
  label: "Biomedical Evidence",
  viewLabel: "biomed",
  layout: "workbench",
  pageSize: 25,
  rowKey: "evidence_id",
  defaultSortBy: "updated_at",

  columns: [
    { key: "paper_id", label: "Paper", width: 132, cellClass: "mono", rawTitle: true },
    { key: "evidence_direction", label: "Dir", width: 92, renderCell: (value) => pill(String(value || "")) },
    { key: "confidence", label: "Conf", width: 72, renderCell: (value) => pill(String(value || "")) },
    { key: "claim", label: "Claim", flex: true, fmt: "text-preview", cellClass: "content-preview" },
  ],

  countTitle(total: number): string {
    return `${total} evidence items`;
  },

  async getCount(): Promise<number | null> {
    const data = await api<{ total: number }>("/api/biomed/evidence?page_size=1").catch(() => ({ total: 0 }));
    return data.total || 0;
  },

  async fetchPage({ page, pageSize, filters }) {
    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    for (const key of ["q", "direction", "entity"]) {
      const value = filters?.[key];
      if (value) params.set(key, value);
    }
    const data = await api<{ items: Record<string, unknown>[]; total: number }>(`/api/biomed/evidence?${params.toString()}`);
    return { items: data.items || [], total: data.total || 0 };
  },

  renderFilters(container: HTMLElement): void {
    container.innerHTML = `
      <div class="biomed-topbar-status" aria-label="Biomedical Evidence workspace status">
        <span class="biomed-topbar-dot"></span>
        <strong>research-only agent</strong>
        <span>literature · review · provenance</span>
      </div>
    `;
  },

  renderNavBody(container: HTMLElement, dispatch: PluginDispatch): void {
    const view = viewFromDispatch(dispatch);
    let railCollapsed = false;
    try {
      railCollapsed = window.localStorage.getItem("biomed-rail-collapsed") === "1";
    } catch {
      railCollapsed = false;
    }
    container.closest<HTMLElement>(".workspace")?.classList.toggle("biomed-rail-collapsed", railCollapsed);
    container.innerHTML = `
      <div class="biomed-plugin-nav">
        <button
          id="biomed-agent-rail-toggle"
          class="biomed-agent-rail-toggle"
          type="button"
          title="${railCollapsed ? "Expand navigation" : "Collapse navigation"}"
          aria-label="${railCollapsed ? "Expand navigation" : "Collapse navigation"}"
        >${railCollapsed ? "›" : "‹"}</button>
        ${BIOMED_VIEW_ITEMS.map((item) => `
          <button class="biomed-plugin-nav-item ${item.id === view ? "is-active" : ""}" data-biomed-view="${item.id}" data-biomed-short="${escapeHtml(item.label.slice(0, 1))}" type="button" aria-label="${escapeHtml(item.label)}">
            <span>${escapeHtml(item.label)}</span>
            <small>${escapeHtml(item.description)}</small>
          </button>
        `).join("")}
      </div>
    `;
    container.querySelector<HTMLButtonElement>("#biomed-agent-rail-toggle")?.addEventListener("click", () => {
      const workspace = container.closest<HTMLElement>(".workspace");
      const button = container.querySelector<HTMLButtonElement>("#biomed-agent-rail-toggle");
      const collapsed = !workspace?.classList.contains("biomed-rail-collapsed");
      workspace?.classList.toggle("biomed-rail-collapsed", collapsed);
      if (button) {
        button.textContent = collapsed ? "›" : "‹";
        button.title = collapsed ? "Expand navigation" : "Collapse navigation";
        button.setAttribute("aria-label", button.title);
      }
      try {
        window.localStorage.setItem("biomed-rail-collapsed", collapsed ? "1" : "0");
      } catch {
        // localStorage can be unavailable in embedded/private contexts.
      }
    });
    container.querySelectorAll<HTMLButtonElement>("[data-biomed-view]").forEach((button) => {
      button.addEventListener("click", () => {
        dispatch.setFilter("_view", button.dataset.biomedView || "chat");
        dispatch.activate();
      });
    });
  },

  renderMain(container: HTMLElement, dispatch: PluginDispatch): void {
    const view = viewFromDispatch(dispatch);
    container.innerHTML = '<div class="biomed-wrap biomed-workbench-root"></div>';
    const root = container.querySelector<HTMLElement>(".biomed-wrap");
    if (!root) return;
    renderBiomedWorkbench(root, view, dispatch);
  },

  renderDetail(item: Record<string, unknown> | null, container: HTMLElement, dispatch?: PluginDispatch): void {
    const view = viewFromDispatch(dispatch);
    container.innerHTML = '<div class="biomed-wrap"></div>';
    const root = container.querySelector<HTMLElement>(".biomed-wrap");
    if (!root) return;
    renderBiomedDetail(root, item, view, dispatch);
  },
});
