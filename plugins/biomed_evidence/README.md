# Biomedical Evidence Plugin

Biomedical Evidence is a research-only Akashic plugin for citation-grounded
biomedical literature work. It supports deterministic mock demos, optional
PubMed retrieval, structured router/planner output, planner-driven
primary/support/refute retrieval bundles, structured evidence extraction, cited
answers, retrieval manifests, claim-level citation audit, audit/revise traces,
claim logic entailment audit, symbolic logic fact export, project evidence
workspaces, framework-native tool guardrails, prompt context injection,
literature-source readiness checks, the controlled `search_literature` tool, a
lightweight evidence graph, and Research Watch decision logs. It is
implemented as a plugin on top of the collaborative Akashic framework, not as a
standalone clinical system.

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
- `export_evidence_report`
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
primary/support/refute retrieval records, per-query manifest IDs, deduped paper
IDs, duplicate IDs, and bundle warnings. Extracted evidence carries
`retrieval_intent` as `primary`, `support`, `refute`, or `unknown`.

Audit responses can include `ClaimAuditItem.logic_audit` with parsed logical
claim/evidence frames, deterministic entailment verdicts, triggered rules,
mismatch details, parser mode/model/prompt provenance, fallback warnings, and
optional symbolic logic facts.

Project-enabled answer responses include `project_id` and
`project_context_trace`. Saved papers are prioritized after retrieval; rejected
papers are excluded by default unless `include_rejected_papers` is true.
Project memory is never accepted as citation evidence.

## Dashboard

Start the dashboard:

```bash
uv run python main.py dashboard
```

Open `http://127.0.0.1:2236` and choose `Biomedical Evidence`.

The panel includes:

- Ask: answer biomedical research questions with citations, optional LLM
  planner/extractor/synthesis/verifier/revision, optional support/refute
  retrieval, and optional project context.
- Projects: create project workspaces, record saved/rejected/needs-review paper
  decisions, record project claims, inspect review queue items, and generate
  evidence briefs.
- Evidence: browse extracted claims, entities, limitations, and confidence.
- Graph: inspect paper, claim, and entity links.
- Watch: create, update, check, and review research-watch topics, snapshots,
  and push/skip decisions.
- Audit: inspect atomic claims, citation-support verdicts, overclaims,
  conflict awareness, uncertainty calibration, claim-logic verdicts, symbolic
  fact exports, and recommended action.
- Trace: inspect planner validation, retrieval bundle metadata, draft answer,
  final answer, revision mode/action, removed/softened claims, added
  limitations, logic-audit summary metadata, and ordered agent steps.
- Responsible AI: review the research-only operating boundary and retrieval
  limitations.

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
- `GET /api/biomed/answer-runs/{run_id}/trace`
- `GET /api/biomed/projects`
- `POST /api/biomed/projects`
- `POST /api/biomed/projects/{project_id}/papers`
- `POST /api/biomed/projects/{project_id}/claims`
- `GET /api/biomed/projects/{project_id}/review-queue`
- `POST /api/biomed/projects/{project_id}/briefs`

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
python -m pytest -q tests/test_biomed_framework_integration.py tests/test_biomed_evidence.py tests/test_biomed_api.py
python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_results.json
python -m eval.biomed_evidence.run_eval --source pubmed --live-pubmed --output /tmp/biomed_live_eval_results.json
npm run typecheck
npm run build
docker build -t bio-agent-biomed:latest .
```

Literature search, retrieval-bundle, and V2.5 claim-logic API smoke:

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

For local Ollama Pro testing, configure the OpenAI-compatible base URL and run
the same smoke with `gpt-oss:120b-cloud`. V2.5 should expose `logic_audit`,
symbolic fact exports, parser mode/model/prompt provenance, and explainable
fallback warnings if the provider-backed logic parser is unavailable or returns
schema-invalid frames. Framework pre-tool behavior is covered by
`tests/test_biomed_framework_integration.py`; dashboard/API routes keep their
existing explicit request flags.
