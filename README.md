# Akashic Agent

Akashic Agent is an AI agent that can both respond to messages and proactively
reach out when subscribed information sources become relevant. It combines a
plugin-driven agent loop, long-term memory, background workflows, channel
integrations, and a FastAPI dashboard.

This repository also includes a portfolio-grade **Biomedical Evidence** demo:
a research-only biomedical literature assistant with deterministic mock data,
optional PubMed retrieval, citation-grounded answers, evidence extraction,
Research Watch decision logs, dashboard views, evaluation, Docker, and CI.

## Quickstart

Requires Python 3.12.

```bash
git clone <this-repo>
cd bio-agent
uv venv
uv pip install -r requirements.txt
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
User message -> passive reply -> agent loop -> response
                         |
                         +-> memory retrieval and consolidation
                         +-> plugin lifecycle, tool registration, guards

Proactive loop -> alert/content/context sources -> LLM decision -> push or skip
                         |
                         +-> Drift background tasks when there is nothing to push
```

Useful docs:

| Topic | Document |
| --- | --- |
| Proactive monitoring and data sources | [_handbook/proactive-guide.md](./_handbook/proactive-guide.md) |
| Drift background tasks | [_handbook/drift-guide.md](./_handbook/drift-guide.md) |
| Long-term memory flow | [_handbook/memory-markdown.md](./_handbook/memory-markdown.md) |
| Plugin lifecycle and tool registration | [_handbook/plugins-tutorial.md](./_handbook/plugins-tutorial.md) |

## Biomedical Evidence Demo

The `Biomedical Evidence` plugin demonstrates a biomedical research assistant
for literature search, structured evidence extraction, citation-grounded
answers, lightweight evidence graphs, and Research Watch decision logs.

Entry points:

- Plugin code: [plugins/biomed_evidence](./plugins/biomed_evidence)
- Case study: [cases/ki-biomed-research-assistant/README.md](./cases/ki-biomed-research-assistant/README.md)
- Responsible AI: [docs/responsible_ai.md](./docs/responsible_ai.md)
- Deployment: [docs/deployment.md](./docs/deployment.md)
- Evaluation: [docs/evaluation.md](./docs/evaluation.md)

The default source is deterministic `mock` data, so the demo works without
external API keys. Use `source=pubmed` for optional NCBI E-utilities retrieval.
Optional environment variables:

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

The plugin registers these agent tools:

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

Runtime biomedical data is stored under the active workspace:

```text
biomed_evidence/biomed.db
```

## Validation

Run targeted biomedical checks:

```bash
python -m pytest -q tests/test_biomed_evidence.py tests/test_biomed_api.py
python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_results.json
npm run typecheck
npm run build
docker build -t bio-agent-biomed:latest .
```

Run the broader test suite:

```bash
pytest tests/
akashic_RUN_SCENARIOS=1 pytest -c pytest-scenarios.ini tests_scenarios/
```

## Docker

Build and run locally:

```bash
docker compose up --build
```

The compose file mounts `.akashic-workspace` as the runtime workspace and
exposes the dashboard on port `2236`.

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

Local configuration files, workspace databases, logs, and generated artifacts
are excluded from Git.
