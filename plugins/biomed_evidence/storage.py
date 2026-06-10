from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plugins.biomed_evidence.schemas import (
    AdvisoryVerifierResult,
    AgentTraceStep,
    AnswerWithEvidenceResult,
    AnswerRevision,
    BiomedProject,
    BiomedicalEntity,
    BiomedicalPaper,
    CitationAuditResult,
    ConflictAuditResult,
    EvidenceItem,
    ProjectClaimRecord,
    ProjectEvidenceBrief,
    ProjectPaperDecision,
    ProjectReviewQueueItem,
    RetrievalManifest,
    WatchDecisionDetail,
    WatchSnapshot,
    WatchTopic,
)


class BiomedStorage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._ensure_schema()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def upsert_paper(self, paper: BiomedicalPaper) -> None:
        now = _now_iso()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_papers(
                    paper_id, source, title, abstract, authors_json, journal,
                    publication_date, doi, url, mesh_terms_json, keywords_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, paper_id) DO UPDATE SET
                    title=excluded.title,
                    abstract=excluded.abstract,
                    authors_json=excluded.authors_json,
                    journal=excluded.journal,
                    publication_date=excluded.publication_date,
                    doi=excluded.doi,
                    url=excluded.url,
                    mesh_terms_json=excluded.mesh_terms_json,
                    keywords_json=excluded.keywords_json,
                    updated_at=excluded.updated_at
                """,
                (
                    paper.paper_id,
                    paper.source,
                    paper.title,
                    paper.abstract,
                    _json(paper.authors),
                    paper.journal,
                    paper.publication_date,
                    paper.doi,
                    paper.url,
                    _json(paper.mesh_terms),
                    _json(paper.keywords),
                    now,
                    now,
                ),
            )
            self._db.commit()

    def get_paper(self, paper_id: str, *, source: str = "") -> BiomedicalPaper | None:
        where = "paper_id = ?"
        params: tuple[Any, ...] = (paper_id,)
        if source:
            where += " AND source = ?"
            params = (paper_id, source)
        with self._lock:
            row = self._db.execute(
                f"""
                SELECT paper_id, source, title, abstract, authors_json, journal,
                       publication_date, doi, url, mesh_terms_json, keywords_json
                FROM biomed_papers
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return _paper_from_row(row) if row is not None else None

    def list_papers(
        self,
        *,
        q: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, object]], int]:
        where, params = self._build_filters(
            ("(title LIKE ? OR abstract LIKE ? OR paper_id LIKE ?)", _like3(q))
        )
        return self._list_rows(
            table="biomed_papers",
            columns=(
                "paper_id, source, title, journal, publication_date, doi, url, "
                "abstract IS NOT NULL AS abstract_available, updated_at"
            ),
            where=where,
            params=params,
            order_by="publication_date DESC, updated_at DESC",
            page=page,
            page_size=page_size,
        )

    def upsert_evidence(
        self,
        item: EvidenceItem,
        *,
        paper_source: str = "",
        retrieval_id: str | None = None,
    ) -> None:
        now = _now_iso()
        claim_hash = _claim_hash(item.claim)
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_evidence(
                    evidence_id, paper_id, source, claim_hash, claim, finding,
                    evidence_direction, methods_json, datasets_json, limitations_json,
                    confidence, evidence_span, retrieval_intent,
                    extraction_mode, extractor_model, extractor_prompt_hash,
                    requires_expert_review, retrieval_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id, claim_hash) DO UPDATE SET
                    source=excluded.source,
                    claim=excluded.claim,
                    finding=excluded.finding,
                    evidence_direction=excluded.evidence_direction,
                    methods_json=excluded.methods_json,
                    datasets_json=excluded.datasets_json,
                    limitations_json=excluded.limitations_json,
                    confidence=excluded.confidence,
                    evidence_span=excluded.evidence_span,
                    retrieval_intent=excluded.retrieval_intent,
                    extraction_mode=excluded.extraction_mode,
                    extractor_model=excluded.extractor_model,
                    extractor_prompt_hash=excluded.extractor_prompt_hash,
                    requires_expert_review=excluded.requires_expert_review,
                    retrieval_id=COALESCE(excluded.retrieval_id, biomed_evidence.retrieval_id),
                    updated_at=excluded.updated_at
                """,
                (
                    item.evidence_id,
                    item.paper_id,
                    paper_source,
                    claim_hash,
                    item.claim,
                    item.finding,
                    item.evidence_direction,
                    _json(item.methods),
                    _json(item.datasets_or_cohorts),
                    _json(item.limitations),
                    item.confidence,
                    item.evidence_span,
                    item.retrieval_intent,
                    item.extraction_mode,
                    item.extractor_model,
                    item.extractor_prompt_hash,
                    1 if item.requires_expert_review else 0,
                    retrieval_id,
                    now,
                    now,
                ),
            )
            row = self._db.execute(
                "SELECT evidence_id FROM biomed_evidence WHERE paper_id=? AND claim_hash=?",
                (item.paper_id, claim_hash),
            ).fetchone()
            evidence_id = str(
                row["evidence_id"] if row is not None else item.evidence_id
            )
            self._db.execute(
                "DELETE FROM biomed_evidence_entities WHERE evidence_id=?",
                (evidence_id,),
            )
            for entity in item.entities:
                entity_id = self._upsert_entity_locked(entity)
                self._db.execute(
                    """
                    INSERT OR IGNORE INTO biomed_evidence_entities(evidence_id, entity_id)
                    VALUES (?, ?)
                    """,
                    (evidence_id, entity_id),
                )
            self._db.commit()

    def list_evidence(
        self,
        *,
        q: str = "",
        paper_id: str = "",
        direction: str = "",
        entity: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, object]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if q.strip():
            needle = f"%{q.strip()}%"
            clauses.append("(e.claim LIKE ? OR e.finding LIKE ? OR p.title LIKE ?)")
            params.extend([needle, needle, needle])
        if paper_id.strip():
            clauses.append("e.paper_id = ?")
            params.append(paper_id.strip())
        if direction.strip():
            clauses.append("e.evidence_direction = ?")
            params.append(direction.strip())
        if entity.strip():
            needle = f"%{entity.strip()}%"
            clauses.append("""
                EXISTS (
                    SELECT 1 FROM biomed_evidence_entities ee
                    JOIN biomed_entities be ON be.entity_id = ee.entity_id
                    WHERE ee.evidence_id = e.evidence_id AND be.name LIKE ?
                )
                """)
            params.append(needle)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            total = int(
                self._db.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM biomed_evidence e
                    LEFT JOIN biomed_papers p ON p.paper_id = e.paper_id
                    {where}
                    """,
                    tuple(params),
                ).fetchone()[0]
            )
            rows = self._db.execute(
                f"""
                SELECT e.*, p.title AS paper_title, p.url AS paper_url, p.doi AS paper_doi
                FROM biomed_evidence e
                LEFT JOIN biomed_papers p ON p.paper_id = e.paper_id
                {where}
                ORDER BY e.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, _safe_size(page_size), _offset(page, page_size)),
            ).fetchall()
        return [self._evidence_row_to_dict(row) for row in rows], total

    def get_evidence_for_paper(self, paper_id: str) -> list[EvidenceItem]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM biomed_evidence WHERE paper_id=? ORDER BY created_at ASC",
                (paper_id,),
            ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def save_answer_run(
        self, result: AnswerWithEvidenceResult, *, question: str
    ) -> None:
        now = _now_iso()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_answer_runs(
                    run_id, question, answer_json, retrieval_id, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    question=excluded.question,
                    answer_json=excluded.answer_json,
                    retrieval_id=excluded.retrieval_id
                """,
                (
                    result.run_id,
                    question,
                    result.model_dump_json(),
                    result.retrieval_id,
                    now,
                ),
            )
            self._db.commit()

    def get_answer_run(self, run_id: str) -> AnswerWithEvidenceResult | None:
        with self._lock:
            row = self._db.execute(
                "SELECT answer_json FROM biomed_answer_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return AnswerWithEvidenceResult.model_validate_json(str(row["answer_json"]))

    def list_answer_runs(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[dict[str, object]], int]:
        return self._list_rows(
            table="biomed_answer_runs",
            columns="run_id, question, retrieval_id, created_at",
            where="",
            params=(),
            order_by="created_at DESC",
            page=page,
            page_size=page_size,
        )

    def save_project(self, project: BiomedProject) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_projects(
                    project_id, name, description, research_question,
                    include_keywords_json, exclude_keywords_json,
                    preferred_methods_json, preferred_species_json,
                    preferred_study_types_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    research_question=excluded.research_question,
                    include_keywords_json=excluded.include_keywords_json,
                    exclude_keywords_json=excluded.exclude_keywords_json,
                    preferred_methods_json=excluded.preferred_methods_json,
                    preferred_species_json=excluded.preferred_species_json,
                    preferred_study_types_json=excluded.preferred_study_types_json,
                    updated_at=excluded.updated_at
                """,
                _project_values(project),
            )
            self._db.commit()

    def get_project(self, project_id: str) -> BiomedProject | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM biomed_projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
        return _project_from_row(row) if row is not None else None

    def list_projects(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[BiomedProject], int]:
        with self._lock:
            total = int(
                self._db.execute("SELECT COUNT(*) FROM biomed_projects").fetchone()[0]
            )
            rows = self._db.execute(
                """
                SELECT *
                FROM biomed_projects
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (_safe_size(page_size), _offset(page, page_size)),
            ).fetchall()
        return [_project_from_row(row) for row in rows], total

    def save_project_paper_decision(
        self, decision: ProjectPaperDecision
    ) -> ProjectPaperDecision:
        now = decision.updated_at or _now_iso()
        created_at = decision.created_at or now
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_project_paper_decisions(
                    decision_id, project_id, paper_id, source, decision,
                    reason, tags_json, notes, run_id, retrieval_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, source, paper_id) DO UPDATE SET
                    decision=excluded.decision,
                    reason=excluded.reason,
                    tags_json=excluded.tags_json,
                    notes=excluded.notes,
                    run_id=excluded.run_id,
                    retrieval_id=excluded.retrieval_id,
                    updated_at=excluded.updated_at
                """,
                (
                    decision.decision_id,
                    decision.project_id,
                    decision.paper_id,
                    decision.source,
                    decision.decision,
                    decision.reason,
                    _json(decision.tags),
                    decision.notes,
                    decision.run_id,
                    decision.retrieval_id,
                    created_at,
                    now,
                ),
            )
            row = self._db.execute(
                """
                SELECT *
                FROM biomed_project_paper_decisions
                WHERE project_id=? AND source=? AND paper_id=?
                """,
                (decision.project_id, decision.source, decision.paper_id),
            ).fetchone()
            self._db.commit()
        return _project_paper_decision_from_row(row)

    def list_project_paper_decisions(
        self,
        project_id: str,
        *,
        decision: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[ProjectPaperDecision], int]:
        where = "WHERE project_id=?"
        params: list[Any] = [project_id]
        if decision.strip():
            where += " AND decision=?"
            params.append(decision.strip())
        with self._lock:
            total = int(
                self._db.execute(
                    f"SELECT COUNT(*) FROM biomed_project_paper_decisions {where}",
                    tuple(params),
                ).fetchone()[0]
            )
            rows = self._db.execute(
                f"""
                SELECT *
                FROM biomed_project_paper_decisions
                {where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, _safe_size(page_size), _offset(page, page_size)),
            ).fetchall()
        return [_project_paper_decision_from_row(row) for row in rows], total

    def get_project_paper_decision_map(
        self,
        project_id: str,
        *,
        source: str = "",
    ) -> dict[str, ProjectPaperDecision]:
        clauses = ["project_id=?"]
        params: list[Any] = [project_id]
        if source:
            clauses.append("source=?")
            params.append(source)
        with self._lock:
            rows = self._db.execute(
                f"""
                SELECT *
                FROM biomed_project_paper_decisions
                WHERE {' AND '.join(clauses)}
                """,
                tuple(params),
            ).fetchall()
        return {
            str(row["paper_id"]): _project_paper_decision_from_row(row)
            for row in rows
        }

    def save_project_claim_record(
        self, claim: ProjectClaimRecord
    ) -> ProjectClaimRecord:
        now = claim.updated_at or _now_iso()
        created_at = claim.created_at or now
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_project_claims(
                    claim_id, project_id, claim, claim_hash, status,
                    evidence_ids_json, audit_ids_json, verifier_ids_json,
                    notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, claim_hash) DO UPDATE SET
                    claim=excluded.claim,
                    status=excluded.status,
                    evidence_ids_json=excluded.evidence_ids_json,
                    audit_ids_json=excluded.audit_ids_json,
                    verifier_ids_json=excluded.verifier_ids_json,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    claim.claim_id,
                    claim.project_id,
                    claim.claim,
                    _claim_hash(claim.claim),
                    claim.status,
                    _json(claim.evidence_ids),
                    _json(claim.audit_ids),
                    _json(claim.verifier_ids),
                    claim.notes,
                    created_at,
                    now,
                ),
            )
            row = self._db.execute(
                """
                SELECT *
                FROM biomed_project_claims
                WHERE project_id=? AND claim_hash=?
                """,
                (claim.project_id, _claim_hash(claim.claim)),
            ).fetchone()
            self._db.commit()
        return _project_claim_from_row(row)

    def list_project_claim_records(
        self,
        project_id: str,
        *,
        status: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[ProjectClaimRecord], int]:
        where = "WHERE project_id=?"
        params: list[Any] = [project_id]
        if status.strip():
            where += " AND status=?"
            params.append(status.strip())
        with self._lock:
            total = int(
                self._db.execute(
                    f"SELECT COUNT(*) FROM biomed_project_claims {where}",
                    tuple(params),
                ).fetchone()[0]
            )
            rows = self._db.execute(
                f"""
                SELECT *
                FROM biomed_project_claims
                {where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, _safe_size(page_size), _offset(page, page_size)),
            ).fetchall()
        return [_project_claim_from_row(row) for row in rows], total

    def upsert_project_review_item(
        self, item: ProjectReviewQueueItem
    ) -> ProjectReviewQueueItem:
        item_key = _project_review_item_key(item)
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_project_review_queue(
                    item_id, project_id, item_key, item_type, title, reason,
                    risk_level, run_id, evidence_id, audit_id, verifier_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, item_key) DO UPDATE SET
                    item_type=excluded.item_type,
                    title=excluded.title,
                    reason=excluded.reason,
                    risk_level=excluded.risk_level,
                    run_id=excluded.run_id,
                    evidence_id=excluded.evidence_id,
                    audit_id=excluded.audit_id,
                    verifier_id=excluded.verifier_id
                """,
                (
                    item.item_id,
                    item.project_id,
                    item_key,
                    item.item_type,
                    item.title,
                    item.reason,
                    item.risk_level,
                    item.run_id,
                    item.evidence_id,
                    item.audit_id,
                    item.verifier_id,
                    item.created_at,
                ),
            )
            row = self._db.execute(
                """
                SELECT *
                FROM biomed_project_review_queue
                WHERE project_id=? AND item_key=?
                """,
                (item.project_id, item_key),
            ).fetchone()
            self._db.commit()
        return _project_review_item_from_row(row)

    def list_project_review_queue(
        self,
        project_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[ProjectReviewQueueItem], int]:
        with self._lock:
            total = int(
                self._db.execute(
                    "SELECT COUNT(*) FROM biomed_project_review_queue WHERE project_id=?",
                    (project_id,),
                ).fetchone()[0]
            )
            rows = self._db.execute(
                """
                SELECT *
                FROM biomed_project_review_queue
                WHERE project_id=?
                ORDER BY
                    CASE risk_level
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        ELSE 3
                    END,
                    created_at DESC
                LIMIT ? OFFSET ?
                """,
                (project_id, _safe_size(page_size), _offset(page, page_size)),
            ).fetchall()
        return [_project_review_item_from_row(row) for row in rows], total

    def save_project_brief(self, brief: ProjectEvidenceBrief) -> ProjectEvidenceBrief:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_project_briefs(
                    brief_id, project_id, title, format, content,
                    included_claim_ids_json, included_evidence_ids_json,
                    audit_ids_json, verifier_ids_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(brief_id) DO UPDATE SET
                    title=excluded.title,
                    format=excluded.format,
                    content=excluded.content,
                    included_claim_ids_json=excluded.included_claim_ids_json,
                    included_evidence_ids_json=excluded.included_evidence_ids_json,
                    audit_ids_json=excluded.audit_ids_json,
                    verifier_ids_json=excluded.verifier_ids_json
                """,
                (
                    brief.brief_id,
                    brief.project_id,
                    brief.title,
                    brief.format,
                    brief.content,
                    _json(brief.included_claim_ids),
                    _json(brief.included_evidence_ids),
                    _json(brief.audit_ids),
                    _json(brief.verifier_ids),
                    brief.created_at,
                ),
            )
            self._db.commit()
        return brief

    def list_project_briefs(
        self,
        project_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ProjectEvidenceBrief], int]:
        with self._lock:
            total = int(
                self._db.execute(
                    "SELECT COUNT(*) FROM biomed_project_briefs WHERE project_id=?",
                    (project_id,),
                ).fetchone()[0]
            )
            rows = self._db.execute(
                """
                SELECT *
                FROM biomed_project_briefs
                WHERE project_id=?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (project_id, _safe_size(page_size), _offset(page, page_size)),
            ).fetchall()
        return [_project_brief_from_row(row) for row in rows], total

    def save_agent_trace_steps(self, steps: list[AgentTraceStep]) -> None:
        if not steps:
            return
        with self._lock:
            for step in steps:
                self._db.execute(
                    """
                    INSERT INTO biomed_agent_trace_steps(
                        step_id, run_id, step, status, input_summary,
                        output_summary, warnings_json, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(step_id) DO UPDATE SET
                        run_id=excluded.run_id,
                        step=excluded.step,
                        status=excluded.status,
                        input_summary=excluded.input_summary,
                        output_summary=excluded.output_summary,
                        warnings_json=excluded.warnings_json,
                        metadata_json=excluded.metadata_json,
                        created_at=excluded.created_at
                    """,
                    (
                        step.step_id,
                        step.run_id,
                        step.step,
                        step.status,
                        step.input_summary,
                        step.output_summary,
                        _json(step.warnings),
                        _json(step.metadata),
                        step.created_at,
                    ),
                )
            self._db.commit()

    def list_agent_trace_steps(self, run_id: str) -> list[AgentTraceStep]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT *
                FROM biomed_agent_trace_steps
                WHERE run_id=?
                ORDER BY
                    CASE step
                        WHEN 'classify' THEN 1
                        WHEN 'plan' THEN 2
                        WHEN 'validate_plan' THEN 3
                        WHEN 'retrieve' THEN 4
                        WHEN 'extract' THEN 5
                        WHEN 'draft' THEN 6
                        WHEN 'audit' THEN 7
                        WHEN 'advisory_verify' THEN 8
                        WHEN 'revise' THEN 9
                        WHEN 'post_audit' THEN 10
                        WHEN 'finalize' THEN 11
                        ELSE 99
                    END,
                    created_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [_trace_step_from_row(row) for row in rows]

    def save_answer_revision(self, revision: AnswerRevision) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_answer_revisions(
                    revision_id, run_id, audit_id, post_revision_audit_id,
                    revision_mode, llm_model, llm_prompt_hash, draft_answer,
                    final_answer, revision_action, changed_claims_json,
                    removed_claims_json, softened_claims_json,
                    added_limitations_json, llm_raw_response_json,
                    fallback_reason, refusal_reason, revision_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(revision_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    audit_id=excluded.audit_id,
                    post_revision_audit_id=excluded.post_revision_audit_id,
                    revision_mode=excluded.revision_mode,
                    llm_model=excluded.llm_model,
                    llm_prompt_hash=excluded.llm_prompt_hash,
                    draft_answer=excluded.draft_answer,
                    final_answer=excluded.final_answer,
                    revision_action=excluded.revision_action,
                    changed_claims_json=excluded.changed_claims_json,
                    removed_claims_json=excluded.removed_claims_json,
                    softened_claims_json=excluded.softened_claims_json,
                    added_limitations_json=excluded.added_limitations_json,
                    llm_raw_response_json=excluded.llm_raw_response_json,
                    fallback_reason=excluded.fallback_reason,
                    refusal_reason=excluded.refusal_reason,
                    revision_json=excluded.revision_json,
                    created_at=excluded.created_at
                """,
                (
                    revision.revision_id,
                    revision.run_id,
                    revision.audit_id,
                    revision.post_revision_audit_id,
                    revision.revision_mode,
                    revision.llm_model,
                    revision.llm_prompt_hash,
                    revision.draft_answer,
                    revision.final_answer,
                    revision.revision_action,
                    _json(revision.changed_claims),
                    _json(revision.removed_claims),
                    _json(revision.softened_claims),
                    _json(revision.added_limitations),
                    _json(revision.llm_raw_response or {}),
                    revision.fallback_reason,
                    revision.refusal_reason,
                    revision.model_dump_json(),
                    revision.created_at,
                ),
            )
            self._db.commit()

    def get_answer_revision(self, run_id: str) -> AnswerRevision | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT revision_json
                FROM biomed_answer_revisions
                WHERE run_id=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return AnswerRevision.model_validate_json(str(row["revision_json"]))

    def save_advisory_verifier(self, result: AdvisoryVerifierResult) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_advisory_verifiers(
                    verifier_id, run_id, audit_id, retrieval_id, verifier_mode,
                    llm_model, llm_prompt_hash, deterministic_action,
                    advisory_action, high_risk_disagreement_count,
                    fallback_reason, verifier_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(verifier_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    audit_id=excluded.audit_id,
                    retrieval_id=excluded.retrieval_id,
                    verifier_mode=excluded.verifier_mode,
                    llm_model=excluded.llm_model,
                    llm_prompt_hash=excluded.llm_prompt_hash,
                    deterministic_action=excluded.deterministic_action,
                    advisory_action=excluded.advisory_action,
                    high_risk_disagreement_count=excluded.high_risk_disagreement_count,
                    fallback_reason=excluded.fallback_reason,
                    verifier_json=excluded.verifier_json,
                    created_at=excluded.created_at
                """,
                (
                    result.verifier_id,
                    result.run_id,
                    result.audit_id,
                    result.retrieval_id,
                    result.verifier_mode,
                    result.llm_model,
                    result.llm_prompt_hash,
                    result.deterministic_action,
                    result.advisory_action,
                    result.high_risk_disagreement_count,
                    result.fallback_reason,
                    result.model_dump_json(),
                    result.created_at,
                ),
            )
            self._db.commit()

    def get_latest_advisory_verifier_for_run(
        self, run_id: str
    ) -> AdvisoryVerifierResult | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT verifier_json
                FROM biomed_advisory_verifiers
                WHERE run_id=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return AdvisoryVerifierResult.model_validate_json(str(row["verifier_json"]))

    def save_citation_audit(self, audit: CitationAuditResult) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_answer_audits(
                    audit_id, run_id, retrieval_id, metrics_json,
                    recommended_action, audit_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(audit_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    retrieval_id=excluded.retrieval_id,
                    metrics_json=excluded.metrics_json,
                    recommended_action=excluded.recommended_action,
                    audit_json=excluded.audit_json,
                    created_at=excluded.created_at
                """,
                (
                    audit.audit_id,
                    audit.run_id,
                    audit.retrieval_id,
                    _json(
                        {
                            "claim_support_rate": audit.claim_support_rate,
                            "citation_precision": audit.citation_precision,
                            "unsupported_claim_rate": audit.unsupported_claim_rate,
                            "overclaim_rate": audit.overclaim_rate,
                            "conflict_awareness": audit.conflict_awareness,
                            "uncertainty_calibrated": audit.uncertainty_calibrated,
                        }
                    ),
                    audit.recommended_action,
                    audit.model_dump_json(),
                    audit.created_at,
                ),
            )
            self._db.execute(
                "DELETE FROM biomed_claim_audits WHERE audit_id=?",
                (audit.audit_id,),
            )
            for item in audit.claim_audits:
                self._db.execute(
                    """
                    INSERT INTO biomed_claim_audits(
                        claim_audit_id, audit_id, run_id, claim_text, claim_type,
                        verdict, support_score, cited_paper_ids_json,
                        evidence_ids_json, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{audit.audit_id}:{item.claim_id}",
                        audit.audit_id,
                        audit.run_id,
                        item.claim,
                        item.claim_type,
                        item.verdict,
                        item.support_score,
                        _json(item.cited_paper_ids),
                        _json(item.evidence_ids),
                        item.reason,
                        audit.created_at,
                    ),
                )
            self._db.commit()

    def get_citation_audit(self, audit_id: str) -> CitationAuditResult | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT audit_json
                FROM biomed_answer_audits
                WHERE audit_id=?
                """,
                (audit_id,),
            ).fetchone()
        if row is None:
            return None
        return CitationAuditResult.model_validate_json(str(row["audit_json"]))

    def get_latest_citation_audit_for_run(
        self, run_id: str
    ) -> CitationAuditResult | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT audit_json
                FROM biomed_answer_audits
                WHERE run_id=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return CitationAuditResult.model_validate_json(str(row["audit_json"]))

    def list_citation_audits(
        self,
        *,
        run_id: str = "",
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[dict[str, object]], int]:
        where = " WHERE run_id=?" if run_id else ""
        params: tuple[Any, ...] = (run_id,) if run_id else ()
        rows, total = self._list_rows(
            table="biomed_answer_audits",
            columns=(
                "audit_id, run_id, retrieval_id, metrics_json, "
                "recommended_action, created_at"
            ),
            where=where,
            params=params,
            order_by="created_at DESC",
            page=page,
            page_size=page_size,
        )
        for row in rows:
            row["metrics"] = _json_dict(row.pop("metrics_json", "{}"))
        return rows, total

    def save_conflict_audit(self, audit: ConflictAuditResult) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_conflict_audits(
                    conflict_audit_id, claim_hash, topic, retrieval_id,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(conflict_audit_id) DO UPDATE SET
                    topic=excluded.topic,
                    retrieval_id=excluded.retrieval_id,
                    result_json=excluded.result_json,
                    created_at=excluded.created_at
                """,
                (
                    audit.conflict_audit_id,
                    _claim_hash(audit.claim),
                    audit.topic,
                    audit.retrieval_id,
                    audit.model_dump_json(),
                    audit.created_at,
                ),
            )
            self._db.commit()

    def create_watch(self, watch: WatchTopic) -> WatchTopic:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_watch_topics(
                    watch_id, topic, description, include_keywords_json,
                    exclude_keywords_json, preferred_methods_json, min_relevance_score,
                    schedule, enabled, created_at, updated_at, last_checked_at,
                    next_check_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _watch_values(watch),
            )
            self._db.commit()
        return watch

    def update_watch(self, watch: WatchTopic) -> WatchTopic:
        with self._lock:
            self._db.execute(
                """
                UPDATE biomed_watch_topics SET
                    topic=?, description=?, include_keywords_json=?,
                    exclude_keywords_json=?, preferred_methods_json=?,
                    min_relevance_score=?, schedule=?, enabled=?, updated_at=?,
                    last_checked_at=?, next_check_at=?
                WHERE watch_id=?
                """,
                (
                    watch.topic,
                    watch.description,
                    _json(watch.include_keywords),
                    _json(watch.exclude_keywords),
                    _json(watch.preferred_methods),
                    watch.min_relevance_score,
                    watch.schedule,
                    1 if watch.enabled else 0,
                    watch.updated_at,
                    watch.last_checked_at,
                    watch.next_check_at,
                    watch.watch_id,
                ),
            )
            self._db.commit()
        return watch

    def get_watch(self, watch_id: str) -> WatchTopic | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM biomed_watch_topics WHERE watch_id=?",
                (watch_id,),
            ).fetchone()
        return _watch_from_row(row) if row is not None else None

    def list_watches(
        self,
        *,
        include_disabled: bool = True,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[WatchTopic], int]:
        where = "" if include_disabled else " WHERE enabled = 1"
        with self._lock:
            total = int(
                self._db.execute(
                    f"SELECT COUNT(*) FROM biomed_watch_topics{where}"
                ).fetchone()[0]
            )
            rows = self._db.execute(
                f"""
                SELECT * FROM biomed_watch_topics{where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (_safe_size(page_size), _offset(page, page_size)),
            ).fetchall()
        return [_watch_from_row(row) for row in rows], total

    def delete_watch(self, watch_id: str) -> bool:
        with self._lock:
            result = self._db.execute(
                "DELETE FROM biomed_watch_topics WHERE watch_id=?",
                (watch_id,),
            )
            self._db.commit()
        return bool(result.rowcount)

    def upsert_watch_decision(
        self,
        decision: WatchDecisionDetail,
        *,
        source: str,
    ) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_watch_decisions(
                    decision_id, watch_id, paper_id, source, retrieval_id, snapshot_id,
                    relevance_score, decision, rationale, uncertainty, dedupe_reason,
                    notification_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(watch_id, paper_id) DO UPDATE SET
                    source=excluded.source,
                    retrieval_id=excluded.retrieval_id,
                    snapshot_id=excluded.snapshot_id,
                    relevance_score=excluded.relevance_score,
                    decision=excluded.decision,
                    rationale=excluded.rationale,
                    uncertainty=excluded.uncertainty,
                    dedupe_reason=excluded.dedupe_reason,
                    notification_json=excluded.notification_json,
                    created_at=excluded.created_at
                """,
                (
                    decision.decision_id,
                    decision.watch_id,
                    decision.paper_id,
                    source,
                    decision.retrieval_id,
                    decision.snapshot_id,
                    decision.relevance_score,
                    decision.decision,
                    decision.rationale,
                    decision.uncertainty,
                    decision.dedupe_reason,
                    _json(decision.notification),
                    decision.created_at,
                ),
            )
            self._db.commit()

    def save_retrieval_manifest(self, manifest: RetrievalManifest) -> None:
        now = _now_iso()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_retrieval_manifests(
                    retrieval_id, source, original_query, compiled_query,
                    manifest_json, started_at, finished_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(retrieval_id) DO UPDATE SET
                    source=excluded.source,
                    original_query=excluded.original_query,
                    compiled_query=excluded.compiled_query,
                    manifest_json=excluded.manifest_json,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at
                """,
                (
                    manifest.retrieval_id,
                    manifest.source,
                    manifest.original_query,
                    manifest.compiled_query,
                    manifest.model_dump_json(),
                    manifest.started_at,
                    manifest.finished_at,
                    now,
                ),
            )
            self._db.commit()

    def get_retrieval_manifest(self, retrieval_id: str) -> RetrievalManifest | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT manifest_json
                FROM biomed_retrieval_manifests
                WHERE retrieval_id=?
                """,
                (retrieval_id,),
            ).fetchone()
        if row is None:
            return None
        return RetrievalManifest.model_validate_json(str(row["manifest_json"]))

    def link_retrieval_papers(
        self,
        retrieval_id: str,
        *,
        source: str,
        paper_ids: list[str],
    ) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM biomed_retrieval_papers WHERE retrieval_id=?",
                (retrieval_id,),
            )
            for index, paper_id in enumerate(paper_ids):
                self._db.execute(
                    """
                    INSERT OR IGNORE INTO biomed_retrieval_papers(
                        retrieval_id, source, paper_id, ordinal
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (retrieval_id, source, paper_id, index),
                )
            self._db.commit()

    def save_watch_snapshot(self, snapshot: WatchSnapshot) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO biomed_watch_snapshots(
                    snapshot_id, watch_id, retrieval_id, paper_ids_json,
                    new_paper_ids_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    retrieval_id=excluded.retrieval_id,
                    paper_ids_json=excluded.paper_ids_json,
                    new_paper_ids_json=excluded.new_paper_ids_json,
                    created_at=excluded.created_at
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.watch_id,
                    snapshot.retrieval_id,
                    _json(snapshot.paper_ids),
                    _json(snapshot.new_paper_ids),
                    snapshot.created_at,
                ),
            )
            self._db.commit()

    def list_watch_decisions(
        self,
        *,
        watch_id: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[WatchDecisionDetail], int]:
        where = " WHERE watch_id=?" if watch_id else ""
        params: tuple[Any, ...] = (watch_id,) if watch_id else ()
        with self._lock:
            total = int(
                self._db.execute(
                    f"SELECT COUNT(*) FROM biomed_watch_decisions{where}",
                    params,
                ).fetchone()[0]
            )
            rows = self._db.execute(
                f"""
                SELECT d.*, p.title AS title
                FROM biomed_watch_decisions d
                LEFT JOIN biomed_papers p ON p.paper_id = d.paper_id
                {where}
                ORDER BY d.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, _safe_size(page_size), _offset(page, page_size)),
            ).fetchall()
        return [_decision_from_row(row) for row in rows], total

    def _evidence_from_row(self, row: sqlite3.Row) -> EvidenceItem:
        entities = self._entities_for_evidence(str(row["evidence_id"]))
        return EvidenceItem(
            evidence_id=str(row["evidence_id"]),
            paper_id=str(row["paper_id"]),
            claim=str(row["claim"]),
            finding=str(row["finding"]),
            evidence_direction=row["evidence_direction"],
            entities=entities,
            methods=_json_list(row["methods_json"]),
            datasets_or_cohorts=_json_list(row["datasets_json"]),
            limitations=_json_list(row["limitations_json"]),
            confidence=row["confidence"],
            evidence_span=row["evidence_span"],
            retrieval_intent=(
                row["retrieval_intent"]
                if "retrieval_intent" in row.keys()
                else "unknown"
            ),
            extraction_mode=(
                row["extraction_mode"]
                if "extraction_mode" in row.keys()
                else "deterministic"
            ),
            extractor_model=(
                row["extractor_model"] if "extractor_model" in row.keys() else None
            ),
            extractor_prompt_hash=(
                row["extractor_prompt_hash"]
                if "extractor_prompt_hash" in row.keys()
                else None
            ),
            requires_expert_review=bool(row["requires_expert_review"]),
        )

    def _evidence_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        item = self._evidence_from_row(row)
        data = item.model_dump(mode="json")
        data["paper_title"] = row["paper_title"]
        data["paper_url"] = row["paper_url"]
        data["paper_doi"] = row["paper_doi"]
        data["source"] = row["source"]
        data["retrieval_id"] = (
            row["retrieval_id"] if "retrieval_id" in row.keys() else None
        )
        return data

    def _entities_for_evidence(self, evidence_id: str) -> list[BiomedicalEntity]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT be.name, be.entity_type, be.normalized_id
                FROM biomed_evidence_entities ee
                JOIN biomed_entities be ON be.entity_id = ee.entity_id
                WHERE ee.evidence_id=?
                ORDER BY be.name ASC
                """,
                (evidence_id,),
            ).fetchall()
        return [
            BiomedicalEntity(
                name=str(row["name"]),
                entity_type=row["entity_type"],
                normalized_id=row["normalized_id"],
            )
            for row in rows
        ]

    def _upsert_entity_locked(self, entity: BiomedicalEntity) -> str:
        key = _entity_key(entity)
        entity_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        self._db.execute(
            """
            INSERT INTO biomed_entities(entity_id, entity_key, name, entity_type, normalized_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(entity_key) DO UPDATE SET
                name=excluded.name,
                entity_type=excluded.entity_type,
                normalized_id=excluded.normalized_id
            """,
            (entity_id, key, entity.name, entity.entity_type, entity.normalized_id),
        )
        return entity_id

    def _list_rows(
        self,
        *,
        table: str,
        columns: str,
        where: str,
        params: tuple[Any, ...],
        order_by: str,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], int]:
        safe_size = _safe_size(page_size)
        offset = _offset(page, page_size)
        with self._lock:
            total = int(
                self._db.execute(
                    f"SELECT COUNT(*) FROM {table}{where}", params
                ).fetchone()[0]
            )
            rows = self._db.execute(
                f"""
                SELECT {columns}
                FROM {table}{where}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                (*params, safe_size, offset),
            ).fetchall()
        return [_row_to_dict(row) for row in rows], total

    @staticmethod
    def _build_filters(
        *filters: tuple[str, tuple[Any, ...] | None]
    ) -> tuple[str, tuple[Any, ...]]:
        clauses: list[str] = []
        params: list[Any] = []
        for clause, values in filters:
            if values is None:
                continue
            clauses.append(clause)
            params.extend(values)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)

    def _ensure_schema(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS biomed_papers(
                paper_id TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                abstract TEXT,
                authors_json TEXT NOT NULL DEFAULT '[]',
                journal TEXT,
                publication_date TEXT,
                doi TEXT,
                url TEXT,
                mesh_terms_json TEXT NOT NULL DEFAULT '[]',
                keywords_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(source, paper_id)
            );
            CREATE TABLE IF NOT EXISTS biomed_entities(
                entity_id TEXT PRIMARY KEY,
                entity_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                normalized_id TEXT
            );
            CREATE TABLE IF NOT EXISTS biomed_evidence(
                evidence_id TEXT PRIMARY KEY,
                paper_id TEXT NOT NULL,
                source TEXT NOT NULL,
                claim_hash TEXT NOT NULL,
                claim TEXT NOT NULL,
                finding TEXT NOT NULL,
                evidence_direction TEXT NOT NULL,
                methods_json TEXT NOT NULL DEFAULT '[]',
                datasets_json TEXT NOT NULL DEFAULT '[]',
                limitations_json TEXT NOT NULL DEFAULT '[]',
                confidence TEXT NOT NULL,
                evidence_span TEXT,
                retrieval_intent TEXT NOT NULL DEFAULT 'unknown',
                extraction_mode TEXT NOT NULL DEFAULT 'deterministic',
                extractor_model TEXT,
                extractor_prompt_hash TEXT,
                requires_expert_review INTEGER NOT NULL DEFAULT 1,
                retrieval_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(paper_id, claim_hash)
            );
            CREATE TABLE IF NOT EXISTS biomed_evidence_entities(
                evidence_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                PRIMARY KEY(evidence_id, entity_id),
                FOREIGN KEY(evidence_id) REFERENCES biomed_evidence(evidence_id) ON DELETE CASCADE,
                FOREIGN KEY(entity_id) REFERENCES biomed_entities(entity_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS biomed_watch_topics(
                watch_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                description TEXT,
                include_keywords_json TEXT NOT NULL DEFAULT '[]',
                exclude_keywords_json TEXT NOT NULL DEFAULT '[]',
                preferred_methods_json TEXT NOT NULL DEFAULT '[]',
                min_relevance_score REAL NOT NULL DEFAULT 0.7,
                schedule TEXT NOT NULL DEFAULT 'daily',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_checked_at TEXT,
                next_check_at TEXT
            );
            CREATE TABLE IF NOT EXISTS biomed_watch_decisions(
                decision_id TEXT PRIMARY KEY,
                watch_id TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                source TEXT NOT NULL,
                retrieval_id TEXT,
                snapshot_id TEXT,
                relevance_score REAL NOT NULL,
                decision TEXT NOT NULL,
                rationale TEXT NOT NULL,
                uncertainty TEXT NOT NULL,
                dedupe_reason TEXT,
                notification_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(watch_id, paper_id),
                FOREIGN KEY(watch_id) REFERENCES biomed_watch_topics(watch_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS biomed_projects(
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                research_question TEXT NOT NULL DEFAULT '',
                include_keywords_json TEXT NOT NULL DEFAULT '[]',
                exclude_keywords_json TEXT NOT NULL DEFAULT '[]',
                preferred_methods_json TEXT NOT NULL DEFAULT '[]',
                preferred_species_json TEXT NOT NULL DEFAULT '[]',
                preferred_study_types_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biomed_project_paper_decisions(
                decision_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                source TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT,
                run_id TEXT,
                retrieval_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, source, paper_id),
                FOREIGN KEY(project_id) REFERENCES biomed_projects(project_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS biomed_project_claims(
                claim_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                claim TEXT NOT NULL,
                claim_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'needs_review',
                evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                audit_ids_json TEXT NOT NULL DEFAULT '[]',
                verifier_ids_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, claim_hash),
                FOREIGN KEY(project_id) REFERENCES biomed_projects(project_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS biomed_project_review_queue(
                item_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL,
                reason TEXT NOT NULL,
                risk_level TEXT NOT NULL DEFAULT 'medium',
                run_id TEXT,
                evidence_id TEXT,
                audit_id TEXT,
                verifier_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, item_key),
                FOREIGN KEY(project_id) REFERENCES biomed_projects(project_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS biomed_project_briefs(
                brief_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                format TEXT NOT NULL DEFAULT 'markdown',
                content TEXT NOT NULL,
                included_claim_ids_json TEXT NOT NULL DEFAULT '[]',
                included_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                audit_ids_json TEXT NOT NULL DEFAULT '[]',
                verifier_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES biomed_projects(project_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS biomed_answer_runs(
                run_id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                answer_json TEXT NOT NULL,
                retrieval_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biomed_retrieval_manifests(
                retrieval_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                original_query TEXT NOT NULL,
                compiled_query TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biomed_retrieval_papers(
                retrieval_id TEXT NOT NULL,
                source TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                PRIMARY KEY(retrieval_id, paper_id),
                FOREIGN KEY(retrieval_id) REFERENCES biomed_retrieval_manifests(retrieval_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS biomed_watch_snapshots(
                snapshot_id TEXT PRIMARY KEY,
                watch_id TEXT NOT NULL,
                retrieval_id TEXT NOT NULL,
                paper_ids_json TEXT NOT NULL DEFAULT '[]',
                new_paper_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY(watch_id) REFERENCES biomed_watch_topics(watch_id) ON DELETE CASCADE,
                FOREIGN KEY(retrieval_id) REFERENCES biomed_retrieval_manifests(retrieval_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS biomed_answer_audits(
                audit_id TEXT PRIMARY KEY,
                run_id TEXT,
                retrieval_id TEXT,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                recommended_action TEXT NOT NULL,
                audit_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biomed_claim_audits(
                claim_audit_id TEXT PRIMARY KEY,
                audit_id TEXT NOT NULL,
                run_id TEXT,
                claim_text TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                verdict TEXT NOT NULL,
                support_score REAL NOT NULL,
                cited_paper_ids_json TEXT NOT NULL DEFAULT '[]',
                evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(audit_id) REFERENCES biomed_answer_audits(audit_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS biomed_conflict_audits(
                conflict_audit_id TEXT PRIMARY KEY,
                claim_hash TEXT NOT NULL,
                topic TEXT NOT NULL,
                retrieval_id TEXT,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biomed_agent_trace_steps(
                step_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step TEXT NOT NULL,
                status TEXT NOT NULL,
                input_summary TEXT NOT NULL DEFAULT '',
                output_summary TEXT NOT NULL DEFAULT '',
                warnings_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(run_id, step)
            );
            CREATE TABLE IF NOT EXISTS biomed_answer_revisions(
                revision_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                audit_id TEXT,
                post_revision_audit_id TEXT,
                revision_mode TEXT NOT NULL DEFAULT 'deterministic',
                llm_model TEXT,
                llm_prompt_hash TEXT,
                draft_answer TEXT NOT NULL,
                final_answer TEXT NOT NULL,
                revision_action TEXT NOT NULL,
                changed_claims_json TEXT NOT NULL DEFAULT '[]',
                removed_claims_json TEXT NOT NULL DEFAULT '[]',
                softened_claims_json TEXT NOT NULL DEFAULT '[]',
                added_limitations_json TEXT NOT NULL DEFAULT '[]',
                llm_raw_response_json TEXT NOT NULL DEFAULT '{}',
                fallback_reason TEXT,
                refusal_reason TEXT,
                revision_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS biomed_advisory_verifiers(
                verifier_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                audit_id TEXT NOT NULL,
                retrieval_id TEXT,
                verifier_mode TEXT NOT NULL,
                llm_model TEXT,
                llm_prompt_hash TEXT,
                deterministic_action TEXT NOT NULL,
                advisory_action TEXT NOT NULL,
                high_risk_disagreement_count INTEGER NOT NULL DEFAULT 0,
                fallback_reason TEXT,
                verifier_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """)
        self._ensure_column("biomed_evidence", "retrieval_id", "TEXT")
        self._ensure_column(
            "biomed_evidence", "retrieval_intent", "TEXT NOT NULL DEFAULT 'unknown'"
        )
        self._ensure_column(
            "biomed_evidence",
            "extraction_mode",
            "TEXT NOT NULL DEFAULT 'deterministic'",
        )
        self._ensure_column("biomed_evidence", "extractor_model", "TEXT")
        self._ensure_column("biomed_evidence", "extractor_prompt_hash", "TEXT")
        self._ensure_column("biomed_watch_decisions", "retrieval_id", "TEXT")
        self._ensure_column("biomed_watch_decisions", "snapshot_id", "TEXT")
        self._ensure_column("biomed_watch_decisions", "dedupe_reason", "TEXT")
        self._ensure_column("biomed_answer_runs", "retrieval_id", "TEXT")
        self._ensure_column("biomed_answer_revisions", "post_revision_audit_id", "TEXT")
        self._ensure_column(
            "biomed_answer_revisions",
            "revision_mode",
            "TEXT NOT NULL DEFAULT 'deterministic'",
        )
        self._ensure_column("biomed_answer_revisions", "llm_model", "TEXT")
        self._ensure_column("biomed_answer_revisions", "llm_prompt_hash", "TEXT")
        self._ensure_column(
            "biomed_answer_revisions",
            "llm_raw_response_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        self._ensure_column("biomed_answer_revisions", "fallback_reason", "TEXT")
        self._db.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        rows = self._db.execute(f"PRAGMA table_info({table})").fetchall()
        if any(str(row["name"]) == column for row in rows):
            return
        self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _paper_from_row(row: sqlite3.Row) -> BiomedicalPaper:
    return BiomedicalPaper(
        paper_id=str(row["paper_id"]),
        source=row["source"],
        title=str(row["title"]),
        abstract=row["abstract"],
        authors=_json_list(row["authors_json"]),
        journal=row["journal"],
        publication_date=row["publication_date"],
        doi=row["doi"],
        url=row["url"],
        mesh_terms=_json_list(row["mesh_terms_json"]),
        keywords=_json_list(row["keywords_json"]),
    )


def _project_values(project: BiomedProject) -> tuple[object, ...]:
    return (
        project.project_id,
        project.name,
        project.description,
        project.research_question,
        _json(project.include_keywords),
        _json(project.exclude_keywords),
        _json(project.preferred_methods),
        _json(project.preferred_species),
        _json(project.preferred_study_types),
        project.created_at,
        project.updated_at,
    )


def _project_from_row(row: sqlite3.Row) -> BiomedProject:
    return BiomedProject(
        project_id=str(row["project_id"]),
        name=str(row["name"]),
        description=row["description"],
        research_question=str(row["research_question"] or ""),
        include_keywords=_json_list(row["include_keywords_json"]),
        exclude_keywords=_json_list(row["exclude_keywords_json"]),
        preferred_methods=_json_list(row["preferred_methods_json"]),
        preferred_species=_json_list(row["preferred_species_json"]),
        preferred_study_types=_json_list(row["preferred_study_types_json"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _project_paper_decision_from_row(row: sqlite3.Row) -> ProjectPaperDecision:
    return ProjectPaperDecision(
        decision_id=str(row["decision_id"]),
        project_id=str(row["project_id"]),
        paper_id=str(row["paper_id"]),
        source=row["source"],
        decision=row["decision"],
        reason=row["reason"],
        tags=_json_list(row["tags_json"]),
        notes=row["notes"],
        run_id=row["run_id"],
        retrieval_id=row["retrieval_id"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _project_claim_from_row(row: sqlite3.Row) -> ProjectClaimRecord:
    return ProjectClaimRecord(
        claim_id=str(row["claim_id"]),
        project_id=str(row["project_id"]),
        claim=str(row["claim"]),
        status=row["status"],
        evidence_ids=_json_list(row["evidence_ids_json"]),
        audit_ids=_json_list(row["audit_ids_json"]),
        verifier_ids=_json_list(row["verifier_ids_json"]),
        notes=row["notes"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _project_review_item_from_row(row: sqlite3.Row) -> ProjectReviewQueueItem:
    return ProjectReviewQueueItem(
        item_id=str(row["item_id"]),
        project_id=str(row["project_id"]),
        item_type=row["item_type"],
        title=str(row["title"]),
        reason=str(row["reason"]),
        risk_level=row["risk_level"],
        run_id=row["run_id"],
        evidence_id=row["evidence_id"],
        audit_id=row["audit_id"],
        verifier_id=row["verifier_id"],
        created_at=str(row["created_at"]),
    )


def _project_brief_from_row(row: sqlite3.Row) -> ProjectEvidenceBrief:
    return ProjectEvidenceBrief(
        brief_id=str(row["brief_id"]),
        project_id=str(row["project_id"]),
        title=str(row["title"]),
        format=row["format"],
        content=str(row["content"]),
        included_claim_ids=_json_list(row["included_claim_ids_json"]),
        included_evidence_ids=_json_list(row["included_evidence_ids_json"]),
        audit_ids=_json_list(row["audit_ids_json"]),
        verifier_ids=_json_list(row["verifier_ids_json"]),
        created_at=str(row["created_at"]),
    )


def _project_review_item_key(item: ProjectReviewQueueItem) -> str:
    parts = [
        item.item_type,
        item.run_id or "",
        item.evidence_id or "",
        item.audit_id or "",
        item.verifier_id or "",
        item.title,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _watch_values(watch: WatchTopic) -> tuple[object, ...]:
    return (
        watch.watch_id,
        watch.topic,
        watch.description,
        _json(watch.include_keywords),
        _json(watch.exclude_keywords),
        _json(watch.preferred_methods),
        watch.min_relevance_score,
        watch.schedule,
        1 if watch.enabled else 0,
        watch.created_at,
        watch.updated_at,
        watch.last_checked_at,
        watch.next_check_at,
    )


def _watch_from_row(row: sqlite3.Row) -> WatchTopic:
    return WatchTopic(
        watch_id=str(row["watch_id"]),
        topic=str(row["topic"]),
        description=row["description"],
        include_keywords=_json_list(row["include_keywords_json"]),
        exclude_keywords=_json_list(row["exclude_keywords_json"]),
        preferred_methods=_json_list(row["preferred_methods_json"]),
        min_relevance_score=float(row["min_relevance_score"]),
        schedule=row["schedule"],
        enabled=bool(row["enabled"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        last_checked_at=row["last_checked_at"],
        next_check_at=row["next_check_at"],
    )


def _decision_from_row(row: sqlite3.Row) -> WatchDecisionDetail:
    return WatchDecisionDetail(
        decision_id=str(row["decision_id"]),
        watch_id=str(row["watch_id"]),
        paper_id=str(row["paper_id"]),
        retrieval_id=row["retrieval_id"] if "retrieval_id" in row.keys() else None,
        snapshot_id=row["snapshot_id"] if "snapshot_id" in row.keys() else None,
        relevance_score=float(row["relevance_score"]),
        decision=row["decision"],
        rationale=str(row["rationale"]),
        uncertainty=row["uncertainty"],
        dedupe_reason=row["dedupe_reason"] if "dedupe_reason" in row.keys() else None,
        created_at=str(row["created_at"]),
        title=row["title"] if "title" in row.keys() else None,
        source=row["source"] if "source" in row.keys() else None,
        notification=_json_dict(row["notification_json"]),
    )


def _trace_step_from_row(row: sqlite3.Row) -> AgentTraceStep:
    metadata = _json_dict(row["metadata_json"])
    return AgentTraceStep(
        step_id=str(row["step_id"]),
        run_id=str(row["run_id"]),
        step=row["step"],
        status=row["status"],
        input_summary=str(row["input_summary"]),
        output_summary=str(row["output_summary"]),
        warnings=_json_list(row["warnings_json"]),
        metadata=metadata,
        created_at=str(row["created_at"]),
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in row.keys()}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_list(value: object) -> list[str]:
    try:
        loaded = json.loads(str(value or "[]"))
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded]


def _json_dict(value: object) -> dict[str, object]:
    try:
        loaded = json.loads(str(value or "{}"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _like3(value: str) -> tuple[str, str, str] | None:
    text = value.strip()
    if not text:
        return None
    needle = f"%{text}%"
    return (needle, needle, needle)


def _safe_size(page_size: int) -> int:
    return max(1, min(int(page_size), 200))


def _offset(page: int, page_size: int) -> int:
    return (max(1, int(page)) - 1) * _safe_size(page_size)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_hash(claim: str) -> str:
    normalized = " ".join(claim.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _entity_key(entity: BiomedicalEntity) -> str:
    normalized = (entity.normalized_id or entity.name).strip().lower()
    return f"{entity.entity_type}:{normalized}"
