from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "biomed-evidence-graph-v1"

NODE_TYPES = (
    "Paper",
    "EvidenceSpan",
    "Claim",
    "Entity",
    "Method",
    "Limitation",
    "RetrievalManifest",
    "EvidencePacket",
    "AnswerRun",
    "AuditResult",
)

EDGE_TYPES = (
    "RETRIEVAL_RETURNED_PAPER",
    "PAPER_CONTAINS_EVIDENCE",
    "EVIDENCE_SUPPORTS_CLAIM",
    "EVIDENCE_CONTRADICTS_CLAIM",
    "EVIDENCE_QUALIFIES_CLAIM",
    "EVIDENCE_PROVIDES_BACKGROUND_FOR_CLAIM",
    "CLAIM_MENTIONS_ENTITY",
    "EVIDENCE_USES_METHOD",
    "CLAIM_HAS_LIMITATION",
    "PACKET_SELECTS_EVIDENCE",
    "PACKET_SELECTED_FROM_RETRIEVAL",
    "ANSWER_USES_PACKET",
    "ANSWER_CITES_CLAIM",
    "AUDIT_REVIEWS_CLAIM",
    "AUDIT_REVIEWS_ANSWER",
)

NodeType = Literal[
    "Paper",
    "EvidenceSpan",
    "Claim",
    "Entity",
    "Method",
    "Limitation",
    "RetrievalManifest",
    "EvidencePacket",
    "AnswerRun",
    "AuditResult",
]

EdgeType = Literal[
    "RETRIEVAL_RETURNED_PAPER",
    "PAPER_CONTAINS_EVIDENCE",
    "EVIDENCE_SUPPORTS_CLAIM",
    "EVIDENCE_CONTRADICTS_CLAIM",
    "EVIDENCE_QUALIFIES_CLAIM",
    "EVIDENCE_PROVIDES_BACKGROUND_FOR_CLAIM",
    "CLAIM_MENTIONS_ENTITY",
    "EVIDENCE_USES_METHOD",
    "CLAIM_HAS_LIMITATION",
    "PACKET_SELECTS_EVIDENCE",
    "PACKET_SELECTED_FROM_RETRIEVAL",
    "ANSWER_USES_PACKET",
    "ANSWER_CITES_CLAIM",
    "AUDIT_REVIEWS_CLAIM",
    "AUDIT_REVIEWS_ANSWER",
]

GraphScopeKind = Literal[
    "global",
    "topic",
    "entity",
    "paper",
    "run",
    "packet",
    "audit",
    "custom",
]

ValidationSeverity = Literal["error", "warning"]


class GraphScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: GraphScopeKind = "custom"
    identifiers: dict[str, str] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)


class BiomedEvidenceGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class BiomedEvidenceGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    type: EdgeType
    properties: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: ValidationSeverity = "error"
    node_id: str | None = None
    edge_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class GraphValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    error_count: int = 0
    warning_count: int = 0
    issues: list[ValidationIssue] = Field(default_factory=list)


class BiomedEvidenceGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    graph_id: str | None = None
    scope: GraphScope = Field(default_factory=GraphScope)
    nodes: list[BiomedEvidenceGraphNode] = Field(default_factory=list)
    edges: list[BiomedEvidenceGraphEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation: GraphValidationResult | None = None


class EvidenceCardEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_node_id: str
    relation: EdgeType
    text: str
    paper_id: str | None = None
    paper_title: str | None = None
    confidence: str | None = None
    evidence_direction: str | None = None
    retrieval_intent: str | None = None
    extraction_mode: str | None = None
    limitations: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)


class EvidenceCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_node_id: str
    claim_text: str
    support_status: str = "not_assessed"
    support_status_reason: str | None = None
    support_counts: dict[str, int] = Field(default_factory=dict)
    evidence: list[EvidenceCardEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    audit_results: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
