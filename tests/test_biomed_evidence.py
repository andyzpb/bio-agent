from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from agent.plugins.decorators import _derive_params_schema
from plugins.biomed_evidence.literature_client import (
    PubMedLiteratureClient,
    parse_pubmed_articles,
)
from plugins.biomed_evidence.schemas import (
    AnswerWithEvidenceRequest,
    EvidenceExtractionRequest,
    PlanBiomedicalSearchRequest,
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
    assert result.retrieval_id
    assert result.retrieval_manifest is not None
    assert result.retrieval_manifest.returned_paper_ids
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
async def test_patient_specific_dose_question_is_refused(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What dose should my mother take for Alzheimer disease?"
            )
        )
    finally:
        await service.aclose()

    assert not result.citations
    assert "recommend treatment" in result.answer.lower()
    assert result.uncertainty_level == "high"


@pytest.mark.asyncio
async def test_plan_biomedical_search_builds_valid_retrieval_plan(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_results=5,
            )
        )
    finally:
        await service.aclose()

    assert result.classification.intent == "research_question"
    assert result.query_plan is not None
    assert result.query_plan.primary_query
    assert result.query_plan.support_queries
    assert result.query_plan.refute_queries
    assert result.validation.valid is True
    assert result.search_request is not None
    assert result.search_request.source == "mock"


@pytest.mark.asyncio
async def test_plan_biomedical_search_refuses_clinical_query_before_retrieval(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What dose should my mother take for Alzheimer disease?",
                source="mock",
                max_results=5,
            )
        )
    finally:
        await service.aclose()

    assert result.classification.intent == "clinical_or_patient_specific"
    assert result.classification.clinical_boundary is True
    assert result.query_plan is None
    assert result.validation.valid is False
    assert result.search_request is None


@pytest.mark.asyncio
async def test_answer_with_planner_executes_support_refute_bundle(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        result = await service.answer_with_evidence(
            AnswerWithEvidenceRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_papers=5,
                use_llm_planner=True,
                execute_support_refute=True,
            )
        )
    finally:
        await service.aclose()

    assert result.retrieval_bundle is not None
    assert result.retrieval_bundle.executed_multi_query is True
    intents = {record.intent for record in result.retrieval_bundle.records}
    assert {"primary", "support", "refute"} <= intents
    assert result.retrieval_manifest is not None
    assert result.retrieval_bundle.records[0].retrieval_id == result.retrieval_manifest.retrieval_id
    assert len(result.retrieval_bundle.deduped_paper_ids) == len(
        set(result.retrieval_bundle.deduped_paper_ids)
    )
    assert result.retrieval_bundle.duplicate_paper_ids
    assert result.evidence_summary
    assert {item.retrieval_intent for item in result.evidence_summary} <= {
        "primary",
        "support",
        "refute",
    }


@pytest.mark.asyncio
async def test_mock_search_fetch_extract_and_storage_idempotency(tmp_path: Path) -> None:
    service = BiomedEvidenceService(tmp_path)
    try:
        search_result = await service.search_with_manifest(
            SearchBiomedicalLiteratureRequest(
                query="microglial activation Alzheimer's disease",
                max_results=3,
            )
        )
        items = search_result.items
        assert items
        assert search_result.retrieval_manifest.source == "mock"
        assert search_result.retrieval_manifest.compiled_query
        assert search_result.retrieval_manifest.deduped_result_count == len(items)
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


class _FakePubMedResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakePlannerResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakePlannerProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools, model, max_tokens, tool_choice="auto", disable_thinking=False):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        return _FakePlannerResponse(
            json.dumps(
                {
                    "classification": {
                        "intent": "research_question",
                        "normalized_question": payload["question"],
                        "clinical_boundary": False,
                        "needs_clarification": False,
                        "risk_flags": [],
                        "allowed_next_step": "plan_retrieval",
                        "rationale": "fake planner classification",
                    },
                    "query_plan": {
                        "primary_query": "microglial activation Alzheimer disease progression",
                        "mesh_terms": ["Alzheimer Disease", "Microglia"],
                        "include_terms": ["neuroinflammation"],
                        "exclude_terms": ["dosage"],
                        "study_types": ["longitudinal"],
                        "species_terms": [],
                        "support_queries": ["microglial activation Alzheimer disease progression association"],
                        "refute_queries": ["microglial activation Alzheimer disease progression negative results"],
                        "max_results": 5,
                        "rationale": "fake planner query plan",
                    },
                }
            )
        )


class _FakeEchoPlannerProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools, model, max_tokens, tool_choice="auto", disable_thinking=False):
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        return _FakePlannerResponse(
            json.dumps(
                {
                    "deterministic_classification": payload["deterministic_classification"],
                    "deterministic_query_plan": payload["deterministic_query_plan"],
                }
            )
        )


@pytest.mark.asyncio
async def test_plan_biomedical_search_can_use_injected_llm_planner(tmp_path: Path) -> None:
    provider = _FakePlannerProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-light-router",
    )
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What evidence links microglial activation to Alzheimer's disease progression?",
                source="mock",
                max_results=5,
                use_llm_planner=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert result.classification.classifier_mode == "llm"
    assert result.query_plan is not None
    assert result.query_plan.planner_mode == "llm"
    assert result.query_plan.llm_model == "fake-light-router"
    assert result.validation.valid is True
    assert result.search_request is not None


@pytest.mark.asyncio
async def test_plan_biomedical_search_accepts_llm_echoed_deterministic_payload(tmp_path: Path) -> None:
    provider = _FakeEchoPlannerProvider()
    service = BiomedEvidenceService(
        tmp_path,
        revision_provider=provider,
        revision_model="fake-light-router",
    )
    try:
        result = await service.plan_biomedical_search(
            PlanBiomedicalSearchRequest(
                question="What evidence links microglia to Alzheimer's disease?",
                source="mock",
                max_results=5,
                use_llm_planner=True,
            )
        )
    finally:
        await service.aclose()

    assert provider.calls == 1
    assert result.classification.classifier_mode == "llm"
    assert result.query_plan is not None
    assert result.query_plan.planner_mode == "llm"
    assert result.validation.valid is True
    assert result.search_request is not None
    assert result.search_request.query


class _FakePubMedClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, *, params: dict[str, Any]):
        self.calls.append((url, dict(params)))
        if url.endswith("esearch.fcgi"):
            retstart = int(params.get("retstart", 0))
            pmid = "9001" if retstart == 0 else "9002"
            return _FakePubMedResponse(
                f"""
                <eSearchResult>
                  <Count>2</Count>
                  <IdList><Id>{pmid}</Id></IdList>
                </eSearchResult>
                """
            )
        return _FakePubMedResponse(
            """
            <PubmedArticleSet>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>9001</PMID>
                  <Article>
                    <ArticleTitle>Microglia page one</ArticleTitle>
                    <Abstract><AbstractText>Microglia activation was observed.</AbstractText></Abstract>
                  </Article>
                </MedlineCitation>
              </PubmedArticle>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>9002</PMID>
                  <Article>
                    <ArticleTitle>Microglia page two</ArticleTitle>
                    <Abstract><AbstractText>Microglia activation was replicated.</AbstractText></Abstract>
                  </Article>
                </MedlineCitation>
              </PubmedArticle>
            </PubmedArticleSet>
            """
        )


class _FlakyPubMedClient(_FakePubMedClient):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    async def get(self, url: str, *, params: dict[str, Any]):
        if url.endswith("esearch.fcgi") and not self.failed_once:
            self.failed_once = True
            raise httpx.ConnectError("temporary PubMed network failure")
        return await super().get(url, params=params)


@pytest.mark.asyncio
async def test_pubmed_search_trace_records_pagination_with_fake_http() -> None:
    fake = _FakePubMedClient()
    client = PubMedLiteratureClient(client=cast(httpx.AsyncClient, fake))

    result = await client.search_with_trace(
        "microglia",
        max_results=2,
        page_size=1,
    )

    assert [item.paper_id for item in result.items] == ["9001", "9002"]
    assert result.trace["pages_completed"] == 2
    assert result.trace["raw_result_count"] == 2
    starts = [
        params["retstart"]
        for url, params in fake.calls
        if url.endswith("esearch.fcgi")
    ]
    assert starts == [0, 1]


@pytest.mark.asyncio
async def test_pubmed_search_trace_records_retry_and_redacts_api_key() -> None:
    fake = _FlakyPubMedClient()
    client = PubMedLiteratureClient(
        client=cast(httpx.AsyncClient, fake),
        api_key="secret-key",
        retry_backoff_seconds=0.0,
    )

    result = await client.search_with_trace(
        "microglia",
        max_results=2,
        page_size=2,
    )

    assert result.items
    warnings = cast(list[str], result.trace["warnings"])
    assert any("ConnectError" in item for item in warnings)
    params = cast(list[dict[str, object]], result.trace["request_parameters"])
    assert params[0]["api_key"] == "***redacted***"


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
    assert first.retrieval_manifest is not None
    assert first.snapshot is not None
    assert first.snapshot.new_paper_ids
    assert first.decisions
    assert second is not None
    assert second.snapshot is not None
    assert second.snapshot.new_paper_ids == []
    assert second.decisions == []
    assert total == len(decisions)
    assert all(item.retrieval_id and item.snapshot_id for item in decisions)
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
        assert tools.has_tool("plan_biomedical_search")
        assert tools.has_tool("answer_with_evidence")
        assert tools.has_tool("answer_with_audit")
        assert tools.has_tool("validate_citation_support")
        assert tools.has_tool("audit_biomedical_answer")
        assert tools.has_tool("find_conflicting_evidence")
        raw = await tools.execute(
            "answer_with_evidence",
            {
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
            },
        )
        payload = json.loads(str(raw))
        assert payload["citations"]
        audited_raw = await tools.execute(
            "answer_with_audit",
            {
                "question": "What recent evidence links microglial activation to Alzheimer's disease progression?",
                "source": "mock",
            },
        )
        audited_payload = json.loads(str(audited_raw))
        assert audited_payload["audit"]["audit_id"]
        assert audited_payload["revision"]["revision_id"]
        assert audited_payload["trace"]
    finally:
        await manager.terminate_all()
        await bus.aclose()
        plugin_registry._handlers._handlers.clear()
        plugin_registry._classes.clear()
        plugin_registry._instances.clear()
