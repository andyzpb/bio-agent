from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.biomed_evidence.dashboard import register


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    register(app, Path(__file__).parents[1] / "plugins" / "biomed_evidence", tmp_path)
    return TestClient(app)


def test_biomed_api_answer_extract_graph_and_audit(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        search = client.get(
            "/api/biomed/search",
            params={"query": "microglia", "source": "mock"},
        )
        assert search.status_code == 200
        search_payload = search.json()
        assert search_payload["items"]
        retrieval_id = search_payload["retrieval_manifest"]["retrieval_id"]
        retrieval = client.get(f"/api/biomed/retrievals/{retrieval_id}")
        assert retrieval.status_code == 200
        assert retrieval.json()["returned_paper_ids"]

        literature_check = client.post(
            "/api/biomed/literature/check",
            json={
                "query": "microglia Alzheimer",
                "source": "mock",
                "max_results": 2,
            },
        )
        assert literature_check.status_code == 200
        literature_payload = literature_check.json()
        assert literature_payload["ok"] is True
        assert literature_payload["ready"] is True
        assert literature_payload["item_count"] >= 1
        assert literature_payload["retrieval_manifest"]["source"] == "mock"

        literature_search = client.post(
            "/api/biomed/literature/search",
            json={
                "query": "microglia Alzheimer",
                "source": "mock",
                "max_results": 2,
                "retrieval_intent": "primary",
                "require_abstract": True,
                "store": True,
            },
        )
        assert literature_search.status_code == 200
        literature_search_payload = literature_search.json()
        assert literature_search_payload["source"] == "mock"
        assert literature_search_payload["items"]
        assert literature_search_payload["coverage"]["item_count"] >= 1
        assert literature_search_payload["coverage"]["abstract_count"] >= 1
        assert literature_search_payload["source_trace"]["stored_paper_ids"]
        assert literature_search_payload["retrieval_manifest"]["returned_paper_ids"]

        plan = client.post(
            "/api/biomed/plan",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_results": 5,
            },
        )
        assert plan.status_code == 200
        plan_payload = plan.json()
        assert plan_payload["classification"]["intent"] == "research_question"
        assert plan_payload["query_plan"]["support_queries"]
        assert plan_payload["query_plan"]["refute_queries"]
        assert plan_payload["validation"]["valid"] is True
        assert plan_payload["search_request"]["source"] == "mock"

        answer = client.post(
            "/api/biomed/answer",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_papers": 5,
            },
        )
        assert answer.status_code == 200
        payload = answer.json()
        assert payload["citations"]
        assert payload["evidence_summary"]
        assert payload["retrieval_id"]
        assert payload["retrieval_manifest"]["compiled_query"]

        project = client.post(
            "/api/biomed/projects",
            json={
                "name": "Microglia API project",
                "research_question": "microglial activation and Alzheimer's disease progression",
                "include_keywords": ["microglial activation"],
            },
        )
        assert project.status_code == 200
        project_id = project.json()["project_id"]
        rejected_paper = search_payload["items"][0]["paper_id"]
        saved_paper = search_payload["items"][1]["paper_id"]
        assert client.post(
            f"/api/biomed/projects/{project_id}/papers",
            json={
                "paper_id": rejected_paper,
                "source": "mock",
                "decision": "rejected",
                "reason": "API test rejection",
            },
        ).status_code == 200
        assert client.post(
            f"/api/biomed/projects/{project_id}/papers",
            json={
                "paper_id": saved_paper,
                "source": "mock",
                "decision": "saved",
                "reason": "API test priority",
            },
        ).status_code == 200
        project_answer = client.post(
            "/api/biomed/answer",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_papers": 5,
                "project_id": project_id,
            },
        )
        assert project_answer.status_code == 200
        project_payload = project_answer.json()
        assert project_payload["project_id"] == project_id
        assert project_payload["project_context_trace"]["memory_used"] is True
        assert rejected_paper not in project_payload["retrieval_manifest"]["returned_paper_ids"]

        claim = client.post(
            f"/api/biomed/projects/{project_id}/claims",
            json={
                "claim": project_payload["evidence_summary"][0]["claim"],
                "status": "supported",
                "evidence_ids": [project_payload["evidence_summary"][0]["evidence_id"]],
                "audit_ids": ["audit-api-test"],
            },
        )
        assert claim.status_code == 200
        brief = client.post(
            f"/api/biomed/projects/{project_id}/briefs",
            json={"format": "markdown"},
        )
        assert brief.status_code == 200
        assert "Project memory is context only" in brief.json()["content"]
        queue = client.get(f"/api/biomed/projects/{project_id}/review-queue")
        assert queue.status_code == 200

        evidence = client.get("/api/biomed/evidence", params={"direction": "supports"})
        assert evidence.status_code == 200
        assert evidence.json()["total"] >= 1

        graph = client.get("/api/biomed/graph", params={"topic": "microglial activation"})
        assert graph.status_code == 200
        assert graph.json()["nodes"]
        assert graph.json()["edges"]

        graph_schema = client.get("/api/biomed/graph/schema")
        assert graph_schema.status_code == 200
        graph_schema_payload = graph_schema.json()
        assert graph_schema_payload["schema_version"] == "biomed-evidence-graph-v1"
        assert "EvidenceSpan" in graph_schema_payload["node_types"]
        assert "EVIDENCE_SUPPORTS_CLAIM" in graph_schema_payload["edge_types"]

        graph_v1 = client.get(
            "/api/biomed/graph/v1",
            params={"topic": "microglial activation", "validate": True},
        )
        assert graph_v1.status_code == 200
        graph_v1_payload = graph_v1.json()
        assert graph_v1_payload["schema_version"] == "biomed-evidence-graph-v1"
        assert graph_v1_payload["scope"]["kind"] == "topic"
        assert graph_v1_payload["validation"]["ok"] is True
        assert {"Paper", "EvidenceSpan", "Claim"}.issubset(
            {node["type"] for node in graph_v1_payload["nodes"]}
        )
        assert {"PAPER_CONTAINS_EVIDENCE", "EVIDENCE_SUPPORTS_CLAIM"} & {
            edge["type"] for edge in graph_v1_payload["edges"]
        }

        pre_audit_review = client.get(
            f"/api/biomed/answer-runs/{payload['run_id']}/evidence-review",
        )
        assert pre_audit_review.status_code == 200
        pre_audit_review_payload = pre_audit_review.json()
        assert pre_audit_review_payload["schema_version"] == "biomed-evidence-review-v1"
        assert pre_audit_review_payload["snapshot"]["status"] == "missing"
        assert pre_audit_review_payload["snapshot_required"] is True
        assert pre_audit_review_payload["claims"]

        audit = client.get(f"/api/biomed/audit/{payload['run_id']}")
        assert audit.status_code == 200
        assert audit.json()["run_id"] == payload["run_id"]
        assert audit.json()["retrieval_id"] == payload["retrieval_id"]
        assert audit.json()["latest_citation_audit"] is None

        created_audit = client.post(f"/api/biomed/answer-runs/{payload['run_id']}/audit")
        assert created_audit.status_code == 200
        audit_payload = created_audit.json()
        assert audit_payload["run_id"] == payload["run_id"]
        assert audit_payload["claim_support_rate"] >= 0.8
        assert audit_payload["citation_precision"] >= 0.8
        assert audit_payload["recommended_action"] in {
            "pass",
            "pass_with_limitations",
            "revise",
            "refuse_or_abstain",
        }

        audit_detail = client.get(f"/api/biomed/audits/{audit_payload['audit_id']}")
        assert audit_detail.status_code == 200
        assert audit_detail.json()["audit_id"] == audit_payload["audit_id"]

        audit_list = client.get("/api/biomed/audits", params={"run_id": payload["run_id"]})
        assert audit_list.status_code == 200
        assert audit_list.json()["total"] == 1

        audit = client.get(f"/api/biomed/audit/{payload['run_id']}")
        assert audit.status_code == 200
        assert audit.json()["latest_citation_audit"]["audit_id"] == audit_payload["audit_id"]

        review = client.get(
            f"/api/biomed/answer-runs/{payload['run_id']}/evidence-review",
        )
        assert review.status_code == 200
        review_payload = review.json()
        assert review_payload["schema_version"] == "biomed-evidence-review-v1"
        assert review_payload["snapshot"]["status"] == "persisted"
        assert review_payload["snapshot"]["snapshot_id"]
        assert review_payload["snapshot"]["audit_id"] == audit_payload["audit_id"]
        assert review_payload["snapshot_required"] is False
        assert review_payload["summary"]["total_claims"] >= 1
        assert review_payload["summary"]["validation_ok"] is True
        assert review_payload["claims"]
        assert review_payload["claims"][0]["evidence_card"]["claim_text"]
        assert review_payload["claims"][0]["links"]["trace"].endswith("/trace")

        review_with_graph = client.get(
            f"/api/biomed/answer-runs/{payload['run_id']}/evidence-review",
            params={"include_graph": True},
        )
        assert review_with_graph.status_code == 200
        assert review_with_graph.json()["graph"]["schema_version"] == (
            "biomed-evidence-graph-v1"
        )

        snapshot = client.post(
            f"/api/biomed/answer-runs/{payload['run_id']}/evidence-review/snapshot",
        )
        assert snapshot.status_code == 200
        snapshot_payload = snapshot.json()
        assert snapshot_payload["snapshot"]["snapshot_id"] == (
            review_payload["snapshot"]["snapshot_id"]
        )
        assert snapshot_payload["validation"]["ok"] is True

        run_graph = client.get(
            f"/api/biomed/answer-runs/{payload['run_id']}/evidence-graph",
            params={"validate": True},
        )
        assert run_graph.status_code == 200
        run_graph_payload = run_graph.json()
        assert run_graph_payload["schema_version"] == "biomed-evidence-graph-v1"
        assert run_graph_payload["scope"]["kind"] == "run"
        assert run_graph_payload["validation"]["ok"] is True
        assert {"AnswerRun", "Paper", "EvidenceSpan", "Claim", "AuditResult"}.issubset(
            {node["type"] for node in run_graph_payload["nodes"]}
        )
        assert {"AUDIT_REVIEWS_ANSWER", "AUDIT_REVIEWS_CLAIM"}.issubset(
            {edge["type"] for edge in run_graph_payload["edges"]}
        )
        run_claim_id = next(
            edge["target"]
            for edge in run_graph_payload["edges"]
            if edge["type"].startswith("EVIDENCE_") and edge["target"].startswith("claim:")
        )
        run_answer_id = next(
            node["id"] for node in run_graph_payload["nodes"] if node["type"] == "AnswerRun"
        )

        graph_validate = client.post(
            "/api/biomed/graph/v1/validate",
            json={"graph": run_graph_payload},
        )
        assert graph_validate.status_code == 200
        assert graph_validate.json()["ok"] is True

        graph_validate_by_run = client.post(
            "/api/biomed/graph/v1/validate",
            json={"run_id": payload["run_id"]},
        )
        assert graph_validate_by_run.status_code == 200
        assert graph_validate_by_run.json()["ok"] is True

        evidence_card = client.get(
            f"/api/biomed/graph/v1/evidence-card/{run_claim_id}",
            params={"run_id": payload["run_id"]},
        )
        assert evidence_card.status_code == 200
        evidence_card_payload = evidence_card.json()
        assert evidence_card_payload["claim_node_id"] == run_claim_id
        assert evidence_card_payload["claim_text"]
        assert evidence_card_payload["evidence"]

        missing_card = client.get(
            "/api/biomed/graph/v1/evidence-card/claim:unknown",
            params={"run_id": payload["run_id"]},
        )
        assert missing_card.status_code == 404
        assert missing_card.json()["detail"]["error_code"] == "unknown_claim_id"

        graph_path = client.get(
            "/api/biomed/graph/v1/path",
            params={
                "run_id": payload["run_id"],
                "source": run_answer_id,
                "target": run_claim_id,
            },
        )
        assert graph_path.status_code == 200
        graph_path_payload = graph_path.json()
        assert graph_path_payload["path"][0] == run_answer_id
        assert graph_path_payload["path"][-1] == run_claim_id
        assert graph_path_payload["nodes"]
        assert graph_path_payload["edges"]

        missing_path = client.get(
            "/api/biomed/graph/v1/path",
            params={
                "run_id": payload["run_id"],
                "source": run_answer_id,
                "target": "claim:does-not-exist",
            },
        )
        assert missing_path.status_code == 404
        assert missing_path.json()["detail"]["error_code"] == "graph_path_not_found"

        graph_export = client.get(
            "/api/biomed/graph/v1/export/json",
            params={"run_id": payload["run_id"], "validate": True},
        )
        assert graph_export.status_code == 200
        graph_export_payload = graph_export.json()
        assert graph_export_payload["schema_version"] == "biomed-evidence-graph-v1"
        assert graph_export_payload["validation"]["ok"] is True
        graph_export_text = json.dumps(graph_export_payload)
        assert "raw_provider_response" not in graph_export_text
        assert "api_key" not in graph_export_text
        assert "system_prompt" not in graph_export_text

        missing_run_graph = client.get(
            "/api/biomed/graph/v1",
            params={"run_id": "unknown-run"},
        )
        assert missing_run_graph.status_code == 404
        assert missing_run_graph.json()["detail"]["error_code"] == "unknown_run_id"
        missing_review = client.get(
            "/api/biomed/answer-runs/unknown-run/evidence-review",
        )
        assert missing_review.status_code == 404
        assert missing_review.json()["detail"]["error_code"] == "unknown_run_id"

        conflict = client.post(
            "/api/biomed/conflicts",
            json={
                "claim": "Microglial activation is associated with Alzheimer's disease progression.",
                "topic": "microglial activation Alzheimer's disease progression",
                "source": "mock",
            },
        )
        assert conflict.status_code == 200
        assert conflict.json()["verdict"] in {
            "no_conflict_found",
            "mixed_evidence",
            "contradicted",
            "insufficient_search",
        }

        report = client.get("/api/biomed/export", params={"run_id": payload["run_id"]})
        assert report.status_code == 200
        assert "Biomedical Evidence Report" in report.text
        assert "Retrieval Provenance" in report.text

        audited = client.post(
            "/api/biomed/answer/audited",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_papers": 5,
                "use_llm_planner": True,
                "execute_support_refute": True,
                "use_llm_verifier": True,
                "use_llm_claim_logic": True,
                "export_logic_facts": True,
            },
        )
        assert audited.status_code == 200
        audited_payload = audited.json()
        audited_run_id = audited_payload["answer_result"]["run_id"]
        assert audited_payload["audit"]["audit_id"]
        assert audited_payload["advisory_verifier"]["verifier_mode"] == "fallback"
        assert audited_payload["revision"]["revision_id"]
        assert audited_payload["final_action"] in {"pass", "revise", "refuse", "abstain"}
        assert audited_payload["answer_result"]["retrieval_bundle"]["executed_multi_query"] is True
        assert len(audited_payload["answer_result"]["retrieval_bundle"]["records"]) >= 3
        assert audited_payload["answer_result"]["evidence_packet"]["coverage_matrix"]
        assert audited_payload["answer_result"]["evidence_packet"]["stop_reason"] in {
            "coverage_sufficient",
            "gap_followup_complete",
        }
        assert len(audited_payload["trace"]) == 11

        trace = client.get(f"/api/biomed/answer-runs/{audited_run_id}/trace")
        assert trace.status_code == 200
        trace_payload = trace.json()
        assert trace_payload["run_id"] == audited_run_id
        assert trace_payload["revision"]["revision_id"] == audited_payload["revision"]["revision_id"]
        assert trace_payload["latest_advisory_verifier"]["verifier_mode"] == "fallback"
        assert trace_payload["step_telemetry"]["advisory_only"] is True
        assert trace_payload["memory"]["memory_as_evidence"] is False
        assert {step["step"] for step in trace_payload["trace"]} == {
            "classify",
            "plan",
            "validate_plan",
            "retrieve",
            "extract",
            "draft",
            "audit",
            "advisory_verify",
            "revise",
            "post_audit",
            "finalize",
        }
        retrieve_step = next(step for step in trace_payload["trace"] if step["step"] == "retrieve")
        assert retrieve_step["metadata"]["retrieval_bundle"]["executed_multi_query"] is True
        assert retrieve_step["metadata"]["retrieval_bundle"]["coverage_matrix"]
        assert retrieve_step["metadata"]["evidence_packet"]["coverage_matrix"]

        argument_graph = client.get(
            f"/api/biomed/answer-runs/{audited_run_id}/argument-graph"
        )
        assert argument_graph.status_code == 200
        argument_payload = argument_graph.json()
        assert argument_payload["status"] == "ok"
        assert argument_payload["advisory_only"] is True
        assert argument_payload["nodes"]
        assert argument_payload["edges"]
        assert argument_payload["claim_summaries"]
        assert any(
            edge["edge_type"] in {"supports", "limits"}
            for edge in argument_payload["edges"]
        )

        math_signals = client.get(
            f"/api/biomed/answer-runs/{audited_run_id}/math-signals"
        )
        assert math_signals.status_code == 200
        math_payload = math_signals.json()
        assert math_payload["status"] == "ok"
        assert math_payload["advisory_only"] is True
        assert math_payload["answer_uncertainty_bucket"] in {"low", "medium", "high"}
        assert math_payload["recommendation"] in {
            "answer",
            "soften",
            "retrieve_more",
            "expert_review",
        }
        assert math_payload["claim_uncertainty"]
        assert math_payload["claim_uncertainty"][0]["reason_factors"]
        assert math_payload["coverage_diversity"]["evidence_count"] >= 1
        assert 0 <= math_payload["coverage_diversity"]["diversity_score"] <= 1
        assert math_payload["step_telemetry"]["advisory_only"] is True
        assert math_payload["argument_graph"]["nodes"]

        multi_pass = client.post(
            "/api/biomed/retrieval/multi-pass",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_results": 5,
                "max_queries": 6,
                "use_llm_planner": False,
                "execute_support_refute": True,
            },
        )
        assert multi_pass.status_code == 200
        multi_payload = multi_pass.json()
        assert multi_payload["ok"] is True
        assert multi_payload["result"]["item_count"] >= 1
        assert multi_payload["result"]["retrieval_bundle"]["executed_multi_query"] is True
        assert multi_payload["result"]["memory_trace"]["memory_as_evidence"] is False
        assert multi_payload["trace"]["step_telemetry"]["advisory_only"] is True
        multi_retrieval_id = multi_payload["ids"]["retrieval_id"]

        budget_blocked = client.post(
            "/api/biomed/retrieval/multi-pass",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
                "max_results": 5,
                "max_queries": 1,
                "execute_support_refute": True,
            },
        )
        assert budget_blocked.status_code == 200
        assert budget_blocked.json()["error_code"] == "budget_exceeded"

        clinical_blocked = client.post(
            "/api/biomed/retrieval/multi-pass",
            json={
                "question": "What dose should my mother take for Alzheimer disease?",
                "source": "mock",
            },
        )
        assert clinical_blocked.status_code == 200
        clinical_payload = clinical_blocked.json()
        assert clinical_payload["ok"] is False
        assert clinical_payload["error_code"] == "clinical_boundary"
        assert clinical_payload["trace"]["memory_used"] is False

        batch = client.post(
            "/api/biomed/evidence/extract-batch",
            json={
                "retrieval_id": multi_retrieval_id,
                "source": "mock",
                "research_question": "microglial activation and Alzheimer's progression",
                "max_papers": 10,
                "max_evidence_items": 50,
            },
        )
        assert batch.status_code == 200
        batch_payload = batch.json()
        assert batch_payload["ok"] is True
        assert batch_payload["result"]["evidence_count"] >= 1
        assert batch_payload["result"]["extraction_mode_counts"]

        coverage = client.post(
            "/api/biomed/evidence/coverage-gaps",
            json={"run_id": audited_run_id, "max_gap_queries": 2},
        )
        assert coverage.status_code == 200
        coverage_payload = coverage.json()
        assert coverage_payload["ok"] is True
        assert coverage_payload["result"]["coverage_matrix"]
        assert coverage_payload["result"]["bandit_advisory"]["advisory_only"] is True
        assert coverage_payload["result"]["bandit_advisory"]["action"] in {
            "stop",
            "broaden_query",
            "narrow_query",
            "search_support",
            "search_refute",
            "search_mechanism",
            "search_limitation",
            "switch_to_pubmed_if_allowed",
            "manual_review",
        }
        assert (
            coverage_payload["result"]["bandit_advisory"]["based_on"][
                "autonomous_runtime_control"
            ]
            is False
        )
        assert coverage_payload["trace"]["step_telemetry"]["advisory_only"] is True

        packet = client.post(
            "/api/biomed/evidence/packet",
            json={
                "run_id": audited_run_id,
                "max_evidence_items": 2,
                "selection_strategy": "submodular_greedy",
            },
        )
        assert packet.status_code == 200
        packet_payload = packet.json()
        assert packet_payload["ok"] is True
        assert packet_payload["result"]["evidence_packet"]["packet_id"]
        assert packet_payload["result"]["selection"]["token_estimate"] > 0
        selection = packet_payload["result"]["selection"]
        assert len(selection["selected_evidence_ids"]) <= 2
        assert selection["trace"]["hard_cap_enforced"] is True
        assert selection["trace"]["effective_max_items"] <= 2
        assert (
            selection["coverage_contribution"]["protected_evidence_selected_count"]
            <= selection["coverage_contribution"]["protected_evidence_input_count"]
        )
        assert packet_payload["result"]["selection"]["selected"][0]["token_estimate"] > 0
        assert packet_payload["result"]["selection"]["selected"][0][
            "coverage_contribution"
        ]
        assert packet_payload["result"]["memory_trace"]["memory_as_evidence"] is False

        persisted_packet = client.get(
            f"/api/biomed/answer-runs/{audited_run_id}/evidence-packet"
        )
        assert persisted_packet.status_code == 200
        persisted_payload = persisted_packet.json()
        assert persisted_payload["ok"] is True
        assert persisted_payload["result"]["availability"] == "persisted"
        assert (
            persisted_payload["result"]["evidence_packet"]["packet_id"]
            == packet_payload["result"]["evidence_packet"]["packet_id"]
        )

        export_disabled = client.post(
            "/api/biomed/export/obsidian/evidence-packet",
            json={
                "run_id": audited_run_id,
                "export_dir": str(tmp_path / "obsidian"),
                "enabled": False,
            },
        )
        assert export_disabled.status_code == 200
        assert export_disabled.json()["error_code"] == "export_path_blocked"

        export_enabled = client.post(
            "/api/biomed/export/obsidian/evidence-packet",
            json={
                "run_id": audited_run_id,
                "export_dir": str(tmp_path / "obsidian"),
                "enabled": True,
            },
        )
        assert export_enabled.status_code == 200
        export_payload = export_enabled.json()
        assert export_payload["ok"] is True
        assert export_payload["result"]["imported_as_evidence"] is False
        assert export_payload["result"]["note_count"] == 1
        note = export_payload["result"]["notes"][0]
        note_path = Path(note["path"])
        assert note_path.exists()
        note_text = note_path.read_text(encoding="utf-8")
        assert "type: \"evidence_packet\"" in note_text
        assert "source_of_truth: \"biomed_sqlite\"" in note_text
        assert "imported_as_evidence: false" in note_text
        assert "[[answer-run:" in note_text
        assert "[[evidence-packet:" in note_text
        assert "[[paper:" in note_text

        export_again = client.post(
            "/api/biomed/export/obsidian/evidence-packet",
            json={
                "run_id": audited_run_id,
                "export_dir": str(tmp_path / "obsidian"),
                "enabled": True,
            },
        )
        assert export_again.status_code == 200
        assert (
            export_again.json()["result"]["notes"][0]["path"]
            == export_payload["result"]["notes"][0]["path"]
        )
        assert (
            export_again.json()["result"]["notes"][0]["sha256"]
            == export_payload["result"]["notes"][0]["sha256"]
        )

        project_export = client.post(
            "/api/biomed/export/obsidian/project",
            json={
                "project_id": project_id,
                "export_dir": str(tmp_path / "obsidian"),
                "enabled": True,
            },
        )
        assert project_export.status_code == 200
        assert project_export.json()["ok"] is True
        assert "[[project:" in Path(
            project_export.json()["result"]["notes"][0]["path"]
        ).read_text(encoding="utf-8")

        provenance = client.get(
            f"/api/biomed/answer-runs/{audited_run_id}/provenance"
        )
        assert provenance.status_code == 200
        provenance_payload = provenance.json()
        assert provenance_payload["ok"] is True
        graph = provenance_payload["result"]
        assert graph["schema_version"] == "biomed-provenance-v1"
        entity_types = {item["type"] for item in graph["entities"]}
        assert {
            "answer",
            "retrieval_manifest",
            "paper",
            "evidence_item",
            "evidence_packet",
            "citation_audit",
            "logic_audit",
            "revision",
        }.issubset(entity_types)
        activity_types = {item["type"] for item in graph["activities"]}
        assert {"classify", "plan", "search", "extract", "audit", "revise"}.issubset(
            activity_types
        )
        agent_types = {item["type"] for item in graph["agents"]}
        assert {"deterministic_service", "plugin_tool"}.issubset(agent_types)
        relation_types = {item["type"] for item in graph["relations"]}
        assert {"used", "generated", "wasDerivedFrom", "wasAssociatedWith"}.issubset(
            relation_types
        )
        assert graph["redactions"]
        attribute_payloads = [
            item.get("attributes", {})
            for group_name in ("entities", "activities", "agents", "relations")
            for item in graph[group_name]
        ]
        assert all("llm_raw_response" not in attrs for attrs in attribute_payloads)
        assert all("api_key" not in attrs for attrs in attribute_payloads)

        missing_provenance = client.get(
            "/api/biomed/answer-runs/unknown-run/provenance"
        )
        assert missing_provenance.status_code == 200
        assert missing_provenance.json()["error_code"] == "unknown_run_id"

        clinical_audited = client.post(
            "/api/biomed/answer/audited",
            json={
                "question": "What dose should my mother take for Alzheimer disease?",
                "source": "mock",
                "use_llm_claim_logic": True,
                "export_logic_facts": True,
            },
        )
        assert clinical_audited.status_code == 200
        clinical_audited_payload = clinical_audited.json()
        clinical_run_id = clinical_audited_payload["answer_result"]["run_id"]
        assert clinical_audited_payload["final_action"] == "refuse"
        assert clinical_audited_payload["answer_result"]["citations"] == []
        assert clinical_audited_payload["answer_result"]["evidence_summary"] == []

        clinical_math = client.get(
            f"/api/biomed/answer-runs/{clinical_run_id}/math-signals"
        )
        assert clinical_math.status_code == 200
        clinical_math_payload = clinical_math.json()
        assert clinical_math_payload["status"] == "not_applicable"
        assert clinical_math_payload["advisory_only"] is True
        assert clinical_math_payload["argument_graph"]["status"] == "not_applicable"

        clinical_graph = client.get(
            f"/api/biomed/answer-runs/{clinical_run_id}/evidence-graph",
            params={"validate": True},
        )
        assert clinical_graph.status_code == 200
        clinical_graph_payload = clinical_graph.json()
        assert clinical_graph_payload["validation"]["ok"] is True
        assert {node["type"] for node in clinical_graph_payload["nodes"]} == {
            "AnswerRun"
        }
        assert clinical_graph_payload["edges"] == []
        clinical_review = client.get(
            f"/api/biomed/answer-runs/{clinical_run_id}/evidence-review",
        )
        assert clinical_review.status_code == 200
        clinical_review_payload = clinical_review.json()
        assert clinical_review_payload["snapshot"]["status"] == "persisted"
        assert clinical_review_payload["summary"]["clinical_refusal"] is True
        assert clinical_review_payload["summary"]["total_claims"] == 0
        assert clinical_review_payload["claims"] == []


def test_biomed_api_watch_crud_check_events(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        created = client.post(
            "/api/biomed/watch",
            json={
                "topic": "spatial transcriptomics in tumor microenvironment",
                "include_keywords": ["spatial transcriptomics", "tumor microenvironment"],
                "preferred_methods": ["spatial transcriptomics"],
                "min_relevance_score": 0.7,
                "schedule": "daily",
            },
        )
        assert created.status_code == 200
        watch_id = created.json()["watch_id"]

        checked = client.post(f"/api/biomed/watch/{watch_id}/check")
        assert checked.status_code == 200
        checked_payload = checked.json()
        assert checked_payload["decisions"]
        assert checked_payload["retrieval_manifest"]["retrieval_id"]
        assert checked_payload["snapshot"]["new_paper_ids"]

        events = client.get(f"/api/biomed/watch/{watch_id}/events")
        assert events.status_code == 200
        assert events.json()["total"] >= 1
        assert events.json()["items"][0]["retrieval_id"]

        patched = client.patch(
            f"/api/biomed/watch/{watch_id}",
            json={"enabled": False, "schedule": "manual"},
        )
        assert patched.status_code == 200
        assert patched.json()["enabled"] is False

        watch_export = client.post(
            "/api/biomed/export/obsidian/watch",
            json={
                "watch_id": watch_id,
                "export_dir": str(tmp_path / "obsidian"),
                "enabled": True,
            },
        )
        assert watch_export.status_code == 200
        assert watch_export.json()["ok"] is True
        watch_note = Path(watch_export.json()["result"]["notes"][0]["path"])
        assert watch_note.exists()
        assert "[[watch:" in watch_note.read_text(encoding="utf-8")

        deleted = client.delete(f"/api/biomed/watch/{watch_id}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True


def test_biomed_workflow_templates_api(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        templates = client.get("/api/biomed/workflow/templates")
        assert templates.status_code == 200
        template_payload = templates.json()
        template_ids = {item["template_id"] for item in template_payload["items"]}
        assert "biomed-template-mock-ci" in template_ids
        assert "biomed-template-pubmed-live-research" in template_ids
        assert template_payload["total"] >= 4

        pubmed_blocked = client.post(
            "/api/biomed/workflow/templates/biomed-template-pubmed-live-research/run",
            json={
                "question": "What evidence links microglia to Alzheimer disease?",
                "allow_live_pubmed": False,
            },
        )
        assert pubmed_blocked.status_code == 200
        assert pubmed_blocked.json()["ok"] is False
        assert pubmed_blocked.json()["error_code"] == "source_policy_blocked"

        clinical_blocked = client.post(
            "/api/biomed/workflow/templates/biomed-template-mock-ci/run",
            json={"question": "What dose should my mother take for Alzheimer disease?"},
        )
        assert clinical_blocked.status_code == 200
        clinical_payload = clinical_blocked.json()
        assert clinical_payload["ok"] is False
        assert clinical_payload["error_code"] == "clinical_boundary"
        assert clinical_payload["errors"][0]["detail"]["retrieval_executed"] is False

        saved = client.post(
            "/api/biomed/workflow/templates",
            json={
                "name": "Custom Mock Audit",
                "source": "mock",
                "max_papers": 4,
                "execute_support_refute": True,
                "use_llm_claim_logic": True,
                "export_logic_facts": True,
                "required_skills": [
                    "biomed-evidence-review",
                    "biomed-clinical-boundary",
                ],
            },
        )
        assert saved.status_code == 200
        saved_payload = saved.json()
        assert saved_payload["template_id"] == "biomed-template-custom-mock-audit"
        assert saved_payload["builtin"] is False

        run = client.post(
            f"/api/biomed/workflow/templates/{saved_payload['template_id']}/run",
            json={
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
            },
        )
        assert run.status_code == 200
        run_payload = run.json()
        assert run_payload["ok"] is True
        assert run_payload["ids"]["run_id"]
        assert run_payload["result"]["template"]["required_skills"] == [
            "biomed-evidence-review",
            "biomed-clinical-boundary",
        ]
        audited = run_payload["result"]["audited_answer"]
        assert audited["answer_result"]["citations"]
        assert audited["answer_result"]["evidence_packet"]["packet_id"]
        assert run_payload["result"]["provenance"]["ok"] is True

        deleted = client.delete(
            f"/api/biomed/workflow/templates/{saved_payload['template_id']}"
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True


def test_biomed_api_validation_error(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/biomed/answer", json={"source": "mock"})
        assert response.status_code == 422
