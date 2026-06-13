"""Internal Biomedical Evidence Graph module.

This package is intentionally kept independent from dashboard, FastAPI routes,
plugin lifecycle, and LLM providers so it can later be extracted if the graph
layer becomes a standalone package.
"""

from plugins.biomed_evidence.graph.builder import (
    EvidenceGraphBuilder,
    build_graph_from_evidence,
    build_run_graph,
)
from plugins.biomed_evidence.graph.evidence_card import build_evidence_card
from plugins.biomed_evidence.graph.export import (
    REDACTED_VALUE,
    graph_to_json,
    graph_to_json_dict,
    redact_graph_export,
)
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
    normalize_text,
    paper_node_id,
    retrieval_manifest_node_id,
)
from plugins.biomed_evidence.graph.query import shortest_path
from plugins.biomed_evidence.graph.schema import (
    EDGE_TYPES,
    NODE_TYPES,
    SCHEMA_VERSION,
    BiomedEvidenceGraph,
    BiomedEvidenceGraphEdge,
    BiomedEvidenceGraphNode,
    EvidenceCard,
    EvidenceCardEvidence,
    GraphScope,
    GraphValidationResult,
    ValidationIssue,
)
from plugins.biomed_evidence.graph.validation import validate_evidence_graph

__all__ = [
    "SCHEMA_VERSION",
    "EDGE_TYPES",
    "NODE_TYPES",
    "REDACTED_VALUE",
    "BiomedEvidenceGraph",
    "BiomedEvidenceGraphEdge",
    "BiomedEvidenceGraphNode",
    "EvidenceCard",
    "EvidenceCardEvidence",
    "EvidenceGraphBuilder",
    "GraphScope",
    "GraphValidationResult",
    "ValidationIssue",
    "answer_run_node_id",
    "audit_result_node_id",
    "build_evidence_card",
    "build_graph_from_evidence",
    "build_run_graph",
    "claim_id_from_text",
    "claim_node_id",
    "edge_id",
    "entity_node_id",
    "evidence_packet_node_id",
    "evidence_span_node_id",
    "graph_to_json",
    "graph_to_json_dict",
    "limitation_node_id",
    "method_node_id",
    "normalize_text",
    "paper_node_id",
    "retrieval_manifest_node_id",
    "redact_graph_export",
    "shortest_path",
    "validate_evidence_graph",
]
