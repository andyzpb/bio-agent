from __future__ import annotations

import hashlib
import re


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def stable_digest(value: str, *, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _required(value: str, name: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{name} is required")
    return clean


def claim_id_from_text(text: str) -> str:
    normalized = normalize_text(_required(text, "claim text"))
    return f"claim-{stable_digest(normalized, length=16)}"


def paper_node_id(paper_id: str) -> str:
    return f"paper:{_required(paper_id, 'paper_id')}"


def evidence_span_node_id(evidence_id: str) -> str:
    return f"evidence:{_required(evidence_id, 'evidence_id')}"


def claim_node_id(claim_id: str) -> str:
    return f"claim:{_required(claim_id, 'claim_id')}"


def entity_node_id(
    name: str,
    *,
    entity_type: str = "other",
    normalized_id: str | None = None,
) -> str:
    if normalized_id:
        return f"entity:{stable_digest(f'{entity_type}:{normalized_id}', length=20)}"
    return f"entity:{stable_digest(f'{entity_type}:{normalize_text(name)}', length=20)}"


def method_node_id(label: str) -> str:
    return f"method:{stable_digest(normalize_text(label), length=20)}"


def limitation_node_id(label: str) -> str:
    return f"limitation:{stable_digest(normalize_text(label), length=20)}"


def retrieval_manifest_node_id(retrieval_id: str) -> str:
    return f"retrieval_manifest:{_required(retrieval_id, 'retrieval_id')}"


def evidence_packet_node_id(packet_id: str) -> str:
    return f"evidence_packet:{_required(packet_id, 'packet_id')}"


def answer_run_node_id(run_id: str) -> str:
    return f"answer_run:{_required(run_id, 'run_id')}"


def audit_result_node_id(audit_id: str) -> str:
    return f"audit_result:{_required(audit_id, 'audit_id')}"


def edge_id(source: str, edge_type: str, target: str) -> str:
    key = f"{_required(source, 'source')}|{_required(edge_type, 'edge_type')}|{_required(target, 'target')}"
    return f"edge:{stable_digest(key, length=24)}"
