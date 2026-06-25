# Biomed Artifact Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic biomedical artifact caching for retrieval, full text, evidence packets, trace observability, and Pilot Report telemetry.

**Architecture:** Reuse framework prompt/provider cache as-is. Add one small metadata table in `plugins/biomed_evidence/storage.py`; cached values point at existing persisted artifacts instead of storing biomedical claims as cache authority. Service methods use read-through cache only at existing artifact entry points.

**Tech Stack:** Python stdlib, SQLite via existing `BiomedStorage`, existing Pydantic schemas, existing FastAPI tests.

---

## File Structure

- Modify `plugins/biomed_evidence/storage.py`
  - Add `biomed_artifact_cache` metadata table.
  - Add `get_artifact_cache_entry()` and `upsert_artifact_cache_entry()`.
- Modify `plugins/biomed_evidence/schemas.py`
  - Add optional cache metadata to `RetrievalManifest`.
  - Extend `PilotReportObservability` with artifact-cache fields.
- Modify `plugins/biomed_evidence/service.py`
  - Add deterministic cache-key helpers.
  - Wrap `search_with_manifest()`, `fetch()`, `ingest_full_text()`, and `build_evidence_packet()` with read-through cache metadata.
  - Extend trace and Pilot Report observability from existing `AgentTraceStep.metadata`.
- Modify `tests/test_biomed_api.py`
  - Add focused cache tests to the existing biomedical API suite.
- Modify `eval/biomed_evidence/run_eval.py`
  - Add cache availability metrics only; no new eval harness.

No new dependency. No Redis. No semantic response cache. No final-answer cache.

---

### Task 1: Storage Metadata Table

**Files:**
- Modify: `plugins/biomed_evidence/storage.py`
- Test: `tests/test_biomed_api.py`

- [ ] **Step 1: Add the failing storage/API assertion**

Append this test near the existing biomedical API artifact tests in `tests/test_biomed_api.py`:

```python
def test_biomed_artifact_cache_storage_records_mock_retrieval(tmp_path: Path) -> None:
    with _biomed_client(tmp_path) as client:
        first = client.post(
            "/api/biomed/literature/search",
            json={
                "query": "microglial activation Alzheimer's disease progression",
                "source": "mock",
                "max_results": 3,
                "store": True,
            },
        )
        assert first.status_code == 200
        second = client.post(
            "/api/biomed/literature/search",
            json={
                "query": "microglial activation Alzheimer's disease progression",
                "source": "mock",
                "max_results": 3,
                "store": True,
            },
        )
        assert second.status_code == 200
        assert second.json()["retrieval_manifest"]["cache_status"] == "hit"
        assert second.json()["retrieval_manifest"]["returned_paper_ids"] == first.json()[
            "retrieval_manifest"
        ]["returned_paper_ids"]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_api.py::test_biomed_artifact_cache_storage_records_mock_retrieval
```

Expected: fails because `cache_status` is missing or null.

- [ ] **Step 3: Add the metadata table and storage helpers**

In `plugins/biomed_evidence/storage.py`, add this table inside `_ensure_schema()` after `biomed_retrieval_manifests` is created:

```sql
CREATE TABLE IF NOT EXISTS biomed_artifact_cache(
    cache_key TEXT PRIMARY KEY,
    cache_kind TEXT NOT NULL,
    source TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_json TEXT NOT NULL DEFAULT '{}',
    source_hash TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_biomed_artifact_cache_kind_source
    ON biomed_artifact_cache(cache_kind, source, updated_at);
```

Add these methods to `BiomedStorage` near the retrieval manifest helpers:

```python
    def get_artifact_cache_entry(self, cache_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT cache_key, cache_kind, source, artifact_id, artifact_json,
                       source_hash, expires_at, created_at, updated_at
                FROM biomed_artifact_cache
                WHERE cache_key=?
                """,
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "cache_key": str(row["cache_key"]),
            "cache_kind": str(row["cache_kind"]),
            "source": str(row["source"]),
            "artifact_id": str(row["artifact_id"]),
            "artifact": _loads_dict(row["artifact_json"]),
            "source_hash": row["source_hash"],
            "expires_at": row["expires_at"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def upsert_artifact_cache_entry(
        self,
        *,
        cache_key: str,
        cache_kind: str,
        source: str,
        artifact_id: str,
        artifact: dict[str, Any] | None = None,
        source_hash: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        now = _now_iso()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_artifact_cache(
                    cache_key, cache_kind, source, artifact_id, artifact_json,
                    source_hash, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    cache_kind=excluded.cache_kind,
                    source=excluded.source,
                    artifact_id=excluded.artifact_id,
                    artifact_json=excluded.artifact_json,
                    source_hash=excluded.source_hash,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at
                """,
                (
                    cache_key,
                    cache_kind,
                    source,
                    artifact_id,
                    _json(artifact or {}),
                    source_hash,
                    expires_at,
                    now,
                    now,
                ),
            )
            self._db.commit()
```

Add this helper near `_json()` if it does not exist:

```python
def _loads_dict(value: object) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
```

- [ ] **Step 4: Run the focused test**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_api.py::test_biomed_artifact_cache_storage_records_mock_retrieval
```

Expected: still fails because service has not used the table yet.

- [ ] **Step 5: Commit**

```bash
git add plugins/biomed_evidence/storage.py tests/test_biomed_api.py
git commit -m "feat: add biomed artifact cache storage"
```

---

### Task 2: Retrieval Read-Through Cache

**Files:**
- Modify: `plugins/biomed_evidence/schemas.py`
- Modify: `plugins/biomed_evidence/service.py`
- Test: `tests/test_biomed_api.py`

- [ ] **Step 1: Add manifest cache fields**

In `plugins/biomed_evidence/schemas.py`, extend `RetrievalManifest`:

```python
    cache_status: Literal["hit", "miss", "write", "disabled", "error"] | None = None
    cache_key: str | None = None
    cache_basis: str | None = None
```

- [ ] **Step 2: Add deterministic cache helpers**

In `plugins/biomed_evidence/service.py`, add these helpers near `_retrieval_id()`:

```python
ARTIFACT_CACHE_SCHEMA_VERSION = "biomed-artifact-cache-v1"


def _artifact_cache_key(kind: str, payload: dict[str, object]) -> str:
    stable = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    return f"{kind}-{digest}"


def _literature_cache_key(
    request: SearchBiomedicalLiteratureRequest,
    *,
    compiled_query: str,
    normalized_filters: dict[str, object],
) -> str:
    return _artifact_cache_key(
        "literature",
        {
            "schema": ARTIFACT_CACHE_SCHEMA_VERSION,
            "source": request.source,
            "compiled_query": _normalize_cache_text(compiled_query),
            "filters": normalized_filters,
            "max_results": max(0, min(request.max_results, 50)),
            "store": bool(request.store),
        },
    )


def _normalize_cache_text(value: str) -> str:
    return " ".join(value.strip().lower().split())
```

- [ ] **Step 3: Read cache at the top of `search_with_manifest()`**

After `_compile_query(request)` in `search_with_manifest()`, insert:

```python
        cache_key = _literature_cache_key(
            request,
            compiled_query=compiled_query,
            normalized_filters=normalized_filters,
        )
        cached = self.storage.get_artifact_cache_entry(cache_key)
        if cached is not None:
            cached_manifest = self.storage.get_retrieval_manifest(
                str(cached["artifact_id"])
            )
            if cached_manifest is not None:
                cached_items: list[PaperMetadata] = []
                for paper_id in cached_manifest.returned_paper_ids:
                    paper = self.storage.get_paper(paper_id, source=request.source)
                    if paper is not None:
                        cached_items.append(_paper_metadata_from_stored_paper(paper))
                cached_manifest.cache_status = "hit"
                cached_manifest.cache_key = cache_key
                cached_manifest.cache_basis = "exact literature cache key"
                return SearchBiomedicalLiteratureResult(
                    items=[item for item in cached_items if item is not None],
                    retrieval_manifest=cached_manifest,
                )
```

If mypy complains about `_paper_metadata_from_stored_paper()` returning optional, use:

```python
                metadata = _paper_metadata_from_stored_paper(paper)
                if metadata is not None:
                    cached_items.append(metadata)
```

- [ ] **Step 4: Write cache metadata after a successful retrieval**

Before the final `return SearchBiomedicalLiteratureResult(...)` in `search_with_manifest()`, add:

```python
        manifest.cache_status = "write"
        manifest.cache_key = cache_key
        manifest.cache_basis = "exact literature cache key"
        self.storage.save_retrieval_manifest(manifest)
        self.storage.upsert_artifact_cache_entry(
            cache_key=cache_key,
            cache_kind="literature_search",
            source=request.source,
            artifact_id=manifest.retrieval_id,
            artifact={
                "returned_paper_ids": returned_ids,
                "compiled_query": compiled_query,
                "normalized_filters": normalized_filters,
            },
        )
```

Keep the existing earlier `save_retrieval_manifest()` call; this second write only adds cache fields to the persisted manifest.

- [ ] **Step 5: Run the retrieval cache test**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_api.py::test_biomed_artifact_cache_storage_records_mock_retrieval
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/biomed_evidence/schemas.py plugins/biomed_evidence/service.py tests/test_biomed_api.py
git commit -m "feat: cache biomed retrieval artifacts"
```

---

### Task 3: Trace And Pilot Observability

**Files:**
- Modify: `plugins/biomed_evidence/schemas.py`
- Modify: `plugins/biomed_evidence/service.py`
- Test: `tests/test_biomed_api.py`

- [ ] **Step 1: Add the failing API assertions**

Extend the existing trace/Pilot Report assertions in `tests/test_biomed_api.py`:

```python
        assert "artifact_cache_hit_count" in trace_payload["observability"]
        assert "artifact_cache_miss_count" in trace_payload["observability"]
        assert "artifact_cache_write_count" in trace_payload["observability"]
        assert "saved_source_call_count" in trace_payload["observability"]
        assert isinstance(trace_payload["observability"]["cache_entries"], list)

        assert "artifact_cache_hit_count" in audited_pilot_observability
        assert "artifact_cache_hit_rate" in audited_pilot_observability
        assert isinstance(audited_pilot_observability["cache_entries"], list)
```

- [ ] **Step 2: Run the focused API test**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_api.py::test_biomed_api_export_report_and_pilot_report
```

Expected: fails because observability lacks artifact-cache fields.

- [ ] **Step 3: Extend `PilotReportObservability`**

In `plugins/biomed_evidence/schemas.py`, add fields:

```python
    artifact_cache_hit_count: int | None = None
    artifact_cache_miss_count: int | None = None
    artifact_cache_write_count: int | None = None
    saved_source_call_count: int | None = None
    artifact_cache_hit_rate: float | None = None
    cache_entries: list[dict[str, Any]] = Field(default_factory=list)
    cache_basis: str = "Biomedical artifact cache telemetry is derived from trace metadata."
```

- [ ] **Step 4: Add cache observability helpers**

In `plugins/biomed_evidence/service.py`, add:

```python
def _trace_cache_entry(
    *,
    kind: str,
    status: str | None,
    cache_key: str | None,
    artifact_id: str | None,
    basis: str | None,
) -> dict[str, object] | None:
    if not status:
        return None
    return {
        "kind": kind,
        "status": status,
        "cache_key": cache_key,
        "artifact_id": artifact_id,
        "basis": basis or "exact artifact cache key",
    }


def _artifact_cache_entries_from_trace(
    trace: list[AgentTraceStep],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for step in trace:
        raw = step.metadata.get("artifact_cache")
        if isinstance(raw, list):
            entries.extend(item for item in raw if isinstance(item, dict))
        elif isinstance(raw, dict):
            entries.append(raw)
    return entries


def _artifact_cache_counts(
    entries: list[dict[str, object]],
) -> tuple[int, int, int, int, float | None]:
    hits = sum(1 for item in entries if item.get("status") == "hit")
    misses = sum(1 for item in entries if item.get("status") == "miss")
    writes = sum(1 for item in entries if item.get("status") == "write")
    saved = hits
    total = hits + misses + writes
    hit_rate = round(hits / total, 4) if total else None
    return hits, misses, writes, saved, hit_rate
```

- [ ] **Step 5: Attach retrieval cache metadata to trace**

In `_build_trace_steps()`, before the `"retrieve"` step, compute:

```python
    retrieval_cache = (
        _trace_cache_entry(
            kind="literature_search",
            status=result.retrieval_manifest.cache_status,
            cache_key=result.retrieval_manifest.cache_key,
            artifact_id=result.retrieval_manifest.retrieval_id,
            basis=result.retrieval_manifest.cache_basis,
        )
        if result.retrieval_manifest is not None
        else None
    )
```

In the `"retrieve"` step metadata, add:

```python
            "artifact_cache": [retrieval_cache] if retrieval_cache else [],
```

Extend that step's `_trace_observability(...)` call:

```python
                artifact_cache_hit_count=1 if retrieval_cache and retrieval_cache["status"] == "hit" else 0,
                artifact_cache_miss_count=0 if retrieval_cache and retrieval_cache["status"] == "hit" else 1,
                artifact_cache_write_count=1 if retrieval_cache and retrieval_cache["status"] == "write" else 0,
                saved_source_call_count=1 if retrieval_cache and retrieval_cache["status"] == "hit" else 0,
```

- [ ] **Step 6: Extend `_trace_observability()`**

Change the signature and returned dict:

```python
def _trace_observability(
    *,
    llm_call_count: int | None = None,
    source_call_count: int | None = None,
    prompt_tokens: int | None = None,
    artifact_cache_hit_count: int | None = None,
    artifact_cache_miss_count: int | None = None,
    artifact_cache_write_count: int | None = None,
    saved_source_call_count: int | None = None,
) -> dict[str, int]:
    return {
        key: value
        for key, value in {
            "llm_call_count": llm_call_count,
            "source_call_count": source_call_count,
            "prompt_tokens": prompt_tokens,
            "artifact_cache_hit_count": artifact_cache_hit_count,
            "artifact_cache_miss_count": artifact_cache_miss_count,
            "artifact_cache_write_count": artifact_cache_write_count,
            "saved_source_call_count": saved_source_call_count,
        }.items()
        if value is not None
    }
```

- [ ] **Step 7: Extend `build_run_observability()`**

At the top of `build_run_observability()`, compute entries and counts:

```python
    cache_entries = _artifact_cache_entries_from_trace(trace)
    cache_hits, cache_misses, cache_writes, saved_source_calls, artifact_hit_rate = (
        _artifact_cache_counts(cache_entries)
    )
```

Add these keys to `values`:

```python
        "artifact_cache_hit_count": cache_hits,
        "artifact_cache_miss_count": cache_misses,
        "artifact_cache_write_count": cache_writes,
        "saved_source_call_count": saved_source_calls,
        "artifact_cache_hit_rate": artifact_hit_rate,
        "cache_entries": cache_entries,
        "cache_basis": (
            "Provider prompt-cache telemetry comes from provider usage fields; "
            "biomedical artifact-cache telemetry comes from persisted trace metadata."
        ),
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_api.py::test_biomed_api_export_report_and_pilot_report tests/test_biomed_api.py::test_biomed_artifact_cache_storage_records_mock_retrieval
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add plugins/biomed_evidence/schemas.py plugins/biomed_evidence/service.py tests/test_biomed_api.py
git commit -m "feat: expose biomed artifact cache observability"
```

---

### Task 4: Full-Text And Evidence Packet Cache Metadata

**Files:**
- Modify: `plugins/biomed_evidence/service.py`
- Test: `tests/test_biomed_api.py`

- [ ] **Step 1: Add focused assertions**

Add this test near the existing full-text and evidence-packet tests:

```python
def test_biomed_artifact_cache_full_text_and_packet_metadata(tmp_path: Path) -> None:
    with _biomed_client(tmp_path) as client:
        answer = client.post(
            "/api/biomed/answer/audited",
            json={
                "question": "What evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_papers": 4,
            },
        )
        assert answer.status_code == 200
        run_id = answer.json()["answer_result"]["run_id"]

        packet = client.post(
            "/api/biomed/evidence-packets",
            json={"run_id": run_id, "max_evidence_items": 8},
        )
        assert packet.status_code == 200
        second_packet = client.post(
            "/api/biomed/evidence-packets",
            json={"run_id": run_id, "max_evidence_items": 8},
        )
        assert second_packet.status_code == 200
        assert second_packet.json()["result"]["evidence_packet"]["packet_id"] == packet.json()[
            "result"
        ]["evidence_packet"]["packet_id"]

        paper_id = answer.json()["answer_result"]["retrieval_manifest"]["returned_paper_ids"][0]
        full_text = client.post(
            "/api/biomed/full-text/ingest",
            json={
                "paper_id": paper_id,
                "source": "mock",
                "content": "Introduction\nMicroglial activation is measured.\nResults\nDisease progression is associated.",
                "content_type": "text",
                "source_filename": "cache-test.txt",
            },
        )
        assert full_text.status_code == 200
        second_full_text = client.post(
            "/api/biomed/full-text/ingest",
            json={
                "paper_id": paper_id,
                "source": "mock",
                "content": "Introduction\nMicroglial activation is measured.\nResults\nDisease progression is associated.",
                "content_type": "text",
                "source_filename": "cache-test.txt",
            },
        )
        assert second_full_text.status_code == 200
        assert second_full_text.json()["document"]["document_id"] == full_text.json()[
            "document"
        ]["document_id"]
```

- [ ] **Step 2: Run the focused test**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_api.py::test_biomed_artifact_cache_full_text_and_packet_metadata
```

Expected: current behavior likely passes document/packet identity but does not write artifact-cache metadata. Keep the identity test as a guard; metadata observability is checked through trace/Pilot Report in Task 3.

- [ ] **Step 3: Add full-text cache key and write metadata**

In `plugins/biomed_evidence/service.py`, add:

```python
def _full_text_cache_key(
    *,
    paper_id: str,
    source: str,
    source_hash: str,
    parser_version: str = "1",
) -> str:
    return _artifact_cache_key(
        "full_text",
        {
            "schema": ARTIFACT_CACHE_SCHEMA_VERSION,
            "paper_id": paper_id,
            "source": source,
            "source_hash": source_hash,
            "parser_version": parser_version,
        },
    )
```

In `ingest_full_text()`, after `source_hash` is computed and before `document_id`, compute:

```python
        cache_key = _full_text_cache_key(
            paper_id=request.paper_id,
            source=request.source,
            source_hash=source_hash,
        )
```

After `self.storage.upsert_full_text_document(document, sections)`, add:

```python
        self.storage.upsert_artifact_cache_entry(
            cache_key=cache_key,
            cache_kind="full_text",
            source=request.source,
            artifact_id=document.document_id,
            artifact={
                "paper_id": request.paper_id,
                "source_hash": source_hash,
                "section_count": len(sections),
            },
            source_hash=source_hash,
        )
```

- [ ] **Step 4: Add packet cache key and read-through**

In `plugins/biomed_evidence/service.py`, add:

```python
def _evidence_packet_cache_key(
    *,
    run: AnswerWithEvidenceResult,
    max_items: int,
    strategy: str,
) -> str:
    evidence_ids = sorted(item.evidence_id for item in run.evidence_summary)
    paper_ids = (
        run.retrieval_bundle.deduped_paper_ids
        if run.retrieval_bundle is not None
        else run.retrieval_manifest.returned_paper_ids
        if run.retrieval_manifest is not None
        else []
    )
    return _artifact_cache_key(
        "evidence_packet",
        {
            "schema": ARTIFACT_CACHE_SCHEMA_VERSION,
            "run_id": run.run_id,
            "retrieval_id": run.retrieval_id,
            "paper_ids": sorted(paper_ids),
            "evidence_ids": evidence_ids,
            "max_items": max_items,
            "strategy": strategy,
        },
    )
```

In `build_evidence_packet()`, after validating `run`, compute:

```python
        packet_cache_key = _evidence_packet_cache_key(
            run=run,
            max_items=request.max_evidence_items,
            strategy=request.selection_strategy,
        )
        cached_packet = self.storage.get_artifact_cache_entry(packet_cache_key)
        if cached_packet is not None:
            cached_run = self.storage.get_answer_run(run.run_id)
            if cached_run is not None and cached_run.evidence_packet is not None:
                return release_ok(
                    tool_name=tool_name,
                    result={
                        "evidence_packet": cached_run.evidence_packet.model_dump(mode="json"),
                        "cache": {
                            "status": "hit",
                            "cache_key": packet_cache_key,
                            "artifact_id": cached_run.evidence_packet.packet_id,
                        },
                    },
                    metadata=metadata,
                )
```

After building the packet and before returning success, write:

```python
        self.storage.upsert_artifact_cache_entry(
            cache_key=packet_cache_key,
            cache_kind="evidence_packet",
            source=run.retrieval_manifest.source,
            artifact_id=packet.packet_id,
            artifact={
                "run_id": run.run_id,
                "retrieval_id": run.retrieval_id,
                "paper_ids": packet.paper_ids,
                "evidence_ids": packet.evidence_ids,
            },
        )
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_api.py::test_biomed_artifact_cache_full_text_and_packet_metadata
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/biomed_evidence/service.py tests/test_biomed_api.py
git commit -m "feat: cache full text and evidence packet artifacts"
```

---

### Task 5: Eval Metrics And Final Gates

**Files:**
- Modify: `eval/biomed_evidence/run_eval.py`
- Test: `tests/test_biomed_api.py`
- Test: `tests/test_biomed_release_contracts.py`

- [ ] **Step 1: Add cache metric extraction**

In `eval/biomed_evidence/run_eval.py`, extend the Release 2.1 metric collection where Pilot Report observability is read:

```python
    observability = pilot_report.get("observability", {})
    metrics["artifact_cache_fields_present"] = float(
        all(
            key in observability
            for key in (
                "artifact_cache_hit_count",
                "artifact_cache_miss_count",
                "artifact_cache_write_count",
                "saved_source_call_count",
                "cache_entries",
            )
        )
    )
    metrics["artifact_cache_not_evidence"] = float(
        "cache_entries" in observability
        and pilot_report.get("policy", {}).get("pilot_report_is_evidence_source") is False
        and pilot_report.get("policy", {}).get("memory_as_evidence") is False
    )
```

Use the existing metric dict variable name in that file. Do not add a new eval runner.

- [ ] **Step 2: Run targeted pytest**

Run:

```bash
.venv/bin/pytest -q tests/test_biomed_api.py tests/test_biomed_release_contracts.py
```

Expected: pass.

- [ ] **Step 3: Run release eval**

Run:

```bash
.venv/bin/python -m eval.biomed_evidence.run_eval --output /tmp/biomed_eval_release_2_1_artifact_cache.json
```

Expected: command exits 0 and writes JSON containing `artifact_cache_fields_present`.

- [ ] **Step 4: Run diff check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add eval/biomed_evidence/run_eval.py tests/test_biomed_api.py tests/test_biomed_release_contracts.py
git commit -m "test: add biomed artifact cache gates"
```

---

## Self-Review

- Spec coverage: retrieval, paper metadata via existing `biomed_papers`, full text, evidence packet, trace observability, Pilot Report observability, no semantic answer cache, and no memory-as-evidence are covered.
- Scope check: one subsystem only, implemented through existing biomedical storage/service/API/test surfaces.
- Placeholder scan: every task has concrete files, snippets, commands, and expected outcomes.
- Type consistency: cache entries are plain dicts; no new Pydantic cache model is introduced.
- Ponytail check: one table, no new dependency, no generic cache framework, no UI slice in this plan.
