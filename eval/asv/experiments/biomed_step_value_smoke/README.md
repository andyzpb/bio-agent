# Biomed Step Value Smoke

This provider-free fixture demonstrates the ASV biomedical status candidate
space:

- `supported`
- `refuted`
- `not_enough_information`

The trajectory and belief fixture are synthetic. They contain no patient data,
provider payloads, API keys, or prompts.

## Offline Provided-Belief Run

```bash
python -m asv_eval evaluate \
  --input eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl \
  --belief-fixture eval/asv/experiments/biomed_step_value_smoke/beliefs.jsonl \
  --output-dir /tmp/asv-biomed-provided
```

Expected high-level output:

```text
trajectory_count=1 step_count=3
```

The offline path is suitable for CI and does not call DeepSeek or PubMed.

## Optional Live DeepSeek Smoke

Run this only on a local machine where the shell environment provides
`DEEPSEEK_API_KEY`. The command uses `zsh -ic` so local shell configuration can
load the credential without writing it into the repository or command text.

```bash
zsh -ic 'cd /Users/andyz/Documents/bio-agent && \
  eval/asv/experiments/biomed_step_value_smoke/run_live_deepseek_smoke.sh'
```

The script runs the evaluator twice with the same cache:

```bash
.venv/bin/python -m asv_eval evaluate \
  --input eval/asv/experiments/biomed_step_value_smoke/trajectory.jsonl \
  --evaluator deepseek-chat-logprob \
  --cache /tmp/asv-biomed-deepseek-cache.jsonl \
  --write-evaluated-trajectories /tmp/asv-biomed-deepseek-evaluated.jsonl \
  --output-dir /tmp/asv-biomed-deepseek
```

It writes live outputs under `/tmp` and should not create committed artifacts.
The script fails automatically on evaluator-mode, cache-hit, or secret-marker
mismatches, and prints `live_deepseek_asv_smoke=passed` after a successful
second run.
