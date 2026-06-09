from __future__ import annotations

import html
import logging
import re
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
class PubMedLiteratureClient:
    client: httpx.AsyncClient | None = None
    base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    email: str | None = None
    api_key: str | None = None

    def __post_init__(self) -> None:
        self._owns_client = self.client is None
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=20.0)

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
        ids = await self._esearch(
            query=query,
            max_results=max_results,
            date_from=date_from,
            date_to=date_to,
        )
        if not ids:
            return []
        papers = await self._efetch(ids)
        return [_paper_to_metadata(paper, source="pubmed") for paper in papers]

    async def fetch(self, paper_id: str) -> BiomedicalPaper | None:
        papers = await self._efetch([paper_id.strip()])
        return papers[0] if papers else None

    async def _esearch(
        self,
        *,
        query: str,
        max_results: int,
        date_from: str | None,
        date_to: str | None,
    ) -> list[str]:
        params: dict[str, ParamValue] = {
            "db": "pubmed",
            "term": query,
            "retmode": "xml",
            "retmax": max(0, min(int(max_results), 50)),
            "sort": "relevance",
        }
        if date_from:
            params["mindate"] = date_from
        if date_to:
            params["maxdate"] = date_to
        if date_from or date_to:
            params["datetype"] = "pdat"
        self._add_identity_params(params)
        text = await self._get_text("esearch.fcgi", params=params)
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise LiteratureClientError("PubMed search returned invalid XML") from exc
        return [
            (node.text or "").strip()
            for node in root.findall(".//IdList/Id")
            if (node.text or "").strip()
        ]

    async def _efetch(self, ids: list[str]) -> list[BiomedicalPaper]:
        clean_ids = [item.strip() for item in ids if item.strip()]
        if not clean_ids:
            return []
        params: dict[str, ParamValue] = {
            "db": "pubmed",
            "id": ",".join(clean_ids),
            "retmode": "xml",
        }
        self._add_identity_params(params)
        text = await self._get_text("efetch.fcgi", params=params)
        return parse_pubmed_articles(text)

    async def _get_text(self, endpoint: str, *, params: dict[str, ParamValue]) -> str:
        assert self.client is not None
        url = f"{self.base_url.rstrip('/')}/{endpoint}"
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("PubMed request failed: %s", exc)
            raise LiteratureClientError(f"PubMed request failed: {exc}") from exc
        return response.text

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
