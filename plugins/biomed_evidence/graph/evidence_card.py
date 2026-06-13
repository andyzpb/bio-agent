from __future__ import annotations

from plugins.biomed_evidence.graph.schema import (
    BiomedEvidenceGraph,
    EvidenceCard,
    EvidenceCardEvidence,
)

_EVIDENCE_TO_CLAIM = {
    "EVIDENCE_SUPPORTS_CLAIM",
    "EVIDENCE_CONTRADICTS_CLAIM",
    "EVIDENCE_QUALIFIES_CLAIM",
    "EVIDENCE_PROVIDES_BACKGROUND_FOR_CLAIM",
}


def build_evidence_card(graph: BiomedEvidenceGraph, claim_node_id: str) -> EvidenceCard:
    nodes = {node.id: node for node in graph.nodes}
    claim = nodes.get(claim_node_id)
    if claim is None or claim.type != "Claim":
        raise ValueError("claim_node_id does not reference a Claim node")

    paper_by_evidence: dict[str, tuple[str | None, str | None]] = {}
    methods_by_evidence: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.type != "PAPER_CONTAINS_EVIDENCE":
            if edge.type == "EVIDENCE_USES_METHOD":
                method = nodes.get(edge.target)
                if method is not None:
                    methods_by_evidence.setdefault(edge.source, []).append(
                        str(method.properties.get("name") or method.label)
                    )
            continue
        paper = nodes.get(edge.source)
        if paper is not None:
            paper_by_evidence[edge.target] = (
                paper.properties.get("paper_id"),
                paper.label,
            )

    evidence_items: list[EvidenceCardEvidence] = []
    for edge in graph.edges:
        if edge.target != claim_node_id or edge.type not in _EVIDENCE_TO_CLAIM:
            continue
        evidence = nodes.get(edge.source)
        if evidence is None or evidence.type != "EvidenceSpan":
            continue
        paper_id, paper_title = paper_by_evidence.get(edge.source, (None, None))
        methods = _unique_strings(
            [
                *_string_list(evidence.properties.get("methods")),
                *methods_by_evidence.get(edge.source, []),
            ]
        )
        evidence_items.append(
            EvidenceCardEvidence(
                evidence_id=str(evidence.properties.get("evidence_id") or edge.source),
                evidence_node_id=edge.source,
                relation=edge.type,
                text=str(evidence.properties.get("text") or evidence.label),
                paper_id=paper_id,
                paper_title=paper_title,
                confidence=_optional_str(evidence.properties.get("confidence")),
                evidence_direction=_optional_str(
                    evidence.properties.get("evidence_direction")
                ),
                retrieval_intent=_optional_str(
                    evidence.properties.get("retrieval_intent")
                ),
                extraction_mode=_optional_str(evidence.properties.get("extraction_mode")),
                limitations=_string_list(evidence.properties.get("limitations")),
                methods=methods,
            )
        )

    limitations: list[str] = []
    audits: list[dict[str, object]] = []
    for edge in graph.edges:
        if edge.type == "CLAIM_HAS_LIMITATION" and edge.source == claim_node_id:
            limitation = nodes.get(edge.target)
            if limitation is not None:
                limitations.append(str(limitation.properties.get("text") or limitation.label))
        if edge.type != "AUDIT_REVIEWS_CLAIM" or edge.target != claim_node_id:
            continue
        source = nodes.get(edge.source)
        if source is not None:
            audits.append({"audit_node_id": source.id, **edge.properties})
            limitations.extend(_string_list(edge.properties.get("overclaim_reason")))
            limitations.extend(_string_list(edge.properties.get("reviewer_notes")))
    for item in evidence_items:
        limitations.extend(item.limitations)

    return EvidenceCard(
        claim_id=str(claim.properties.get("claim_id") or claim_node_id),
        claim_node_id=claim_node_id,
        claim_text=str(claim.properties.get("text") or claim.label),
        support_status=str(claim.properties.get("support_status") or "not_assessed"),
        support_status_reason=_optional_str(
            claim.properties.get("support_status_reason")
        ),
        support_counts=_int_dict(claim.properties.get("support_counts")),
        evidence=evidence_items,
        limitations=_unique_strings(limitations),
        audit_results=audits,
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        try:
            result[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return result
