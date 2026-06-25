# Biomedical Evidence Plugin

Biomedical Evidence is a research-only Akashic plugin for citation-grounded
biomedical literature work. It supports deterministic mock demos, optional
PubMed retrieval, structured planning, multi-pass retrieval bundles, evidence
extraction, citation-grounded answers, claim-level audit, logic audit,
audit/revise traces, project workspaces, Research Watch, Evidence Graph v1,
Run Evidence Review, Pilot Report handoff export, provenance export, one-way
Obsidian export, and a review-first dashboard workspace.

It is implemented as a plugin on top of the collaborative Akashic framework,
not as a standalone clinical system and not as a separate chat runtime.

## Default Mode

The default source is `mock`, so the demo works without network access or API
keys. Use `source=pubmed` to query NCBI E-utilities. Optional environment
variables:

- `NCBI_EMAIL`
- `NCBI_API_KEY`

Runtime storage is created under the active workspace:

```text
biomed_evidence/biomed.db
```

Use `/api/biomed/literature/check` or the `check_literature_access` tool to
verify source readiness before running live literature workflows. The readiness
check exercises search, retrieval manifest creation, paper persistence, and
abstract coverage.

Optional LLM planner, extractor, synthesizer, verifier, and revision paths use
the framework-configured provider. They are request-gated with
`use_llm_planner`, `use_llm_extractor`, `use_llm_synthesis`,
`use_llm_verifier`, `use_llm_revision`, and `use_llm_claim_logic`; default
demos, tests, and eval remain deterministic and keyless. With
`use_llm_claim_logic=true`, V2.2 attempts provider-backed claim/evidence logic
frame parsing and then validates every frame strictly before deterministic
entailment rules run. If the provider is unavailable or emits invalid JSON,
missing frames, or schema-invalid fields, the audit fails fast into
deterministic frame parsing and records the fallback reason.

Claim logic can be enabled with `use_llm_claim_logic=true`; symbolic fact
export can be added with `export_logic_facts=true`. The fact exporter is a
deterministic transformation over validated logical frames and audit results. It
does not call an LLM and does not override the deterministic audit verdict.

## Framework Integration

V2.3 uses the host framework's plugin lifecycle instead of keeping every
control point inside the biomedical service:

- `_conf_schema.json` defines safe plugin defaults: mock source, disabled live
  PubMed tool calls, count caps, prompt-context injection, active-project
  policy, controlled-search abstract requirement, and optional default LLM
  flags.
- Plugin KV stores lightweight local preferences such as last source, active
  project ID, active watch ID, and last LLM option set. KV is never biomedical
  evidence.
- `@on_tool_pre` guards all Biomedical Evidence tools during ordinary agent
  tool calls. It denies clinical or patient-specific requests, prevents
  accidental live PubMed use when disabled, caps oversized requests, validates
  project IDs, applies safe defaults, and records hook trace reasons.
- `prompt_render_modules()` injects a concise research-only boundary and active
  project context only when the turn is biomedical or a project is active.
- `before_turn_modules()` adds a clinical boundary guard that can abort
  patient-specific or clinical requests before memory/context preparation.
- Dashboard Chat uses the framework's generic `dashboard` channel. Biomedical
  behavior remains plugin-side through prompt modules, before-turn modules,
  tool hooks, and registered tools.
- Sensitive write/export/review tools marked `requires_confirmation=true` deny
  in Dashboard Chat until the framework provides durable approval and
  resume-after-approval semantics.

The framework guard is an outer safety layer. API/dashboard service routes keep
their existing service-level validation, refusal, audit, and trace behavior.

## Tools

Registered agent tools:

- `plan_biomedical_search`
- `check_literature_access`
- `search_literature`
- `search_biomedical_literature`
- `fetch_biomedical_paper`
- `extract_evidence`
- `answer_with_evidence`
- `answer_with_audit`
- `create_biomed_project`
- `list_biomed_projects`
- `update_biomed_project`
- `record_project_paper_decision`
- `save_project_paper`
- `reject_project_paper`
- `list_project_paper_decisions`
- `record_project_claim`
- `save_project_claim`
- `list_project_evidence`
- `list_project_review_queue`
- `generate_project_evidence_brief`
- `watch_research_topic`
- `list_research_watch_topics`
- `update_research_watch_topic`
- `delete_research_watch_topic`
- `get_evidence_graph`
- `get_evidence_card`
- `validate_evidence_graph`
- `find_evidence_path`
- `export_evidence_graph_json`
- `get_run_evidence_review`
- `record_run_review_decision`
- `list_run_review_decisions`
- `export_run_review_packet`
- `run_multi_pass_literature_search`
- `extract_evidence_batch`
- `analyze_coverage_gaps`
- `build_evidence_packet`
- `get_evidence_packet`
- `get_answer_trace`
- `export_provenance_graph`
- `export_evidence_packet_to_obsidian`
- `export_project_to_obsidian`
- `export_research_watch_to_obsidian`
- `export_evidence_report`
- `run_saved_tool_chain_template`
- `list_biomed_workflow_templates`
- `validate_citation_support`
- `audit_biomedical_answer`
- `find_conflicting_evidence`

All tool outputs are JSON-compatible envelopes so they can be used by the agent,
FastAPI routes, tests, and the dashboard panel.

Search responses include a `retrieval_manifest` with source, original query,
compiled query, API parameters, pagination, result counts, warnings, and
returned paper IDs.

Literature access checks return `ok`, `ready`, source liveness, item count,
abstract coverage, stored-paper count, NCBI identity flags, retrieval manifest,
items, warnings, and errors.

## V2.6 Multi-Pass Gap-Directed Retrieval

V2.6 builds on `search_literature` with a bounded multi-pass retrieval loop:

```text
router / guardrail
  -> planner subquestions
  -> search_literature per query
  -> retrieval bundle + coverage matrix
  -> optional gap-directed follow-up
  -> structured evidence packet
  -> synthesis / audit / revision
```

Answer responses can include `evidence_packet` with planner mode, retrieval
manifest IDs, paper IDs, evidence IDs, supported/conflicting claims,
limitations, coverage matrix rows, gap decisions, source warnings, and a stop
reason. The final answer path uses this curated packet and evidence items, not
raw search noise or unsupported intermediate summaries.

## V2.5 Controlled Literature Search Tool

V2.5 promotes literature retrieval into the agent's core controlled tool
surface. The `search_literature` tool wraps the existing biomedical search
service contract with a clearer agent-facing boundary:

```text
planner query
  -> search_literature
  -> normalized papers + retrieval manifest + coverage/source trace
  -> extraction / synthesis / audit
```

The tool supports `mock` and `pubmed`, returns structured paper records,
manifest metadata, coverage metrics, source trace, warnings, errors, and stored
paper IDs. It persists papers when requested and keeps
`check_literature_access` as the separate readiness/smoke path. It must not
generate answers, browse arbitrary websites, or bypass the framework
`@on_tool_pre` clinical/source/count/project guards. Europe PMC is the preferred
next structured adapter after the PubMed path is stable.

Planner-enabled answer responses can also include a `retrieval_bundle` with
per-query retrieval records, subquestions, retrieval intents, pass numbers,
per-query manifest IDs, coverage rows, gap decisions, deduped paper IDs,
duplicate IDs, and bundle warnings. Extracted evidence carries
`retrieval_intent` as `primary`, `background`, `support`, `refute`,
`mechanism`, `limitation`, `recent`, or `unknown`.

Audit responses can include `ClaimAuditItem.logic_audit` with parsed logical
claim/evidence frames, deterministic entailment verdicts, triggered rules,
mismatch details, parser mode/model/prompt provenance, fallback warnings, and
optional symbolic logic facts.

Project-enabled answer responses include `project_id` and
`project_context_trace`. Saved papers are prioritized after retrieval; rejected
papers are excluded by default unless `include_rejected_papers` is true.
Project memory is never accepted as citation evidence.

## Release 1.0 Toolized Workflow

Release 1.0 exposes the internal evidence workflow as independently callable
tools and API routes:

- `run_multi_pass_literature_search` / `POST /api/biomed/retrieval/multi-pass`
- `extract_evidence_batch` / `POST /api/biomed/evidence/extract-batch`
- `analyze_coverage_gaps` / `POST /api/biomed/evidence/coverage-gaps`
- `build_evidence_packet` / `POST /api/biomed/evidence/packet`
- `get_evidence_packet` / `GET /api/biomed/answer-runs/{run_id}/evidence-packet`
- `get_answer_trace` / `GET /api/biomed/answer-runs/{run_id}/trace`
- `export_provenance_graph` / `GET /api/biomed/answer-runs/{run_id}/provenance`
- `export_evidence_packet_to_obsidian`
- `export_project_to_obsidian`
- `export_research_watch_to_obsidian`

Every Release 1.0 tool returns `release-tool-envelope-v1`, including `ok`,
`result`, `warnings`, `errors`, `error_code`, `trace`, stable `ids`, and
metadata. Clinical, source-policy, budget, unknown-ID, export-path, and
provenance failures are structured and recoverable where appropriate.

Memory bridge behavior is explicit: memory may guide planner preferences,
saved/rejected-paper handling, project selection, and reviewer workflow, but
`memory_as_evidence` remains false. The trace API includes memory effects,
budget snapshots, and advisory step telemetry.

Release 1.0 also adds deterministic/advisory mathematical aids:

- submodular-style packet selection with selected/dropped evidence IDs, drop
  reasons, coverage contribution, token estimate, and protected
  conflict/limitation retention;
- contextual-bandit-style retrieval advisory that recommends stop/broaden or
  support/refute/mechanism/limitation search without controlling runtime;
- PROV/OpenLineage-style provenance graph export that links answer, papers,
  evidence, manifests, packets, audits, logic audits, revisions, activities,
  agents, and tools while redacting prompts, provider raw responses, secrets,
  and API keys;
- Obsidian-compatible Markdown export for evidence packets, projects, and
  Watch topics. Export is one-way and disabled by default.

## Biomedical Evidence Graph v1

The v1 graph layer is an internal detachable module under
`plugins/biomed_evidence/graph/`. It formalizes the previous dashboard graph as
a typed property graph with `schema_version=biomed-evidence-graph-v1`.

Node types:

- `Paper`
- `EvidenceSpan`
- `Claim`
- `Entity`
- `Method`
- `Limitation`
- `RetrievalManifest`
- `EvidencePacket`
- `AnswerRun`
- `AuditResult`

Core paths:

```text
RetrievalManifest -> Paper -> EvidenceSpan -> Claim
AnswerRun -> EvidencePacket -> EvidenceSpan
AuditResult -> Claim
```

Evidence Graph and Provenance Graph are separate projections. The Evidence
Graph represents claim/evidence/source relationships for evidence cards, path
queries, validation, and redacted JSON export. The Provenance Graph represents
execution lineage: tools, activities, agents, trace steps, and redacted runtime
artifacts. They share stable IDs such as `run_id`, `paper_id`, `evidence_id`,
`retrieval_id`, `packet_id`, and `audit_id`, but they answer different review
questions.

Graph validation enforces the first product invariants:

- supported claims must have an incoming `EVIDENCE_SUPPORTS_CLAIM` edge from an
  `EvidenceSpan`;
- each `EvidenceSpan` must trace to exactly one `Paper`;
- clinical refusal run graphs must not contain biomedical `Claim` nodes or
  `ANSWER_CITES_CLAIM` edges;
- direction-derived evidence edges cannot invert support and contradiction.

The graph JSON export is read-only and does not write files. Export helpers and
the `/api/biomed/graph/v1/export/json` route recursively redact raw prompts,
provider responses, API keys, tokens, secrets, authorization headers, and common
secret-like strings before returning payloads.

## Run Evidence Review

Run Evidence Review is the product-facing layer above Evidence Graph v1. For an
answer run, it persists an immutable redacted graph snapshot after audited
answer generation or manual run audit, then returns a compact review contract:
claim statuses, audit verdicts, evidence cards, paper/evidence IDs, validation
summary, and links to graph, trace, provenance, and JSON export views.

Snapshot-backed review uses `schema_version=biomed-evidence-review-v1`.
Legacy runs without snapshots can be backfilled with:

```text
POST /api/biomed/answer-runs/{run_id}/evidence-review/snapshot
POST /api/biomed/evidence-graph/snapshots/backfill
```

Snapshot rows are immutable. Review responses derive `snapshot.stale` when a
newer citation audit exists than the latest persisted graph snapshot. Snapshot
diffs are available at:

```text
GET /api/biomed/answer-runs/{run_id}/evidence-review/snapshot-diff
```

Invalid or stale graph situations are captured in the project review queue only
when the answer run has a valid `project_id`. Runs without project scope keep
the warning run-local.

Review access and decision loop:

```text
GET /api/biomed/answer-runs/{run_id}/evidence-review
POST /api/biomed/answer-runs/{run_id}/evidence-review/decisions
GET /api/biomed/answer-runs/{run_id}/evidence-review/decisions
GET /api/biomed/answer-runs/{run_id}/evidence-review/packet
```

The `get_run_evidence_review`, `record_run_review_decision`,
`list_run_review_decisions`, and `export_run_review_packet` tools expose the
same review loop to agent workflows. Reviewer notes are persisted as QA
metadata and are never treated as biomedical evidence. Snapshot creation is
intentionally not exposed as an agent tool in this phase.

## Release 2.1 Team Evidence Review Pilot

Release 2.1 adds the team handoff layer around existing audited runs:

```text
/biomed audit
  -> Run Evidence Review / evidence packet / trace / provenance links
  -> /biomed pilot-report <run_id> [--format json|markdown]
  -> reviewer decision/export
```

Pilot Report is available through the existing export surface:

```text
GET /api/biomed/export?run_id={run_id}&report_type=pilot&format=json
GET /api/biomed/export?run_id={run_id}&report_type=pilot&format=markdown
```

It returns `schema_version=biomed-pilot-report-v1`, ROI fields, review state,
artifact links, and run-level observability derived from persisted trace
artifacts where available. Cost/cache fields remain nullable until real
billing/cache telemetry exists. Pilot Report is not a new evidence source:
biomedical support still comes from retrieved papers, evidence spans,
manifests, audits, logic audit, and evidence packets.

Dashboard Chat also accepts:

```text
/biomed pilot-report <run_id> --format markdown
/biomed template run <template_id> "question" [--source mock|pubmed]
```

Built-in pilot templates cover literature audit, weekly Watch review, reviewer
handoff, evidence packet export, and conflicting-evidence check. Live PubMed
remains opt-in behind `allow_live_pubmed_tools`.

## Release 2.0 Full-Text Contract

Release 2.0 extends the abstract-level workflow with deterministic full-text/PDF
ingestion behind the same graph and review contracts:

```text
paper metadata
  -> full-text document + sections
  -> section/page/offset span locators
  -> evidence extraction
  -> evidence packet + audit
  -> Evidence Graph snapshot + Run Evidence Review
```

PDF or full-text parser output is never treated as biomedical evidence by
itself. It can only provide source sections and span locators for extracted
`EvidenceItem` records. Full-text-derived evidence remains subject to citation
audit, logic audit, graph validation, snapshot review, and expert review.

Research Watch drift and Argument Graph v2 are also Release 2.0 review aids.
They are advisory reviewer signals, not evidence, and they do not control
runtime behavior.

## Dashboard

Start the dashboard:

```bash
uv run python main.py dashboard
```

Open `http://127.0.0.1:2236` and choose `Biomedical Evidence`.

The panel uses a quieter Codex-style workspace shell:

- Chat: framework Dashboard Chat session access from the biomed workspace.
- Runs: template-first workflow runner and main run inspector. Review,
  snapshot diff, trace, evidence packet, audit, logic, argument, math, and
  provenance views live in the selected run inspector.
- Review Queue: project workspaces, saved/rejected/needs-review paper
  decisions, project claims, queue items, and evidence briefs.
- Library: project context, Research Watch, evidence records, and graph lookup.
- Settings: research-only operating boundary, clinical refusal behavior,
  memory-as-context policy, and retrieval limitations.

Trace/Export and Audit now start from recent answer runs. Reviewers can load a
run, inspect trace or latest audit, build an evidence packet, view provenance,
and trigger disabled-by-default one-way Obsidian export without leaving the
run context.

## API

The plugin mounts `/api/biomed/*` routes for search, paper detail, evidence
extraction, answer runs, audited answer generation, claim-level citation audit,
trace retrieval, project workspaces, graph retrieval, watch CRUD/check/events,
conflict checks, and export.

Common routes:

- `POST /api/biomed/plan`
- `POST /api/biomed/literature/check`
- `POST /api/biomed/literature/search`
- `GET /api/biomed/search`
- `POST /api/biomed/answer`
- `POST /api/biomed/answer/audited`
- `POST /api/biomed/answer-runs/{run_id}/audit`
- `GET /api/biomed/export?run_id={run_id}&report_type=pilot`
- `GET /api/biomed/answer-runs/{run_id}/trace`
- `GET /api/biomed/answer-runs/{run_id}/evidence-graph`
- `GET /api/biomed/answer-runs/{run_id}/argument-graph`
- `GET /api/biomed/answer-runs/{run_id}/evidence-review`
- `POST /api/biomed/answer-runs/{run_id}/evidence-review/snapshot`
- `GET /api/biomed/watch/{watch_id}/drift`
- `POST /api/biomed/papers/{paper_id}/full-text`
- `GET /api/biomed/papers/{paper_id}/full-text`
- `GET /api/biomed/projects`
- `POST /api/biomed/projects`
- `POST /api/biomed/projects/{project_id}/papers`
- `POST /api/biomed/projects/{project_id}/claims`
- `GET /api/biomed/projects/{project_id}/review-queue`
- `POST /api/biomed/projects/{project_id}/briefs`
- `GET /api/biomed/graph/schema`
- `GET /api/biomed/graph/v1`
- `POST /api/biomed/graph/v1/validate`
- `GET /api/biomed/graph/v1/evidence-card/{claim_id}`
- `GET /api/biomed/graph/v1/path`
- `GET /api/biomed/graph/v1/export/json`

## Safety Boundary

This plugin is not a clinical decision system. It refuses or redirects clinical
diagnosis, treatment, prognosis, medication, and patient-specific requests.
Project memory can personalize context, but it is never treated as biomedical
fact.

`answer_with_audit` preserves the older citation-grounded answer path as a
draft, runs deterministic claim-level audit, revises or refuses risky claims,
optionally uses an injected framework LLM provider for schema-validated
planning and evidence-grounded revision, repairs or rejects LLM-generated lines
that fail post-audit, falls back to deterministic behavior when no
provider/model is configured, and persists the trace for reviewer inspection.

## Validation

Useful local checks:

```bash
python -m pytest -q tests/test_biomed_evidence_graph.py tests/test_biomed_framework_integration.py tests/test_biomed_evidence.py tests/test_biomed_api.py
python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_results.json
python -m eval.biomed_evidence.run_eval --source pubmed --live-pubmed --output /tmp/biomed_live_eval_results.json
npm run typecheck
npm run build
docker build -t bio-agent-biomed:latest .
```

Literature search, V2.6 retrieval-bundle/evidence-packet, and claim-logic API smoke:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/literature/check" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "microglia Alzheimer disease",
    "source": "mock",
    "max_results": 3
  }' | jq '{ok, ready, source, item_count, abstract_coverage, warnings}'

curl -s -X POST "http://127.0.0.1:2236/api/biomed/literature/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "microglia Alzheimer disease",
    "source": "mock",
    "max_results": 3,
    "retrieval_intent": "primary",
    "require_abstract": true,
    "store": true
  }' | jq '{
    source,
    item_count: .coverage.item_count,
    abstract_coverage: .coverage.abstract_coverage,
    stored: .coverage.stored_paper_count,
    retrieval_id: .retrieval_manifest.retrieval_id,
    first_paper: .items[0].paper_id,
    warnings
  }'

curl -s -X POST "http://127.0.0.1:2236/api/biomed/plan" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What recent evidence links microglial activation to Alzheimer disease progression?",
    "source": "mock",
    "max_results": 5,
    "use_llm_planner": true
  }' | jq '{planner_mode: .query_plan.planner_mode, valid: .validation.valid}'

curl -s -X POST "http://127.0.0.1:2236/api/biomed/answer/audited" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What recent evidence links microglial activation to Alzheimer disease progression?",
    "source": "mock",
    "max_papers": 5,
    "use_llm_planner": true,
    "use_llm_extractor": true,
    "use_llm_synthesis": true,
    "use_llm_verifier": true,
    "use_llm_revision": true,
    "execute_support_refute": true,
    "use_llm_claim_logic": true,
    "export_logic_facts": true
  }' | jq '{
    planner_mode: .answer_result.query_plan.planner_mode,
    extraction_modes: ([.answer_result.evidence_summary[].extraction_mode] | unique),
    synthesis_mode: .answer_result.synthesis_mode,
    verifier_mode: .advisory_verifier.verifier_mode,
    revision_mode: .revision.revision_mode,
    multi_query: .answer_result.retrieval_bundle.executed_multi_query,
    retrieval_records: (.answer_result.retrieval_bundle.records | length),
    logic_trace: ([.trace[] | select(.step=="audit") | .metadata.logic_audit][0]),
    parser_modes: ([.trace[] | select(.step=="audit") | .metadata.logic_audit.parser_mode_counts][0]),
    parser_models: ([.trace[] | select(.step=="audit") | .metadata.logic_audit.parser_models][0]),
    logic_verdicts: [.audit.claim_audits[] | .logic_audit.logic_verdict],
    fact_exports: [.audit.claim_audits[] | .logic_audit.logic_fact_export.export_id],
    trace_steps: (.trace | length)
  }'
```

For local DeepSeek testing, set `DEEPSEEK_API_KEY` and run the same smoke with
`deepseek-v4-pro`. V2.5 should expose `logic_audit`, symbolic fact exports,
parser mode/model/prompt provenance, and explainable fallback warnings if the
provider-backed logic parser is unavailable or returns schema-invalid frames.
Framework pre-tool behavior is covered by
`tests/test_biomed_framework_integration.py`; dashboard/API routes keep their
existing explicit request flags.
