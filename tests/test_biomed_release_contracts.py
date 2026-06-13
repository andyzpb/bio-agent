from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.lifecycle.types import PreToolCtx
from agent.plugins.config import PluginConfig
from agent.plugins.context import PluginContext, PluginKVStore
from bus.event_bus import EventBus
from plugins.biomed_evidence.dashboard import register
from plugins.biomed_evidence.errors import release_error, release_ok
from plugins.biomed_evidence.obsidian_export import export_packet_note
from plugins.biomed_evidence.plugin import BiomedEvidencePlugin
from plugins.biomed_evidence.schemas import (
    AgentTraceStep,
    EvidenceItem,
    EvidencePacketSummary,
    ReleaseToolMetadata,
)
from plugins.biomed_evidence.service import _select_evidence_for_packet
from plugins.biomed_evidence.telemetry_service import build_step_telemetry
from plugins.biomed_evidence.tool_contracts import (
    get_release_tool_metadata,
    list_release_tool_contracts,
    release_source_policy_error,
)


def test_release_tool_envelope_success_and_error_shapes() -> None:
    metadata = ReleaseToolMetadata(
        tool_name="search_literature",
        risk_level="external_network",
        source_policy="live_opt_in",
        side_effects=["read_storage", "write_storage", "external_network"],
    )
    ok = release_ok(
        tool_name="search_literature",
        result={"item_count": 1},
        ids={"retrieval_id": "retrieval-1"},
        metadata=metadata,
    )
    ok_payload = ok.model_dump(mode="json")
    assert ok_payload["ok"] is True
    assert ok_payload["errors"] == []
    assert ok_payload["metadata"]["source_policy"] == "live_opt_in"
    assert "external_network" in ok_payload["metadata"]["side_effects"]

    blocked = release_error(
        tool_name="search_literature",
        code="source_policy_blocked",
        message="Live PubMed is disabled.",
        detail={"source": "pubmed"},
        metadata=metadata,
    )
    blocked_payload = blocked.model_dump(mode="json")
    assert blocked_payload["ok"] is False
    assert blocked_payload["error_code"] == "source_policy_blocked"
    assert blocked_payload["recoverable"] is True
    assert "use_mock" in blocked_payload["next_allowed_actions"]
    assert blocked_payload["errors"][0]["detail"]["source"] == "pubmed"

    clinical = release_error(
        tool_name="answer_with_audit",
        code="clinical_boundary",
        message="Clinical request blocked.",
    )
    assert clinical.recoverable is False
    assert clinical.errors[0].recoverable is False


def test_release_tool_contract_registry_and_source_policy() -> None:
    contracts = {item.tool_name: item for item in list_release_tool_contracts()}
    assert "search_literature" in contracts
    assert "run_multi_pass_literature_search" in contracts
    assert "export_evidence_packet_to_obsidian" in contracts
    assert "run_saved_tool_chain_template" in contracts
    assert "list_biomed_workflow_templates" in contracts
    assert "get_evidence_card" in contracts
    assert "validate_evidence_graph" in contracts
    assert "find_evidence_path" in contracts
    assert "export_evidence_graph_json" in contracts
    assert "get_run_evidence_review" in contracts

    search_contract = get_release_tool_metadata("search_literature")
    assert search_contract.risk_level == "external_network"
    assert search_contract.source_policy == "live_opt_in"
    assert search_contract.output_schema_version == "release-tool-envelope-v1"
    graph_export_contract = get_release_tool_metadata("export_evidence_graph_json")
    assert graph_export_contract.risk_level == "read_only"
    assert graph_export_contract.side_effects == ["read_storage"]
    assert graph_export_contract.requires_confirmation is False
    review_contract = get_release_tool_metadata("get_run_evidence_review")
    assert review_contract.risk_level == "read_only"
    assert review_contract.side_effects == ["read_storage"]

    blocked = release_source_policy_error(
        tool_name="search_literature",
        source="pubmed",
        allow_live_pubmed_tools=False,
    )
    assert blocked is not None
    assert blocked.error_code == "source_policy_blocked"
    assert blocked.metadata is not None
    assert blocked.metadata.tool_name == "search_literature"

    allowed_mock = release_source_policy_error(
        tool_name="search_literature",
        source="mock",
        allow_live_pubmed_tools=False,
    )
    assert allowed_mock is None


def test_release_config_schema_exposes_phase_b_knobs() -> None:
    schema_path = (
        Path(__file__).parents[1] / "plugins" / "biomed_evidence" / "_conf_schema.json"
    )
    config_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    for key in (
        "max_tool_steps",
        "max_retrieval_queries",
        "max_followup_queries",
        "max_llm_calls",
        "max_wall_clock_seconds",
        "max_obsidian_export_files",
        "obsidian_export_dir",
        "enable_obsidian_export",
        "enable_provenance_export",
        "enable_step_telemetry",
        "enable_bandit_advisory",
    ):
        assert key in config_schema


def test_release_tool_contracts_api(tmp_path: Path) -> None:
    app = FastAPI()
    register(app, Path(__file__).parents[1] / "plugins" / "biomed_evidence", tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/biomed/release/tool-contracts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "release-tool-envelope-v1"
    assert payload["tool_count"] >= 1
    tools = {item["tool_name"]: item for item in payload["tools"]}
    assert tools["run_multi_pass_literature_search"]["source_policy"] == "live_opt_in"
    assert tools["export_evidence_packet_to_obsidian"]["requires_confirmation"] is True
    assert tools["export_evidence_graph_json"]["risk_level"] == "read_only"
    assert tools["export_evidence_graph_json"]["side_effects"] == ["read_storage"]
    assert tools["get_run_evidence_review"]["risk_level"] == "read_only"


def test_step_telemetry_summary_is_advisory_only() -> None:
    created_at = datetime.now().isoformat()
    trace = [
        AgentTraceStep(
            step_id="step-1",
            run_id="run-1",
            step="classify",
            status="completed",
            created_at=created_at,
        ),
        AgentTraceStep(
            step_id="step-2",
            run_id="run-1",
            step="plan",
            status="completed",
            created_at=created_at,
        ),
        AgentTraceStep(
            step_id="step-3",
            run_id="run-1",
            step="retrieve",
            status="completed",
            created_at=created_at,
        ),
    ]
    telemetry = build_step_telemetry(trace, run_id="run-1")
    assert telemetry.advisory_only is True
    assert telemetry.transition_matrix["classified"]["planned"] == 1
    assert telemetry.transition_matrix["planned"]["searched"] == 1
    assert telemetry.mean_tool_step_count == 3.0


def test_obsidian_packet_export_extracts_bare_pubmed_pmids(tmp_path: Path) -> None:
    packet = EvidencePacketSummary(
        packet_id="packet-pubmed",
        question="microglia Alzheimer disease",
        source="pubmed",
        retrieval_manifest_ids=["retrieval-1"],
        paper_ids=["37774678", "pmid:29196460", "MOCK-PMID-1004"],
        evidence_ids=["ev-1"],
        supported_claims=["Microglia are implicated in Alzheimer disease."],
        conflicting_claims=[],
        limitations=[],
        stop_reason="coverage_sufficient",
        created_at=datetime.now().isoformat(),
    )

    exported = export_packet_note(
        packet=packet,
        export_dir=tmp_path,
        run_id="biomed-run-1",
    )

    note = exported.notes[0]
    assert note.frontmatter["pmid"] == ["37774678", "29196460", "1004"]
    assert "[[paper:pmid-37774678]]" in note.links
    assert "[[paper:pmid-29196460]]" in note.links
    assert "[[paper:pmid-1004]]" in note.links
    text = Path(note.path).read_text(encoding="utf-8")
    assert 'pmid: ["37774678", "29196460", "1004"]' in text


def test_packet_selector_honors_max_items_when_protected_exceeds_cap() -> None:
    evidence = [
        EvidenceItem(
            evidence_id=f"ev-{index}",
            paper_id=f"paper-{index}",
            claim=f"Claim {index}",
            finding=f"Finding {index}",
            evidence_direction="contradicts" if index == 0 else "supports",
            confidence="high",
            limitations=["protected limitation"],
            methods=["review"],
            evidence_span=f"Evidence span {index}",
        )
        for index in range(5)
    ]

    selection = _select_evidence_for_packet(
        evidence,
        max_items=2,
        strategy="submodular_greedy",
    )

    assert selection.max_items == 2
    assert len(selection.selected_evidence_ids) == 2
    assert len(selection.dropped_evidence_ids) == 3
    assert selection.trace["requested_max_items"] == 2
    assert selection.trace["effective_max_items"] == 2
    assert selection.trace["hard_cap_enforced"] is True
    assert selection.coverage_contribution["protected_evidence_input_count"] == 5
    assert selection.coverage_contribution["protected_evidence_selected_count"] == 2
    assert selection.coverage_contribution["protected_evidence_retained"] is False


async def _make_plugin(
    tmp_path: Path,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[BiomedEvidencePlugin, EventBus]:
    bus = EventBus()
    plugin = BiomedEvidencePlugin()
    plugin.context = PluginContext(
        event_bus=bus,
        tool_registry=None,
        plugin_id="biomed_evidence",
        plugin_dir=tmp_path,
        kv_store=PluginKVStore(tmp_path / ".kv.json"),
        config=PluginConfig(config or {}),
        workspace=tmp_path,
    )
    await plugin.initialize()
    return plugin, bus


@pytest.mark.asyncio
async def test_release_workflow_tools_are_guarded(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(
        tmp_path,
        config={
            "allow_live_pubmed_tools": False,
            "max_retrieval_queries": 2,
            "max_followup_queries": 1,
        },
    )
    try:
        clinical = await plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key="test",
                channel="cli",
                chat_id="local",
                tool_name="run_multi_pass_literature_search",
                arguments={
                    "question": "What dose should my mother take for Alzheimer disease?",
                    "source": "pubmed",
                },
                source="passive",
            )
        )
        assert clinical is not None
        assert clinical.decision == "deny"
        assert "clinical_boundary" in clinical.reason
        assert "source_policy_blocked" not in clinical.reason

        source_blocked = await plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key="test",
                channel="cli",
                chat_id="local",
                tool_name="run_multi_pass_literature_search",
                arguments={
                    "question": "What evidence links microglia to Alzheimer disease?",
                    "source": "pubmed",
                },
                source="passive",
            )
        )
        assert source_blocked is not None
        assert source_blocked.decision == "deny"
        assert "source_policy_blocked" in source_blocked.reason

        capped = await plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key="test",
                channel="cli",
                chat_id="local",
                tool_name="run_multi_pass_literature_search",
                arguments={
                    "question": "What evidence links microglia to Alzheimer disease?",
                    "source": "mock",
                    "max_queries": 10,
                    "max_followups": 10,
                },
                source="passive",
            )
        )
        assert capped is not None
        assert capped.updated_input is not None
        assert capped.updated_input["max_queries"] == 2
        assert capped.updated_input["max_followups"] == 1
    finally:
        await plugin.terminate()
        await bus.aclose()
