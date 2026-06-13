from __future__ import annotations

from collections import defaultdict

from plugins.biomed_evidence.graph.schema import (
    BiomedEvidenceGraph,
    BiomedEvidenceGraphEdge,
    BiomedEvidenceGraphNode,
    GraphValidationResult,
    ValidationIssue,
)


def validate_evidence_graph(graph: BiomedEvidenceGraph) -> GraphValidationResult:
    nodes = {node.id: node for node in graph.nodes}
    incoming: dict[str, list[BiomedEvidenceGraphEdge]] = defaultdict(list)
    outgoing: dict[str, list[BiomedEvidenceGraphEdge]] = defaultdict(list)
    issues: list[ValidationIssue] = []

    for edge in graph.edges:
        if edge.source not in nodes:
            issues.append(
                ValidationIssue(
                    code="edge_source_missing",
                    message="Graph edge source does not reference an existing node.",
                    edge_id=edge.id,
                    data={"source": edge.source, "edge_type": edge.type},
                )
            )
        if edge.target not in nodes:
            issues.append(
                ValidationIssue(
                    code="edge_target_missing",
                    message="Graph edge target does not reference an existing node.",
                    edge_id=edge.id,
                    data={"target": edge.target, "edge_type": edge.type},
                )
            )
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)

    _validate_supported_claims(nodes, incoming, issues)
    _validate_evidence_traces_to_paper(nodes, incoming, issues)
    _validate_refusal_boundary(graph, nodes, outgoing, issues)
    _validate_direction_consistency(nodes, graph.edges, issues)

    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    return GraphValidationResult(
        ok=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        issues=issues,
    )


def _validate_supported_claims(
    nodes: dict[str, BiomedEvidenceGraphNode],
    incoming: dict[str, list[BiomedEvidenceGraphEdge]],
    issues: list[ValidationIssue],
) -> None:
    for node in nodes.values():
        if node.type != "Claim":
            continue
        if node.properties.get("support_status") != "supported":
            continue
        support_edges = [
            edge
            for edge in incoming.get(node.id, [])
            if edge.type == "EVIDENCE_SUPPORTS_CLAIM"
            and nodes.get(edge.source, None)
            and nodes[edge.source].type == "EvidenceSpan"
        ]
        if not support_edges:
            issues.append(
                ValidationIssue(
                    code="supported_claim_requires_evidence",
                    message=(
                        "Supported Claim must have an incoming "
                        "EVIDENCE_SUPPORTS_CLAIM edge from EvidenceSpan."
                    ),
                    node_id=node.id,
                )
            )


def _validate_evidence_traces_to_paper(
    nodes: dict[str, BiomedEvidenceGraphNode],
    incoming: dict[str, list[BiomedEvidenceGraphEdge]],
    issues: list[ValidationIssue],
) -> None:
    for node in nodes.values():
        if node.type != "EvidenceSpan":
            continue
        paper_edges = [
            edge
            for edge in incoming.get(node.id, [])
            if edge.type == "PAPER_CONTAINS_EVIDENCE"
            and nodes.get(edge.source, None)
            and nodes[edge.source].type == "Paper"
        ]
        if len(paper_edges) != 1:
            issues.append(
                ValidationIssue(
                    code="evidence_span_requires_one_paper",
                    message="EvidenceSpan must trace to exactly one Paper.",
                    node_id=node.id,
                    data={"paper_edge_count": len(paper_edges)},
                )
            )


def _validate_refusal_boundary(
    graph: BiomedEvidenceGraph,
    nodes: dict[str, BiomedEvidenceGraphNode],
    outgoing: dict[str, list[BiomedEvidenceGraphEdge]],
    issues: list[ValidationIssue],
) -> None:
    refusal_runs = [
        node
        for node in nodes.values()
        if node.type == "AnswerRun" and bool(node.properties.get("clinical_refusal"))
    ]
    for run in refusal_runs:
        claim_edges = [
            edge for edge in outgoing.get(run.id, []) if edge.type == "ANSWER_CITES_CLAIM"
        ]
        if claim_edges:
            issues.append(
                ValidationIssue(
                    code="clinical_refusal_cites_claim",
                    message="Clinical refusal AnswerRun must not cite biomedical claims.",
                    node_id=run.id,
                    data={"edge_ids": [edge.id for edge in claim_edges]},
                )
            )
    if graph.scope.kind == "run" and refusal_runs:
        claim_nodes = [node for node in nodes.values() if node.type == "Claim"]
        if claim_nodes:
            issues.append(
                ValidationIssue(
                    code="clinical_refusal_has_claim",
                    message=(
                        "Run-scoped clinical refusal graph must not contain "
                        "biomedical Claim nodes."
                    ),
                    node_id=refusal_runs[0].id,
                    data={"claim_node_ids": [node.id for node in claim_nodes]},
                )
            )


def _validate_direction_consistency(
    nodes: dict[str, BiomedEvidenceGraphNode],
    edges: list[BiomedEvidenceGraphEdge],
    issues: list[ValidationIssue],
) -> None:
    for edge in edges:
        source = nodes.get(edge.source)
        if source is None or source.type != "EvidenceSpan":
            continue
        direction = edge.properties.get("evidence_direction")
        if direction is None:
            continue
        if direction == "supports" and edge.type == "EVIDENCE_CONTRADICTS_CLAIM":
            issues.append(
                ValidationIssue(
                    code="evidence_direction_edge_conflict",
                    message="Supporting EvidenceSpan cannot contradict a Claim.",
                    edge_id=edge.id,
                    data={"evidence_direction": direction, "edge_type": edge.type},
                )
            )
        if direction == "contradicts" and edge.type == "EVIDENCE_SUPPORTS_CLAIM":
            issues.append(
                ValidationIssue(
                    code="evidence_direction_edge_conflict",
                    message="Contradicting EvidenceSpan cannot support a Claim.",
                    edge_id=edge.id,
                    data={"evidence_direction": direction, "edge_type": edge.type},
                )
            )
