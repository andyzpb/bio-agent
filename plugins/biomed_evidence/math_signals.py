from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Iterable
from typing import Literal

from plugins.biomed_evidence.schemas import (
    AnswerRevision,
    AnswerWithEvidenceResult,
    ArgumentGraphEdge,
    ArgumentGraphNode,
    ArgumentGraphResult,
    ClaimArgumentSummary,
    ClaimAuditItem,
    ClaimUncertaintySignal,
    ConfidenceLevel,
    CoverageDiversitySignal,
    EvidenceItem,
    MathSignalsResult,
    StepTelemetrySummary,
)


def build_argument_graph(
    *,
    run: AnswerWithEvidenceResult,
    audit: object | None,
) -> ArgumentGraphResult:
    audit_id = str(getattr(audit, "audit_id", "") or "") or None
    if _not_applicable(run):
        return ArgumentGraphResult(
            run_id=run.run_id,
            audit_id=audit_id,
            retrieval_id=run.retrieval_id,
            status="not_applicable",
            not_applicable_reason=(
                "No retrieval-backed evidence is attached to this run. Clinical "
                "or policy-boundary runs intentionally skip argument graph review."
            ),
        )

    claim_audits = list(getattr(audit, "claim_audits", []) or [])
    evidence_by_id = {item.evidence_id: item for item in run.evidence_summary}
    nodes: dict[str, ArgumentGraphNode] = {}
    edges: dict[str, ArgumentGraphEdge] = {}
    summaries: list[ClaimArgumentSummary] = []

    for claim_index, claim in enumerate(claim_audits):
        claim_node_id = _claim_node_id(claim, claim_index)
        nodes[claim_node_id] = ArgumentGraphNode(
            node_id=claim_node_id,
            node_type="claim",
            label=claim.claim,
            metadata={
                "claim_id": claim.claim_id,
                "verdict": claim.verdict,
                "support_score": claim.support_score,
                "claim_type": claim.claim_type,
            },
        )
        support_ids: list[str] = []
        attack_ids: list[str] = []
        limitation_summary: list[str] = []
        citation_count = 0

        for paper_id in claim.cited_paper_ids:
            paper_node_id = f"paper:{_stable_token(paper_id)}"
            nodes.setdefault(
                paper_node_id,
                ArgumentGraphNode(
                    node_id=paper_node_id,
                    node_type="paper",
                    label=paper_id,
                    metadata={"paper_id": paper_id},
                ),
            )
            citation_count += 1
            _add_edge(
                edges,
                source=claim_node_id,
                target=paper_node_id,
                edge_type="cites",
                weight=1.0,
                metadata={"paper_id": paper_id},
            )

        evidence_ids = claim.evidence_ids or _fallback_evidence_ids(
            claim, run.evidence_summary
        )
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            evidence_node_id = f"evidence:{_stable_token(evidence.evidence_id)}"
            nodes.setdefault(
                evidence_node_id,
                ArgumentGraphNode(
                    node_id=evidence_node_id,
                    node_type="evidence",
                    label=_short_label(evidence.finding or evidence.claim),
                    metadata={
                        "evidence_id": evidence.evidence_id,
                        "paper_id": evidence.paper_id,
                        "direction": evidence.evidence_direction,
                        "confidence": evidence.confidence,
                        "retrieval_intent": evidence.retrieval_intent,
                    },
                ),
            )
            edge_type = _argument_edge_type(claim, evidence)
            if edge_type == "attacks":
                attack_ids.append(evidence.evidence_id)
            else:
                support_ids.append(evidence.evidence_id)
            _add_edge(
                edges,
                source=evidence_node_id,
                target=claim_node_id,
                edge_type=edge_type,
                weight=_edge_weight(claim, evidence),
                metadata={
                    "verdict": claim.verdict,
                    "evidence_direction": evidence.evidence_direction,
                },
            )
            for limitation in evidence.limitations:
                limitation_text = limitation.strip()
                if not limitation_text:
                    continue
                limitation_summary.append(limitation_text)
                limitation_node_id = (
                    f"limitation:{_stable_token(claim.claim_id + limitation_text)}"
                )
                nodes.setdefault(
                    limitation_node_id,
                    ArgumentGraphNode(
                        node_id=limitation_node_id,
                        node_type="limitation",
                        label=_short_label(limitation_text),
                        metadata={
                            "claim_id": claim.claim_id,
                            "evidence_id": evidence.evidence_id,
                        },
                    ),
                )
                _add_edge(
                    edges,
                    source=evidence_node_id,
                    target=limitation_node_id,
                    edge_type="limits",
                    weight=0.5,
                    metadata={"claim_id": claim.claim_id},
                )

        summaries.append(
            ClaimArgumentSummary(
                claim_id=claim.claim_id,
                support_count=len(set(support_ids)),
                attack_count=len(set(attack_ids)),
                limitation_count=len(set(limitation_summary)),
                citation_count=citation_count,
                unresolved_conflict_count=(
                    1 if support_ids and attack_ids else 0
                ),
                strongest_supporting_evidence_ids=_unique(support_ids)[:3],
                strongest_attacking_evidence_ids=_unique(attack_ids)[:3],
                limitation_summary=_unique(limitation_summary)[:5],
            )
        )

    warnings: list[str] = []
    if not claim_audits:
        warnings.append("No persisted claim audit is available for this run.")
    if not run.evidence_summary:
        warnings.append("No evidence items are available for argument graph review.")
    unresolved = sum(item.unresolved_conflict_count for item in summaries)
    return ArgumentGraphResult(
        run_id=run.run_id,
        audit_id=audit_id,
        retrieval_id=run.retrieval_id,
        status="ok",
        nodes=list(nodes.values()),
        edges=list(edges.values()),
        claim_summaries=summaries,
        unresolved_conflict_count=unresolved,
        warnings=warnings,
    )


def build_math_signals(
    *,
    run: AnswerWithEvidenceResult,
    audit: object | None,
    revision: AnswerRevision | None,
    step_telemetry: StepTelemetrySummary,
    argument_graph: ArgumentGraphResult | None = None,
) -> MathSignalsResult:
    graph = argument_graph or build_argument_graph(run=run, audit=audit)
    if _not_applicable(run):
        return MathSignalsResult(
            run_id=run.run_id,
            audit_id=graph.audit_id,
            retrieval_id=run.retrieval_id,
            status="not_applicable",
            answer_uncertainty_bucket="high",
            recommendation="expert_review",
            coverage_diversity=_coverage_diversity(run),
            step_telemetry=step_telemetry,
            argument_graph=graph,
            reason_factors=[
                "No retrieval-backed evidence is available for math review signals."
            ],
            not_applicable_reason=graph.not_applicable_reason,
        )

    claim_signals = [
        _claim_uncertainty(
            claim,
            run=run,
            revision=revision,
        )
        for claim in list(getattr(audit, "claim_audits", []) or [])
    ]
    coverage = _coverage_diversity(run)
    warnings = list(getattr(audit, "warnings", []) or [])
    warnings.extend(step_telemetry.unusual_path_warnings)
    if graph.unresolved_conflict_count:
        warnings.append("Argument graph contains unresolved support/attack conflicts.")
    answer_bucket = _answer_bucket(claim_signals, coverage, graph)
    recommendation = _answer_recommendation(
        claim_signals=claim_signals,
        coverage=coverage,
        graph=graph,
        revision=revision,
    )
    reason_factors = _unique(
        [
            factor
            for claim in claim_signals
            for factor in claim.reason_factors[:2]
        ]
    )
    if coverage.concentration_warnings:
        reason_factors.extend(coverage.concentration_warnings[:2])
    if coverage.missing_intent_warnings:
        reason_factors.extend(coverage.missing_intent_warnings[:2])
    if revision and revision.revision_action in {"revise", "refuse", "abstain"}:
        reason_factors.append(
            f"Revision action was {revision.revision_action}; keep reviewer pressure high."
        )
    if not reason_factors:
        reason_factors.append(
            "Claim audits and evidence diversity did not trigger a high-risk signal."
        )
    return MathSignalsResult(
        run_id=run.run_id,
        audit_id=graph.audit_id,
        retrieval_id=run.retrieval_id,
        status="ok",
        answer_uncertainty_bucket=answer_bucket,
        recommendation=recommendation,
        claim_uncertainty=claim_signals,
        coverage_diversity=coverage,
        step_telemetry=step_telemetry,
        argument_graph=graph,
        reason_factors=_unique(reason_factors),
        warnings=_unique(warnings),
    )


def _claim_uncertainty(
    claim: ClaimAuditItem,
    *,
    run: AnswerWithEvidenceResult,
    revision: AnswerRevision | None,
) -> ClaimUncertaintySignal:
    risk = 0.0
    factors: list[str] = []
    verdict_weight = {
        "supported": 0.1,
        "partial_support": 0.35,
        "overclaimed": 0.75,
        "contradicted": 0.9,
        "insufficient_evidence": 0.8,
        "irrelevant_citation": 0.8,
        "not_cited": 0.85,
    }.get(claim.verdict, 0.5)
    risk += verdict_weight
    factors.append(f"Citation audit verdict is {claim.verdict}.")

    support_gap = max(0.0, 1.0 - float(claim.support_score))
    risk += support_gap * 0.35
    if support_gap > 0.5:
        factors.append("Citation support score is weak for this claim.")

    if claim.logic_audit is not None:
        logic_weight = {
            "entailed": 0.0,
            "partially_entailed": 0.2,
            "overclaimed": 0.55,
            "contradicted": 0.8,
            "scope_mismatch": 0.55,
            "modality_mismatch": 0.55,
            "insufficient_evidence": 0.7,
            "not_assessed": 0.15,
        }.get(claim.logic_audit.logic_verdict, 0.3)
        risk += logic_weight
        factors.append(f"Logic audit verdict is {claim.logic_audit.logic_verdict}.")
    else:
        risk += 0.1
        factors.append("No logic audit was attached to this claim.")

    strength_weight = {
        "abstract_only": 0.25,
        "animal_or_in_vitro": 0.35,
        "observational": 0.25,
        "longitudinal": 0.15,
        "interventional": 0.1,
        "review_or_guideline": 0.2,
        "not_assessed": 0.2,
    }.get(claim.evidence_strength, 0.2)
    risk += strength_weight
    if claim.evidence_strength in {"abstract_only", "animal_or_in_vitro"}:
        factors.append(f"Evidence strength is {claim.evidence_strength}.")

    evidence_items = [
        item for item in run.evidence_summary if item.evidence_id in claim.evidence_ids
    ]
    if any(item.extraction_mode == "fallback" for item in evidence_items):
        risk += 0.15
        factors.append("At least one supporting evidence item used fallback extraction.")
    if any(item.limitations for item in evidence_items):
        factors.append("Evidence limitations are present and should remain visible.")
    if run.retrieval_manifest and run.retrieval_manifest.warnings:
        risk += 0.12
        factors.append("Retrieval manifest contains source warnings.")
    if revision and revision.revision_action in {"revise", "refuse", "abstain"}:
        risk += 0.2
        factors.append(f"Final revision action was {revision.revision_action}.")

    normalized = min(1.0, round(risk / 2.45, 3))
    bucket = _risk_bucket(normalized)
    return ClaimUncertaintySignal(
        claim_id=claim.claim_id,
        claim=claim.claim,
        risk_bucket=bucket,
        risk_score=normalized,
        recommendation=_claim_recommendation(claim, bucket),
        reason_factors=_unique(factors),
        support_score=claim.support_score,
        citation_verdict=claim.verdict,
        logic_verdict=(
            claim.logic_audit.logic_verdict if claim.logic_audit is not None else None
        ),
        evidence_strength=claim.evidence_strength,
    )


def _coverage_diversity(run: AnswerWithEvidenceResult) -> CoverageDiversitySignal:
    evidence = run.evidence_summary
    paper_counts = Counter(item.paper_id for item in evidence)
    evidence_count = len(evidence)
    paper_count = len(paper_counts)
    methods = {
        _norm(method)
        for item in evidence
        for method in item.methods
        if _norm(method)
    }
    model_or_population = {
        _norm(value)
        for item in evidence
        for value in [*item.datasets_or_cohorts, *_model_terms(item)]
        if _norm(value)
    }
    intent_counts = Counter(item.retrieval_intent for item in evidence)
    if run.retrieval_bundle is not None:
        for record in run.retrieval_bundle.records:
            intent_counts.setdefault(record.intent, 0)
    duplicate_pressure = (
        len(run.retrieval_bundle.duplicate_paper_ids)
        if run.retrieval_bundle is not None
        else 0
    )
    top_ratio = (
        max(paper_counts.values()) / evidence_count if evidence_count else 0.0
    )
    concentration_warnings: list[str] = []
    if evidence_count >= 3 and top_ratio >= 0.65:
        concentration_warnings.append(
            "Evidence is concentrated in one paper; broaden retrieval before strong conclusions."
        )
    if paper_count <= 1 and evidence_count > 1:
        concentration_warnings.append(
            "Multiple evidence items come from a single paper."
        )
    expected_intents = ["primary", "support", "refute", "mechanism", "limitation"]
    missing_intents = [
        intent
        for intent in expected_intents
        if intent_counts.get(intent, 0) == 0
    ]
    missing_intent_warnings = [
        f"Retrieval intent has no evidence coverage: {intent}."
        for intent in missing_intents[:4]
    ]
    limitation_count = sum(len(item.limitations) for item in evidence)
    paper_balance = 1.0 - top_ratio if evidence_count else 0.0
    intent_score = min(1.0, len([v for v in intent_counts.values() if v > 0]) / 3.0)
    method_score = min(1.0, len(methods) / 3.0)
    model_score = min(1.0, len(model_or_population) / 2.0)
    limitation_score = 1.0 if limitation_count else (0.45 if evidence else 0.0)
    diversity_score = round(
        (paper_balance + intent_score + method_score + model_score + limitation_score)
        / 5.0,
        3,
    )
    return CoverageDiversitySignal(
        diversity_score=diversity_score,
        paper_count=paper_count,
        evidence_count=evidence_count,
        unique_method_count=len(methods),
        unique_model_or_population_count=len(model_or_population),
        paper_concentration={
            paper_id: round(count / evidence_count, 3)
            for paper_id, count in paper_counts.items()
        }
        if evidence_count
        else {},
        retrieval_intent_coverage=dict(intent_counts),
        limitation_count=limitation_count,
        duplicate_pressure=duplicate_pressure,
        concentration_warnings=concentration_warnings,
        missing_intent_warnings=missing_intent_warnings,
        recommended_retrieval_direction=_recommended_retrieval_direction(
            concentration_warnings=concentration_warnings,
            missing_intents=missing_intents,
            method_count=len(methods),
            limitation_count=limitation_count,
        ),
    )


def _not_applicable(run: AnswerWithEvidenceResult) -> bool:
    return (
        not run.evidence_summary
        and not run.citations
        and run.retrieval_manifest is None
    )


def _argument_edge_type(
    claim: ClaimAuditItem,
    evidence: EvidenceItem,
) -> str:
    if (
        claim.verdict in {"contradicted", "overclaimed"}
        or evidence.evidence_direction == "contradicts"
    ):
        return "attacks"
    return "supports"


def _edge_weight(claim: ClaimAuditItem, evidence: EvidenceItem) -> float:
    confidence = {"high": 1.0, "medium": 0.72, "low": 0.45}.get(
        evidence.confidence,
        0.5,
    )
    return round(max(0.1, min(1.0, claim.support_score * 0.7 + confidence * 0.3)), 3)


def _fallback_evidence_ids(
    claim: ClaimAuditItem,
    evidence: Iterable[EvidenceItem],
) -> list[str]:
    cited = set(claim.cited_paper_ids)
    return [item.evidence_id for item in evidence if item.paper_id in cited]


def _add_edge(
    edges: dict[str, ArgumentGraphEdge],
    *,
    source: str,
    target: str,
    edge_type: str,
    weight: float,
    metadata: dict[str, object],
) -> None:
    edge_id = f"edge:{_stable_token(f'{source}:{target}:{edge_type}')}"
    edges[edge_id] = ArgumentGraphEdge(
        edge_id=edge_id,
        source=source,
        target=target,
        edge_type=edge_type,  # type: ignore[arg-type]
        weight=weight,
        metadata=metadata,
    )


def _claim_node_id(claim: ClaimAuditItem, index: int) -> str:
    return f"claim:{claim.claim_id or _stable_token(f'{index}:{claim.claim}')}"


def _stable_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _short_label(value: str) -> str:
    clean = re.sub(r"\s+", " ", value or "").strip()
    return clean[:180] if len(clean) > 180 else clean


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _model_terms(item: EvidenceItem) -> list[str]:
    text = " ".join([item.claim, item.finding, item.evidence_span or ""]).lower()
    terms: list[str] = []
    for pattern, label in (
        (r"\b(mouse|mice|murine|transgenic)\b", "animal"),
        (r"\b(in vitro|cell culture|cell line)\b", "in_vitro"),
        (r"\b(human|patient|cohort|post-mortem)\b", "human"),
    ):
        if re.search(pattern, text):
            terms.append(label)
    return terms


def _risk_bucket(score: float) -> ConfidenceLevel:
    if score >= 0.66:
        return "high"
    if score >= 0.36:
        return "medium"
    return "low"


def _claim_recommendation(
    claim: ClaimAuditItem,
    bucket: ConfidenceLevel,
) -> Literal["answer", "soften", "retrieve_more", "expert_review"]:
    if bucket == "high":
        if claim.verdict in {"not_cited", "irrelevant_citation", "insufficient_evidence"}:
            return "retrieve_more"
        return "expert_review"
    if bucket == "medium":
        return "soften"
    return "answer"


def _answer_bucket(
    claim_signals: list[ClaimUncertaintySignal],
    coverage: CoverageDiversitySignal,
    graph: ArgumentGraphResult,
) -> ConfidenceLevel:
    if any(item.risk_bucket == "high" for item in claim_signals):
        return "high"
    if graph.unresolved_conflict_count:
        return "high"
    if coverage.diversity_score < 0.35 and claim_signals:
        return "high"
    if any(item.risk_bucket == "medium" for item in claim_signals):
        return "medium"
    if coverage.diversity_score < 0.55 and claim_signals:
        return "medium"
    return "low"


def _answer_recommendation(
    *,
    claim_signals: list[ClaimUncertaintySignal],
    coverage: CoverageDiversitySignal,
    graph: ArgumentGraphResult,
    revision: AnswerRevision | None,
) -> Literal["answer", "soften", "retrieve_more", "expert_review"]:
    if revision and revision.revision_action in {"refuse", "abstain"}:
        return "expert_review"
    if any(item.recommendation == "expert_review" for item in claim_signals):
        return "expert_review"
    if coverage.recommended_retrieval_direction:
        return "retrieve_more"
    if any(item.recommendation == "retrieve_more" for item in claim_signals):
        return "retrieve_more"
    if any(item.recommendation == "soften" for item in claim_signals):
        return "soften"
    if graph.unresolved_conflict_count:
        return "soften"
    return "answer"


def _recommended_retrieval_direction(
    *,
    concentration_warnings: list[str],
    missing_intents: list[str],
    method_count: int,
    limitation_count: int,
) -> str | None:
    if "refute" in missing_intents:
        return "search_refute"
    if "limitation" in missing_intents or limitation_count == 0:
        return "search_limitation"
    if concentration_warnings:
        return "broaden_query"
    if method_count < 2:
        return "search_method_diversity"
    return None


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
