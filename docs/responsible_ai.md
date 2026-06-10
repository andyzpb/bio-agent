# Biomedical Evidence Agent Responsible AI

The Biomedical Evidence Agent is a research support tool. It is not a clinical decision system.

## Research-Only Scope

- Supports literature search, evidence extraction, citation-grounded summaries, and project monitoring.
- Does not diagnose patients, recommend treatment, interpret private medical records, or replace expert review.
- Uses public literature and synthetic project context by default.

## Citation Policy

- Biomedical factual claims should be grounded in retrieved papers.
- If no citation is available, the agent must say so and avoid strong claims.
- Project memory is treated as user preference or project context, not biomedical fact.
- Retrieval manifests expose source, compiled query, pagination, result counts, warnings, and returned paper IDs so reviewers can inspect how evidence was found.
- Citation presence is not treated as sufficient. V1.3 adds claim-level audit
  that separates supported, partially supported, overclaimed, contradicted,
  insufficient, irrelevant, and uncited claims.
- V1.4 routes draft answers through deterministic audit/revise/refuse logic and
  persists trace steps so reviewers can inspect how the final answer changed.
- Optional LLM revision can only be used as a framework-injected reviser over
  supplied evidence and citations. The deterministic citation audit remains the
  verifier of record.

## Uncertainty Policy

The system raises uncertainty when evidence is conflicting, observational,
abstract-only, missing abstracts, heuristic-extracted, or based on small/animal
cohorts. The citation audit also derives an uncertainty calibration signal from
claim-support failures, retrieval warnings, conflicting evidence, and indirect
animal/in-vitro evidence.

When the audit detects unsupported, overclaimed, contradicted, or clinical-risk
claims, the revised answer should remove the claim, soften it, add limitations,
abstain, or refuse rather than present the draft as-is.

## Human Review

All evidence items include `requires_expert_review=true` by default. Researchers should inspect source papers, evidence spans, limitations, and conflicting findings before using outputs in research decisions.

## Data Handling

- Demo mode uses mock public-domain-style literature data.
- Secrets must be provided through environment variables or local config excluded from Git.
- Watch topics and biomedical evidence are stored in the local workspace database and can be deleted.
