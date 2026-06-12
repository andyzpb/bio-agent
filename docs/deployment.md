# Biomedical Evidence Agent Deployment

## Local

```bash
uv venv
uv pip install -r requirements.txt
uv pip install -r requirements-dev.txt
uv run python main.py init
uv run python main.py dashboard
```

Open the dashboard at `http://127.0.0.1:2236` and select `Biomedical Evidence`.

## Literature Sources

- `mock` is the default and requires no network or API keys.
- `pubmed` uses NCBI E-utilities. Optional environment variables:
  - `NCBI_EMAIL`
  - `NCBI_API_KEY`

Check source readiness before relying on live literature workflows:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/literature/check" \
  -H "Content-Type: application/json" \
  -d '{"query":"microglia Alzheimer disease","source":"pubmed","max_results":3}' | jq
```

The response reports `ok`, `ready`, item count, abstract coverage, NCBI
identity flags, retrieval manifest, warnings, and errors.

Run the controlled V2.5 literature search tool path before answer generation:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/literature/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"microglia Alzheimer disease","source":"mock","max_results":3,"retrieval_intent":"primary","require_abstract":true,"store":true}' \
  | jq '{source, item_count:.coverage.item_count, stored:.coverage.stored_paper_count, abstract_coverage:.coverage.abstract_coverage, retrieval_id:.retrieval_manifest.retrieval_id, warnings}'
```

`check_literature_access` is a readiness smoke. `search_literature` is the
agent-facing retrieval path that returns normalized paper records, manifest,
coverage, source trace, warnings, and errors; it does not synthesize answers.

## Docker

```bash
docker compose up --build
```

The compose file mounts `.akashic-workspace` as the runtime workspace and exposes the dashboard on port `2236`.

## Troubleshooting

- If PubMed requests fail, switch the source back to `mock`.
- If PubMed requests are transiently unstable, inspect retrieval manifest warnings for retry telemetry.
- If the literature readiness check returns `ok=true` but `ready=false`, inspect
  abstract coverage and warnings before running answer generation.
- If plugin panels do not appear, run `npm ci` and `npm run build`.
- If the dashboard starts but has no evidence rows, ask a mock evidence question first; extraction stores evidence in `biomed_evidence/biomed.db`.
