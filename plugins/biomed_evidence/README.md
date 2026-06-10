# Biomedical Evidence Plugin

Biomedical Evidence is a research-only Akashic plugin for citation-grounded
biomedical literature work. It supports deterministic mock demos, optional
PubMed retrieval, structured router/planner output, planner-driven
primary/support/refute retrieval bundles, structured evidence extraction, cited
answers, retrieval manifests, claim-level citation audit, audit/revise traces,
a lightweight evidence graph, and Research Watch decision logs. It is
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

Optional LLM planner/revision uses the framework-configured provider. It is
request-gated with `use_llm_planner` and `use_llm_revision`; default demos,
tests, and eval remain deterministic and keyless.

## Tools

Registered agent tools:

- `plan_biomedical_search`
- `search_biomedical_literature`
- `fetch_biomedical_paper`
- `extract_evidence`
- `answer_with_evidence`
- `answer_with_audit`
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

Planner-enabled answer responses can also include a `retrieval_bundle` with
primary/support/refute retrieval records, per-query manifest IDs, deduped paper
IDs, duplicate IDs, and bundle warnings. Extracted evidence carries
`retrieval_intent` as `primary`, `support`, `refute`, or `unknown`.

## Dashboard

Start the dashboard:

```bash
uv run python main.py dashboard
```

Open `http://127.0.0.1:2236` and choose `Biomedical Evidence`.

The panel includes:

- Ask: answer biomedical research questions with citations, optional LLM
  planner/revision, and optional support/refute retrieval.
- Evidence: browse extracted claims, entities, limitations, and confidence.
- Graph: inspect paper, claim, and entity links.
- Watch: create, update, check, and review research-watch topics, snapshots,
  and push/skip decisions.
- Audit: inspect atomic claims, citation-support verdicts, overclaims,
  conflict awareness, uncertainty calibration, and recommended action.
- Trace: inspect planner validation, retrieval bundle metadata, draft answer,
  final answer, revision mode/action, removed/softened claims, added
  limitations, and ordered agent steps.
- Responsible AI: review the research-only operating boundary and retrieval
  limitations.

## API

The plugin mounts `/api/biomed/*` routes for search, paper detail, evidence
extraction, answer runs, audited answer generation, claim-level citation audit,
trace retrieval, graph retrieval, watch CRUD/check/events, conflict checks, and
export.

Common routes:

- `POST /api/biomed/plan`
- `GET /api/biomed/search`
- `POST /api/biomed/answer`
- `POST /api/biomed/answer/audited`
- `POST /api/biomed/answer-runs/{run_id}/audit`
- `GET /api/biomed/answer-runs/{run_id}/trace`

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
python -m pytest -q tests/test_biomed_evidence.py tests/test_biomed_api.py
python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_results.json
python -m eval.biomed_evidence.run_eval --source pubmed --live-pubmed --output /tmp/biomed_live_eval_results.json
npm run typecheck
npm run build
docker build -t bio-agent-biomed:latest .
```

Planner and V1.6 retrieval-bundle API smoke:

```bash
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
    "use_llm_revision": true,
    "execute_support_refute": true
  }' | jq '{
    planner_mode: .answer_result.query_plan.planner_mode,
    revision_mode: .revision.revision_mode,
    multi_query: .answer_result.retrieval_bundle.executed_multi_query,
    retrieval_records: (.answer_result.retrieval_bundle.records | length),
    trace_steps: (.trace | length)
  }'
```
