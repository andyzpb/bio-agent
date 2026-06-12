from __future__ import annotations

import hashlib
from typing import Any

from plugins.biomed_evidence.schemas import (
    AdvisoryVerifierResult,
    AgentTraceStep,
    AnswerRevision,
    AnswerWithEvidenceResult,
    CitationAuditResult,
    ProvenanceActivity,
    ProvenanceAgent,
    ProvenanceGraphResult,
    ProvenanceNodeEntity,
    ProvenanceRelation,
)

_TRACE_ACTIVITY_TYPE: dict[str, str] = {
    "classify": "classify",
    "plan": "plan",
    "validate_plan": "plan",
    "retrieve": "search",
    "extract": "extract",
    "coverage_gap_analysis": "gap_analyze",
    "build_packet": "packet_build",
    "draft": "synthesize",
    "audit": "audit",
    "advisory_verify": "audit",
    "post_audit": "audit",
    "revise": "revise",
    "finalize": "revise",
}


def build_provenance_graph(
    *,
    answer: AnswerWithEvidenceResult,
    trace: list[AgentTraceStep],
    audit: CitationAuditResult | None,
    revision: AnswerRevision | None,
    advisory: AdvisoryVerifierResult | None,
) -> ProvenanceGraphResult:
    entities: dict[str, ProvenanceNodeEntity] = {}
    activities: dict[str, ProvenanceActivity] = {}
    agents: dict[str, ProvenanceAgent] = {}
    relations: list[ProvenanceRelation] = []
    warnings: list[str] = []
    redactions = [
        "query_plan.llm_raw_response",
        "advisory_verifier.llm_raw_response",
        "answer_revision.llm_raw_response",
        "raw_provider_prompts",
        "api_keys",
        "secrets",
    ]

    def add_entity(entity: ProvenanceNodeEntity) -> None:
        entities[entity.id] = entity

    def add_activity(activity: ProvenanceActivity) -> None:
        activities[activity.id] = activity

    def add_agent(agent: ProvenanceAgent) -> None:
        agents[agent.id] = agent

    def add_relation(
        source: str,
        target: str,
        relation_type: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if source == target:
            return
        relations.append(
            ProvenanceRelation(
                source=source,
                target=target,
                type=relation_type,  # type: ignore[arg-type]
                attributes=attributes or {},
            )
        )

    run_id = answer.run_id
    graph_id = f"prov-{_digest(run_id)}"
    deterministic_agent_id = "agent:biomed_evidence:deterministic_service"
    plugin_agent_id = "agent:biomed_evidence:plugin_tool"
    reviewer_agent_id = "agent:biomed_evidence:reviewer"
    add_agent(
        ProvenanceAgent(
            id=deterministic_agent_id,
            type="deterministic_service",
            label="Biomedical Evidence deterministic service",
            attributes={"source_of_truth": "biomed_sqlite"},
        )
    )
    add_agent(
        ProvenanceAgent(
            id=plugin_agent_id,
            type="plugin_tool",
            label="Biomedical Evidence plugin tools",
            attributes={"tool_contract": "release-tool-envelope-v1"},
        )
    )
    add_agent(
        ProvenanceAgent(
            id=reviewer_agent_id,
            type="reviewer",
            label="Human reviewer memory boundary",
            attributes={"memory_as_evidence": False},
        )
    )

    answer_entity_id = f"answer:{run_id}"
    add_entity(
        ProvenanceNodeEntity(
            id=answer_entity_id,
            type="answer",
            stable_id=run_id,
            label=f"Answer run {run_id}",
            attributes={
                "citation_count": len(answer.citations),
                "evidence_count": len(answer.evidence_summary),
                "uncertainty_level": answer.uncertainty_level,
                "synthesis_mode": answer.synthesis_mode,
                "synthesis_model": answer.synthesis_model,
                "synthesis_prompt_hash": answer.synthesis_prompt_hash,
                "not_medical_advice": answer.not_medical_advice,
            },
        )
    )

    if answer.retrieval_manifest is not None:
        manifest = answer.retrieval_manifest
        manifest_id = f"retrieval_manifest:{manifest.retrieval_id}"
        add_entity(
            ProvenanceNodeEntity(
                id=manifest_id,
                type="retrieval_manifest",
                stable_id=manifest.retrieval_id,
                label=f"Retrieval manifest {manifest.retrieval_id}",
                attributes={
                    "source": manifest.source,
                    "original_query": manifest.original_query,
                    "compiled_query_hash": _digest(manifest.compiled_query or ""),
                    "returned_count": len(manifest.returned_paper_ids),
                    "started_at": manifest.started_at,
                    "finished_at": manifest.finished_at,
                    "warnings": manifest.warnings,
                },
            )
        )
        add_relation(manifest_id, answer_entity_id, "used")

    for record in answer.retrieval_bundle.records if answer.retrieval_bundle else []:
        if not record.retrieval_id:
            continue
        record_manifest_id = f"retrieval_manifest:{record.retrieval_id}"
        if record.manifest is not None:
            add_entity(
                ProvenanceNodeEntity(
                    id=record_manifest_id,
                    type="retrieval_manifest",
                    stable_id=record.retrieval_id,
                    label=f"Retrieval manifest {record.retrieval_id}",
                    attributes={
                        "source": record.manifest.source,
                        "retrieval_intent": record.intent,
                        "pass_index": record.pass_index,
                        "query_hash": _digest(record.query),
                        "returned_count": len(record.returned_paper_ids),
                        "warnings": record.warnings,
                    },
                )
            )
        add_relation(record_manifest_id, answer_entity_id, "used")

    for citation in answer.citations:
        paper_id = f"paper:{citation.paper_id}"
        add_entity(
            ProvenanceNodeEntity(
                id=paper_id,
                type="paper",
                stable_id=citation.paper_id,
                label=citation.title or citation.paper_id,
                attributes={
                    "source": citation.source,
                    "doi": citation.doi,
                    "url": citation.url,
                },
            )
        )
        add_relation(paper_id, answer_entity_id, "used")

    for evidence in answer.evidence_summary:
        evidence_id = f"evidence:{evidence.evidence_id}"
        paper_id = f"paper:{evidence.paper_id}"
        add_entity(
            ProvenanceNodeEntity(
                id=evidence_id,
                type="evidence_item",
                stable_id=evidence.evidence_id,
                label=evidence.claim[:120],
                attributes={
                    "paper_id": evidence.paper_id,
                    "evidence_direction": evidence.evidence_direction,
                    "retrieval_intent": evidence.retrieval_intent,
                    "extraction_mode": evidence.extraction_mode,
                    "confidence": evidence.confidence,
                    "has_span": bool(evidence.evidence_span),
                    "limitation_count": len(evidence.limitations),
                },
            )
        )
        add_relation(paper_id, evidence_id, "wasDerivedFrom")
        add_relation(evidence_id, answer_entity_id, "used")

    if answer.evidence_packet is not None:
        packet = answer.evidence_packet
        packet_id = f"evidence_packet:{packet.packet_id}"
        add_entity(
            ProvenanceNodeEntity(
                id=packet_id,
                type="evidence_packet",
                stable_id=packet.packet_id,
                label=f"Evidence packet {packet.packet_id}",
                attributes={
                    "source": packet.source,
                    "evidence_count": len(packet.evidence_ids),
                    "paper_count": len(packet.paper_ids),
                    "coverage_gap_count": len(packet.coverage_gaps),
                    "stop_reason": packet.stop_reason,
                },
            )
        )
        add_relation(packet_id, answer_entity_id, "used")
        for evidence_id in packet.evidence_ids:
            add_relation(f"evidence:{evidence_id}", packet_id, "used")
        for manifest_id in packet.retrieval_manifest_ids:
            add_relation(f"retrieval_manifest:{manifest_id}", packet_id, "used")

    if audit is not None:
        audit_id = f"citation_audit:{audit.audit_id}"
        add_entity(
            ProvenanceNodeEntity(
                id=audit_id,
                type="citation_audit",
                stable_id=audit.audit_id,
                label=f"Citation audit {audit.audit_id}",
                attributes={
                    "recommended_action": audit.recommended_action,
                    "claim_support_rate": audit.claim_support_rate,
                    "citation_precision": audit.citation_precision,
                    "unsupported_claim_rate": audit.unsupported_claim_rate,
                    "overclaim_rate": audit.overclaim_rate,
                },
            )
        )
        add_relation(audit_id, answer_entity_id, "wasDerivedFrom")
        for item in audit.claim_audits:
            if item.logic_audit is None:
                continue
            logic_id = f"logic_audit:{audit.audit_id}:{item.claim_id}"
            add_entity(
                ProvenanceNodeEntity(
                    id=logic_id,
                    type="logic_audit",
                    stable_id=f"{audit.audit_id}:{item.claim_id}",
                    label=f"Logic audit {item.claim_id}",
                    attributes={
                        "logic_verdict": item.logic_audit.logic_verdict,
                        "entailment_score": item.logic_audit.entailment_score,
                        "rules_triggered": item.logic_audit.rules_triggered,
                        "fact_export_id": (
                            item.logic_audit.logic_fact_export.export_id
                            if item.logic_audit.logic_fact_export is not None
                            else None
                        ),
                    },
                )
            )
            add_relation(logic_id, audit_id, "wasDerivedFrom")

    if revision is not None:
        revision_id = f"revision:{revision.revision_id}"
        add_entity(
            ProvenanceNodeEntity(
                id=revision_id,
                type="revision",
                stable_id=revision.revision_id,
                label=f"Revision {revision.revision_id}",
                attributes={
                    "revision_mode": revision.revision_mode,
                    "revision_action": revision.revision_action,
                    "llm_model": revision.llm_model,
                    "llm_prompt_hash": revision.llm_prompt_hash,
                    "fallback_reason": revision.fallback_reason,
                    "post_revision_audit_id": revision.post_revision_audit_id,
                },
            )
        )
        add_relation(revision_id, answer_entity_id, "generated")
        if revision.audit_id:
            add_relation(f"citation_audit:{revision.audit_id}", revision_id, "used")

    if advisory is not None and advisory.llm_model:
        llm_agent_id = f"agent:llm:{_safe_id(advisory.llm_model)}"
        add_agent(
            ProvenanceAgent(
                id=llm_agent_id,
                type="llm_provider_model",
                label=advisory.llm_model,
                attributes={
                    "prompt_hash": advisory.llm_prompt_hash,
                    "verifier_mode": advisory.verifier_mode,
                },
            )
        )

    for index, step in enumerate(trace, start=1):
        activity_type = _TRACE_ACTIVITY_TYPE.get(step.step)
        if activity_type is None:
            warnings.append(f"Trace step {step.step} is not mapped to provenance.")
            continue
        activity_id = f"activity:{run_id}:{index}:{step.step}"
        add_activity(
            ProvenanceActivity(
                id=activity_id,
                type=activity_type,  # type: ignore[arg-type]
                label=step.step,
                started_at=step.created_at,
                ended_at=step.created_at,
                attributes={
                    "status": step.status,
                    "input_summary_hash": _digest(step.input_summary),
                    "output_summary": step.output_summary[:240],
                    "warning_count": len(step.warnings),
                    "metadata_keys": sorted(step.metadata.keys()),
                },
            )
        )
        add_relation(activity_id, deterministic_agent_id, "wasAssociatedWith")
        add_relation(activity_id, plugin_agent_id, "wasAssociatedWith")
        if step.step in {"retrieve", "extract", "draft", "audit", "revise", "finalize"}:
            add_relation(activity_id, answer_entity_id, "generated")

    if answer.project_context_trace.get("memory_used"):
        add_relation(answer_entity_id, reviewer_agent_id, "wasAssociatedWith")

    if not trace:
        warnings.append("No persisted trace steps were available for this run.")
    if audit is None:
        warnings.append("No citation audit was available for this run.")
    if revision is None:
        warnings.append("No revision was available for this run.")

    return ProvenanceGraphResult(
        graph_id=graph_id,
        run_id=run_id,
        entities=sorted(entities.values(), key=lambda item: item.id),
        activities=sorted(activities.values(), key=lambda item: item.id),
        agents=sorted(agents.values(), key=lambda item: item.id),
        relations=relations,
        redactions=redactions,
        warnings=warnings,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value)
