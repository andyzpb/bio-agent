from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from plugins.biomed_evidence.graph.ids import (
    answer_run_node_id,
    audit_result_node_id,
    claim_id_from_text,
    claim_node_id,
    edge_id,
    entity_node_id,
    evidence_packet_node_id,
    evidence_span_node_id,
    limitation_node_id,
    method_node_id,
    paper_node_id,
    retrieval_manifest_node_id,
    stable_digest,
)
from plugins.biomed_evidence.graph.schema import (
    BiomedEvidenceGraph,
    BiomedEvidenceGraphEdge,
    BiomedEvidenceGraphNode,
    EdgeType,
    GraphScope,
    NodeType,
)


class EvidenceGraphBuilder:
    def __init__(self, *, scope: GraphScope | None = None) -> None:
        self.scope = scope or GraphScope()
        self._nodes: dict[str, BiomedEvidenceGraphNode] = {}
        self._edges: dict[str, BiomedEvidenceGraphEdge] = {}
        self._warnings: list[str] = []

    def add_node(
        self,
        node_type: NodeType,
        node_id: str,
        label: str,
        *,
        properties: dict[str, Any] | None = None,
    ) -> str:
        existing = self._nodes.get(node_id)
        if existing is not None:
            merged = {**existing.properties, **(properties or {})}
            self._nodes[node_id] = existing.model_copy(update={"properties": merged})
            return node_id
        self._nodes[node_id] = BiomedEvidenceGraphNode(
            id=node_id,
            type=node_type,
            label=label,
            properties=properties or {},
        )
        return node_id

    def add_edge(
        self,
        edge_type: EdgeType,
        source: str,
        target: str,
        *,
        properties: dict[str, Any] | None = None,
    ) -> str:
        item_id = edge_id(source, edge_type, target)
        self._edges[item_id] = BiomedEvidenceGraphEdge(
            id=item_id,
            source=source,
            target=target,
            type=edge_type,
            properties=properties or {},
        )
        return item_id

    def warn(self, message: str) -> None:
        if message not in self._warnings:
            self._warnings.append(message)

    def build(self, *, graph_id_seed: str | None = None) -> BiomedEvidenceGraph:
        graph_id = (
            f"evidence_graph:{stable_digest(graph_id_seed, length=20)}"
            if graph_id_seed
            else None
        )
        return BiomedEvidenceGraph(
            graph_id=graph_id,
            scope=self.scope,
            nodes=sorted(self._nodes.values(), key=lambda item: item.id),
            edges=sorted(self._edges.values(), key=lambda item: item.id),
            warnings=list(self._warnings),
        )


def build_graph_from_evidence(
    evidence_items: Iterable[Any],
    *,
    papers: Iterable[Any] = (),
    retrieval_manifests: Iterable[Any] = (),
    scope: GraphScope | None = None,
) -> BiomedEvidenceGraph:
    builder = EvidenceGraphBuilder(scope=scope)
    paper_titles = _add_papers(builder, papers)
    manifest_ids = _add_retrieval_manifests(builder, retrieval_manifests)
    seed_parts: list[str] = []

    for item in evidence_items:
        evidence_id = str(_field(item, "evidence_id") or "").strip()
        paper_id = str(_field(item, "paper_id") or "").strip()
        claim_text = str(_field(item, "claim") or "").strip()
        if not evidence_id or not paper_id or not claim_text:
            builder.warn("Skipped evidence item missing evidence_id, paper_id, or claim.")
            continue
        seed_parts.append(evidence_id)
        paper_node = _ensure_paper(
            builder,
            paper_id,
            paper_titles.get(paper_id) or _optional_str(_field(item, "paper_title")),
        )
        evidence_node = evidence_span_node_id(evidence_id)
        span_text = str(
            _field(item, "evidence_span")
            or _field(item, "finding")
            or _field(item, "claim")
            or ""
        )
        direction = str(_field(item, "evidence_direction") or "background")
        confidence = str(_field(item, "confidence") or "low")
        builder.add_node(
            "EvidenceSpan",
            evidence_node,
            _short_label(span_text or evidence_id),
            properties={
                "evidence_id": evidence_id,
                "paper_id": paper_id,
                "text": span_text,
                "span_hash": stable_digest(span_text, length=20) if span_text else None,
                "finding": _field(item, "finding"),
                "evidence_direction": direction,
                "confidence": confidence,
                "retrieval_intent": _field(item, "retrieval_intent"),
                "extraction_mode": _field(item, "extraction_mode"),
                "requires_expert_review": _field(item, "requires_expert_review"),
                "datasets_or_cohorts": _list_field(item, "datasets_or_cohorts"),
                "retrieval_id": _field(item, "retrieval_id"),
            },
        )
        builder.add_edge(
            "PAPER_CONTAINS_EVIDENCE",
            paper_node,
            evidence_node,
            properties={"paper_id": paper_id, "evidence_id": evidence_id},
        )

        claim_id = claim_id_from_text(claim_text)
        claim_node = claim_node_id(claim_id)
        builder.add_node(
            "Claim",
            claim_node,
            _short_label(claim_text),
            properties={
                "claim_id": claim_id,
                "text": claim_text,
                "claim_type": "not_assessed",
                "support_status": _support_status_from_direction(direction),
            },
        )
        builder.add_edge(
            _edge_type_from_direction(direction),
            evidence_node,
            claim_node,
            properties={
                "evidence_id": evidence_id,
                "evidence_direction": direction,
                "confidence": confidence,
            },
        )

        for entity in _list_field(item, "entities"):
            _add_entity(builder, claim_node, entity)
        for method in _list_field(item, "methods"):
            _add_method(builder, evidence_node, str(method))
        for limitation in _list_field(item, "limitations"):
            _add_limitation(builder, claim_node, str(limitation))

        retrieval_id = str(_field(item, "retrieval_id") or "").strip()
        manifest_node_ids = (
            [retrieval_manifest_node_id(retrieval_id)]
            if retrieval_id
            else manifest_ids
        )
        for manifest_node in manifest_node_ids:
            if manifest_node not in builder._nodes:
                continue
            builder.add_edge(
                "RETRIEVAL_RETURNED_PAPER",
                manifest_node,
                paper_node,
                properties={"paper_id": paper_id},
            )

    return builder.build(graph_id_seed=":".join(sorted(seed_parts)))


def build_run_graph(
    run: Any,
    *,
    audit: Any | None = None,
    scope: GraphScope | None = None,
) -> BiomedEvidenceGraph:
    run_id = str(_field(run, "run_id") or "").strip()
    active_scope = scope or GraphScope(kind="run", identifiers={"run_id": run_id})
    builder = EvidenceGraphBuilder(scope=active_scope)
    if not run_id:
        builder.warn("Run graph skipped answer run without run_id.")
        return builder.build()

    clinical_refusal = _is_clinical_refusal_run(run)
    run_node = answer_run_node_id(run_id)
    builder.add_node(
        "AnswerRun",
        run_node,
        f"Answer run {run_id}",
        properties={
            "run_id": run_id,
            "retrieval_id": _field(run, "retrieval_id"),
            "clinical_refusal": clinical_refusal,
            "uncertainty_level": _field(run, "uncertainty_level"),
            "citation_count": len(_list_field(run, "citations")),
            "evidence_count": len(_list_field(run, "evidence_summary")),
            "not_medical_advice": _field(run, "not_medical_advice"),
        },
    )
    if clinical_refusal:
        return builder.build(graph_id_seed=run_id)

    evidence_graph = build_graph_from_evidence(
        _list_field(run, "evidence_summary"),
        retrieval_manifests=[
            item for item in [_field(run, "retrieval_manifest")] if item is not None
        ],
        scope=active_scope,
    )
    _merge_graph(builder, evidence_graph)

    packet = _field(run, "evidence_packet")
    if packet is not None:
        packet_node = _add_packet(builder, packet)
        builder.add_edge("ANSWER_USES_PACKET", run_node, packet_node)
        for evidence_id in _list_field(packet, "evidence_ids"):
            evidence_node = evidence_span_node_id(str(evidence_id))
            if evidence_node in builder._nodes:
                builder.add_edge("PACKET_SELECTS_EVIDENCE", packet_node, evidence_node)
        for retrieval_id in _list_field(packet, "retrieval_manifest_ids"):
            manifest_node = retrieval_manifest_node_id(str(retrieval_id))
            if manifest_node in builder._nodes:
                builder.add_edge(
                    "PACKET_SELECTED_FROM_RETRIEVAL",
                    packet_node,
                    manifest_node,
                )

    if audit is not None:
        _add_audit(builder, run_node, audit)

    return builder.build(graph_id_seed=run_id)


def _add_papers(builder: EvidenceGraphBuilder, papers: Iterable[Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for paper in papers:
        paper_id = str(_field(paper, "paper_id") or "").strip()
        if not paper_id:
            continue
        title = str(_field(paper, "title") or paper_id)
        titles[paper_id] = title
        builder.add_node(
            "Paper",
            paper_node_id(paper_id),
            title,
            properties={
                "paper_id": paper_id,
                "source": _field(paper, "source"),
                "title": title,
                "doi": _field(paper, "doi"),
                "url": _field(paper, "url"),
                "published_at": _field(paper, "publication_date"),
                "abstract_available": _field(paper, "abstract_available"),
                "authors": _list_field(paper, "authors"),
                "journal": _field(paper, "journal"),
            },
        )
    return titles


def _ensure_paper(
    builder: EvidenceGraphBuilder,
    paper_id: str,
    title: str | None = None,
) -> str:
    node_id = paper_node_id(paper_id)
    builder.add_node(
        "Paper",
        node_id,
        title or paper_id,
        properties={"paper_id": paper_id, "title": title or paper_id},
    )
    return node_id


def _add_retrieval_manifests(
    builder: EvidenceGraphBuilder,
    manifests: Iterable[Any],
) -> list[str]:
    node_ids: list[str] = []
    for manifest in manifests:
        retrieval_id = str(_field(manifest, "retrieval_id") or "").strip()
        if not retrieval_id:
            continue
        node_id = retrieval_manifest_node_id(retrieval_id)
        node_ids.append(node_id)
        builder.add_node(
            "RetrievalManifest",
            node_id,
            f"Retrieval manifest {retrieval_id}",
            properties={
                "retrieval_id": retrieval_id,
                "source": _field(manifest, "source"),
                "original_query": _field(manifest, "original_query"),
                "compiled_query": _field(manifest, "compiled_query"),
                "page_size": _field(manifest, "page_size"),
                "pages_requested": _field(manifest, "pages_requested"),
                "pages_completed": _field(manifest, "pages_completed"),
                "raw_result_count": _field(manifest, "raw_result_count"),
                "deduped_result_count": _field(manifest, "deduped_result_count"),
                "started_at": _field(manifest, "started_at"),
                "finished_at": _field(manifest, "finished_at"),
                "warnings": _list_field(manifest, "warnings"),
            },
        )
        for paper_id in _list_field(manifest, "returned_paper_ids"):
            paper_node = _ensure_paper(builder, str(paper_id))
            builder.add_edge(
                "RETRIEVAL_RETURNED_PAPER",
                node_id,
                paper_node,
                properties={"paper_id": str(paper_id)},
            )
    return node_ids


def _add_entity(builder: EvidenceGraphBuilder, claim_node: str, entity: Any) -> None:
    name = str(_field(entity, "name") or "").strip()
    if not name:
        return
    entity_type = str(_field(entity, "entity_type") or "other")
    normalized_id = _field(entity, "normalized_id")
    node_id = entity_node_id(
        name,
        entity_type=entity_type,
        normalized_id=str(normalized_id) if normalized_id else None,
    )
    builder.add_node(
        "Entity",
        node_id,
        name,
        properties={
            "name": name,
            "entity_type": entity_type,
            "normalized_id": normalized_id,
        },
    )
    builder.add_edge("CLAIM_MENTIONS_ENTITY", claim_node, node_id)


def _add_method(builder: EvidenceGraphBuilder, evidence_node: str, label: str) -> None:
    clean = label.strip()
    if not clean:
        return
    node_id = method_node_id(clean)
    builder.add_node("Method", node_id, clean, properties={"name": clean})
    builder.add_edge("EVIDENCE_USES_METHOD", evidence_node, node_id)


def _add_limitation(
    builder: EvidenceGraphBuilder,
    claim_node: str,
    label: str,
) -> None:
    clean = label.strip()
    if not clean:
        return
    node_id = limitation_node_id(clean)
    builder.add_node("Limitation", node_id, _short_label(clean), properties={"text": clean})
    builder.add_edge("CLAIM_HAS_LIMITATION", claim_node, node_id)


def _add_packet(builder: EvidenceGraphBuilder, packet: Any) -> str:
    packet_id = str(_field(packet, "packet_id") or "").strip()
    node_id = evidence_packet_node_id(packet_id)
    builder.add_node(
        "EvidencePacket",
        node_id,
        f"Evidence packet {packet_id}",
        properties={
            "packet_id": packet_id,
            "question": _field(packet, "question"),
            "planner_mode": _field(packet, "planner_mode"),
            "source": _field(packet, "source"),
            "evidence_ids": _list_field(packet, "evidence_ids"),
            "paper_ids": _list_field(packet, "paper_ids"),
            "retrieval_manifest_ids": _list_field(packet, "retrieval_manifest_ids"),
            "stop_reason": _field(packet, "stop_reason"),
        },
    )
    return node_id


def _add_audit(builder: EvidenceGraphBuilder, run_node: str, audit: Any) -> None:
    audit_id = str(_field(audit, "audit_id") or "").strip()
    if not audit_id:
        builder.warn("Skipped audit result missing audit_id.")
        return
    audit_node = audit_result_node_id(audit_id)
    builder.add_node(
        "AuditResult",
        audit_node,
        f"Audit result {audit_id}",
        properties={
            "audit_id": audit_id,
            "run_id": _field(audit, "run_id"),
            "retrieval_id": _field(audit, "retrieval_id"),
            "recommended_action": _field(audit, "recommended_action"),
            "claim_support_rate": _field(audit, "claim_support_rate"),
            "citation_precision": _field(audit, "citation_precision"),
            "unsupported_claim_rate": _field(audit, "unsupported_claim_rate"),
            "overclaim_rate": _field(audit, "overclaim_rate"),
        },
    )
    builder.add_edge("AUDIT_REVIEWS_ANSWER", audit_node, run_node)
    for item in _list_field(audit, "claim_audits"):
        claim_text = str(_field(item, "claim") or "").strip()
        if not claim_text:
            continue
        claim_id = str(_field(item, "claim_id") or claim_id_from_text(claim_text))
        claim_node = claim_node_id(claim_id)
        builder.add_node(
            "Claim",
            claim_node,
            _short_label(claim_text),
            properties={
                "claim_id": claim_id,
                "text": claim_text,
                "claim_type": _field(item, "claim_type") or "not_assessed",
                "support_status": _support_status_from_verdict(
                    str(_field(item, "verdict") or "not_assessed")
                ),
            },
        )
        builder.add_edge(
            "ANSWER_CITES_CLAIM",
            run_node,
            claim_node,
            properties={"claim_id": claim_id},
        )
        builder.add_edge(
            "AUDIT_REVIEWS_CLAIM",
            audit_node,
            claim_node,
            properties={
                "verdict": _field(item, "verdict"),
                "recommended_action": _field(audit, "recommended_action"),
                "support_score": _field(item, "support_score"),
                "overclaim_reason": _field(item, "overclaim_reason"),
            },
        )
        for evidence_id in _list_field(item, "evidence_ids"):
            evidence_node = evidence_span_node_id(str(evidence_id))
            if evidence_node in builder._nodes:
                builder.add_edge(
                    _edge_type_from_verdict(str(_field(item, "verdict") or "")),
                    evidence_node,
                    claim_node,
                    properties={
                        "evidence_id": str(evidence_id),
                        "audit_id": audit_id,
                        "verdict": _field(item, "verdict"),
                    },
                )


def _merge_graph(builder: EvidenceGraphBuilder, graph: BiomedEvidenceGraph) -> None:
    for node in graph.nodes:
        builder.add_node(
            node.type,
            node.id,
            node.label,
            properties=node.properties,
        )
    for edge in graph.edges:
        builder.add_edge(
            edge.type,
            edge.source,
            edge.target,
            properties=edge.properties,
        )
    for warning in graph.warnings:
        builder.warn(warning)


def _edge_type_from_direction(direction: str) -> EdgeType:
    if direction == "supports":
        return "EVIDENCE_SUPPORTS_CLAIM"
    if direction == "contradicts":
        return "EVIDENCE_CONTRADICTS_CLAIM"
    if direction == "inconclusive":
        return "EVIDENCE_QUALIFIES_CLAIM"
    return "EVIDENCE_PROVIDES_BACKGROUND_FOR_CLAIM"


def _edge_type_from_verdict(verdict: str) -> EdgeType:
    if verdict in {"supported", "partial_support"}:
        return "EVIDENCE_SUPPORTS_CLAIM"
    if verdict == "contradicted":
        return "EVIDENCE_CONTRADICTS_CLAIM"
    if verdict in {"overclaimed", "insufficient_evidence", "not_cited"}:
        return "EVIDENCE_QUALIFIES_CLAIM"
    return "EVIDENCE_PROVIDES_BACKGROUND_FOR_CLAIM"


def _support_status_from_direction(direction: str) -> str:
    if direction == "supports":
        return "supported"
    if direction == "contradicts":
        return "contradicted"
    if direction == "inconclusive":
        return "qualified"
    return "background"


def _support_status_from_verdict(verdict: str) -> str:
    if verdict in {"supported", "partial_support"}:
        return "supported"
    if verdict == "contradicted":
        return "contradicted"
    if verdict in {"overclaimed", "insufficient_evidence", "not_cited"}:
        return "unsupported"
    return "not_assessed"


def _is_clinical_refusal_run(run: Any) -> bool:
    if _list_field(run, "evidence_summary") or _list_field(run, "citations"):
        return False
    answer = str(_field(run, "answer") or "").lower()
    if "cannot help diagnose" in answer or "recommend treatment" in answer:
        return True
    classification = _field(run, "question_classification")
    return bool(_field(classification, "clinical_boundary"))


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _list_field(obj: Any, name: str) -> list[Any]:
    value = _field(obj, name, [])
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _short_label(value: str, *, limit: int = 180) -> str:
    clean = " ".join(str(value or "").split())
    return clean[:limit] if len(clean) > limit else clean


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    clean = str(value).strip()
    return clean or None
