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

## Docker

```bash
docker compose up --build
```

The compose file mounts `.akashic-workspace` as the runtime workspace and exposes the dashboard on port `2236`.

## Troubleshooting

- If PubMed requests fail, switch the source back to `mock`.
- If plugin panels do not appear, run `npm install` and `npm run build`.
- If the dashboard starts but has no evidence rows, ask a mock evidence question first; extraction stores evidence in `biomed_evidence/biomed.db`.
