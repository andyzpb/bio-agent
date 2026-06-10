# Akashic Agent

Akashic Agent is a collaborative, plugin-based AI agent framework. It combines
an agent loop, long-term memory, background/proactive workflows, channel
integrations, tool plugins, and a FastAPI dashboard.

This repository also includes a portfolio-grade **Biomedical Evidence** plugin:
a research-only biomedical literature assistant built on top of the framework.
The current implementation is **V2.0 Project Evidence Workspace + Review
Memory**.

The biomedical direction is claim-level evidence trustworthiness: every answer
should be traceable from question, routing, retrieval plan, retrieved papers,
evidence spans, citations, audit, revision, and final output.

## Current V2.0 Snapshot

Implemented now:

- Plugin-based framework with memory, background workflows, channels, dashboard,
  and tool lifecycle.
- Biomedical Evidence plugin with deterministic mock retrieval and optional
  PubMed E-utilities retrieval.
- Structured biomedical router/planner with clinical boundary classification,
  schema-validated plans, and primary/support/refute query generation.
- Retrieval manifests and retrieval bundles with source, compiled query,
  pagination, returned paper IDs, duplicate handling, and warnings.
- Evidence extraction with paper/entity/claim records, limitations, confidence,
  evidence spans, and retrieval-intent provenance.
- Optional LLM stages behind explicit flags:
  `use_llm_planner`, `use_llm_extractor`, `use_llm_synthesis`,
  `use_llm_verifier`, and `use_llm_revision`.
- Citation-grounded answers with deterministic claim-level audit, overclaim
  checks, conflict awareness, uncertainty calibration, audit/revise loop, and
  persisted trace.
- Optional advisory verifier model. It records disagreement and review pressure,
  but deterministic audit remains the verifier of record.
- V2.0 project evidence workspace:
  `BiomedProject`, saved/rejected/needs-review paper decisions, project claim
  records, review queue, evidence brief generation, project-aware answer trace,
  API/tools, dashboard Projects view, and eval metrics.
- Research Watch topics with relevance scoring, retrieval snapshots, and
  push/skip decision logs.
- Mock eval, Python tests, Node typecheck/build, Docker, and CI-friendly checks.

Project memory is context only. It can influence planning preferences and
post-retrieval filtering, but it is never treated as biomedical evidence.

## Version Summary

- V1.0: Biomedical Evidence plugin, service/storage/API/dashboard/eval, mock
  retrieval, citation-grounded answers, graph, Docker, and CI baseline.
- V1.1: Reproducible installs and local smoke hardening.
- V1.2: Retrieval reliability, PubMed pagination/dedupe, retrieval manifests,
  Watch snapshots, and answer/export provenance.
- V1.3: Claim-level citation audit with atomic claims, support verdicts,
  overclaim detection, conflict checks, uncertainty calibration, persisted
  audits, API/tools, dashboard Audit view, and eval metrics.
- V1.4: `answer_with_audit`, audit/revise loop, optional LLM revision,
  post-revision audit, persisted trace, dashboard Trace view, and revision
  eval metrics.
- V1.5: Structured router/planner with schema-validated query plans and
  clinical routing.
- V1.6: Planner-driven primary/support/refute retrieval bundles and
  retrieval-intent labels.
- V1.7: Optional span-grounded LLM evidence extraction and audit-gated LLM
  synthesis.
- V1.8: Optional advisory verifier model / LLM judge with disagreement trace.
- V2.0: Project evidence workspace, project memory as context, saved/rejected
  paper decisions, project claims, review queue, evidence briefs, dashboard
  Projects view, API/tools, and project-level eval metrics.

## What Remains

Near-term V2.1:

- Richer project reviewer workflows: accept/reject review queue items, claim
  status transitions, reviewer notes, and decision provenance.
- Better project evidence brief templates, export controls, and dashboard
  comparison views.
- Dashboard visual regression checks for Ask, Projects, Audit, and Trace.
- Larger project-level golden eval set with human-labeled claims, conflicts,
  and overclaims.

Trust and evaluation:

- CI gates for claim support, citation precision, overclaim rate, clinical
  boundary robustness, trace completeness, and project memory isolation.
- More adversarial clinical-boundary and memory-as-evidence tests.
- Better disagreement analysis between deterministic audit and advisory
  verifier.

Retrieval expansion:

- Keep live PubMed optional until reliability and rate-limit behavior are
  hardened further.
- Add optional Europe PMC or Semantic Scholar adapters.
- Improve conflict search across claims and topics.
- Add full-text/PDF ingestion only after abstract-level provenance and audit
  gates remain stable.

Non-goals:

- Clinical diagnosis, treatment, dosing, prognosis, or patient-specific advice.
- Treating saved papers, project notes, or memory as biomedical fact.
- Replacing deterministic audit with an advisory verifier.
- Making live PubMed the default source in CI or demos.
- Multi-user auth/permissions before the single-user research workflow is solid.

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

Create or edit `config.toml`. Default biomedical demos and evals use mock data
and do not require external API keys.

Optional LLM paths use the framework-configured OpenAI-compatible provider.
For local Ollama/OpenAI-compatible testing, use the local proxy configuration
documented in `agent.md`.

Example shape:

```toml
[llm]
provider = "deepseek"

[llm.main]
model = "deepseek-v4-flash"
api_key = "sk-..."
base_url = "https://api.deepseek.com/v1"
enable_thinking = true
multimodal = false

[memory]
enabled = true
engine = ""

[memory.embedding]
model = "text-embedding-v3"
api_key = "sk-..."
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

Optional PubMed environment variables:

```bash
NCBI_EMAIL=you@example.com
NCBI_API_KEY=...
```

## Biomedical Pipeline

```text
User question
  -> clinical/research boundary check
  -> optional project context loading for research questions only
  -> structured router / planner
  -> deterministic plan validation
  -> primary/support/refute retrieval bundle
  -> project saved/rejected paper prioritization and filtering
  -> paper fetch
  -> evidence extraction with spans and retrieval-intent labels
  -> citation-grounded draft answer
  -> deterministic claim-level audit
  -> optional advisory verifier
  -> deterministic or LLM-backed revision
  -> final answer + citations + trace + project review queue update
```

Clinical or patient-specific requests are refused before project memory,
retrieval, extraction, synthesis, verifier, or brief generation.

## Biomedical Dashboard

Run:

```bash
uv run python main.py dashboard
```

Open `http://127.0.0.1:2236` and choose `Biomedical Evidence`.

Views:

- Ask: citation-grounded answers, optional LLM stages, support/refute retrieval,
  and project-aware answer traces.
- Projects: project creation, saved/rejected/needs-review paper decisions,
  project claims, review queue, and evidence brief generation.
- Evidence: extracted claims, entities, methods, limitations, confidence, and
  retrieval provenance.
- Graph: paper, entity, and claim graph.
- Watch: research topic monitoring, snapshots, and push/skip decision logs.
- Audit: atomic claim audit, support verdicts, overclaims, conflicts, and
  uncertainty calibration.
- Trace: classify, plan, validate_plan, retrieve, extract, draft, audit,
  advisory_verify, revise, post_audit, and finalize steps.
- Responsible AI: research-only boundary and project-memory constraints.

Example question:

```text
What recent evidence links microglial activation to Alzheimer's disease progression?
```

## Biomedical Tools

The plugin registers:

- `plan_biomedical_search`
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

## API Surface

Core routes are mounted under `/api/biomed`.

Common routes:

- `POST /api/biomed/plan`
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

## Validation

Run targeted biomedical checks:

```bash
python -m pytest -q tests/test_biomed_evidence.py tests/test_biomed_api.py tests/test_dashboard_api.py
python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_results.json
npm ci
npm run typecheck
npm run build
docker build -t bio-agent-biomed:latest .
```

Run broader tests:

```bash
pytest tests/
akashic_RUN_SCENARIOS=1 pytest -c pytest-scenarios.ini tests_scenarios/
```

Optional live PubMed eval remains opt-in:

```bash
python -m eval.biomed_evidence.run_eval \
  --source pubmed \
  --live-pubmed \
  --output /tmp/biomed_live_eval_results.json
```

Local audited answer smoke:

```bash
uv run python main.py dashboard

curl -s -X POST "http://127.0.0.1:2236/api/biomed/answer/audited" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What recent evidence links microglial activation to Alzheimer disease progression?",
    "source": "mock",
    "max_papers": 5,
    "project_id": null,
    "use_llm_planner": true,
    "use_llm_extractor": true,
    "use_llm_synthesis": true,
    "use_llm_verifier": true,
    "use_llm_revision": true,
    "execute_support_refute": true
  }' | jq '{
    planner_mode: .answer_result.query_plan.planner_mode,
    extraction_modes: ([.answer_result.evidence_summary[].extraction_mode] | unique),
    synthesis_mode: .answer_result.synthesis_mode,
    verifier_mode: .advisory_verifier.verifier_mode,
    revision_mode: .revision.revision_mode,
    multi_query: .answer_result.retrieval_bundle.executed_multi_query,
    retrieval_records: (.answer_result.retrieval_bundle.records | length),
    citations: (.answer_result.citations | length),
    evidence: (.answer_result.evidence_summary | length),
    trace_steps: (.trace | length)
  }'
```

With no configured LLM provider, optional LLM stages may report `fallback`.
The request should still return citations, a retrieval bundle, and an 11-step
trace.

## Docker

Build and run locally:

```bash
docker compose up --build
```

The compose file mounts `.akashic-workspace` as the runtime workspace and
exposes the dashboard on port `2236`.

CI builds the Docker image as `akashic-biomed-agent`. Local docs use
`bio-agent-biomed:latest`.

## Useful Docs

| Topic | Document |
| --- | --- |
| Biomedical plugin details | [plugins/biomed_evidence/README.md](./plugins/biomed_evidence/README.md) |
| Biomedical case study | [cases/ki-biomed-research-assistant/README.md](./cases/ki-biomed-research-assistant/README.md) |
| Responsible AI | [docs/responsible_ai.md](./docs/responsible_ai.md) |
| Evaluation | [docs/evaluation.md](./docs/evaluation.md) |
| Deployment | [docs/deployment.md](./docs/deployment.md) |
| Proactive workflows | [_handbook/proactive-guide.md](./_handbook/proactive-guide.md) |
| Long-term memory | [_handbook/memory-markdown.md](./_handbook/memory-markdown.md) |
| Plugin lifecycle | [_handbook/plugins-tutorial.md](./_handbook/plugins-tutorial.md) |

## Responsible AI Boundary

Biomedical Evidence is a research support plugin, not a clinical decision
system. It should:

- cite retrieved papers for factual biomedical claims when possible;
- avoid strong claims when citations or evidence are missing;
- surface uncertainty and limitations;
- refuse diagnosis, treatment, medication, prognosis, dosing, and
  patient-specific medical-record interpretation;
- treat project memory as user/project context, not biomedical fact.
