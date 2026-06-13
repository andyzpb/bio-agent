from __future__ import annotations

from collections.abc import Iterable

from plugins.biomed_evidence.errors import release_error
from plugins.biomed_evidence.schemas import (
    ReleaseToolEnvelope,
    ReleaseToolMetadata,
    ReleaseToolRiskLevel,
    ReleaseToolSideEffect,
    ReleaseToolSourcePolicy,
)

_RELEASE_TOOL_CONTRACTS: dict[str, ReleaseToolMetadata] = {}


def register_release_tool_contract(
    *,
    tool_name: str,
    risk_level: ReleaseToolRiskLevel = "read_only",
    source_policy: ReleaseToolSourcePolicy = "no_source",
    side_effects: Iterable[ReleaseToolSideEffect] = (),
    requires_confirmation: bool = False,
    max_runtime_seconds: int = 30,
) -> ReleaseToolMetadata:
    metadata = ReleaseToolMetadata(
        tool_name=tool_name,
        risk_level=risk_level,
        source_policy=source_policy,
        side_effects=list(side_effects),
        requires_confirmation=requires_confirmation,
        max_runtime_seconds=max_runtime_seconds,
    )
    _RELEASE_TOOL_CONTRACTS[tool_name] = metadata
    return metadata


def get_release_tool_metadata(tool_name: str) -> ReleaseToolMetadata:
    metadata = _RELEASE_TOOL_CONTRACTS.get(tool_name)
    if metadata is not None:
        return metadata
    return ReleaseToolMetadata(tool_name=tool_name)


def list_release_tool_contracts() -> list[ReleaseToolMetadata]:
    return [
        _RELEASE_TOOL_CONTRACTS[key]
        for key in sorted(_RELEASE_TOOL_CONTRACTS.keys())
    ]


def release_source_policy_error(
    *,
    tool_name: str,
    source: str | None,
    allow_live_pubmed_tools: bool,
) -> ReleaseToolEnvelope | None:
    metadata = get_release_tool_metadata(tool_name)
    if metadata.source_policy == "no_source":
        return None
    normalized = (source or "mock").strip().lower()
    if metadata.source_policy == "mock_only" and normalized != "mock":
        return release_error(
            tool_name=tool_name,
            code="source_policy_blocked",
            message=f"{tool_name} only allows source=mock in Release 1.0.",
            detail={"source": normalized, "source_policy": metadata.source_policy},
            metadata=metadata,
        )
    if (
        metadata.source_policy == "live_opt_in"
        and normalized == "pubmed"
        and not allow_live_pubmed_tools
    ):
        return release_error(
            tool_name=tool_name,
            code="source_policy_blocked",
            message=(
                "live PubMed tool calls are disabled by plugin config; use "
                "source=mock or enable allow_live_pubmed_tools."
            ),
            detail={"source": normalized, "source_policy": metadata.source_policy},
            metadata=metadata,
        )
    return None


def _register_defaults() -> None:
    for tool_name in (
        "plan_biomedical_search",
        "check_literature_access",
        "search_literature",
        "search_biomedical_literature",
        "fetch_biomedical_paper",
        "answer_with_evidence",
        "answer_with_audit",
        "find_conflicting_evidence",
    ):
        register_release_tool_contract(
            tool_name=tool_name,
            risk_level="external_network",
            source_policy="live_opt_in",
            side_effects=["read_storage", "write_storage", "external_network"],
            max_runtime_seconds=90,
        )

    for tool_name in (
        "extract_evidence",
        "validate_citation_support",
        "audit_biomedical_answer",
        "get_evidence_graph",
        "get_evidence_card",
        "validate_evidence_graph",
        "find_evidence_path",
        "export_evidence_graph_json",
        "get_run_evidence_review",
        "export_evidence_report",
        "list_biomed_projects",
        "list_project_paper_decisions",
        "list_project_evidence",
        "list_project_review_queue",
        "list_research_watch_topics",
        "list_biomed_workflow_templates",
    ):
        register_release_tool_contract(
            tool_name=tool_name,
            risk_level="read_only",
            side_effects=["read_storage"],
        )

    for tool_name in (
        "create_biomed_project",
        "update_biomed_project",
        "record_project_paper_decision",
        "save_project_paper",
        "reject_project_paper",
        "record_project_claim",
        "save_project_claim",
        "generate_project_evidence_brief",
        "watch_research_topic",
        "update_research_watch_topic",
        "delete_research_watch_topic",
        "save_biomed_workflow_template",
        "delete_biomed_workflow_template",
    ):
        register_release_tool_contract(
            tool_name=tool_name,
            risk_level="writes_storage",
            side_effects=["read_storage", "write_storage"],
        )

    for tool_name in (
        "run_multi_pass_literature_search",
        "extract_evidence_batch",
        "analyze_coverage_gaps",
        "build_evidence_packet",
        "get_answer_trace",
        "get_evidence_packet",
        "export_provenance_graph",
        "run_saved_tool_chain_template",
    ):
        register_release_tool_contract(
            tool_name=tool_name,
            risk_level=(
                "external_network"
                if tool_name
                in {"run_multi_pass_literature_search", "run_saved_tool_chain_template"}
                else "read_only"
            ),
            source_policy=(
                "live_opt_in"
                if tool_name
                in {
                    "run_multi_pass_literature_search",
                    "extract_evidence_batch",
                    "run_saved_tool_chain_template",
                }
                else "no_source"
            ),
            side_effects=(
                ["read_storage", "write_storage", "external_network", "llm_call"]
                if tool_name == "run_saved_tool_chain_template"
                else ["read_storage", "write_storage", "external_network"]
                if tool_name == "run_multi_pass_literature_search"
                else ["read_storage"]
            ),
            max_runtime_seconds=90,
        )

    for tool_name in (
        "export_evidence_packet_to_obsidian",
        "export_project_to_obsidian",
        "export_research_watch_to_obsidian",
    ):
        register_release_tool_contract(
            tool_name=tool_name,
            risk_level="exports_files",
            side_effects=["read_storage", "write_files"],
            requires_confirmation=True,
        )


_register_defaults()
