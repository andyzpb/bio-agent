#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT"

INPUT="eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl"
CACHE="/tmp/asv-biomed-deepseek-cache.jsonl"
EVALUATED="/tmp/asv-biomed-deepseek-evaluated.jsonl"
OUTPUT_DIR="/tmp/asv-biomed-deepseek"

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DEEPSEEK_API_KEY is not set in the current environment." >&2
  echo "Run through: zsh -ic 'cd $ROOT && $0'" >&2
  exit 2
fi

rm -rf "$OUTPUT_DIR" "$EVALUATED" "$CACHE"

.venv/bin/python -m asv_eval evaluate \
  --input "$INPUT" \
  --evaluator deepseek-chat-logprob \
  --cache "$CACHE" \
  --write-evaluated-trajectories "$EVALUATED" \
  --output-dir "$OUTPUT_DIR"

.venv/bin/python -m asv_eval evaluate \
  --input "$INPUT" \
  --evaluator deepseek-chat-logprob \
  --cache "$CACHE" \
  --write-evaluated-trajectories "$EVALUATED" \
  --output-dir "$OUTPUT_DIR"

.venv/bin/python - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

summary = json.loads(Path("/tmp/asv-biomed-deepseek/summary.json").read_text())
coverage = summary["evaluator_coverage"]
if summary["evaluator"]["mode"] != "deepseek-chat-logprob":
    raise SystemExit("unexpected evaluator mode")
if coverage["cache_hit_state_count"] != coverage["evaluated_state_count"]:
    raise SystemExit("expected every evaluated state to be served from cache after second run")

scan_paths = [
    Path("/tmp/asv-biomed-deepseek-evaluated.jsonl"),
    Path("/tmp/asv-biomed-deepseek-cache.jsonl"),
]
scan_paths.extend(
    path for path in Path("/tmp/asv-biomed-deepseek").rglob("*") if path.is_file()
)
for path in scan_paths:
    text = path.read_text(encoding="utf-8")
    for marker in (
        "Bearer" + " ",
        "Authorization",
        "api_key",
        "client_secret",
        "password",
        "token=",
        "sk-live",
        "provider_response",
        "raw_provider_response",
        "raw_response",
    ):
        if marker in text:
            raise SystemExit(f"secret marker {marker!r} found in {path}")

print("live_deepseek_asv_smoke=passed")
print(f"cache_hit_state_count={coverage['cache_hit_state_count']}")
PY
