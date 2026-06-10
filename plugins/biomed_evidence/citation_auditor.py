from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable, cast

from plugins.biomed_evidence.schemas import (
    AtomicClaim,
    AuditRecommendedAction,
    Citation,
    CitationAuditResult,
    CitationSupportVerdict,
    ClaimAuditItem,
    ClaimType,
    ConfidenceLevel,
    ConflictAuditResult,
    ConflictVerdict,
    EvidenceItem,
    EvidenceStrength,
    RetrievalManifest,
    UncertaintyAudit,
)


_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "been",
    "being",
    "but",
    "can",
    "could",
    "does",
    "for",
    "from",
    "has",
    "have",
    "into",
    "its",
    "may",
    "not",
    "only",
    "that",
    "the",
    "their",
    "this",
    "was",
    "were",
    "with",
}

_FAILED_VERDICTS = {
    "overclaimed",
    "contradicted",
    "insufficient_evidence",
    "irrelevant_citation",
    "not_cited",
}


def validate_citation_support(
    *,
    answer: str,
    citations: list[Citation],
    evidence_items: list[EvidenceItem],
    run_id: str | None = None,
    retrieval_id: str | None = None,
    observed_uncertainty: str | None = None,
    retrieval_manifest: RetrievalManifest | None = None,
) -> CitationAuditResult:
    claims = extract_atomic_claims(answer)
    citation_ids = {citation.paper_id for citation in citations}
    claim_audits = [
        _audit_claim(claim, evidence_items, citation_ids)
        for claim in claims
    ]
    uncertainty_audit = derive_uncertainty_audit(
        claim_audits=claim_audits,
        evidence_items=evidence_items,
        retrieval_manifest=retrieval_manifest,
        observed_uncertainty=observed_uncertainty,
    )
    failed_claims = [
        item for item in claim_audits if item.verdict in _FAILED_VERDICTS
    ]
    supported_claims = [
        item for item in claim_audits if item.verdict in {"supported", "partial_support"}
    ]
    unsupported_claims = [
        item
        for item in claim_audits
        if item.verdict in {"insufficient_evidence", "irrelevant_citation", "not_cited"}
    ]
    overclaimed_claims = [
        item for item in claim_audits if item.verdict == "overclaimed"
    ]
    cited_ids = set().union(*(set(item.cited_paper_ids) for item in claim_audits)) if claim_audits else set()
    supported_citation_ids = set().union(
        *(set(item.cited_paper_ids) for item in supported_claims)
    ) if supported_claims else set()
    conflict_awareness = _conflict_awareness(answer, evidence_items)
    recommended_action = _recommended_action(
        failed_claims=failed_claims,
        uncertainty_audit=uncertainty_audit,
        conflict_awareness=conflict_awareness,
        evidence_items=evidence_items,
    )
    return CitationAuditResult(
        audit_id=_audit_id(run_id, answer, evidence_items),
        run_id=run_id,
        retrieval_id=retrieval_id,
        claims=claims,
        claim_audits=claim_audits,
        uncertainty_audit=uncertainty_audit,
        claim_support_rate=_rate(len(supported_claims), len(claim_audits)),
        citation_precision=_rate(len(supported_citation_ids), len(citation_ids or cited_ids)),
        unsupported_claim_rate=_rate(len(unsupported_claims), len(claim_audits)),
        overclaim_rate=_rate(len(overclaimed_claims), len(claim_audits)),
        conflict_awareness=conflict_awareness,
        uncertainty_calibrated=uncertainty_audit.calibrated,
        failed_claims=failed_claims,
        recommended_action=recommended_action,
        created_at=_now_iso(),
        warnings=[],
        errors=[],
    )


def extract_atomic_claims(answer: str) -> list[AtomicClaim]:
    claims: list[AtomicClaim] = []
    index = 0
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if not line or _skip_line(line):
            continue
        if line.startswith("- "):
            candidates = [line[2:].strip()]
        else:
            candidates = _split_sentences(line)
        for candidate in candidates:
            text = _clean_claim_text(candidate)
            if not text or _skip_line(text):
                continue
            claim = AtomicClaim(
                claim_id=_claim_id(text, index),
                text=text,
                claim_type=_claim_type(text),
                sentence_index=index,
                cited_paper_ids=_paper_ids(candidate),
            )
            claims.append(claim)
            index += 1
    return claims


def derive_uncertainty_audit(
    *,
    claim_audits: list[ClaimAuditItem],
    evidence_items: list[EvidenceItem],
    retrieval_manifest: RetrievalManifest | None,
    observed_uncertainty: str | None,
) -> UncertaintyAudit:
    reasons: list[str] = []
    expected: ConfidenceLevel = "low"
    if not claim_audits:
        expected = "high"
        reasons.append("No atomic claims were available to audit.")
    if any(item.verdict in _FAILED_VERDICTS for item in claim_audits):
        expected = "high"
        reasons.append("One or more claims were unsupported, overclaimed, contradicted, irrelevant, or not cited.")
    if any(item.evidence_direction in {"contradicts", "inconclusive"} for item in evidence_items):
        expected = "high"
        reasons.append("Retrieved evidence includes contradictory or inconclusive findings.")
    if retrieval_manifest and (retrieval_manifest.warnings or retrieval_manifest.errors):
        expected = "high"
        reasons.append("Retrieval manifest contains warnings or errors.")
    if expected != "high" and any(item.confidence == "low" for item in evidence_items):
        expected = "medium"
        reasons.append("At least one evidence item has low confidence.")
    if expected != "high" and any(_evidence_strength(item) == "animal_or_in_vitro" for item in evidence_items):
        expected = "medium"
        reasons.append("Evidence includes animal or in-vitro model limitations.")
    if expected != "high" and any(_evidence_strength(item) == "abstract_only" for item in evidence_items):
        expected = "medium"
        reasons.append("Evidence is abstract-level only.")
    if not reasons:
        reasons.append("Audited claims were citation-supported with no explicit conflict detected.")
    observed: ConfidenceLevel | None = (
        cast(ConfidenceLevel, observed_uncertainty)
        if observed_uncertainty in {"low", "medium", "high"}
        else None
    )
    calibrated = observed is None or _uncertainty_rank(observed) >= _uncertainty_rank(expected)
    return UncertaintyAudit(
        expected_uncertainty=expected,
        observed_uncertainty=observed,
        calibrated=calibrated,
        reasons=reasons,
        grade_like_factors={
            "risk_of_bias": "unclear",
            "inconsistency": "serious" if any(item.evidence_direction in {"contradicts", "inconclusive"} for item in evidence_items) else "not_serious",
            "indirectness": "serious" if any(_evidence_strength(item) == "animal_or_in_vitro" for item in evidence_items) else "not_serious",
            "imprecision": "unclear",
            "publication_bias": "not_assessed",
        },
    )


def find_conflicting_evidence(
    *,
    claim: str,
    topic: str,
    evidence_items: list[EvidenceItem],
    retrieval_id: str | None = None,
) -> ConflictAuditResult:
    supporting = [
        item.paper_id
        for item in evidence_items
        if item.evidence_direction in {"supports", "background"} and _overlap(claim, _evidence_text(item)) >= 0.08
    ]
    contradicting = [
        item.paper_id
        for item in evidence_items
        if item.evidence_direction == "contradicts" and _overlap(claim, _evidence_text(item)) >= 0.04
    ]
    inconclusive = [
        item.paper_id
        for item in evidence_items
        if item.evidence_direction == "inconclusive" and _overlap(claim, _evidence_text(item)) >= 0.04
    ]
    axes = _conflict_axes(evidence_items)
    verdict: ConflictVerdict
    if contradicting:
        verdict = "mixed_evidence" if supporting or inconclusive else "contradicted"
    elif inconclusive:
        verdict = "mixed_evidence"
    elif supporting:
        verdict = "no_conflict_found"
    else:
        verdict = "insufficient_search"
    return ConflictAuditResult(
        conflict_audit_id=_conflict_audit_id(claim, topic, retrieval_id),
        claim=claim,
        topic=topic,
        retrieval_id=retrieval_id,
        supporting_papers=_unique(supporting),
        contradicting_papers=_unique(contradicting),
        inconclusive_papers=_unique(inconclusive),
        conflict_axes=axes,
        verdict=verdict,
        created_at=_now_iso(),
    )


def _audit_claim(
    claim: AtomicClaim,
    evidence_items: list[EvidenceItem],
    citation_ids: set[str],
) -> ClaimAuditItem:
    cited_ids = claim.cited_paper_ids or _infer_cited_ids(claim.text, evidence_items, citation_ids)
    if not cited_ids:
        return _claim_audit(
            claim,
            cited_paper_ids=[],
            evidence_items=[],
            verdict="not_cited",
            support_score=0.0,
            reason="No citation or cited paper ID was aligned to this claim.",
        )
    candidates = [item for item in evidence_items if item.paper_id in cited_ids]
    if not candidates:
        return _claim_audit(
            claim,
            cited_paper_ids=cited_ids,
            evidence_items=[],
            verdict="irrelevant_citation",
            support_score=0.0,
            reason="The claim cites papers that have no extracted evidence item in this run.",
        )
    ranked = sorted(
        ((item, _overlap(claim.text, _evidence_text(item))) for item in candidates),
        key=lambda pair: pair[1],
        reverse=True,
    )
    best, score = ranked[0]
    overclaim_reason = _overclaim_reason(claim.text, best)
    if overclaim_reason:
        return _claim_audit(
            claim,
            cited_paper_ids=cited_ids,
            evidence_items=[best],
            verdict="overclaimed",
            support_score=round(score, 3),
            reason=overclaim_reason,
            overclaim_reason=overclaim_reason,
        )
    if best.evidence_direction == "contradicts" and not _claim_reports_limiting_evidence(claim.text):
        return _claim_audit(
            claim,
            cited_paper_ids=cited_ids,
            evidence_items=[best],
            verdict="contradicted",
            support_score=round(score, 3),
            reason="The cited evidence is a contradicting finding, but the claim presents it as positive support.",
        )
    if best.evidence_direction == "inconclusive":
        return _claim_audit(
            claim,
            cited_paper_ids=cited_ids,
            evidence_items=[best],
            verdict="partial_support",
            support_score=round(score, 3),
            reason="The citation aligns to evidence marked inconclusive, so support is partial.",
        )
    if score >= 0.14:
        return _claim_audit(
            claim,
            cited_paper_ids=cited_ids,
            evidence_items=[best],
            verdict="supported",
            support_score=round(score, 3),
            reason="The cited evidence span overlaps with and supports the claim.",
        )
    if score >= 0.06:
        return _claim_audit(
            claim,
            cited_paper_ids=cited_ids,
            evidence_items=[best],
            verdict="partial_support",
            support_score=round(score, 3),
            reason="The citation is directionally relevant but only partially overlaps the claim.",
        )
    return _claim_audit(
        claim,
        cited_paper_ids=cited_ids,
        evidence_items=candidates[:1],
        verdict="insufficient_evidence",
        support_score=round(score, 3),
        reason="The citation exists, but extracted evidence does not substantively support the claim.",
    )


def _claim_audit(
    claim: AtomicClaim,
    *,
    cited_paper_ids: list[str],
    evidence_items: list[EvidenceItem],
    verdict: CitationSupportVerdict,
    support_score: float,
    reason: str,
    overclaim_reason: str | None = None,
) -> ClaimAuditItem:
    best = evidence_items[0] if evidence_items else None
    return ClaimAuditItem(
        claim_id=claim.claim_id,
        claim=claim.text,
        claim_type=claim.claim_type,
        cited_paper_ids=_unique(cited_paper_ids),
        evidence_ids=[item.evidence_id for item in evidence_items],
        evidence_span=best.evidence_span if best is not None else None,
        verdict=verdict,
        support_score=support_score,
        evidence_strength=_evidence_strength(best) if best is not None else "not_assessed",
        overclaim_reason=overclaim_reason,
        reason=reason,
        reviewer_notes=_reviewer_notes(evidence_items),
    )


def _infer_cited_ids(
    claim_text: str,
    evidence_items: list[EvidenceItem],
    citation_ids: set[str],
) -> list[str]:
    if not citation_ids:
        return []
    ranked = sorted(
        (
            (item.paper_id, _overlap(claim_text, _evidence_text(item)))
            for item in evidence_items
            if item.paper_id in citation_ids
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    if not ranked or ranked[0][1] < 0.2:
        return []
    return [ranked[0][0]]


def _skip_line(line: str) -> bool:
    lowered = line.lower().strip()
    heading = _normalized_section_heading(line)
    if _is_markdown_section_heading(line):
        return True
    if lowered.startswith(("research question:", "project context", "##", "#")):
        return True
    if heading in {
        "evidence supporting the hypothesis:",
        "evidence supporting the hypothesis",
        "evidence that contradicts or limits the hypothesis:",
        "evidence that contradicts or limits the hypothesis",
        "inconclusive evidence:",
        "inconclusive evidence",
        "citations",
        "limitations",
        "disclaimer",
    }:
        return True
    return (
        "research support only" in lowered
        or "not a clinical or causal conclusion" in lowered
        or "not medical advice" in lowered
        or lowered.startswith("interpretation:")
    )


def _normalized_section_heading(line: str) -> str:
    heading = re.sub(r"^[#>\-\s]+", "", line).strip()
    heading = re.sub(r"\*+", "", heading).strip().lower()
    return heading.strip(" :")


def _is_markdown_section_heading(line: str) -> bool:
    stripped = line.strip()
    if _paper_ids(stripped):
        return False
    return bool(re.fullmatch(r"\*{1,3}\s*[^*][^.\n]{1,140}?\s*\*{1,3}", stripped))


def _split_sentences(text: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", text)
        if item.strip()
    ]


def _clean_claim_text(text: str) -> str:
    clean = re.sub(r"\[[^\]]*\]", "", text)
    clean = re.sub(r"\s+", " ", clean).strip(" -")
    return clean


def _paper_ids(text: str) -> list[str]:
    matches = re.findall(r"(MOCK-PMID-\d+|PMID:\d+|\b\d{5,}\b)", text)
    return _unique(matches)


def _claim_type(text: str) -> ClaimType:
    lowered = text.lower()
    if re.search(r"\b(treat|treatment|therapy|prescribe|dose|medication)\b", lowered):
        return "treatment_recommendation"
    if re.search(r"\b(patient|clinical|diagnos|prognos)\b", lowered):
        return "clinical_implication"
    if re.search(r"\b(caus|drive|drives|led to|leads to|resulted in|proves?)\b", lowered):
        return "causal"
    if re.search(r"\b(mechanis|pathway|program|expression|activation|phagocytosis)\b", lowered):
        return "mechanistic_hypothesis"
    if re.search(r"\b(associated|association|correlat|linked|enriched|observed|found|suggest)\b", lowered):
        return "association"
    if re.search(r"\b(method|cohort|sequencing|transcriptomics|immunostaining)\b", lowered):
        return "methodological"
    if re.search(r"\b(uncertain|inconclusive|limited|limitation)\b", lowered):
        return "uncertainty"
    return "background"


def _evidence_text(item: EvidenceItem) -> str:
    return " ".join(
        [
            item.claim,
            item.finding,
            item.evidence_span or "",
            " ".join(item.methods),
            " ".join(item.datasets_or_cohorts),
            " ".join(item.limitations),
        ]
    )


def _overlap(left: str, right: str) -> float:
    left_terms = set(_terms(left))
    right_terms = set(_terms(right))
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms)


def _terms(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", text.lower())
        if token not in _STOPWORDS
    ]


def _overclaim_reason(claim_text: str, evidence: EvidenceItem) -> str | None:
    lowered = claim_text.lower()
    evidence_text = _evidence_text(evidence).lower()
    if re.search(r"\b(causes?|caused|causal|drives?|proves?|establishes?)\b", lowered):
        if _claim_reports_limiting_evidence(claim_text):
            return None
        if re.search(r"\b(associated|association|correlated|cross-sectional|limits causal)\b", evidence_text):
            return "The claim upgrades association or cross-sectional evidence into causality."
    if re.search(r"\b(human|patients?|clinical|alzheimer's disease progression)\b", lowered):
        if re.search(r"\b(mouse|mice|animal|transgenic|in vitro|cell culture)\b", evidence_text):
            if _claim_reports_limiting_evidence(claim_text):
                return None
            return "The claim generalizes animal or in-vitro evidence to human/clinical relevance."
    if re.search(r"\b(established|definitive|consensus|robust|proven)\b", lowered):
        if re.search(r"\b(small|single|abstract|limited|requires validation|cohort)\b", evidence_text):
            return "The claim presents limited or abstract-level evidence as established consensus."
    if re.search(r"\b(treat|treatment|therapy|prescribe|medication)\b", lowered):
        if re.search(r"\b(mechanism|activation|pathway|expression|association)\b", evidence_text):
            return "The claim turns mechanistic or association evidence into treatment guidance."
    return None


def _claim_reports_limiting_evidence(claim_text: str) -> bool:
    lowered = claim_text.lower()
    return any(
        term in lowered
        for term in (
            "did not",
            "does not",
            "no ",
            "not improve",
            "fail",
            "failed",
            "limit",
            "limiting",
            "caution",
            "contradict",
            "weakened",
            "inconclusive",
        )
    )


def _evidence_strength(item: EvidenceItem | None) -> EvidenceStrength:
    if item is None:
        return "not_assessed"
    text = _evidence_text(item).lower()
    if re.search(r"\b(mouse|mice|animal|transgenic|in vitro|cell culture)\b", text):
        return "animal_or_in_vitro"
    if re.search(r"\b(longitudinal|follow-up)\b", text):
        return "longitudinal"
    if re.search(r"\b(intervention|randomized|trial|perturbation)\b", text):
        return "interventional"
    if re.search(r"\b(review|guideline|meta-analysis)\b", text):
        return "review_or_guideline"
    if re.search(r"\b(cohort|cross-sectional|post-mortem|observational)\b", text):
        return "observational"
    return "abstract_only"


def _reviewer_notes(evidence_items: list[EvidenceItem]) -> list[str]:
    notes: list[str] = []
    for item in evidence_items:
        notes.extend(item.limitations)
        if item.requires_expert_review:
            notes.append("Requires expert review.")
    return _unique(notes)


def _conflict_awareness(answer: str, evidence_items: list[EvidenceItem]) -> bool:
    has_conflict = any(item.evidence_direction in {"contradicts", "inconclusive"} for item in evidence_items)
    if not has_conflict:
        return True
    lowered = answer.lower()
    return any(term in lowered for term in ("contradict", "limit", "inconclusive", "conflict", "uncertain"))


def _recommended_action(
    *,
    failed_claims: list[ClaimAuditItem],
    uncertainty_audit: UncertaintyAudit,
    conflict_awareness: bool,
    evidence_items: list[EvidenceItem],
) -> AuditRecommendedAction:
    if any(item.claim_type in {"clinical_implication", "treatment_recommendation"} for item in failed_claims):
        return "refuse_or_abstain"
    if any(item.verdict in {"overclaimed", "contradicted"} for item in failed_claims):
        return "revise"
    if any(item.verdict in {"insufficient_evidence", "irrelevant_citation", "not_cited"} for item in failed_claims):
        return "revise"
    if not uncertainty_audit.calibrated or not conflict_awareness:
        return "pass_with_limitations"
    if any(item.evidence_direction in {"contradicts", "inconclusive"} for item in evidence_items):
        return "pass_with_limitations"
    return "pass"


def _conflict_axes(evidence_items: list[EvidenceItem]) -> list[str]:
    text = " ".join(_evidence_text(item).lower() for item in evidence_items)
    axes: list[str] = []
    if "mouse" in text or "animal" in text:
        axes.append("human cohort vs animal model")
    if "cross-sectional" in text or "longitudinal" in text:
        axes.append("cross-sectional vs longitudinal design")
    if "adjustment" in text or "confound" in text:
        axes.append("confounding adjustment")
    if "small" in text or "limited" in text:
        axes.append("cohort size and generalizability")
    if "memory outcomes" in text or "amyloid" in text or "braak" in text:
        axes.append("endpoint difference")
    return _unique(axes)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def _uncertainty_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value, 2)


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _claim_id(text: str, index: int) -> str:
    digest = hashlib.sha256(f"{index}:{text.lower()}".encode("utf-8")).hexdigest()[:12]
    return f"claim-{digest}"


def _audit_id(run_id: str | None, answer: str, evidence_items: list[EvidenceItem]) -> str:
    key = {
        "run_id": run_id or "",
        "answer": answer,
        "evidence": [item.evidence_id for item in evidence_items],
    }
    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:16]
    return f"audit-{digest}"


def _conflict_audit_id(claim: str, topic: str, retrieval_id: str | None) -> str:
    digest = hashlib.sha256(
        f"{claim.lower()}:{topic.lower()}:{retrieval_id or ''}".encode("utf-8")
    ).hexdigest()[:16]
    return f"conflict-{digest}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
