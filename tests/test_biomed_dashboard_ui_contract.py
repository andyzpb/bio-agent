from pathlib import Path


def test_runs_workspace_exposes_core_run_detail_tabs() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()

    assert '["literature", "Literature Set"]' in source
    assert '["fulltext", "Full Text"]' in source
    assert '["pilot", "Pilot Report"]' in source


def test_pubmed_audited_planner_uses_assisted_llm_chain() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()

    assert 'const useAssistedPubmedAudit = audited && source === "pubmed" && usePlanner;' in source
    assert "use_llm_extractor: useAssistedPubmedAudit ||" in source
    assert "use_llm_synthesis: useAssistedPubmedAudit ||" in source
    assert "use_llm_revision: useAssistedPubmedAudit ||" in source
    assert "use_llm_claim_logic: useAssistedPubmedAudit ||" in source


def test_full_text_enhance_button_requests_open_provider() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()

    assert "use_open_provider: true" in source
    assert "paper.provider_status" in source
    assert "paper.source_locator" in source


def test_full_text_reanalysis_button_calls_run_endpoint() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()

    assert "Re-analyze with Full Text" in source
    assert "full-text-reanalysis" in source
    assert "fullTextReanalysis" in source
    assert "hasFullTextEvidence" in source
    assert "paper.evidence_ids.length" in source
