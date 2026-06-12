/// <reference path="../../types/akashic-dashboard.d.ts" />

type BiomedView = "ask" | "projects" | "evidence" | "graph" | "watch" | "audit" | "trace" | "responsible";

let biomedWorkflowTemplates: SavedToolChainTemplate[] = [];

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
  suggested_next_steps: string[];
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

interface TracePayload {
  run_id: string;
  answer_run: AnswerResult;
  trace: AgentTraceStep[];
  step_telemetry?: StepTelemetrySummary | null;
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

function viewFromDispatch(dispatch?: PluginDispatch): BiomedView {
  const value = dispatch?.filters["_view"];
  if (value === "projects" || value === "graph" || value === "watch" || value === "audit" || value === "trace" || value === "responsible" || value === "evidence") {
    return value;
  }
  return "ask";
}

function pill(value: string): string {
  return `<span class="biomed-pill biomed-pill-${escapeHtml(value)}">${escapeHtml(value)}</span>`;
}

function renderList(items: unknown[] | undefined): string {
  const values = (items || []).map((item) => String(item || "").trim()).filter(Boolean);
  if (!values.length) return '<span class="biomed-muted">None recorded</span>';
  return `<ul class="biomed-list">${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderEvidenceItem(item: EvidenceRow): string {
  return `
    <div class="biomed-evidence-item">
      <div class="biomed-evidence-head">
        ${pill(item.evidence_direction)}
        ${pill(item.confidence)}
        ${item.retrieval_intent ? pill(item.retrieval_intent) : ""}
        ${item.extraction_mode ? pill(item.extraction_mode) : ""}
        <code>${escapeHtml(item.paper_id)}</code>
      </div>
      <div class="biomed-evidence-claim">${escapeHtml(item.claim)}</div>
      <div class="biomed-evidence-finding">${escapeHtml(item.finding)}</div>
    </div>
  `;
}

function renderRetrievalBundle(bundle: RetrievalBundle | null | undefined): string {
  if (!bundle) return '<div class="biomed-muted">No retrieval bundle recorded.</div>';
  const coverageRows = bundle.coverage_matrix || [];
  const gapDecisions = bundle.gap_decisions || [];
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Bundle</span><code>${escapeHtml(bundle.bundle_id)}</code></div>
        <div><span>Source</span><strong>${escapeHtml(bundle.source)}</strong></div>
        <div><span>Mode</span><strong>${bundle.executed_multi_query ? "multi-query" : "single-query"}</strong></div>
        <div><span>Papers</span><strong>${bundle.deduped_paper_ids.length}</strong></div>
        <div><span>Stop</span><strong>${escapeHtml(bundle.stop_reason || "-")}</strong></div>
        <div><span>Gaps</span><strong>${coverageRows.filter((row) => row.coverage_status !== "covered").length}</strong></div>
      </div>
      ${bundle.warnings?.length ? `<div class="biomed-label">Warnings</div>${renderList(bundle.warnings)}` : ""}
      ${coverageRows.length ? `
        <div class="biomed-label">Coverage Matrix</div>
        <div class="biomed-audit-table">
          ${coverageRows.map((row) => `
            <div class="biomed-audit-row">
              <div class="biomed-audit-row-head">
                ${pill(row.retrieval_intent)}
                ${pill(row.coverage_status)}
                ${pill(`pass ${row.pass_index}`)}
                <span>${row.evidence_count}/${row.papers_found} evidence</span>
              </div>
              <div class="biomed-evidence-claim">${escapeHtml(row.subquestion)}</div>
              ${row.gap_reason ? `<div class="biomed-evidence-finding">${escapeHtml(row.gap_reason)}</div>` : ""}
            </div>
          `).join("")}
        </div>
      ` : ""}
      ${gapDecisions.length ? `
        <div class="biomed-label">Gap Follow-up</div>
        ${gapDecisions.map((gap) => `
          <div class="biomed-evidence-item">
            <div class="biomed-evidence-head">
              ${pill(gap.retrieval_intent)}
              ${pill(gap.executed ? "executed" : "skipped")}
              ${gap.retrieval_id ? `<code>${escapeHtml(gap.retrieval_id)}</code>` : ""}
            </div>
            <code class="biomed-query">${escapeHtml(gap.followup_query)}</code>
            <div class="biomed-evidence-finding">${escapeHtml(gap.reason)}</div>
            ${gap.stop_reason ? `<div class="biomed-muted">${escapeHtml(gap.stop_reason)}</div>` : ""}
          </div>
        `).join("")}
      ` : ""}
      <div class="biomed-label">Retrieval Records</div>
      ${bundle.records.map((record) => `
        <div class="biomed-evidence-item">
          <div class="biomed-evidence-head">
            ${pill(record.intent)}
            ${record.pass_index ? pill(`pass ${record.pass_index}`) : ""}
            ${record.coverage ? pill(`${record.coverage.item_count} items`) : ""}
            ${record.retrieval_id ? `<code>${escapeHtml(record.retrieval_id)}</code>` : ""}
          </div>
          <code class="biomed-query">${escapeHtml(record.query)}</code>
          ${record.reason ? `<div class="biomed-evidence-finding">${escapeHtml(record.reason)}</div>` : ""}
          ${record.returned_paper_ids.length ? renderList(record.returned_paper_ids) : '<div class="biomed-muted">No papers returned.</div>'}
          ${record.added_paper_ids?.length ? `<div class="biomed-label">Added Papers</div>${renderList(record.added_paper_ids)}` : ""}
          ${record.skipped_reason ? `<div class="biomed-muted">${escapeHtml(record.skipped_reason)}</div>` : ""}
        </div>
      `).join("")}
      ${bundle.duplicate_paper_ids.length ? `<div class="biomed-label">Duplicates</div>${renderList(bundle.duplicate_paper_ids)}` : ""}
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

function renderWorkflowTemplateRun(envelope: ReleaseToolEnvelope<SavedToolChainTemplateRunResult>): string {
  if (!envelope.ok) return renderReleaseError(envelope);
  const result = envelope.result;
  return `
    <div class="biomed-answer-meta">
      ${pill("template")}
      ${pill(result.template.name)}
      ${pill(result.template.source)}
      <code>${escapeHtml(envelope.ids.run_id || result.audited_answer.answer_result.run_id)}</code>
    </div>
    ${renderAuditedAnswer(result.audited_answer)}
    ${result.provenance ? `<div class="biomed-label">Template Provenance</div>${renderProvenanceResult(result.provenance)}` : ""}
  `;
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

function renderAuditedAnswer(result: AuditedAnswerResult): string {
  return `
    <div class="biomed-answer-meta">
      <code>${escapeHtml(result.answer_result.run_id)}</code>
      ${pill(result.answer_result.uncertainty_level)}
      ${pill(result.final_action)}
      ${result.answer_result.synthesis_mode ? pill(result.answer_result.synthesis_mode) : ""}
    </div>
    <div class="biomed-label">Retrieval Provenance</div>
    ${renderManifest(result.answer_result.retrieval_manifest)}
    <div class="biomed-label">Retrieval Bundle</div>
    ${renderRetrievalBundle(result.answer_result.retrieval_bundle)}
    <div class="biomed-label">Evidence Packet</div>
    ${renderEvidencePacket(result.answer_result.evidence_packet)}
    <div class="biomed-label">Final Answer</div>
    <div class="biomed-answer">${renderMarkdown(result.final_answer)}</div>
    <div class="biomed-label">Audit</div>
    ${renderAuditResult(result.audit)}
    <div class="biomed-label">Advisory Verifier</div>
    ${renderAdvisoryVerifier(result.advisory_verifier)}
    <div class="biomed-label">Trace Summary</div>
    ${renderTraceResult({
      run_id: result.answer_result.run_id,
      answer_run: result.answer_result,
      trace: result.trace,
      revision: result.revision,
      latest_citation_audit: result.audit,
      latest_advisory_verifier: result.advisory_verifier,
      step_telemetry: undefined,
      memory: result.answer_result.project_context_trace || {},
    })}
  `;
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
  const tabs: { id: BiomedView; label: string }[] = [
    { id: "ask", label: "Ask" },
    { id: "projects", label: "Projects" },
    { id: "evidence", label: "Evidence" },
    { id: "graph", label: "Graph" },
    { id: "watch", label: "Watch" },
    { id: "audit", label: "Audit" },
    { id: "trace", label: "Trace" },
    { id: "responsible", label: "Responsible AI" },
  ];
  return `
    <div class="biomed-tabs">
      ${tabs.map((tab) => `
        <button class="biomed-tab ${tab.id === view ? "is-active" : ""}" data-biomed-view="${tab.id}">
          ${escapeHtml(tab.label)}
        </button>
      `).join("")}
    </div>
  `;
}

function renderAsk(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-section">
      <div class="biomed-section-head">
        <div>
          <div class="biomed-title">Ask Evidence Question</div>
          <div class="biomed-subtitle">Research-only biomedical evidence workflow</div>
        </div>
        ${pill("V2.2")}
      </div>
      <div class="biomed-form">
        <label class="biomed-field">
          <span class="biomed-label">Question</span>
          <textarea id="biomed-question" rows="5">What recent evidence links microglial activation to Alzheimer's disease progression?</textarea>
        </label>
        <div class="biomed-option-panel">
          <div class="biomed-label">Workflow Template</div>
          <div class="biomed-control-grid">
            <label class="biomed-field">
              <span class="biomed-label">Template</span>
              <select id="biomed-template-select">
                <option value="">loading templates...</option>
              </select>
            </label>
            <label class="biomed-field">
              <span class="biomed-label">Save As</span>
              <input id="biomed-template-name" placeholder="custom workflow name" />
            </label>
            <label class="biomed-check"><input id="biomed-allow-live-pubmed" type="checkbox" /> opt in to live PubMed</label>
          </div>
          <div class="biomed-action-row">
            <button id="biomed-template-apply-btn">Apply Template</button>
            <button id="biomed-template-run-btn">Run Template</button>
            <button id="biomed-template-save-btn">Save Current</button>
          </div>
          <div id="biomed-template-summary" class="biomed-muted"></div>
        </div>
        <div class="biomed-control-grid">
          <label class="biomed-field">
            <span class="biomed-label">Project</span>
            <select id="biomed-project-select">
              <option value="">no project</option>
            </select>
          </label>
          <label class="biomed-field">
            <span class="biomed-label">Source</span>
            <select id="biomed-source">
              <option value="mock">mock</option>
              <option value="pubmed">pubmed</option>
            </select>
          </label>
          <label class="biomed-field">
            <span class="biomed-label">Papers</span>
            <input id="biomed-max-papers" type="number" min="1" max="20" value="10" />
          </label>
        </div>
        <details class="biomed-option-panel biomed-advanced-options">
          <summary>Advanced options</summary>
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
                <label class="biomed-check"><input id="biomed-use-planner" type="checkbox" /> LLM planner</label>
                <label class="biomed-check"><input id="biomed-use-extractor" type="checkbox" /> LLM extractor</label>
                <label class="biomed-check"><input id="biomed-use-synthesis" type="checkbox" /> LLM synthesis</label>
                <label class="biomed-check"><input id="biomed-use-verifier" type="checkbox" /> LLM verifier</label>
                <label class="biomed-check"><input id="biomed-use-revision" type="checkbox" /> LLM revision</label>
                <label class="biomed-check"><input id="biomed-use-claim-logic" type="checkbox" /> Claim logic</label>
                <label class="biomed-check"><input id="biomed-export-logic-facts" type="checkbox" /> Export facts</label>
              </div>
            </div>
          </div>
        </details>
        <div class="biomed-action-row">
          <button id="biomed-ask-btn">Answer</button>
          <button id="biomed-audited-btn">Answer + Audit</button>
        </div>
      </div>
      <div id="biomed-ask-result" class="biomed-result"></div>
    </div>
  `;
  container.querySelector<HTMLSelectElement>("#biomed-template-select")?.addEventListener("change", () => {
    const summary = container.querySelector<HTMLElement>("#biomed-template-summary");
    if (summary) summary.textContent = renderWorkflowTemplateSummary(selectedWorkflowTemplate(container));
  });
  container.querySelector<HTMLButtonElement>("#biomed-template-apply-btn")?.addEventListener("click", () => {
    const template = selectedWorkflowTemplate(container);
    if (!template) return;
    applyWorkflowTemplate(container, template);
  });
  container.querySelector<HTMLButtonElement>("#biomed-template-run-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    const button = container.querySelector<HTMLButtonElement>("#biomed-template-run-btn");
    const template = selectedWorkflowTemplate(container);
    if (!resultNode || !template) return;
    resultNode.innerHTML = renderLoading("Running saved workflow template...");
    if (button) button.disabled = true;
    const question = container.querySelector<HTMLTextAreaElement>("#biomed-question")?.value || "";
    const projectId = container.querySelector<HTMLSelectElement>("#biomed-project-select")?.value || "";
    const source = container.querySelector<HTMLSelectElement>("#biomed-source")?.value || template.source;
    const maxPapers = Number(container.querySelector<HTMLInputElement>("#biomed-max-papers")?.value || template.max_papers);
    const allowLivePubmed = Boolean(container.querySelector<HTMLInputElement>("#biomed-allow-live-pubmed")?.checked);
    try {
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
      resultNode.innerHTML = renderWorkflowTemplateRun(envelope);
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-template-save-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    const button = container.querySelector<HTMLButtonElement>("#biomed-template-save-btn");
    const name = container.querySelector<HTMLInputElement>("#biomed-template-name")?.value.trim() || "";
    if (!resultNode || !name) {
      if (resultNode) resultNode.innerHTML = '<div class="biomed-error">Template name is required.</div>';
      return;
    }
    if (button) button.disabled = true;
    try {
      const template = await api<SavedToolChainTemplate>("/api/biomed/workflow/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentWorkflowTemplatePayload(container)),
      });
      await loadWorkflowTemplates(container);
      const select = container.querySelector<HTMLSelectElement>("#biomed-template-select");
      if (select) select.value = template.template_id;
      resultNode.innerHTML = `<div class="biomed-muted">Saved workflow template: ${escapeHtml(template.name)}</div>`;
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-ask-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    if (!resultNode) return;
    const button = container.querySelector<HTMLButtonElement>("#biomed-ask-btn");
    resultNode.innerHTML = renderLoading("Running evidence search...");
    if (button) button.disabled = true;
    const question = container.querySelector<HTMLTextAreaElement>("#biomed-question")?.value || "";
    const projectId = container.querySelector<HTMLSelectElement>("#biomed-project-select")?.value || "";
    const source = container.querySelector<HTMLSelectElement>("#biomed-source")?.value || "mock";
    const maxPapers = Number(container.querySelector<HTMLInputElement>("#biomed-max-papers")?.value || 10);
    const includeRejected = Boolean(container.querySelector<HTMLInputElement>("#biomed-include-rejected")?.checked);
    const usePlanner = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-planner")?.checked);
    const executeSupportRefute = Boolean(container.querySelector<HTMLInputElement>("#biomed-execute-support-refute")?.checked);
    const useExtractor = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-extractor")?.checked);
    const useSynthesis = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-synthesis")?.checked);
    try {
      const result = await api<AnswerResult>("/api/biomed/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          project_id: projectId || null,
          source,
          max_papers: maxPapers,
          include_rejected_papers: includeRejected,
          use_llm_planner: usePlanner,
          execute_support_refute: executeSupportRefute,
          use_llm_extractor: useExtractor,
          use_llm_synthesis: useSynthesis,
        }),
      });
      resultNode.innerHTML = `
        <div class="biomed-answer-meta">
          <code>${escapeHtml(result.run_id)}</code>
          ${pill(result.uncertainty_level)}
          ${result.project_id ? pill("project") : ""}
          ${result.synthesis_mode ? pill(result.synthesis_mode) : ""}
          <button data-biomed-audit-run="${escapeHtml(result.run_id)}">Run Audit</button>
        </div>
        <div class="biomed-label">Retrieval Provenance</div>
        ${renderManifest(result.retrieval_manifest)}
        <div class="biomed-label">Retrieval Bundle</div>
        ${renderRetrievalBundle(result.retrieval_bundle)}
        <div class="biomed-label">Evidence Packet</div>
        ${renderEvidencePacket(result.evidence_packet)}
        ${result.project_context_trace ? `<div class="biomed-label">Project Trace</div><pre class="biomed-json">${escapeHtml(JSON.stringify(result.project_context_trace, null, 2))}</pre>` : ""}
        <div class="biomed-answer">${renderMarkdown(result.answer)}</div>
        <div class="biomed-label">Citations</div>
        ${renderList(result.citations.map((citation) => `${citation.title} | ${citation.paper_id}${citation.doi ? ` | doi:${citation.doi}` : ""}`))}
        <div class="biomed-label">Evidence</div>
        ${result.evidence_summary.map(renderEvidenceItem).join("") || '<div class="biomed-muted">No evidence extracted.</div>'}
        <div class="biomed-label">Limitations</div>
        ${renderList(result.limitations)}
        <div id="biomed-inline-audit-result" class="biomed-result"></div>
      `;
      resultNode.querySelector<HTMLButtonElement>("[data-biomed-audit-run]")?.addEventListener("click", async (event) => {
        const button = event.currentTarget as HTMLButtonElement;
        const runId = button.dataset.biomedAuditRun || "";
        const auditTarget = resultNode.querySelector<HTMLElement>("#biomed-inline-audit-result");
        if (!auditTarget || !runId) return;
        button.disabled = true;
        button.textContent = "Auditing...";
        try {
          const audit = await api<CitationAuditResult>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/audit`, { method: "POST" });
          auditTarget.innerHTML = renderAuditResult(audit);
        } catch (error) {
          auditTarget.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
        } finally {
          button.disabled = false;
          button.textContent = "Run Audit";
        }
      });
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-audited-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    if (!resultNode) return;
    const button = container.querySelector<HTMLButtonElement>("#biomed-audited-btn");
    resultNode.innerHTML = renderLoading("Running evidence search, audit, and revision...");
    if (button) button.disabled = true;
    const question = container.querySelector<HTMLTextAreaElement>("#biomed-question")?.value || "";
    const projectId = container.querySelector<HTMLSelectElement>("#biomed-project-select")?.value || "";
    const source = container.querySelector<HTMLSelectElement>("#biomed-source")?.value || "mock";
    const maxPapers = Number(container.querySelector<HTMLInputElement>("#biomed-max-papers")?.value || 10);
    const includeRejected = Boolean(container.querySelector<HTMLInputElement>("#biomed-include-rejected")?.checked);
    const usePlanner = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-planner")?.checked);
    const executeSupportRefute = Boolean(container.querySelector<HTMLInputElement>("#biomed-execute-support-refute")?.checked);
    const useExtractor = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-extractor")?.checked);
    const useSynthesis = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-synthesis")?.checked);
    const useRevision = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-revision")?.checked);
    const useVerifier = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-verifier")?.checked);
    const useClaimLogic = Boolean(container.querySelector<HTMLInputElement>("#biomed-use-claim-logic")?.checked);
    const exportLogicFacts = Boolean(container.querySelector<HTMLInputElement>("#biomed-export-logic-facts")?.checked);
    try {
      const result = await api<AuditedAnswerResult>("/api/biomed/answer/audited", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          project_id: projectId || null,
          source,
          max_papers: maxPapers,
          include_rejected_papers: includeRejected,
          use_llm_planner: usePlanner,
          execute_support_refute: executeSupportRefute,
          use_llm_extractor: useExtractor,
          use_llm_synthesis: useSynthesis,
          use_llm_verifier: useVerifier,
          use_llm_revision: useRevision,
          use_llm_claim_logic: useClaimLogic,
          export_logic_facts: exportLogicFacts,
        }),
      });
      resultNode.innerHTML = renderAuditedAnswer(result);
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  });
  void loadProjectOptions(container);
  void loadWorkflowTemplates(container);
}

function renderGraph(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-section">
      <div class="biomed-title">Evidence Graph</div>
      <div class="biomed-row">
        <input id="biomed-graph-topic" placeholder="topic or entity" value="microglial activation Alzheimer's disease" />
        <button id="biomed-graph-btn">Load</button>
      </div>
      <div id="biomed-graph-result" class="biomed-result"></div>
    </div>
  `;
  container.querySelector<HTMLButtonElement>("#biomed-graph-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-graph-result");
    if (!resultNode) return;
    const topic = container.querySelector<HTMLInputElement>("#biomed-graph-topic")?.value || "";
    resultNode.textContent = "Loading graph...";
    try {
      const params = new URLSearchParams({ topic });
      const graph = await api<{ nodes: { id: string; label: string; kind: string }[]; edges: { source: string; target: string; type: string }[] }>(`/api/biomed/graph?${params.toString()}`);
      resultNode.innerHTML = `
        <div class="biomed-two-col">
          <div>
            <div class="biomed-label">Nodes (${graph.nodes.length})</div>
            ${renderList(graph.nodes.slice(0, 30).map((node) => `${node.kind}: ${node.label}`))}
          </div>
          <div>
            <div class="biomed-label">Edges (${graph.edges.length})</div>
            ${renderList(graph.edges.slice(0, 30).map((edge) => `${edge.source} -> ${edge.type} -> ${edge.target}`))}
          </div>
        </div>
      `;
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
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
      <button data-biomed-check="${escapeHtml(watch.watch_id)}">Check</button>
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
    <div class="biomed-section">
      <div class="biomed-title">Citation & Evidence Audit</div>
      <div class="biomed-form">
        <div class="biomed-row">
          <input id="biomed-audit-run-id" placeholder="answer run id" />
          <button id="biomed-audit-run-btn">Run Audit</button>
        </div>
      </div>
      <div id="biomed-audit-result" class="biomed-result"></div>
      <div class="biomed-label">Recent Audits</div>
      <div id="biomed-audit-list" class="biomed-result"></div>
    </div>
  `;
  container.querySelector<HTMLButtonElement>("#biomed-audit-run-btn")?.addEventListener("click", async () => {
    const target = container.querySelector<HTMLElement>("#biomed-audit-result");
    const runId = container.querySelector<HTMLInputElement>("#biomed-audit-run-id")?.value || "";
    if (!target || !runId) return;
    target.textContent = "Running citation audit...";
    try {
      const audit = await api<CitationAuditResult>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/audit`, { method: "POST" });
      target.innerHTML = renderAuditResult(audit);
      await loadAuditList(container);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
  void loadAuditList(container);
}

async function loadAuditList(container: HTMLElement): Promise<void> {
  const target = container.querySelector<HTMLElement>("#biomed-audit-list");
  if (!target) return;
  try {
    const data = await api<{ items: { audit_id: string; run_id?: string | null; recommended_action: string; metrics?: Record<string, unknown>; created_at: string }[] }>("/api/biomed/audits");
    target.innerHTML = data.items.map((item) => `
      <div class="biomed-decision">
        <div>${pill(item.recommended_action)} <code>${escapeHtml(item.audit_id)}</code></div>
        <div class="biomed-watch-meta">
          run ${escapeHtml(item.run_id || "-")} · ${escapeHtml(item.created_at || "")}
        </div>
      </div>
    `).join("") || '<div class="biomed-muted">No audits yet.</div>';
  } catch (error) {
    target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
  }
}

function renderTrace(container: HTMLElement): void {
  container.innerHTML += `
    <div class="biomed-section">
      <div class="biomed-title">Answer Trace</div>
      <div class="biomed-form">
        <div class="biomed-row">
          <input id="biomed-trace-run-id" placeholder="answer run id" />
          <button id="biomed-trace-load-btn">Load Trace</button>
          <button id="biomed-packet-build-btn">Build Packet</button>
          <button id="biomed-provenance-load-btn">Provenance</button>
        </div>
        <div class="biomed-row">
          <input id="biomed-obsidian-dir" placeholder="workspace-relative Obsidian export dir" value="obsidian-export" />
          <label class="biomed-check"><input id="biomed-obsidian-enabled" type="checkbox" /> enable one-way export</label>
          <button id="biomed-obsidian-export-btn">Export Packet</button>
        </div>
      </div>
      <div id="biomed-trace-result" class="biomed-result"></div>
      <div id="biomed-release-tool-result" class="biomed-result"></div>
    </div>
  `;
  container.querySelector<HTMLButtonElement>("#biomed-trace-load-btn")?.addEventListener("click", async () => {
    const target = container.querySelector<HTMLElement>("#biomed-trace-result");
    const runId = container.querySelector<HTMLInputElement>("#biomed-trace-run-id")?.value || "";
    if (!target || !runId) return;
    target.textContent = "Loading trace...";
    try {
      const trace = await api<TracePayload>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/trace`);
      target.innerHTML = renderTraceResult(trace);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-packet-build-btn")?.addEventListener("click", async () => {
    const target = container.querySelector<HTMLElement>("#biomed-release-tool-result");
    const runId = container.querySelector<HTMLInputElement>("#biomed-trace-run-id")?.value || "";
    if (!target || !runId) return;
    target.textContent = "Building evidence packet...";
    try {
      const envelope = await api<ReleaseToolEnvelope<EvidencePacketBuildResult>>("/api/biomed/evidence/packet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, max_evidence_items: 12, selection_strategy: "submodular_greedy" }),
      });
      target.innerHTML = renderPacketBuildResult(envelope);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-provenance-load-btn")?.addEventListener("click", async () => {
    const target = container.querySelector<HTMLElement>("#biomed-release-tool-result");
    const runId = container.querySelector<HTMLInputElement>("#biomed-trace-run-id")?.value || "";
    if (!target || !runId) return;
    target.textContent = "Loading provenance graph...";
    try {
      const envelope = await api<ReleaseToolEnvelope<ProvenanceGraphResult>>(`/api/biomed/answer-runs/${encodeURIComponent(runId)}/provenance`);
      target.innerHTML = renderProvenanceResult(envelope);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-obsidian-export-btn")?.addEventListener("click", async () => {
    const target = container.querySelector<HTMLElement>("#biomed-release-tool-result");
    const runId = container.querySelector<HTMLInputElement>("#biomed-trace-run-id")?.value || "";
    const exportDir = container.querySelector<HTMLInputElement>("#biomed-obsidian-dir")?.value || "";
    const enabled = Boolean(container.querySelector<HTMLInputElement>("#biomed-obsidian-enabled")?.checked);
    if (!target || !runId) return;
    target.textContent = "Exporting one-way Obsidian note...";
    try {
      const envelope = await api<ReleaseToolEnvelope<ObsidianExportResult>>("/api/biomed/export/obsidian/evidence-packet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, export_dir: exportDir, enabled }),
      });
      target.innerHTML = renderObsidianExportResult(envelope);
    } catch (error) {
      target.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
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
      const view = (button.dataset.biomedView || "ask") as BiomedView;
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
  if (item && view === "evidence") {
    root.innerHTML += renderEvidenceDetail(item as unknown as EvidenceRow);
    attachDetailTabs(root, item, dispatch);
    void hydrateRetrievalBlocks(root);
    return;
  }
  if (view === "graph") {
    renderGraph(root);
  } else if (view === "projects") {
    renderProjects(root);
  } else if (view === "watch") {
    renderWatch(root);
  } else if (view === "audit") {
    renderAudit(root);
  } else if (view === "trace") {
    renderTrace(root);
  } else if (view === "responsible") {
    renderResponsible(root);
  } else if (view === "evidence") {
    root.innerHTML += '<div class="biomed-section"><div class="biomed-title">Evidence Browser</div><div class="biomed-muted">Select an evidence row to inspect entities, methods, and limitations.</div></div>';
  } else {
    renderAsk(root);
  }
  attachDetailTabs(root, item, dispatch);
}

window.AkashicDashboard.registerPlugin({
  id: "biomed_evidence",
  label: "Biomedical Evidence",
  viewLabel: "biomed",
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

  renderFilters(container: HTMLElement, dispatch: PluginDispatch): void {
    container.innerHTML = `
      <input class="filter-input" placeholder="Search evidence" value="${escapeHtml(dispatch.filters["q"] || "")}" data-filter="q" />
      <select class="filter-input" data-filter="direction">
        <option value="">all directions</option>
        ${["supports", "contradicts", "inconclusive", "background"].map((value) => `
          <option value="${value}" ${dispatch.filters["direction"] === value ? "selected" : ""}>${value}</option>
        `).join("")}
      </select>
      <input class="filter-input" placeholder="Entity" value="${escapeHtml(dispatch.filters["entity"] || "")}" data-filter="entity" />
    `;
    container.querySelectorAll<HTMLInputElement | HTMLSelectElement>("[data-filter]").forEach((node) => {
      node.addEventListener("change", () => dispatch.setFilter(node.dataset.filter || "", node.value));
      if (node instanceof HTMLInputElement) {
        node.addEventListener("keydown", (event) => {
          if (event.key === "Enter") dispatch.setFilter(node.dataset.filter || "", node.value);
        });
      }
    });
  },

  renderNavBody(container: HTMLElement, dispatch: PluginDispatch): void {
    const view = viewFromDispatch(dispatch);
    container.innerHTML = renderTabs(view);
    container.querySelectorAll<HTMLButtonElement>("[data-biomed-view]").forEach((button) => {
      button.addEventListener("click", () => {
        dispatch.setFilter("_view", button.dataset.biomedView || "ask");
        dispatch.activate();
      });
    });
  },

  renderDetail(item: Record<string, unknown> | null, container: HTMLElement, dispatch?: PluginDispatch): void {
    const view = viewFromDispatch(dispatch);
    container.innerHTML = '<div class="biomed-wrap"></div>';
    const root = container.querySelector<HTMLElement>(".biomed-wrap");
    if (!root) return;
    renderBiomedDetail(root, item, view, dispatch);
  },
});
