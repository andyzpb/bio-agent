/// <reference path="../../types/akashic-dashboard.d.ts" />

type BiomedView = "ask" | "evidence" | "graph" | "watch" | "audit" | "trace" | "responsible";

interface EvidenceRow {
  evidence_id: string;
  paper_id: string;
  retrieval_id?: string | null;
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

interface AnswerResult {
  run_id: string;
  retrieval_id?: string | null;
  retrieval_manifest?: RetrievalManifest | null;
  answer: string;
  citations: { paper_id: string; title: string; doi?: string | null; url?: string | null; cited_claim: string }[];
  evidence_summary: EvidenceRow[];
  conflicting_evidence: EvidenceRow[];
  limitations: string[];
  uncertainty_level: string;
  suggested_next_steps: string[];
  disclaimer: string;
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
  revision: AnswerRevision;
  trace: AgentTraceStep[];
  final_action: string;
}

interface TracePayload {
  run_id: string;
  answer_run: AnswerResult;
  trace: AgentTraceStep[];
  revision?: AnswerRevision | null;
  latest_citation_audit?: CitationAuditResult | null;
}

function viewFromDispatch(dispatch?: PluginDispatch): BiomedView {
  const value = dispatch?.filters["_view"];
  if (value === "graph" || value === "watch" || value === "audit" || value === "trace" || value === "responsible" || value === "evidence") {
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
        <code>${escapeHtml(item.paper_id)}</code>
      </div>
      <div class="biomed-evidence-claim">${escapeHtml(item.claim)}</div>
      <div class="biomed-evidence-finding">${escapeHtml(item.finding)}</div>
    </div>
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

function renderTraceResult(payload: TracePayload): string {
  const revision = payload.revision;
  const audit = payload.latest_citation_audit;
  return `
    <div class="biomed-provenance">
      <div class="biomed-provenance-grid">
        <div><span>Run</span><code>${escapeHtml(payload.run_id)}</code></div>
        <div><span>Action</span><strong>${escapeHtml(revision?.revision_action || "-")}</strong></div>
        <div><span>Mode</span><strong>${escapeHtml(revision?.revision_mode || "-")}</strong></div>
        <div><span>Audit</span><code>${escapeHtml(audit?.audit_id || "-")}</code></div>
        <div><span>Trace</span><strong>${payload.trace.length}</strong></div>
      </div>
    </div>
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
    </div>
    <div class="biomed-label">Retrieval Provenance</div>
    ${renderManifest(result.answer_result.retrieval_manifest)}
    <div class="biomed-label">Final Answer</div>
    <div class="biomed-answer">${renderMarkdown(result.final_answer)}</div>
    <div class="biomed-label">Audit</div>
    ${renderAuditResult(result.audit)}
    <div class="biomed-label">Trace Summary</div>
    ${renderTraceResult({
      run_id: result.answer_result.run_id,
      answer_run: result.answer_result,
      trace: result.trace,
      revision: result.revision,
      latest_citation_audit: result.audit,
    })}
  `;
}

function renderTabs(view: BiomedView): string {
  const tabs: { id: BiomedView; label: string }[] = [
    { id: "ask", label: "Ask" },
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
      <div class="biomed-title">Ask Evidence Question</div>
      <div class="biomed-form">
        <textarea id="biomed-question" rows="4">What recent evidence links microglial activation to Alzheimer's disease progression?</textarea>
        <div class="biomed-row">
          <select id="biomed-source">
            <option value="mock">mock</option>
            <option value="pubmed">pubmed</option>
          </select>
          <input id="biomed-max-papers" type="number" min="1" max="20" value="10" />
          <button id="biomed-ask-btn">Answer</button>
          <button id="biomed-audited-btn">Answer + Audit</button>
        </div>
      </div>
      <div id="biomed-ask-result" class="biomed-result"></div>
    </div>
  `;
  container.querySelector<HTMLButtonElement>("#biomed-ask-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    if (!resultNode) return;
    resultNode.textContent = "Running evidence search...";
    const question = container.querySelector<HTMLTextAreaElement>("#biomed-question")?.value || "";
    const source = container.querySelector<HTMLSelectElement>("#biomed-source")?.value || "mock";
    const maxPapers = Number(container.querySelector<HTMLInputElement>("#biomed-max-papers")?.value || 10);
    try {
      const result = await api<AnswerResult>("/api/biomed/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, source, max_papers: maxPapers }),
      });
      resultNode.innerHTML = `
        <div class="biomed-answer-meta">
          <code>${escapeHtml(result.run_id)}</code>
          ${pill(result.uncertainty_level)}
          <button data-biomed-audit-run="${escapeHtml(result.run_id)}">Run Audit</button>
        </div>
        <div class="biomed-label">Retrieval Provenance</div>
        ${renderManifest(result.retrieval_manifest)}
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
    }
  });
  container.querySelector<HTMLButtonElement>("#biomed-audited-btn")?.addEventListener("click", async () => {
    const resultNode = container.querySelector<HTMLElement>("#biomed-ask-result");
    if (!resultNode) return;
    resultNode.textContent = "Running evidence search, audit, and revision...";
    const question = container.querySelector<HTMLTextAreaElement>("#biomed-question")?.value || "";
    const source = container.querySelector<HTMLSelectElement>("#biomed-source")?.value || "mock";
    const maxPapers = Number(container.querySelector<HTMLInputElement>("#biomed-max-papers")?.value || 10);
    try {
      const result = await api<AuditedAnswerResult>("/api/biomed/answer/audited", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, source, max_papers: maxPapers }),
      });
      resultNode.innerHTML = renderAuditedAnswer(result);
    } catch (error) {
      resultNode.innerHTML = `<div class="biomed-error">${escapeHtml(String(error))}</div>`;
    }
  });
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
        </div>
      </div>
      <div id="biomed-trace-result" class="biomed-result"></div>
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
        <li>Citation presence is not enough; V1.3 audits claim-level support, overclaims, conflicts, and uncertainty calibration.</li>
        <li>V1.4 routes draft answers through audit, deterministic revision, and persisted trace before final presentation.</li>
      </ul>
    </div>
  `;
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
      button.addEventListener("click", () => dispatch.setFilter("_view", button.dataset.biomedView || "ask"));
    });
  },

  renderDetail(item: Record<string, unknown> | null, container: HTMLElement, dispatch?: PluginDispatch): void {
    const view = viewFromDispatch(dispatch);
    container.innerHTML = `<div class="biomed-wrap">${renderTabs(view)}</div>`;
    container.querySelectorAll<HTMLButtonElement>("[data-biomed-view]").forEach((button) => {
      button.addEventListener("click", () => dispatch?.setFilter("_view", button.dataset.biomedView || "ask"));
    });
    const root = container.querySelector<HTMLElement>(".biomed-wrap");
    if (!root) return;
    if (item && view === "evidence") {
      root.innerHTML += renderEvidenceDetail(item as unknown as EvidenceRow);
      void hydrateRetrievalBlocks(root);
      return;
    }
    if (view === "graph") {
      renderGraph(root);
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
  },
});
