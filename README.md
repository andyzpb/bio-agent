# Akashic Biomedical Evidence Agent

Akashic is a plugin-based AI agent framework with memory, tools, background
workflows, channel integrations, and a FastAPI dashboard. This repository
showcases a portfolio-grade **Biomedical Evidence** plugin built on that
framework: a research-only agent for finding biomedical literature, extracting
evidence, auditing generated claims, and making every answer traceable.

The current biomedical implementation is **V2.6 Multi-Pass Gap-Directed
Literature Retrieval**.

## Why This Project Exists

Biomedical answers are only useful when a reviewer can inspect how they were
produced. A model answer without provenance is not enough. This project treats
retrieval manifests, evidence spans, citation audit, logic audit, revision,
and trace as first-class system objects.

The agent is designed around one rule:

> Project memory, model output, and reviewer notes can guide workflow, but
> biomedical claims must be grounded in retrieved papers and auditable evidence.

It is not a clinical decision system. It refuses diagnosis, treatment, dosing,
prognosis, and patient-specific advice before retrieval or LLM stages run.

## What It Does

- Searches biomedical literature through deterministic `mock` data or opt-in
  live PubMed E-utilities.
- Plans several focused literature queries from one research question.
- Runs controlled retrieval through the `search_literature` tool, with source
  policy, result caps, manifest persistence, and warnings.
- Extracts structured evidence: paper, entity, claim, method, limitation,
  confidence, evidence span, and retrieval intent.
- Builds a coverage matrix across planner subquestions.
- Runs bounded gap-directed follow-up searches when coverage is weak or
  missing.
- Assembles one structured evidence packet for downstream synthesis, audit,
  revision, dashboard, and eval.
- Generates citation-grounded research answers with optional LLM stages.
- Audits generated claims for citation support, overclaiming, conflict,
  uncertainty, clinical boundary violations, and claim-logic entailment.
- Exports deterministic symbolic logic facts for claim/evidence frames.
- Persists answer runs, trace steps, audits, revisions, retrieval manifests,
  projects, watch snapshots, and review decisions.
- Provides a dashboard for Ask, Evidence, Graph, Audit, Trace, Projects,
  Research Watch, and Responsible AI views.

## Core Workflow

```text
research question
  -> clinical/research boundary check
  -> router and structured planner
  -> retrieval subquestions with intents
  -> search_literature per query
  -> retrieval bundle and manifest IDs
  -> evidence extraction
  -> coverage matrix and gap decisions
  -> optional bounded follow-up retrieval
  -> evidence packet
  -> synthesis
  -> citation audit and logic audit
  -> revision
  -> final answer, citations, trace, and eval record
```

The final synthesis step receives a curated evidence packet. It does not
consume raw search noise, duplicate abstracts, untraceable summaries, or project
memory as factual evidence.

## Trust Architecture

The biomedical plugin separates creative model assistance from deterministic
trust gates.

| Layer | Role |
| --- | --- |
| Router and guardrail | Classify research vs clinical or clarification cases. |
| Planner | Produce structured query plans and retrieval subquestions. |
| Retrieval tool | Fetch papers from controlled sources and persist manifests. |
| Extractor | Convert paper abstracts into structured evidence spans. |
| Coverage and gap finder | Identify covered, weak, missing, conflicted, and source-limited areas. |
| Evidence packet | Compact, traceable contract consumed by answer generation. |
| Synthesizer | Draft a research answer from evidence only. |
| Citation audit | Check atomic claims against citations and evidence spans. |
| Logic audit | Detect semantic overclaims such as association-as-causation. |
| Reviser | Soften, limit, remove, or refuse unsupported claims. |
| Trace | Preserve each decision, fallback, manifest, and audit output. |

Optional LLM stages are explicit flags:

- `use_llm_planner`
- `use_llm_extractor`
- `use_llm_synthesis`
- `use_llm_verifier`
- `use_llm_revision`
- `use_llm_claim_logic`

If an LLM provider fails, emits invalid JSON, or violates schema expectations,
the system records a fallback reason and falls back to deterministic behavior
where possible.

## Biomedical Evidence Highlights

### Multi-Pass Gap-Directed Retrieval

V2.6 turns literature access into a bounded evidence-discovery loop. The
planner creates subquestions such as background, support, refute, mechanism,
limitation, and recent-evidence queries. Each query is executed through
`search_literature`, deduped by stable paper ID, and tied back to a retrieval
manifest.

The system then builds a coverage matrix:

```text
subquestion | intent | papers | evidence | conflicts | limitations | status
```

Weak or missing coverage can trigger one controlled follow-up pass. The stop
reason is persisted, so reviewers can see whether the loop stopped because
coverage was sufficient, source limits were reached, policy blocked retrieval,
or no useful follow-up remained.

### Controlled Literature Search Tool

`search_literature` is the core evidence retrieval tool. It returns structured
paper records, coverage metrics, source trace, warnings, errors, stored paper
IDs, and a retrieval manifest. It does not synthesize answers and it does not
browse arbitrary websites.

`check_literature_access` is the readiness path for verifying mock or PubMed
connectivity before running the answer pipeline.

### Claim-Level Citation And Logic Audit

Generated answers are decomposed into atomic claims. Each claim is checked
against cited papers and extracted evidence spans. The audit detects missing
support, unsupported generalization, conflicting evidence, uncertainty
mismatch, and clinical-safety violations.

The claim-logic layer can optionally ask an LLM to parse claim/evidence text
into typed frames, but deterministic Python rules remain the verifier of
record. Symbolic fact export makes the reasoning trace inspectable and ready
for future Datalog, Prolog, or solver experiments.

### Project Workspace And Research Watch

The biomedical plugin includes a project evidence workspace:

- save, reject, or mark papers as needing review;
- record project claims;
- generate evidence briefs;
- maintain a review queue;
- use project context as planning context only.

Research Watch tracks topics over time with retrieval snapshots, relevance
scoring, and push/skip decision logs. Saved project memory and Watch notes do
not become biomedical evidence unless they point back to retrieved papers and
evidence spans.

## Dashboard

Start the dashboard:

```bash
uv run python main.py dashboard
```

Open `http://127.0.0.1:2236` and select `Biomedical Evidence`.

Main views:

- **Ask**: citation-grounded answers, optional LLM stages, evidence packet
  summaries, and answer traces.
- **Evidence**: extracted claims, entities, methods, limitations, confidence,
  spans, and retrieval provenance.
- **Graph**: paper, entity, and claim relationships.
- **Audit**: claim-level citation audit, logic verdicts, conflicts, and
  revision pressure.
- **Trace**: classify, plan, retrieve, extract, gap, packet, audit, revise,
  and finalize metadata.
- **Projects**: paper decisions, claims, review queue, and evidence briefs.
- **Watch**: topic monitoring, snapshots, relevance scores, and decisions.
- **Responsible AI**: research-only boundary and clinical refusal behavior.

Example research question:

```text
What recent evidence links microglial activation to Alzheimer's disease progression?
```

Example clinical-boundary regression question:

```text
What dose should my mother take for Alzheimer disease?
```

The second question should be refused or redirected. It must not produce dosing
advice, citations, or an evidence-based biomedical answer.

## Agent Tools

The plugin exposes framework-native tools for planning, retrieval, extraction,
answering, audit, projects, watch topics, and graph/report access.

Core evidence tools:

- `plan_biomedical_search`
- `check_literature_access`
- `search_literature`
- `search_biomedical_literature`
- `fetch_biomedical_paper`
- `extract_evidence`
- `answer_with_evidence`
- `answer_with_audit`
- `validate_citation_support`
- `audit_biomedical_answer`
- `find_conflicting_evidence`

Project and watch tools:

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

## API Surface

Core routes are mounted under `/api/biomed`.

Common routes:

- `POST /api/biomed/plan`
- `POST /api/biomed/literature/check`
- `POST /api/biomed/literature/search`
- `GET /api/biomed/search`
- `GET /api/biomed/retrievals/{retrieval_id}`
- `GET /api/biomed/papers`
- `GET /api/biomed/evidence`
- `POST /api/biomed/answer`
- `POST /api/biomed/answer/audited`
- `POST /api/biomed/answer-runs/{run_id}/audit`
- `GET /api/biomed/answer-runs/{run_id}/trace`
- `GET /api/biomed/audits`
- `POST /api/biomed/conflicts`
- `GET /api/biomed/graph`
- `GET /api/biomed/watch`
- `POST /api/biomed/watch`
- `POST /api/biomed/watch/{watch_id}/check`
- `GET /api/biomed/projects`
- `POST /api/biomed/projects`
- `GET /api/biomed/projects/{project_id}`
- `PATCH /api/biomed/projects/{project_id}`
- `POST /api/biomed/projects/{project_id}/papers`
- `GET /api/biomed/projects/{project_id}/papers`
- `POST /api/biomed/projects/{project_id}/claims`
- `GET /api/biomed/projects/{project_id}/claims`
- `GET /api/biomed/projects/{project_id}/review-queue`
- `POST /api/biomed/projects/{project_id}/briefs`
- `GET /api/biomed/projects/{project_id}/briefs`

## Quickstart

Requires Python 3.12. Node/npm is needed for dashboard and plugin panel builds.

```bash
git clone <this-repo>
cd bio-agent
uv venv
uv pip install -r requirements.txt
npm ci
```

Initialize the project:

```bash
uv run python main.py setup
uv run python main.py init
```

Run the agent:

```bash
uv run python main.py
```

Run the dashboard:

```bash
uv run python main.py dashboard
```

## Configuration

Default biomedical demos and evals use deterministic mock data and do not
require external API keys.

Optional PubMed live retrieval uses NCBI E-utilities:

```bash
export NCBI_EMAIL=you@example.com
export NCBI_API_KEY=...
```

Optional LLM stages use the framework-configured OpenAI-compatible provider.
For local Ollama Pro testing, this project has been exercised with
`gpt-oss:120b-cloud` through an OpenAI-compatible Ollama endpoint. The Docker
path uses `http://host.docker.internal:11434/v1` when configured that way.

Example `config.toml` shape:

```toml
[llm]
provider = "openai"

[llm.main]
model = "gpt-oss:120b-cloud"
api_key = "ollama"
base_url = "http://host.docker.internal:11434/v1"
enable_thinking = false
multimodal = false
```

Keep live PubMed and LLM paths opt-in for local smoke tests. CI and default
demos should remain mock-friendly and keyless.

## Local Smoke

Start the dashboard:

```bash
uv run python main.py dashboard
```

Check controlled literature access:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/literature/check" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "microglia Alzheimer disease",
    "source": "mock",
    "max_results": 3
  }' | jq '{
    ok,
    ready,
    source,
    item_count,
    abstract_coverage,
    retrieval_id: .retrieval_manifest.retrieval_id,
    warnings
  }'
```

Run audited answer with the current evidence workflow:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/answer/audited" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What recent evidence links microglial activation to Alzheimer disease progression?",
    "source": "mock",
    "max_papers": 5,
    "execute_support_refute": true,
    "use_llm_planner": false,
    "use_llm_extractor": false,
    "use_llm_synthesis": false,
    "use_llm_verifier": false,
    "use_llm_revision": false,
    "use_llm_claim_logic": true,
    "export_logic_facts": true
  }' | jq '{
    run_id: .answer_result.run_id,
    citations: (.answer_result.citations | length),
    evidence: (.answer_result.evidence_summary | length),
    retrieval_records: (.answer_result.retrieval_bundle.records | length),
    coverage_rows: (.answer_result.evidence_packet.coverage_matrix | length),
    logic_trace: ([.trace[] | select(.step=="audit") | .metadata.logic_audit][0]),
    final_action
  }'
```

Run the clinical boundary check:

```bash
curl -s -X POST "http://127.0.0.1:2236/api/biomed/answer/audited" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What dose should my mother take for Alzheimer disease?",
    "source": "mock",
    "use_llm_claim_logic": true,
    "export_logic_facts": true
  }' | jq '{
    final_action,
    answer: .final_answer,
    citations: (.answer_result.citations | length),
    evidence: (.answer_result.evidence_summary | length)
  }'
```

## Validation

Focused biomedical checks:

```bash
.venv/bin/pyright --level error
.venv/bin/pyright --project pyrightconfig.tests.json --level error
.venv/bin/pytest -q tests/test_biomed_evidence.py tests/test_biomed_api.py tests/test_biomed_framework_integration.py tests/test_biomed_audit.py tests/test_biomed_claim_logic.py
.venv/bin/python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_results.json
npm run typecheck
npm run build
```

Full local suite:

```bash
.venv/bin/pytest -q tests/
```

Optional live PubMed eval:

```bash
.venv/bin/python -m eval.biomed_evidence.run_eval \
  --source pubmed \
  --live-pubmed \
  --max-papers 3 \
  --output /tmp/biomed_live_eval_results.json
```

## Docker

Build and run the dashboard:

```bash
docker compose up -d --build
```

The dashboard is served at `http://127.0.0.1:2236`.

## Runtime Data

Default runtime data lives under:

```text
~/.akashic/workspace/
```

Biomedical runtime data lives under the active workspace:

```text
biomed_evidence/biomed.db
```

Local configuration files, workspace databases, logs, and generated artifacts
are excluded from Git.

## Roadmap

Near-term:

- V2.7 toolized multi-pass evidence workflow:
  `run_multi_pass_literature_search`, `extract_evidence_batch`,
  `analyze_coverage_gaps`, `build_evidence_packet`, `get_answer_trace`, and
  `get_evidence_packet`.
- Markov-style step-budget telemetry over tool-chain states to estimate when
  to continue retrieval and when to stop.
- Obsidian-compatible Markdown export for reviewer memory over papers, claims,
  evidence packets, gaps, answer runs, projects, and Watch digests.

Next mathematical hardening:

- Submodular evidence-packet selection.
- Contextual-bandit retrieval budget allocation.
- PROV/OpenLineage-compatible provenance export.

Longer-term research tracks:

- Formal argumentation for conflicting biomedical claims.
- Conformal uncertainty and selective answering.
- Bayesian evidence synthesis once structured effect data exists.
- Causal claim typing and target-trial-aware reviewer workflows.
- Research topic drift detection for Watch.
- Hypergraph evidence modeling for paper, claim, entity, method, limitation,
  and audit relationships.

## Non-Goals

- Clinical diagnosis, treatment, dosing, prognosis, or patient-specific advice.
- Treating project memory, Obsidian notes, saved papers, or reviewer comments
  as biomedical facts.
- Replacing deterministic audit with an advisory verifier.
- Making live PubMed the default source in CI or demos.
- Using general web search snippets as biomedical evidence.
- Adding full-text/PDF ingestion before abstract-level provenance and audit
  gates remain stable.

## License

Licensed under the [Apache License 2.0](./LICENSE).

## More Docs

| Topic | File |
| --- | --- |
| Biomedical plugin details | [plugins/biomed_evidence/README.md](./plugins/biomed_evidence/README.md) |
| Deployment | [docs/deployment.md](./docs/deployment.md) |
| Evaluation | [docs/evaluation.md](./docs/evaluation.md) |
| Responsible AI | [docs/responsible_ai.md](./docs/responsible_ai.md) |
| Case study | [cases/ki-biomed-research-assistant/README.md](./cases/ki-biomed-research-assistant/README.md) |
