from pathlib import Path


def test_runs_workspace_exposes_answer_first_inspector_modes() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()

    assert '["overview", "Summary"]' in source
    assert '["evidence", "Evidence"]' in source
    assert '["fulltext", "Full Text"]' in source
    assert '["review", "Review"]' in source
    assert '["advanced", "Advanced"]' in source
    assert '["logic", "Logic"]' not in source
    assert '["raw", "Raw"]' not in source


def test_runs_workspace_default_summary_has_clear_visual_priorities() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()
    styles = Path("plugins/biomed_evidence/dashboard_panel.css").read_text()

    assert "Audit checks" in source
    assert "Evidence conclusion:" in source
    assert "Evidence that matters" in source
    assert "Main limitations" in source
    assert "renderTrustSignals" in source
    assert "renderEvidenceThatMatters" in source
    assert "biomed-answer-trust-layout" in styles
    assert "biomed-trust-panel" in styles
    assert "biomed-stat-strip" in styles
    assert "biomed-important-evidence-list" in styles


def test_contradicting_evidence_status_is_red() -> None:
    styles = Path("plugins/biomed_evidence/dashboard_panel.css").read_text()

    assert ".biomed-important-evidence-list span.is-contradicting" in styles
    assert "color: #991b1b" in styles


def test_runs_workspace_composer_collapses_and_inspector_resizes() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()
    styles = Path("plugins/biomed_evidence/dashboard_panel.css").read_text()

    assert '<details class="biomed-composer" open>' in source
    assert '<summary class="biomed-composer-head">' in source
    assert "biomed-composer-body" in source
    assert "biomed-inspector-resizer" in source
    assert "bindInspectorResize" in source
    assert "--biomed-inspector-width" in styles
    assert "grid-template-columns: minmax(0, 1fr) var(--biomed-inspector-width" in styles


def test_run_result_label_prefers_post_revision_audit_action() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()

    assert "function answerStatusLabel(" in source
    assert 'revision.revision_action === "revise"' in source
    assert "auditAcceptsDisplayedClaims" in source
    assert "Answer accepted by audit" in source
    assert "Answer accepted with caveats" not in source
    assert "Evidence conclusion:" in source
    assert "Audit action" in source
    assert "final_action: activeTrace.latest_citation_audit.recommended_action || activeTrace.revision.revision_action || \"pass\"" in source


def test_run_summary_uses_direct_answer_evidence_for_conclusion() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()

    assert "direct_answer_evidence_ids" in source
    assert "directAnswerEvidenceRows" in source
    assert "function evidenceConclusionLabel(answer: AnswerResult): string" in source
    assert "const rows = directAnswerEvidenceRows(answer);" in source


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


def test_run_summary_distinguishes_retrieved_extracted_and_used_counts() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()

    assert "retrievedPaperCount" in source
    assert "usedCitationPaperCount" in source
    assert "Retrieved papers" in source
    assert "Extracted evidence" in source
    assert "Used citations" in source
    assert "Full-text coverage" in source
    assert "fullTextReanalysisCoverageWarning" in source


def test_full_text_results_are_cached_and_update_summary_answer() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()

    assert "fullTextRunCache" in source
    assert "answerSourceScopeLabel" in source
    assert "abstract-derived" in source
    assert "full-text-derived" in source
    assert "syncFullTextCacheToContext" in source
    assert "rememberFullTextContext" in source
    assert 'loadWorkspaceTrace(`${runId}-fulltext`)' in source
    assert "context.answer = result.answer_result" in source
    assert "renderWorkspaceRunSummary(context)" in source
    assert 'pill(item.source_scope || "abstract")' in source


def test_full_text_warning_text_wraps_and_workbench_rail_collapses() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()
    styles = Path("plugins/biomed_evidence/dashboard_panel.css").read_text()
    nav_body = source[source.index("renderNavBody"):source.index("renderMain")]
    ask_workspace = source[source.index("function renderAskWorkspace"):source.index("container.querySelector<HTMLSelectElement>(\"#biomed-template-select\")")]

    assert "biomed-breakable" in source
    assert "biomed-agent-rail-toggle" in nav_body
    assert "biomed-agent-rail-toggle" not in ask_workspace
    assert "biomed-rail-collapsed" in source
    assert ".biomed-breakable" in styles
    assert ".workspace.plugin-workbench-mode.biomed-rail-collapsed:has(.biomed-plugin-nav)" in styles


def test_biomed_pills_have_high_coverage_tooltips() -> None:
    source = Path("plugins/biomed_evidence/dashboard_panel.ts").read_text()
    styles = Path("plugins/biomed_evidence/dashboard_panel.css").read_text()

    assert "TAG_HELP" in source
    assert "function tagHelp" in source
    for tag in [
        "abstract",
        "full_text",
        "fallback",
        "revise",
        "overclaimed",
        "modality_mismatch",
        "pubmed",
        "submodular_greedy",
    ]:
        assert f'"{tag}"' in source
    for dynamic_prefix in [
        'value.match(/^claim citation support ',
        'value.match(/^citation alignment ',
        'value.match(/^\\d+ evidence$/)',
    ]:
        assert dynamic_prefix in source
    assert "data-biomed-tooltip" in source
    assert "aria-label" in source
    assert ".biomed-pill[data-biomed-tooltip]::after" in styles
