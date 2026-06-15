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

Run the controlled literature search tool path before answer generation:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/literature/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"microglia Alzheimer disease","source":"mock","max_results":3,"retrieval_intent":"primary","require_abstract":true,"store":true}' \
  | jq '{source, item_count:.coverage.item_count, stored:.coverage.stored_paper_count, abstract_coverage:.coverage.abstract_coverage, retrieval_id:.retrieval_manifest.retrieval_id, warnings}'
```

`check_literature_access` is a readiness smoke. `search_literature` is the
agent-facing retrieval path that returns normalized paper records, manifest,
coverage, source trace, warnings, and errors; it does not synthesize answers.

Run the V2.6 multi-pass audited answer path to verify planner subquestions,
coverage matrix, optional gap follow-up, and evidence packet assembly:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/answer/audited" \
  -H "Content-Type: application/json" \
  -d '{"question":"What recent evidence links microglial activation to Alzheimer disease progression?","source":"mock","max_papers":5,"use_llm_planner":true,"execute_support_refute":true}' \
  | jq '{
      run_id:.answer_result.run_id,
      retrieval_records:(.answer_result.retrieval_bundle.records | length),
      coverage_rows:(.answer_result.evidence_packet.coverage_matrix | length),
      gaps:(.answer_result.evidence_packet.coverage_gaps | length),
      stop:.answer_result.evidence_packet.stop_reason,
      trace_steps:(.trace | length)
    }'
```

## Release 1.0 Tool Chain Smoke

After creating an audited answer run, inspect the toolized workflow surfaces:

```bash
RUN_ID="<answer run id>"

curl -s "http://127.0.0.1:2236/api/biomed/answer-runs/$RUN_ID/trace" \
  | jq '{run_id, steps:[.trace[] | {step,status}], step_telemetry, memory}'

curl -s -X POST "http://127.0.0.1:2236/api/biomed/evidence/packet" \
  -H "Content-Type: application/json" \
  -d "{\"run_id\":\"$RUN_ID\",\"max_evidence_items\":12,\"selection_strategy\":\"submodular_greedy\"}" \
  | jq '{ok, packet:.result.evidence_packet.packet_id, selected:.result.selection.selected_evidence_ids, dropped:.result.selection.dropped_evidence_ids}'

curl -s "http://127.0.0.1:2236/api/biomed/answer-runs/$RUN_ID/provenance" \
  | jq '{ok, graph:.result.graph_id, entities:(.result.entities|length), activities:(.result.activities|length), redactions:.result.redactions}'
```

Obsidian export is disabled by default. For a local one-way export, pass an
explicit workspace-relative directory and `enabled=true`:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/export/obsidian/evidence-packet" \
  -H "Content-Type: application/json" \
  -d "{\"run_id\":\"$RUN_ID\",\"export_dir\":\"obsidian-export\",\"enabled\":true}" \
  | jq '{ok, export_id:.result.export_id, notes:.result.notes, imported_as_evidence:.result.imported_as_evidence}'
```

The export is deterministic and one-way; Markdown notes are reviewer artifacts
and are not imported as biomedical evidence.

## Release 2.0 Full-Text And Drift Smoke

After creating an audited answer run, inspect Argument Graph v2:

```bash
curl -s "http://127.0.0.1:2236/api/biomed/answer-runs/$RUN_ID/argument-graph" \
  | jq '{schema_version, status, advisory_only, nodes:(.nodes|length), edges:(.edges|length)}'
```

For a known stored paper, ingest deterministic local full text and extract
locator-backed evidence:

```bash
PAPER_ID="<stored paper id>"

curl -s -X POST "http://127.0.0.1:2236/api/biomed/papers/$PAPER_ID/full-text" \
  -H "Content-Type: application/json" \
  -d '{"source":"mock","content_type":"text/plain","content":"## Results\nMicroglial activation was associated with Alzheimer disease progression in a human cohort. This cohort study requires validation.","overwrite":true}' \
  | jq '{ok, document:.document.document_id, sections:(.sections|length)}'

curl -s -X POST "http://127.0.0.1:2236/api/biomed/papers/$PAPER_ID/full-text/evidence" \
  -H "Content-Type: application/json" \
  -d '{"source":"mock","research_question":"microglial activation Alzheimer progression"}' \
  | jq '{paper_id, evidence:[.evidence[] | {evidence_id, source_scope, document_id, section_id, char_start, char_end}]}'
```

For Watch drift, create/check a Watch at least twice, then inspect the advisory
diff:

```bash
WATCH_ID="<watch id>"

curl -s "http://127.0.0.1:2236/api/biomed/watch/$WATCH_ID/drift" \
  | jq '{schema_version, status, advisory_only, change_count, summary}'
```

Full-text sections, Watch drift, and Argument Graph v2 are reviewer context.
They do not bypass evidence packets, citation audit, logic audit, graph
validation, provenance, or Run Evidence Review.

## Docker

```bash
docker compose up -d --build --force-recreate
```

The compose file mounts `.akashic-workspace` as the runtime workspace and exposes the dashboard on port `2236`.

Release gates before merging:

```bash
.venv/bin/pyright --level error
.venv/bin/pyright --project pyrightconfig.tests.json --level error
.venv/bin/pytest -q tests/
.venv/bin/python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_release_2_0.json
npm run typecheck
npm run build
docker compose up -d --build --force-recreate
```

## Troubleshooting

- If PubMed requests fail, switch the source back to `mock`.
- If PubMed requests are transiently unstable, inspect retrieval manifest warnings for retry telemetry.
- If the literature readiness check returns `ok=true` but `ready=false`, inspect
  abstract coverage and warnings before running answer generation.
- If plugin panels do not appear, run `npm ci` and `npm run build`.
- If the dashboard starts but has no evidence rows, ask a mock evidence question first; extraction stores evidence in `biomed_evidence/biomed.db`.
