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
