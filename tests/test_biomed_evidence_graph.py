from __future__ import annotations

from plugins.biomed_evidence.graph import (
    REDACTED_VALUE,
    build_evidence_card,
    build_graph_from_evidence,
    build_run_graph,
    claim_id_from_text,
    edge_id,
    graph_to_json,
    graph_to_json_dict,
    shortest_path,
    validate_evidence_graph,
)
from plugins.biomed_evidence.graph.schema import (
    BiomedEvidenceGraph,
    BiomedEvidenceGraphEdge,
    BiomedEvidenceGraphNode,
    GraphScope,
)
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceResult,
    BiomedicalEntity,
    Citation,
    CitationAuditRequest,
    EvidenceItem,
    RetrievalManifest,
)
from plugins.biomed_evidence.service import BiomedEvidenceService


def test_graph_ids_are_stable_and_normalized() -> None:
    first = claim_id_from_text(" Microglial   activation supports progression ")
    second = claim_id_from_text("microglial activation supports progression")

    assert first == second
    assert edge_id("a", "EVIDENCE_SUPPORTS_CLAIM", "b") == edge_id(
        "a",
        "EVIDENCE_SUPPORTS_CLAIM",
        "b",
    )


def test_graph_json_export_redacts_sensitive_properties() -> None:
    graph = BiomedEvidenceGraph(
        nodes=[
            BiomedEvidenceGraphNode(
                id="answer_run:redaction",
                type="AnswerRun",
                label="Answer run redaction",
                properties={
                    "run_id": "redaction",
                    "text": "safe evidence graph metadata",
                    "prompt": "raw system prompt should not leave the process",
                    "raw_provider_response": {"content": "provider raw payload"},
                    "nested": {
                        "api_key": "sk-test-secret-token-123456",
                        "authorization": "Bearer abcdefghijklmnop123456",
                    },
                    "notes": [
                        {"access_token": "access-token-secret-value"},
                        "safe text with api_key=sk-value-that-should-redact",
                    ],
                },
            )
        ],
        edges=[],
        warnings=["Authorization: Bearer warningsecret123456"],
    )

    payload = graph_to_json_dict(graph)
    text = graph_to_json(graph)

    properties = payload["nodes"][0]["properties"]
    assert properties["text"] == "safe evidence graph metadata"
    assert properties["prompt"] == REDACTED_VALUE
    assert properties["raw_provider_response"] == REDACTED_VALUE
    assert properties["nested"]["api_key"] == REDACTED_VALUE
    assert properties["nested"]["authorization"] == REDACTED_VALUE
    assert properties["notes"][0]["access_token"] == REDACTED_VALUE
    assert REDACTED_VALUE in properties["notes"][1]
    assert REDACTED_VALUE in payload["warnings"][0]
    assert "raw system prompt" not in text
    assert "provider raw payload" not in text
    assert "sk-test-secret-token" not in text
    assert "Bearer abcdefgh" not in text
    assert "safe evidence graph metadata" in text


def test_build_graph_from_evidence_validates_and_builds_card() -> None:
    item = EvidenceItem(
        evidence_id="ev-graph-1",
        paper_id="PMID:1",
        claim="Microglial activation is associated with disease progression.",
        finding="The abstract reports microglial activation in progression.",
        evidence_direction="supports",
        entities=[
            BiomedicalEntity(
                name="microglial activation",
                entity_type="cell_type",
            )
        ],
        methods=["single-cell RNA-seq"],
        limitations=["Abstract-only extraction."],
        confidence="medium",
        evidence_span="The abstract reports microglial activation in progression.",
    )
    manifest = RetrievalManifest(
        retrieval_id="ret-graph-1",
        source="mock",
        original_query="microglial activation",
        compiled_query="microglial activation",
        page_size=5,
        pages_requested=1,
        pages_completed=1,
        raw_result_count=1,
        deduped_result_count=1,
        returned_paper_ids=["PMID:1"],
        started_at="2026-01-01T00:00:00+00:00",
    )

    graph = build_graph_from_evidence([item], retrieval_manifests=[manifest])

    assert graph.schema_version == "biomed-evidence-graph-v1"
    assert {"Paper", "EvidenceSpan", "Claim", "Entity", "Method", "Limitation"} <= {
        node.type for node in graph.nodes
    }
    assert {
        "RETRIEVAL_RETURNED_PAPER",
        "PAPER_CONTAINS_EVIDENCE",
        "EVIDENCE_SUPPORTS_CLAIM",
        "CLAIM_MENTIONS_ENTITY",
        "EVIDENCE_USES_METHOD",
        "CLAIM_HAS_LIMITATION",
    } <= {edge.type for edge in graph.edges}

    validation = validate_evidence_graph(graph)
    assert validation.ok, validation.model_dump(mode="json")

    claim_node_id = next(node.id for node in graph.nodes if node.type == "Claim")
    card = build_evidence_card(graph, claim_node_id)
    assert card.claim_text == item.claim
    assert card.evidence[0].paper_id == "PMID:1"
    assert card.limitations == ["Abstract-only extraction."]

    manifest_node_id = next(
        node.id for node in graph.nodes if node.type == "RetrievalManifest"
    )
    path = shortest_path(graph, manifest_node_id, claim_node_id)
    assert path[0] == manifest_node_id
    assert path[-1] == claim_node_id


def test_validation_requires_supported_claim_evidence_edge() -> None:
    graph = BiomedEvidenceGraph(
        nodes=[
            BiomedEvidenceGraphNode(
                id="claim:unsupported",
                type="Claim",
                label="Unsupported claim",
                properties={
                    "claim_id": "unsupported",
                    "text": "Unsupported claim",
                    "support_status": "supported",
                },
            )
        ],
        edges=[],
    )

    validation = validate_evidence_graph(graph)

    assert not validation.ok
    assert {issue.code for issue in validation.issues} == {
        "supported_claim_requires_evidence"
    }


def test_validation_requires_evidence_span_to_trace_to_paper() -> None:
    graph = BiomedEvidenceGraph(
        nodes=[
            BiomedEvidenceGraphNode(
                id="evidence:missing-paper",
                type="EvidenceSpan",
                label="Evidence without paper",
                properties={
                    "evidence_id": "missing-paper",
                    "paper_id": "PMID:missing",
                    "evidence_direction": "supports",
                },
            )
        ],
        edges=[],
    )

    validation = validate_evidence_graph(graph)

    assert not validation.ok
    assert {issue.code for issue in validation.issues} == {
        "evidence_span_requires_one_paper"
    }


def test_validation_rejects_direction_derived_edge_conflicts() -> None:
    graph = BiomedEvidenceGraph(
        nodes=[
            BiomedEvidenceGraphNode(
                id="paper:1",
                type="Paper",
                label="Paper 1",
                properties={"paper_id": "1"},
            ),
            BiomedEvidenceGraphNode(
                id="evidence:1",
                type="EvidenceSpan",
                label="Evidence 1",
                properties={
                    "evidence_id": "1",
                    "paper_id": "1",
                    "evidence_direction": "supports",
                },
            ),
            BiomedEvidenceGraphNode(
                id="claim:1",
                type="Claim",
                label="Claim 1",
                properties={"claim_id": "1", "support_status": "contradicted"},
            ),
        ],
        edges=[
            BiomedEvidenceGraphEdge(
                id="edge:paper-evidence",
                source="paper:1",
                target="evidence:1",
                type="PAPER_CONTAINS_EVIDENCE",
            ),
            BiomedEvidenceGraphEdge(
                id="edge:evidence-claim",
                source="evidence:1",
                target="claim:1",
                type="EVIDENCE_CONTRADICTS_CLAIM",
                properties={"evidence_direction": "supports"},
            ),
        ],
    )

    validation = validate_evidence_graph(graph)

    assert not validation.ok
    assert {issue.code for issue in validation.issues} == {
        "evidence_direction_edge_conflict"
    }


def test_clinical_refusal_run_graph_does_not_create_claims() -> None:
    run = AnswerWithEvidenceResult(
        run_id="run-clinical",
        answer=(
            "This system is intended for biomedical research support only.\n\n"
            "I cannot help diagnose a patient or recommend treatment."
        ),
        citations=[],
        evidence_summary=[],
        conflicting_evidence=[],
        limitations=["Clinical boundary."],
        uncertainty_level="high",
        disclaimer="Research support only.",
    )

    graph = build_run_graph(run)
    validation = validate_evidence_graph(graph)

    assert {node.type for node in graph.nodes} == {"AnswerRun"}
    assert not graph.edges
    assert validation.ok


def test_validation_rejects_claims_in_refusal_run_scope() -> None:
    graph = BiomedEvidenceGraph(
        scope=GraphScope(kind="run", identifiers={"run_id": "run-clinical"}),
        nodes=[
            BiomedEvidenceGraphNode(
                id="answer_run:run-clinical",
                type="AnswerRun",
                label="Answer run run-clinical",
                properties={"run_id": "run-clinical", "clinical_refusal": True},
            ),
            BiomedEvidenceGraphNode(
                id="claim:bad",
                type="Claim",
                label="Bad biomedical claim",
                properties={"claim_id": "bad", "support_status": "not_assessed"},
            ),
        ],
        edges=[
            BiomedEvidenceGraphEdge(
                id="edge:bad",
                source="answer_run:run-clinical",
                target="claim:bad",
                type="ANSWER_CITES_CLAIM",
            )
        ],
    )

    validation = validate_evidence_graph(graph)

    assert not validation.ok
    assert {
        "clinical_refusal_cites_claim",
        "clinical_refusal_has_claim",
    } <= {issue.code for issue in validation.issues}


def test_snapshot_storage_contract_is_deterministic_and_immutable(tmp_path) -> None:
    service = BiomedEvidenceService(tmp_path)
    evidence = EvidenceItem(
        evidence_id="ev-snapshot-1",
        paper_id="PMID:42",
        claim="Microglial activation is associated with disease progression.",
        finding="The abstract reports microglial activation in progression.",
        evidence_direction="supports",
        entities=[
            BiomedicalEntity(
                name="microglial activation",
                entity_type="cell_type",
            )
        ],
        methods=["single-cell RNA-seq"],
        limitations=["Abstract-only extraction."],
        confidence="medium",
        evidence_span="The abstract reports microglial activation in progression.",
    )
    run = AnswerWithEvidenceResult(
        run_id="run-snapshot",
        retrieval_id="ret-snapshot",
        answer="Microglial activation is associated with disease progression [PMID:42].",
        citations=[
            Citation(
                paper_id="PMID:42",
                title="Microglial activation in progression",
                source="mock",
                cited_claim=evidence.claim,
            )
        ],
        evidence_summary=[evidence],
        limitations=["Abstract-only extraction."],
        uncertainty_level="medium",
        disclaimer="Research support only.",
    )

    try:
        table = service.storage._db.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='biomed_evidence_graph_snapshots'
            """
        ).fetchone()
        assert table is not None

        service.storage.save_answer_run(run, question="What is microglial activation?")
        first = service.create_evidence_graph_snapshot(run.run_id)
        assert first is not None
        assert first.snapshot_id
        assert first.audit_id is None
        assert first.validation["ok"] is True
        assert first.graph["schema_version"] == "biomed-evidence-graph-v1"

        second = service.create_evidence_graph_snapshot(run.run_id)
        assert second is not None
        assert second.snapshot_id == first.snapshot_id
        assert second.created_at == first.created_at

        forced = service.create_evidence_graph_snapshot(run.run_id, force=True)
        assert forced is not None
        assert forced.snapshot_id == first.snapshot_id
        assert forced.created_at == first.created_at

        audit = service.audit_answer(
            CitationAuditRequest(
                answer=run.answer,
                citations=run.citations,
                evidence_items=run.evidence_summary,
                run_id=run.run_id,
                retrieval_id=run.retrieval_id,
                observed_uncertainty=run.uncertainty_level,
            )
        )
        audited_snapshot = service.create_evidence_graph_snapshot(
            run.run_id,
            force=True,
        )
        assert audited_snapshot is not None
        assert audited_snapshot.audit_id == audit.audit_id
        assert audited_snapshot.snapshot_id != first.snapshot_id

        review = service.get_run_evidence_review(run.run_id)
        assert review is not None
        assert review.snapshot.status == "persisted"
        assert review.snapshot.snapshot_id == audited_snapshot.snapshot_id
        assert review.summary.total_claims >= 1
        assert review.claims[0].evidence_card["claim_text"]

        rows = service.storage._db.execute(
            """
            SELECT snapshot_id FROM biomed_evidence_graph_snapshots
            WHERE run_id=?
            ORDER BY created_at ASC
            """,
            (run.run_id,),
        ).fetchall()
        assert [row["snapshot_id"] for row in rows] == [
            first.snapshot_id,
            audited_snapshot.snapshot_id,
        ]
    finally:
        service.close()
