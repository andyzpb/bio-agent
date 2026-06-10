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
- `retrieval_manifest_validity`: retrieval manifests contain IDs, queries, and returned paper IDs.
- `retrieval_repeatability`: repeated mock retrievals return the same ordered paper IDs.
- `retrieval_count_stability`: repeated retrievals return the same result count.
- `claim_support_rate`: audited atomic claims marked supported or partially supported.
- `citation_precision`: citations that support at least one audited claim.
- `unsupported_claim_rate`: audited claims that are uncited, irrelevant, or insufficiently supported.
- `overclaim_rate`: audited claims that upgrade evidence strength beyond what the citation supports.
- `conflict_awareness_rate`: answers that surface known contradicting or inconclusive evidence when present.
- `uncertainty_calibration_rate`: answers whose uncertainty is at least as cautious as the audit-derived uncertainty.

## Optional Live PubMed Eval

Real PubMed evaluation is opt-in and is not used by default CI:

```bash
python -m eval.biomed_evidence.run_eval \
  --source pubmed \
  --live-pubmed \
  --output /tmp/biomed_live_eval_results.json
```

## Interpretation

This evaluation checks engineering behavior, citation-audit behavior, and safety
boundaries. It is not a substitute for biomedical expert review, but it does
verify that the mock demo is traceable, deterministic, citation-audited, and
safe enough for portfolio review.
