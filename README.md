# Akashic Agent

Akashic Agent is a collaborative, plugin-based AI agent framework. It combines
an agent loop, long-term memory, background/proactive workflows, channel
integrations, tool plugins, and a FastAPI dashboard.

This repository also includes a portfolio-grade **Biomedical Evidence** plugin:
a research-only biomedical literature assistant built on top of the framework.
The current implementation is **V2.5 Controlled Literature Search Tool**.

The biomedical direction is claim-level evidence trustworthiness: every answer
should be traceable from question, routing, retrieval plan, retrieved papers,
evidence spans, citations, audit, revision, and final output.

## Current V2.5 Snapshot

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
  `use_llm_verifier`, `use_llm_revision`, and `use_llm_claim_logic`.
- Citation-grounded answers with deterministic claim-level audit, overclaim
  checks, conflict awareness, uncertainty calibration, audit/revise loop, and
  persisted trace.
- V2.2 claim logic audit with provider-backed LLM claim/evidence frame parsing
  behind `use_llm_claim_logic`, JSON-only parser prompts, prompt hashes, model
  metadata, schema validation, and explicit deterministic fallback reasons.
- V2.3 framework-native integration for normal agent tool calls:
  plugin config defaults, plugin KV preferences, `@on_tool_pre` biomedical
  guardrails, source/count/LLM-flag policy mutation, project ID validation, and
  conditional prompt context injection through the framework lifecycle.
- V2.4 literature access readiness check for mock/PubMed sources. The check
  exercises search, retrieval manifest creation, paper storage, abstract
  coverage, NCBI identity metadata, and source readiness without requiring an
  answer-generation run.
- V2.5 controlled `search_literature` tool and
  `POST /api/biomed/literature/search` endpoint. The tool returns normalized
  paper records, source rank, abstracts when available, retrieval manifest,
  coverage metrics, source trace, warnings, errors, and stored paper IDs
  without synthesizing answers.
- Deterministic biomedical entailment rules remain the source of record for
  support, overclaim, scope, population, modality, and clinical-boundary
  verdicts; the LLM parser may only formalize claim/evidence semantics.
- Symbolic logic fact export for claim/evidence frames, alignments,
  non-entailment rules, triggered rules, mismatch facts, warnings, and final
  verdict facts. Fact export is deterministic and does not call an LLM.
- Clinical refusal paths short-circuit before retrieval, claim-logic parsing,
  and fact export, preventing misleading logic artifacts on patient-specific
  requests.
- Dashboard Audit/Trace views expose logic parser mode/model/prompt provenance,
  fallback warnings, parsed logic frames, and symbolic fact exports.
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

## Highlight: V2.5 Controlled Literature Search Tool

V2.5 promotes literature retrieval into the agent's core controlled tool
surface. The LLM planner can propose structured query parameters, but source
access remains deterministic, manifest-backed, and guarded by the framework:

```text
planner query
  -> search_literature
  -> normalized papers + retrieval manifest + coverage/source trace
  -> extraction / synthesis / audit
```

`search_literature` supports deterministic `mock` and opt-in `pubmed` sources,
persists papers when requested, records abstract coverage and stored-paper
coverage, and keeps every returned paper tied to a retrieval manifest. It does
not generate answers, browse arbitrary websites, or bypass clinical/source/count
guards. `check_literature_access` remains the separate readiness smoke path for
confirming source connectivity before answer workflows.

## Highlight: V2.3 Framework-Native Biomedical Guardrails

V2.3 starts using the host framework as more than a tool registry. The
Biomedical Evidence plugin now participates in the framework's native control
points:

```text
agent turn / tool call
  -> conditional biomedical prompt context
  -> @on_tool_pre biomedical guardrail
  -> plugin config defaults and caps
  -> plugin KV for lightweight active project/source preferences
  -> biomedical service trust path
```

The pre-tool guard blocks clinical or patient-specific biomedical tool calls
before retrieval or LLM stages run, denies accidental live PubMed tool use when
plugin config disallows it, caps oversized result requests, validates project
IDs, applies safe default sources, and records explicit mutation/denial reasons
in hook traces. The prompt module injects a short research-only boundary and
active project context only when the turn is biomedical or a project is active.

This layer does not replace service-level guardrails. It is an outer framework
guard for ordinary agent tool use; the biomedical service still remains the
source of record for retrieval, audit, revision, clinical refusal, and trace.

## Highlight: V2.4 Literature Access Hardening

V2.4 makes literature access an explicit, testable capability rather than an
implicit option hidden behind `source=pubmed`. The new readiness path runs the
same search, retrieval manifest, paper persistence, and abstract availability
checks that downstream answer generation depends on:

```text
source readiness query
  -> literature search
  -> retrieval manifest
  -> paper storage
  -> abstract coverage check
  -> readiness result + warnings/errors
```

This gives reviewers a direct way to confirm whether the app is connected to
real literature infrastructure before judging planner, extractor, synthesis, or
audit behavior. Live PubMed remains opt-in for tests/eval and ordinary agent
tool calls, but the readiness result records whether NCBI email/API-key identity
is configured and surfaces lower-rate-limit warnings without leaking secrets.

## Highlight: V2.2 Provider-Backed Claim Logic Parser

V2.2 added a **provider-backed, schema-constrained
biomedical claim/evidence logic parser**. Instead of asking an LLM to judge
whether a citation supports a claim, it lets the provider produce typed
logical frames, validates them strictly, and then exports the deterministic
reasoning trace as symbolic facts:

```text
claim / evidence text
  -> logical frame parsing
  -> Pydantic schema validation
  -> deterministic biomedical entailment rules
  -> symbolic logic fact export
  -> audit verdict, triggered rules, mismatch trace, and revision pressure
```

This should catch semantic overclaims that lexical citation checks often miss:
association stated as causation, animal or in-vitro evidence generalized to
human claims, mechanistic findings turned into treatment claims, weak evidence
written as definitive, and citations that mention the right entities but do not
actually entail the generated claim.

The key trust boundary is that any LLM parser may only help formalize language,
while deterministic code remains the source of record for support, overclaim,
scope, population, modality, and clinical-boundary verdicts. The fact export
layer is for inspectability, regression testing, and future
Datalog/Prolog/Z3-style solver integration; it does not prove biomedical truth
or override the audit verdict. If the provider is unavailable, returns invalid
JSON, misses a frame, or emits schema-invalid fields, V2.2 fails fast into the
deterministic parser and records the fallback reason in audit warnings and
trace metadata.

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
- V2.1: Claim logic entailment audit with schema-validated logical frames,
  deterministic semantic overclaim rules, audit/trace integration, and
  symbolic logic fact export.
- V2.2: Provider-backed LLM claim/evidence logic parser hardening, strict
  schema/fallback handling, clinical-boundary-before-logic enforcement,
  parser provenance in trace/dashboard, and expanded claim-logic tests.
- V2.3: Framework-native biomedical guardrails and context integration:
  plugin config defaults, plugin KV state, `@on_tool_pre` clinical/source/count
  guards, project ID validation, and conditional prompt context injection.
- V2.4: Literature access hardening with explicit source readiness checks,
  retrieval manifest and paper-storage smoke, abstract coverage metrics, API
  and tool surface, and eval metrics.
- V2.5: Controlled literature search tool with stable `search_literature`
  envelope, normalized paper records, retrieval manifest/source trace, coverage
  metrics, storage trace, framework guardrails, API route, and eval metrics.

## Next Roadmap: V2.6+

V2.6+ should build on V2.5 by using the controlled retrieval tool in proactive,
memory-aware, and telemetry workflows without weakening the biomedical trust
path.

Planned next scope:

- Convert Research Watch into an opt-in proactive alert/content source after
  the controlled search tool is stable. Watch pushes must include retrieval
  IDs, snapshot IDs, relevance reasons, citation links, dashboard links, and
  ACK mapped back to watch decision logs.
- Bridge project context into the framework memory layer as context-only
  records. Memory can influence preferences and active project selection, but
  must never satisfy biomedical claims or replace retrieved evidence.
- Add observe/eval telemetry for biomedical run IDs, retrieval manifests, audit
  IDs, parser modes, revision actions, fallback reasons, and clinical refusals.
- Add a first-class dashboard Logic Facts workspace with filtering, copy/export
  controls, parser frame diffing, triggered-rule drilldowns, and better visual
  grouping for multi-claim answers.
- Expand golden claim-logic evals for association-to-causation,
  animal/in-vitro-to-human, mechanism-to-treatment, biomarker-to-diagnostic,
  nonlongitudinal-to-prognostic, weak-to-definitive, and inconclusive evidence
  cases.
- Add CI-visible metrics for parser schema success, fallback rate, expected
  verdict accuracy, expected rule recall, fact export determinism, expected fact
  recall, symbol normalization errors, and clinical-boundary-before-logic rate.
- Prototype optional Datalog/Prolog/Z3-style solver integration using exported
  symbolic facts while keeping deterministic Python rules as the release gate.
- Decide when live PubMed should enter main acceptance rather than optional
  smoke, including rate-limit, reproducibility, and fixture strategy.

Deferred after V2.5:

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
- Add optional Europe PMC before any general web-search evidence source.
- Treat general web search, if added later, as source discovery only; it should
  not bypass structured literature source checks, manifest persistence,
  citation audit, or biomedical trust gates.
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
  -> optional claim logic parser + deterministic entailment audit
  -> optional symbolic logic fact export
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
python -m pytest -q tests/test_biomed_framework_integration.py tests/test_biomed_evidence.py tests/test_biomed_api.py tests/test_dashboard_api.py
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
    citations: (.answer_result.citations | length),
    evidence: (.answer_result.evidence_summary | length),
    logic_trace: ([.trace[] | select(.step=="audit") | .metadata.logic_audit][0]),
    logic_verdicts: [.audit.claim_audits[] | .logic_audit.logic_verdict],
    fact_exports: [.audit.claim_audits[] | .logic_audit.logic_fact_export.export_id],
    trace_steps: (.trace | length)
  }'
```

With no configured LLM provider, optional LLM stages may report `fallback`.
The request should still return citations, a retrieval bundle, logic-audit
metadata when requested, and an 11-step trace.

V2.5 Ollama smoke should use the local Ollama Pro OpenAI-compatible endpoint
and `gpt-oss:120b-cloud`. Planner, synthesis, advisory verifier, revision, and
claim-logic parser paths can all return through the LLM provider; audit JSON and
trace metadata expose parser mode/model/prompt provenance, fallback warnings,
`logic_audit`, and symbolic fact exports. The framework pre-tool guard remains
separate from the dashboard/API route smoke; it is covered by
`tests/test_biomed_framework_integration.py`.

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
