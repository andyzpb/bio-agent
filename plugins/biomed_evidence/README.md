# Biomedical Evidence Plugin

Biomedical Evidence is a research-only Akashic plugin for citation-grounded
biomedical literature work. It supports deterministic mock demos, optional
PubMed retrieval, structured evidence extraction, cited answers, a lightweight
evidence graph, and Research Watch decision logs.

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

## Tools

Registered agent tools:

- `search_biomedical_literature`
- `fetch_biomedical_paper`
- `extract_evidence`
- `answer_with_evidence`
- `watch_research_topic`
- `list_research_watch_topics`
- `update_research_watch_topic`
- `delete_research_watch_topic`
- `get_evidence_graph`
- `export_evidence_report`

All tool outputs are JSON-compatible envelopes so they can be used by the agent,
FastAPI routes, tests, and the dashboard panel.

## Dashboard

Start the dashboard:

```bash
uv run python main.py dashboard
```

Open `http://127.0.0.1:2236` and choose `Biomedical Evidence`.

The panel includes:

- Ask: answer biomedical research questions with citations.
- Evidence: browse extracted claims, entities, limitations, and confidence.
- Graph: inspect paper, claim, and entity links.
- Watch: create, update, check, and review research-watch topics.
- Responsible AI: review the research-only operating boundary.

## API

The plugin mounts `/api/biomed/*` routes for search, paper detail, evidence
extraction, answer runs, graph retrieval, watch CRUD/check/events, audit, and
export.

## Safety Boundary

This plugin is not a clinical decision system. It refuses or redirects clinical
diagnosis, treatment, prognosis, medication, and patient-specific requests.
Project memory can personalize context, but it is never treated as biomedical
fact.

## Validation

Useful local checks:

```bash
python -m pytest -q tests/test_biomed_evidence.py tests/test_biomed_api.py
python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_results.json
npm run typecheck
npm run build
docker build -t bio-agent-biomed:latest .
```
