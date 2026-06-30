from __future__ import annotations

import asyncio
import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Protocol

import httpx

from plugins.biomed_evidence.mock_data import MOCK_PAPERS
from plugins.biomed_evidence.schemas import BiomedicalPaper, PaperMetadata

logger = logging.getLogger(__name__)
ParamValue = str | int


class LiteratureClientError(RuntimeError):
    """Recoverable literature search/fetch failure."""


class LiteratureClient(Protocol):
    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[PaperMetadata]: ...

    async def fetch(self, paper_id: str) -> BiomedicalPaper | None: ...


class MockLiteratureClient:
    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[PaperMetadata]:
        tokens = _tokens(query)
        scored: list[tuple[int, BiomedicalPaper]] = []
        for paper in MOCK_PAPERS:
            if not _within_date(paper.publication_date, date_from, date_to):
                continue
            haystack = " ".join(
                [
                    paper.title,
                    paper.abstract or "",
                    " ".join(paper.mesh_terms),
                    " ".join(paper.keywords),
                ]
            ).lower()
            score = sum(1 for token in tokens if token in haystack)
            if score > 0 or not tokens:
                scored.append((score, paper))
        scored.sort(key=lambda item: (-item[0], item[1].publication_date or "", item[1].paper_id))
        return [_paper_to_metadata(paper, source="mock") for _, paper in scored[: max(0, max_results)]]

    async def fetch(self, paper_id: str) -> BiomedicalPaper | None:
        target = paper_id.strip()
        for paper in MOCK_PAPERS:
            if paper.paper_id == target:
                return paper
        return None


@dataclass
class LiteratureSearchResult:
    items: list[PaperMetadata]
    trace: dict[str, object]
    papers: list[BiomedicalPaper]


@dataclass
class PubMedSearchPage:
    ids: list[str]
    count: int
    endpoint: str
    params: dict[str, ParamValue]


@dataclass
class PubMedLiteratureClient:
    client: httpx.AsyncClient | None = None
    base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    email: str | None = None
    api_key: str | None = None
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25
    rate_limit_requests_per_second: float | None = None

    def __post_init__(self) -> None:
        self._owns_client = self.client is None
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=20.0)
        if self.rate_limit_requests_per_second is None:
            self.rate_limit_requests_per_second = 8.0 if self.api_key else 2.5
        self._rate_limit_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def close(self) -> None:
        if self._owns_client and self.client is not None:
            await self.client.aclose()

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[PaperMetadata]:
        result = await self.search_with_trace(
            query=query,
            max_results=max_results,
            date_from=date_from,
            date_to=date_to,
        )
        return result.items

    async def search_with_trace(
        self,
        query: str,
        *,
        max_results: int = 10,
        date_from: str | None = None,
        date_to: str | None = None,
        page_size: int = 20,
    ) -> LiteratureSearchResult:
        limit = max(0, min(int(max_results), 50))
        safe_page_size = max(1, min(int(page_size), 50, limit or 1))
        ids: list[str] = []
        request_parameters: list[dict[str, object]] = []
        endpoints: list[str] = []
        request_events: list[dict[str, object]] = []
        pages_completed = 0
        raw_result_count = 0
        for retstart in range(0, limit, safe_page_size):
            page = await self._esearch_page(
                query=query,
                retstart=retstart,
                retmax=min(safe_page_size, limit - retstart),
                date_from=date_from,
                date_to=date_to,
                request_events=request_events,
            )
            pages_completed += 1
            raw_result_count = page.count
            endpoints.append(page.endpoint)
            request_parameters.append(_redact_params(page.params))
            ids.extend(page.ids)
            if len(ids) >= min(limit, page.count) or not page.ids:
                break
        deduped_ids, duplicate_ids = _dedupe_ids(ids)
        if not ids:
            return LiteratureSearchResult(
                items=[],
                papers=[],
                trace={
                    "api_endpoints": endpoints,
                    "request_parameters": request_parameters,
                    "page_size": safe_page_size,
                    "pages_requested": 0 if limit == 0 else (limit + safe_page_size - 1) // safe_page_size,
                    "pages_completed": pages_completed,
                    "raw_result_count": raw_result_count,
                    "deduped_ids": [],
                    "duplicate_ids": duplicate_ids,
                    "warnings": _retry_warnings(request_events),
                    "errors": [],
                    "request_events": request_events,
                },
            )
        fetch_params = self._efetch_params(deduped_ids[:limit])
        endpoints.append(f"{self.base_url.rstrip('/')}/efetch.fcgi")
        request_parameters.append(_redact_params(fetch_params))
        papers = await self._efetch(
            deduped_ids[:limit],
            params=fetch_params,
            request_events=request_events,
        )
        return LiteratureSearchResult(
            items=[_paper_to_metadata(paper, source="pubmed") for paper in papers],
            papers=papers,
            trace={
                "api_endpoints": endpoints,
                "request_parameters": request_parameters,
                "page_size": safe_page_size,
                "pages_requested": 0 if limit == 0 else (limit + safe_page_size - 1) // safe_page_size,
                "pages_completed": pages_completed,
                "raw_result_count": raw_result_count,
                "deduped_ids": deduped_ids[:limit],
                "duplicate_ids": duplicate_ids,
                "warnings": _retry_warnings(request_events),
                "errors": [],
                "request_events": request_events,
            },
        )

    async def fetch(self, paper_id: str) -> BiomedicalPaper | None:
        papers = await self._efetch([paper_id.strip()])
        return papers[0] if papers else None

    async def _esearch_page(
        self,
        *,
        query: str,
        retstart: int,
        retmax: int,
        date_from: str | None,
        date_to: str | None,
        request_events: list[dict[str, object]] | None = None,
    ) -> PubMedSearchPage:
        params: dict[str, ParamValue] = {
            "db": "pubmed",
            "term": query,
            "retmode": "xml",
            "retmax": max(0, min(int(retmax), 50)),
            "retstart": max(0, int(retstart)),
            "sort": "relevance",
        }
        if date_from:
            params["mindate"] = date_from
        if date_to:
            params["maxdate"] = date_to
        if date_from or date_to:
            params["datetype"] = "pdat"
        self._add_identity_params(params)
        text = await self._get_text(
            "esearch.fcgi",
            params=params,
            request_events=request_events,
        )
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise LiteratureClientError("PubMed search returned invalid XML") from exc
        ids = [
            (node.text or "").strip()
            for node in root.findall(".//IdList/Id")
            if (node.text or "").strip()
        ]
        count_text = (root.findtext(".//Count") or "0").strip()
        try:
            count = int(count_text)
        except ValueError:
            count = len(ids)
        return PubMedSearchPage(
            ids=ids,
            count=count,
            endpoint=f"{self.base_url.rstrip('/')}/esearch.fcgi",
            params=params,
        )

    def _efetch_params(self, ids: list[str]) -> dict[str, ParamValue]:
        clean_ids = [item.strip() for item in ids if item.strip()]
        params: dict[str, ParamValue] = {
            "db": "pubmed",
            "id": ",".join(clean_ids),
            "retmode": "xml",
        }
        self._add_identity_params(params)
        return params

    async def _efetch(
        self,
        ids: list[str],
        *,
        params: dict[str, ParamValue] | None = None,
        request_events: list[dict[str, object]] | None = None,
    ) -> list[BiomedicalPaper]:
        clean_ids = [item.strip() for item in ids if item.strip()]
        if not clean_ids:
            return []
        if params is None:
            params = self._efetch_params(clean_ids)
        text = await self._get_text(
            "efetch.fcgi",
            params=params,
            request_events=request_events,
        )
        return parse_pubmed_articles(text)

    async def _get_text(
        self,
        endpoint: str,
        *,
        params: dict[str, ParamValue],
        request_events: list[dict[str, object]] | None = None,
    ) -> str:
        assert self.client is not None
        url = f"{self.base_url.rstrip('/')}/{endpoint}"
        attempts = max(0, int(self.max_retries)) + 1
        for attempt in range(1, attempts + 1):
            try:
                await self._wait_for_rate_slot()
                response = await self.client.get(url, params=params)
                response.raise_for_status()
                if request_events is not None and attempt > 1:
                    request_events.append(
                        {
                            "endpoint": endpoint,
                            "attempt": attempt,
                            "event": "success_after_retry",
                        }
                    )
                return response.text
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                retryable = status == 429 or 500 <= status < 600
                _record_request_failure(
                    request_events,
                    endpoint=endpoint,
                    attempt=attempt,
                    exc=exc,
                    retryable=retryable,
                    status_code=status,
                )
                if not retryable or attempt >= attempts:
                    logger.warning("PubMed request failed: %s", exc)
                    raise LiteratureClientError(f"PubMed request failed: {exc}") from exc
                retry_delay = _retry_after_seconds(exc.response.headers.get("Retry-After"))
            except httpx.TransportError as exc:
                _record_request_failure(
                    request_events,
                    endpoint=endpoint,
                    attempt=attempt,
                    exc=exc,
                    retryable=True,
                    status_code=None,
                )
                if attempt >= attempts:
                    logger.warning("PubMed request failed: %s", exc)
                    raise LiteratureClientError(f"PubMed request failed: {exc}") from exc
                retry_delay = None
            except httpx.HTTPError as exc:
                _record_request_failure(
                    request_events,
                    endpoint=endpoint,
                    attempt=attempt,
                    exc=exc,
                    retryable=False,
                    status_code=None,
                )
                logger.warning("PubMed request failed: %s", exc)
                raise LiteratureClientError(f"PubMed request failed: {exc}") from exc
            await asyncio.sleep(
                retry_delay
                if retry_delay is not None
                else self.retry_backoff_seconds * (2 ** (attempt - 1))
            )
        raise LiteratureClientError("PubMed request failed after retry exhaustion")

    async def _wait_for_rate_slot(self) -> None:
        rate = float(self.rate_limit_requests_per_second or 0.0)
        if rate <= 0:
            return
        interval = 1.0 / rate
        async with self._rate_limit_lock:
            now = time.monotonic()
            delay = self._last_request_at + interval - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request_at = time.monotonic()

    def _add_identity_params(self, params: dict[str, ParamValue]) -> None:
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key


def parse_pubmed_articles(xml_text: str) -> list[BiomedicalPaper]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise LiteratureClientError("PubMed fetch returned invalid XML") from exc

    papers: list[BiomedicalPaper] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = _text(article, ".//MedlineCitation/PMID")
        if not pmid:
            continue
        title = _clean_text(_text(article, ".//Article/ArticleTitle")) or f"PubMed {pmid}"
        abstract_parts = [
            _clean_text("".join(node.itertext()))
            for node in article.findall(".//Article/Abstract/AbstractText")
        ]
        abstract = "\n".join(part for part in abstract_parts if part) or None
        authors = _parse_authors(article)
        journal = _clean_text(_text(article, ".//Article/Journal/Title")) or None
        publication_date = _parse_publication_date(article)
        doi = _parse_doi(article)
        mesh_terms = [
            _clean_text("".join(node.itertext()))
            for node in article.findall(".//MeshHeading/DescriptorName")
            if _clean_text("".join(node.itertext()))
        ]
        keywords = [
            _clean_text("".join(node.itertext()))
            for node in article.findall(".//KeywordList/Keyword")
            if _clean_text("".join(node.itertext()))
        ]
        papers.append(
            BiomedicalPaper(
                paper_id=pmid,
                source="pubmed",
                title=title,
                abstract=abstract,
                authors=authors,
                journal=journal,
                publication_date=publication_date,
                doi=doi,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                mesh_terms=mesh_terms,
                keywords=keywords,
            )
        )
    return papers


def parse_bioc_json_full_text(payload: dict[str, object] | list[object]) -> str:
    passages: list[str] = []
    for document in _bioc_documents(payload):
        if not isinstance(document, dict):
            continue
        for passage in document.get("passages", []):
            if not isinstance(passage, dict):
                continue
            text = str(passage.get("text") or "").strip()
            if not text:
                continue
            infons = passage.get("infons")
            label = ""
            if isinstance(infons, dict):
                label = str(
                    infons.get("section_type") or infons.get("type") or ""
                ).strip()
            passages.append(f"## {label or 'Full text'}\n{text}")
    return "\n\n".join(passages).strip()


def parse_bioc_json_license_or_rights(payload: dict[str, object] | list[object]) -> str | None:
    collections: list[object] = payload if isinstance(payload, list) else [payload]
    for item in [*collections, *_bioc_documents(payload)]:
        if not isinstance(item, dict):
            continue
        infons = item.get("infons")
        if not isinstance(infons, dict):
            continue
        for key in ("license", "rights", "copyright"):
            value = str(infons.get(key) or "").strip()
            if value:
                return value
    return None


def _bioc_documents(payload: dict[str, object] | list[object]) -> list[object]:
    collections: list[object] = payload if isinstance(payload, list) else [payload]
    documents: list[object] = []
    for collection in collections:
        if not isinstance(collection, dict):
            continue
        collection_documents = collection.get("documents")
        if isinstance(collection_documents, list):
            documents.extend(collection_documents)
    return documents


def _paper_to_metadata(
    paper: BiomedicalPaper,
    *,
    source: str,
) -> PaperMetadata:
    return PaperMetadata(
        paper_id=paper.paper_id,
        source="pubmed" if source == "pubmed" else "mock",
        title=paper.title,
        authors=paper.authors,
        journal=paper.journal,
        publication_date=paper.publication_date,
        abstract_available=bool((paper.abstract or "").strip()),
        doi=paper.doi,
        url=paper.url,
    )


def _tokens(value: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}", value or "")
        if token.lower() not in {"the", "and", "for", "with", "what", "how", "does"}
    ]


def _dedupe_ids(ids: list[str]) -> tuple[list[str], list[str]]:
    seen: set[str] = set()
    unique: list[str] = []
    duplicates: list[str] = []
    for item in ids:
        if item in seen:
            duplicates.append(item)
            continue
        seen.add(item)
        unique.append(item)
    return unique, duplicates


def _record_request_failure(
    events: list[dict[str, object]] | None,
    *,
    endpoint: str,
    attempt: int,
    exc: httpx.HTTPError,
    retryable: bool,
    status_code: int | None,
) -> None:
    if events is None:
        return
    event: dict[str, object] = {
        "endpoint": endpoint,
        "attempt": attempt,
        "event": "failure",
        "error_type": exc.__class__.__name__,
        "retryable": retryable,
    }
    if status_code is not None:
        event["status_code"] = status_code
    events.append(event)


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        delay = float(value.strip())
    except ValueError:
        return None
    return delay if delay >= 0 else None


def _retry_warnings(events: list[dict[str, object]]) -> list[str]:
    warnings: list[str] = []
    for event in events:
        if event.get("event") != "failure":
            continue
        retryable = bool(event.get("retryable"))
        action = "retrying" if retryable else "not retryable"
        status = event.get("status_code")
        status_part = f" status={status}" if status is not None else ""
        warnings.append(
            "PubMed request failure on "
            f"{event.get('endpoint')} attempt {event.get('attempt')}: "
            f"{event.get('error_type')}{status_part}; {action}."
        )
    return warnings


def _redact_params(params: dict[str, ParamValue]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in params.items():
        redacted[key] = "***redacted***" if key == "api_key" else value
    return redacted


def _within_date(value: str | None, date_from: str | None, date_to: str | None) -> bool:
    if not value:
        return True
    if date_from and value < date_from:
        return False
    if date_to and value > date_to:
        return False
    return True


def _text(node: ET.Element, path: str) -> str:
    found = node.find(path)
    if found is None:
        return ""
    return "".join(found.itertext())


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _parse_authors(article: ET.Element) -> list[str]:
    authors: list[str] = []
    for node in article.findall(".//Article/AuthorList/Author"):
        collective = _clean_text(_text(node, "CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        last = _clean_text(_text(node, "LastName"))
        fore = _clean_text(_text(node, "ForeName"))
        initials = _clean_text(_text(node, "Initials"))
        if last and fore:
            authors.append(f"{fore} {last}")
        elif last and initials:
            authors.append(f"{initials} {last}")
        elif last:
            authors.append(last)
    return authors


def _parse_publication_date(article: ET.Element) -> str | None:
    date_node = article.find(".//Article/Journal/JournalIssue/PubDate")
    if date_node is None:
        return None
    year = _clean_text(_text(date_node, "Year"))
    month = _month_to_number(_clean_text(_text(date_node, "Month")))
    day = _clean_text(_text(date_node, "Day"))
    medline = _clean_text(_text(date_node, "MedlineDate"))
    if year:
        parts = [year]
        if month:
            parts.append(month)
        if day:
            parts.append(day.zfill(2))
        return "-".join(parts)
    return medline or None


def _month_to_number(value: str) -> str:
    if not value:
        return ""
    if value.isdigit():
        return value.zfill(2)
    lookup = {
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "may": "05",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dec": "12",
    }
    return lookup.get(value[:3].lower(), "")


def _parse_doi(article: ET.Element) -> str | None:
    for node in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if str(node.attrib.get("IdType", "")).lower() == "doi":
            doi = _clean_text("".join(node.itertext()))
            if doi:
                return doi
    return None
