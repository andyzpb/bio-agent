# Biomedical Artifact Cache Design

Date: 2026-06-25

## Goal

Add a Release 2.1 cache slice that reduces repeated biomedical retrieval and
artifact construction cost while preserving the existing evidence boundary.

The cache must reuse framework cache capabilities where they already exist and
only add Biomedical Evidence-specific behavior where the framework has no
artifact-aware cache.

## Context

The framework already provides:

- in-process static prompt section caching through `SectionCache`;
- provider cache token extraction through `LLMResponse.cache_prompt_tokens` and
  `LLMResponse.cache_hit_tokens`;
- observe storage and `/kvcache` reporting for provider prompt-cache telemetry;
- plugin `PluginKVStore` for lightweight preferences;
- SQLite hash-cache precedent in the Akasha embedding cache.

These cover prompt/provider cache visibility. They do not cover PubMed,
full-text, retrieval manifest, evidence packet, or provenance-safe biomedical
artifact reuse.

## External Findings

- OpenAI prompt caching only helps when prompt prefixes match exactly; stable
  instructions and examples belong first, variable inputs last.
- RedisVL-style semantic response caches can reduce cost and latency, but they
  rely on similarity thresholds, TTLs, and access filters.
- Agentic plan-caching research argues that ordinary query/response semantic
  caches are insufficient for agents because outputs depend on external data and
  execution context. Reusable plans and artifacts are safer than reusable final
  answers.

Sources:

- https://developers.openai.com/api/docs/guides/prompt-caching
- https://redis.io/docs/latest/develop/ai/redisvl/user_guide/llmcache/
- https://arxiv.org/abs/2506.14852
- https://arxiv.org/abs/2511.02919
- https://arxiv.org/abs/2602.13165

## Design

Use a framework-cache-first, biomedical-artifact-only design.

Do not introduce a generic framework cache, Redis, vector semantic cache, or
final-answer cache in this slice. Add a small persistent artifact cache layer
inside `plugins/biomed_evidence`, backed by the existing workspace SQLite DB.

The cache is per workspace.

### Cacheable Artifacts

1. Literature retrieval artifacts:
   - retrieval manifest;
   - returned paper IDs;
   - normalized paper metadata already persisted by the service.

2. Paper metadata:
   - source;
   - paper ID;
   - normalized title, abstract, authors, journal, year, DOI, keywords, MeSH.

3. Full-text artifacts:
   - source locator;
   - source hash;
   - document ID;
   - normalized sections and span locators.

4. Evidence packets:
   - packet ID or cache entry ID;
   - normalized question;
   - retrieval manifest IDs;
   - source hash set;
   - packet schema version.

### Non-Cacheable Outputs

These must not be served from cache as authority:

- final answer;
- standalone audit verdict;
- reviewer notes;
- project memory;
- model-generated biomedical claims;
- semantic matches over user questions.

They may use cached retrieved artifacts as inputs, but support for biomedical
claims still comes only from retrieved papers, evidence spans, manifests,
audits, logic audit, and evidence packets.

## Cache Keys

Use exact deterministic keys. No semantic similarity in v1.

Literature retrieval key fields:

- cache kind: `literature_search`;
- source: `mock` or `pubmed`;
- normalized compiled query;
- normalized filters and max result count;
- provider policy flags, including live PubMed opt-in;
- source client/version marker;
- schema version.

Paper metadata key fields:

- cache kind: `paper_metadata`;
- source;
- paper ID;
- schema version.

Full-text key fields:

- cache kind: `full_text`;
- source;
- paper ID;
- source locator;
- source hash;
- parser/schema version.

Evidence packet key fields:

- cache kind: `evidence_packet`;
- normalized question;
- source;
- retrieval manifest IDs;
- paper IDs;
- evidence IDs or source hashes;
- packet schema version.

## Expiration

Mock artifacts are deterministic and do not expire by time.

PubMed retrieval artifacts get a conservative TTL, default 7 days.

Full-text artifacts expire only when the source hash or parser/schema version
changes.

Evidence packet cache entries are invalidated when any source manifest, paper
ID set, evidence ID set, source hash, or packet schema version changes.

## Read-Through Flow

On cacheable service calls:

1. Compute exact cache key.
2. Check cache metadata and referenced persisted artifact rows.
3. If valid, return the cached artifact and record a cache-hit trace frame.
4. If missing or stale, execute the existing path, persist artifacts, then store
   cache metadata.

Cache hits must preserve artifact provenance. A cached retrieval manifest or
packet is still an artifact with source IDs and timestamps, not a new evidence
source.

## Observability

Extend existing run observability with artifact-cache fields:

- `artifact_cache_hit_count`;
- `artifact_cache_miss_count`;
- `artifact_cache_write_count`;
- `source_call_count`;
- `saved_source_call_count`;
- `cache_hit_rate`;
- `cache_entries`;
- `cache_basis`.

Continue to use existing provider prompt-cache telemetry for:

- `prompt_tokens`;
- `cache_hit_tokens`;
- provider-level `cache_hit_rate` where provider data exists.

Pilot Report distinguishes:

- provider prompt-cache telemetry;
- biomedical artifact-cache telemetry.

Both are observability signals, not biomedical evidence.

## Public Interfaces

No new export route.

Planned additions:

- trace API includes artifact-cache observability under existing
  `observability`;
- Pilot Report includes artifact-cache observability;
- optional dashboard summary can reuse the existing Trace panel;
- `/biomed status` can report whether biomedical artifact cache is enabled.

No command exposes semantic response cache in v1.

## Configuration

Use plugin config, not framework config, for biomedical artifact cache policy:

- `enable_artifact_cache: bool = true`;
- `pubmed_cache_ttl_days: int = 7`;
- `cache_mock_artifacts: bool = true`;
- `cache_pubmed_artifacts: bool = true`;
- `cache_full_text_artifacts: bool = true`;
- `cache_evidence_packets: bool = true`.

Provider prompt-cache behavior remains framework/provider-owned.

## Error Handling

Cache failures must not fail biomedical workflows.

If cache read/write fails:

- log warning;
- record cache error in trace metadata;
- fall back to existing non-cache execution path.

If a cache entry points to missing or invalid artifact rows:

- treat as stale miss;
- rebuild through the existing path;
- overwrite cache metadata.

## Testing

Targeted tests:

- mock literature search second call hits cache and preserves same paper IDs;
- PubMed cache remains blocked unless live PubMed policy is explicitly enabled;
- full-text cache reuses only when source hash matches;
- evidence packet cache reuses only for exact manifest/paper/evidence set;
- cache hit trace fields appear in `GET /api/biomed/answer-runs/{run_id}/trace`;
- Pilot Report separates provider prompt cache fields from artifact cache fields;
- no cached artifact can make memory, reviewer notes, or final answer an
  evidence source;
- cache failure falls back without changing answer behavior.

Eval additions:

- artifact cache hit rate;
- saved source calls;
- artifact reproducibility rate;
- stale-cache avoidance rate;
- no-memory-as-evidence rate remains 1.0.

## Deferred

- semantic answer cache;
- Redis or external cache service;
- team/global cache sharing;
- LLM-judged semantic cache promotion;
- agent plan cache;
- provider price-table cost accounting.
