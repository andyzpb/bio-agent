from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.plugins.decorators import _derive_params_schema
from plugins.biomed_evidence.literature_client import parse_pubmed_articles
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    EvidenceExtractionRequest,
    SearchBiomedicalLiteratureRequest,
    WatchTopicCreateRequest,
)
from plugins.biomed_evidence.service import BiomedEvidenceService


@pytest.mark.asyncio
async def test_mock_answer_is_citation_grounded(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question=(
                    "What recent evidence links microglial activation to "
                    "Alzheimer's disease progression?"
                )
            )
        )
    finally:
        await service.aclose()

    assert result.not_medical_advice is True
    assert result.citations
    assert result.evidence_summary
    assert "research support only" in result.disclaimer
    assert any(item.evidence_direction == "supports" for item in result.evidence_summary)


@pytest.mark.asyncio
async def test_clinical_question_is_refused(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="My patient has memory loss. What treatment should I prescribe?"
            )
        )
    finally:
        await service.aclose()

    assert not result.citations
    assert "cannot help diagnose" in result.answer.lower()
    assert result.uncertainty_level == "high"


@pytest.mark.asyncio
async def test_mock_search_fetch_extract_and_storage_idempotency(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        items = await service.search(
            SearchBiomedicalLiteratureRequest(
                query="microglial activation Alzheimer's disease",
                max_results=3,
            )
        )
        assert items
        paper = await service.fetch(
            service_module_fetch_request(items[0].paper_id)
        )
        assert paper is not None
        request = EvidenceExtractionRequest(
            paper=paper,
            research_question="microglial activation Alzheimer's disease",
        )
        first = service.extract_evidence(request)
        second = service.extract_evidence(request)
        rows, total = service.list_evidence(paper_id=paper.paper_id)
    finally:
        await service.aclose()

    assert first.evidence
    assert second.evidence
    assert total == len(first.evidence)
    assert rows[0]["paper_id"] == paper.paper_id


def service_module_fetch_request(paper_id: str):
    from plugins.biomed_evidence.schemas import FetchBiomedicalPaperRequest

    return FetchBiomedicalPaperRequest(paper_id=paper_id, source="mock")


def test_empty_abstract_returns_reason(tmp_path: Path) -> None:
    from plugins.biomed_evidence.schemas import BiomedicalPaper

    service = BiomedEvidenceService(tmp_path)
    try:
        result = service.extract_evidence(
            EvidenceExtractionRequest(
                paper=BiomedicalPaper(
                    paper_id="NO-ABSTRACT",
                    source="mock",
                    title="No abstract paper",
                )
            )
        )
    finally:
        service.close()

    assert result.evidence == []
    assert result.reason and "not fabricated" in result.reason


def test_pubmed_xml_parser_extracts_metadata() -> None:
    xml = """
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>12345</PMID>
          <Article>
            <Journal>
              <JournalIssue><PubDate><Year>2025</Year><Month>Jan</Month><Day>02</Day></PubDate></JournalIssue>
              <Title>Journal of Mock Biology</Title>
            </Journal>
            <ArticleTitle>Microglia and disease progression</ArticleTitle>
            <Abstract><AbstractText>Microglia were associated with disease stage.</AbstractText></Abstract>
            <AuthorList><Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author></AuthorList>
          </Article>
          <MeshHeadingList><MeshHeading><DescriptorName>Microglia</DescriptorName></MeshHeading></MeshHeadingList>
          <KeywordList><Keyword>neuroinflammation</Keyword></KeywordList>
        </MedlineCitation>
        <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/mock</ArticleId></ArticleIdList></PubmedData>
      </PubmedArticle>
    </PubmedArticleSet>
    """
    papers = parse_pubmed_articles(xml)
    assert len(papers) == 1
    assert papers[0].paper_id == "12345"
    assert papers[0].publication_date == "2025-01-02"
    assert papers[0].doi == "10.1/mock"
    assert papers[0].authors == ["Ada Lovelace"]


@pytest.mark.asyncio
async def test_watch_check_scores_and_dedupes_decisions(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        watch = service.create_watch(
            WatchTopicCreateRequest(
                topic="spatial transcriptomics in tumor microenvironment",
                include_keywords=["spatial transcriptomics", "tumor microenvironment"],
                preferred_methods=["spatial transcriptomics"],
                min_relevance_score=0.7,
            )
        )
        first = await service.check_watch(watch.watch_id)
        second = await service.check_watch(watch.watch_id)
        decisions, total = service.list_watch_decisions(watch_id=watch.watch_id)
    finally:
        await service.aclose()

    assert first is not None
    assert first.decisions
    assert second is not None
    assert second.decisions == []
    assert total == len(decisions)
    assert any(item.decision == "push" for item in decisions)


def test_tool_schema_derives_literal_and_list_types() -> None:
    from typing import Literal

    async def sample(self, event, source: Literal["pubmed", "mock"], tags: list[str], enabled: bool = True):
        return ""

    schema = _derive_params_schema(sample)
    props = schema["properties"]
    assert props["source"]["enum"] == ["pubmed", "mock"]
    assert props["source"]["type"] == "string"
    assert props["tags"]["type"] == "array"
    assert props["tags"]["items"]["type"] == "string"
    assert props["enabled"]["type"] == "boolean"


@pytest.mark.asyncio
async def test_biomed_plugin_registers_tools(tmp_path: Path) -> None:
    from agent.plugins.manager import PluginManager
    from agent.plugins.registry import plugin_registry
    from agent.tools.registry import ToolRegistry
    from bus.event_bus import EventBus

    plugin_registry._handlers._handlers.clear()
    plugin_registry._classes.clear()
    plugin_registry._instances.clear()
    bus = EventBus()
    tools = ToolRegistry()
    manager = PluginManager(
        plugin_dirs=[Path(__file__).parents[1] / "plugins"],
        event_bus=bus,
        tool_registry=tools,
        workspace=tmp_path,
    )
    try:
        await manager.load_all()
        assert tools.has_tool("search_biomedical_literature")
        assert tools.has_tool("answer_with_evidence")
        raw = await tools.execute(
            "answer_with_evidence",
            {
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
            },
        )
        payload = json.loads(str(raw))
        assert payload["citations"]
    finally:
        await manager.terminate_all()
        await bus.aclose()
        plugin_registry._handlers._handlers.clear()
        plugin_registry._classes.clear()
        plugin_registry._instances.clear()
