# Akashic Agent

Akashic Agent is a collaborative, plugin-based AI agent framework. It combines
an agent loop, long-term memory, background/proactive workflows, channel
integrations, tool plugins, and a FastAPI dashboard.

This repository also includes a portfolio-grade **Biomedical Evidence** plugin:
a research-only biomedical literature assistant built on top of the framework.
The plugin currently supports deterministic mock retrieval, optional PubMed
retrieval, evidence extraction, citation-grounded answers, retrieval
provenance, claim-level citation audit, audit/revise answer traces, Research
Watch decision logs, dashboard views, evaluation, Docker, and CI-friendly
checks.

The current roadmap direction is **claim-level evidence trustworthiness**:
moving from "answers with citations" toward a biomedical research agent that
can audit whether each generated claim is actually supported by cited evidence.

## Status

Implemented today:

- Plugin-driven agent framework with memory, background workflows, channels,
  and dashboard.
- Biomedical Evidence plugin with mock/PubMed literature retrieval.
- Pydantic schemas, SQLite persistence, FastAPI routes, and dashboard panel.
- Structured evidence extraction, citation-grounded answers, evidence graph,
  and report export.
- Retrieval manifests with compiled queries, pagination, warnings, errors, and
  returned paper IDs.
- Research Watch topics with relevance scoring, retrieval snapshots, and
  push/skip decision logs.
- V1.3 claim-level citation audit with atomic claims, support verdicts,
  overclaim detection, conflict checks, uncertainty calibration, persisted
  audit records, API routes, tools, dashboard audit view, and eval metrics.
- V1.4 audit/revise loop with `answer_with_audit`, persisted trace steps,
  deterministic claim revision/refusal, dashboard Trace view, and revision
  eval metrics.
- Optional framework-provider LLM revision path is supported behind
  `use_llm_revision`; default mock demos and CI remain deterministic/keyless.
- Responsible-AI guardrails for research-only use.
- Mock biomedical eval, Python tests, Node typecheck/build, Docker, and CI
  support.

Planned next:

- Structured biomedical query planner.
- Project memory for research preferences.
- Claim-level eval gates in CI and a larger golden dataset.

## Quickstart

Requires Python 3.12. Node/npm is needed for dashboard/plugin panel builds.

```bash
git clone <this-repo>
cd bio-agent
uv venv
uv pip install -r requirements.txt
npm ci
```

If `uv` is not installed:

```bash
pip install uv
```

Initialize the project:

```bash
uv run python main.py setup
uv run python main.py init
```

Start the agent:

```bash
uv run python main.py
```

Start the dashboard:

```bash
uv run python main.py dashboard
```

The dashboard is served at `http://127.0.0.1:2236`.

## Configuration

Create or edit `config.toml`. A typical setup uses a strong main model, a fast
utility model, an optional vision model, and embeddings for memory retrieval.

```toml
[llm]
provider = "deepseek"

[llm.main]
model = "deepseek-v4-flash"
api_key = "sk-..."
base_url = "https://api.deepseek.com/v1"
enable_thinking = true
multimodal = false

[llm.fast]
model = "qwen-flash"
api_key = "sk-..."
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

[llm.vl]
model = "qwen-vl-plus"
api_key = "sk-..."
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

[memory]
enabled = true
engine = ""

[memory.embedding]
model = "text-embedding-v3"
api_key = "sk-..."
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

[channels.telegram]
token = "123456:ABC..."
allow_from = ["your_username"]
```

## Architecture

```text
User message
  -> passive reply
  -> agent loop
       -> memory retrieval and consolidation
       -> plugin lifecycle, tool registration, guards
       -> tool calls
       -> response

Proactive loop
  -> alert/content/context sources
  -> LLM decision
  -> push or skip
  -> Drift background tasks when there is nothing to push
```

Biomedical Evidence currently sits inside the plugin layer:

```text
Question
  -> research/clinical boundary guardrail
  -> literature search with retrieval manifest
  -> paper fetch
  -> evidence extraction
  -> citation-grounded answer
  -> answer run / report / dashboard audit trail
```

Useful framework docs:

| Topic | Document |
| --- | --- |
| Proactive monitoring and data sources | [_handbook/proactive-guide.md](./_handbook/proactive-guide.md) |
| Drift background tasks | [_handbook/drift-guide.md](./_handbook/drift-guide.md) |
| Long-term memory flow | [_handbook/memory-markdown.md](./_handbook/memory-markdown.md) |
| Plugin lifecycle and tool registration | [_handbook/plugins-tutorial.md](./_handbook/plugins-tutorial.md) |

## Biomedical Evidence Plugin

The `Biomedical Evidence` plugin demonstrates research-only biomedical tooling
for literature search, structured evidence extraction, citation-grounded
answers, lightweight evidence graphs, retrieval manifests, and Research Watch
decision logs.

Entry points:

- Plugin code: [plugins/biomed_evidence](./plugins/biomed_evidence)
- Plugin README: [plugins/biomed_evidence/README.md](./plugins/biomed_evidence/README.md)
- Case study: [cases/ki-biomed-research-assistant/README.md](./cases/ki-biomed-research-assistant/README.md)
- Responsible AI: [docs/responsible_ai.md](./docs/responsible_ai.md)
- Deployment: [docs/deployment.md](./docs/deployment.md)
- Evaluation: [docs/evaluation.md](./docs/evaluation.md)

The default source is deterministic `mock` data, so the demo works without
external API keys. Use `source=pubmed` for optional NCBI E-utilities retrieval.

Optional PubMed environment variables:

```bash
NCBI_EMAIL=you@example.com
NCBI_API_KEY=...
```

Run the dashboard and choose `Biomedical Evidence`:

```bash
uv run python main.py dashboard
```

Example question:

```text
What recent evidence links microglial activation to Alzheimer's disease progression?
```

The plugin is for biomedical research support only. It does not provide
clinical diagnosis, treatment recommendations, medication advice, prognosis, or
patient-specific medical guidance.

## Biomedical Tools

The plugin currently registers these agent tools:

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

Runtime biomedical data is stored under the active workspace:

```text
biomed_evidence/biomed.db
```

Search and answer runs record retrieval manifests with source, original query,
compiled query, API parameters, pagination, result counts, warnings, errors,
and returned paper IDs. Research Watch checks also record retrieval snapshots
for push/skip audit.

## Frontier Roadmap

Plain RAG with citations is not enough for biomedical research support. The
next higher-trust direction is a **claim-level evidence audit pipeline**:

```text
Question
  -> research/clinical boundary classifier
  -> structured query planner
  -> retrieval
       -> supporting evidence query
       -> refuting evidence query
       -> neutral/review evidence query
  -> evidence extraction
       -> paper metadata
       -> evidence span
       -> claim
       -> direction
       -> method/cohort/species
       -> limitation
  -> draft answer
  -> post-hoc audit
       -> atomic claim extraction
       -> citation existence check
       -> claim-citation support check
       -> overclaim check
       -> conflict check
       -> uncertainty calibration check
       -> clinical safety check
  -> pass / revise / refuse
  -> final answer with trace
```

The key design principle is generator/verifier separation. The answer generator
drafts the response; an independent verifier audits claims against evidence
spans and citations. The roadmap favors deterministic checks first, with
optional model-based graders only after schema validation and rule-based
baselines.

Target audit labels:

- `supported`
- `partial_support`
- `overclaimed`
- `contradicted`
- `insufficient_evidence`
- `irrelevant_citation`
- `not_cited`

Target audit metrics:

- `claim_support_rate`
- `citation_precision`
- `unsupported_claim_rate`
- `overclaim_rate`
- `conflict_awareness_rate`
- `uncertainty_calibration_rate`
- `clinical_boundary_robustness`
- `audit_trace_completeness`
- `revision_success_rate`

## TODO Roadmap

V1.3 Citation & Evidence Audit Layer:

- [x] Add `AtomicClaim`, `ClaimAuditItem`, `CitationAuditResult`,
  `ConflictAuditResult`, and `UncertaintyAudit` schemas.
- [x] Implement deterministic `extract_atomic_claims`.
- [x] Implement `validate_citation_support` with claim-to-citation/evidence
  span alignment.
- [x] Implement overclaim detection for association-to-causation,
  animal-to-human, in-vitro-to-clinical, single-study-to-consensus,
  abstract-only-to-established, and mechanism-to-treatment errors.
- [x] Implement conflict-aware checks using supporting, refuting, and
  inconclusive evidence.
- [x] Persist answer audits and claim audits in SQLite.
- [x] Add audit API routes and plugin tools.
- [x] Add dashboard audit view with failed-claim table.
- [x] Extend mock eval with claim-level metrics.

Audit/revise loop:

- [x] Add `answer_with_audit` without breaking `answer_with_evidence`.
- [x] Save agent trace steps: classify, plan, retrieve, extract, draft, audit,
  revise, finalize.
- [x] Downgrade unsupported or overclaimed language before final answer.
- [x] Refuse or abstain when clinical or evidence-insufficient boundaries are
  triggered.

Structured biomedical planner:

- [ ] Add `BiomedicalQueryPlan`.
- [ ] Route requests into `research_ok`, `clinical_refuse`, or
  `needs_clarification`.
- [ ] Generate primary, support, refute, and uncertainty queries.
- [ ] Use existing `mesh_terms`, `species_terms`, `publication_types`, and
  `exclude_terms` search fields.

Project memory:

- [ ] Add project memory records for preferred methods, excluded terms/species,
  saved papers, rejected papers, known conflicts, and open questions.
- [ ] Inject project memory into query planning as preference context only.
- [ ] Keep memory out of biomedical factual citation paths.
- [ ] Add dashboard controls to edit, disable, and delete memory entries.

Claim-level evaluation:

- [ ] Add golden biomedical question cases.
- [ ] Add overclaim, conflict, clinical-boundary, and memory eval cases.
- [x] Add mock eval metrics for trace completeness and revision success.
- [ ] Add CI gates for claim support, citation precision, overclaim rate,
  clinical robustness, and trace completeness.
- [ ] Keep live PubMed eval opt-in and out of default CI.

Dashboard and portfolio polish:

- [ ] Add Evidence Audit panel.
- [x] Add Agent Trace panel.
- [ ] Add Conflict Evidence panel.
- [ ] Add Project Memory panel.
- [ ] Add docs for evidence audit, project memory, and claim-level eval after
  implementation.
- [ ] Add screenshots or a demo GIF once the UI stabilizes.

## Validation

Run targeted biomedical checks:

```bash
python -m pytest -q tests/test_biomed_evidence.py tests/test_biomed_api.py
python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_results.json
python -m eval.biomed_evidence.run_eval --source pubmed --live-pubmed --output /tmp/biomed_live_eval_results.json
npm run typecheck
npm run build
docker build -t bio-agent-biomed:latest .
```

Run the broader test suite:

```bash
pytest tests/
akashic_RUN_SCENARIOS=1 pytest -c pytest-scenarios.ini tests_scenarios/
```

For reproducible Node installs, use:

```bash
npm ci
```

## Docker

Build and run locally:

```bash
docker compose up --build
```

The compose file mounts `.akashic-workspace` as the runtime workspace and
exposes the dashboard on port `2236`.

CI builds the Docker image as `akashic-biomed-agent`. Local docs use
`bio-agent-biomed:latest`.

## Common Commands

```bash
uv run python main.py cli
uv run python main.py dashboard
uv run python main.py --help
```

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

## Responsible AI Boundary

Biomedical Evidence is a research support plugin, not a clinical decision
system. It should:

- cite retrieved papers for factual biomedical claims when possible;
- avoid strong claims when citations or evidence are missing;
- surface uncertainty and limitations;
- refuse diagnosis, treatment, medication, prognosis, and patient-specific
  medical-record interpretation;
- treat project memory as user/project context, not biomedical fact.
