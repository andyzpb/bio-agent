# Biomedical Evidence Evaluation

The lightweight evaluation harness uses deterministic mock data so it can run in CI without external API keys.

## Run

```bash
python -m eval.biomed_evidence.run_eval \
  --output /tmp/biomed_eval_results.json
```

## Metrics

- `citation_coverage`: answer runs with at least one citation.
- `schema_validity`: extracted evidence objects that validate against the Pydantic schema.
- `refusal_success`: clinical requests that are refused or redirected.
- `watch_precision`: watch decisions above threshold that are marked `push`.

## Interpretation

This evaluation checks engineering behavior and safety boundaries, not biomedical truth. It is intended to prove that the mock demo is traceable, deterministic, and safe enough for portfolio review.
