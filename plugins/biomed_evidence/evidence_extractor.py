from __future__ import annotations

import hashlib
import re

from plugins.biomed_evidence.mock_data import MOCK_EVIDENCE
from plugins.biomed_evidence.schemas import (
    BiomedicalEntity,
    BiomedicalPaper,
    EntityType,
    EvidenceDirection,
    EvidenceExtractionResult,
    EvidenceItem,
)
from plugins.biomed_evidence.text_utils import split_sentences


_ENTITY_PATTERNS: list[tuple[str, str, EntityType]] = [
    (r"\bmicroglia(?:l)?\b", "microglia", "cell_type"),
    (r"\bTREM2\b", "TREM2", "gene"),
    (r"\bAPOE\b", "APOE", "gene"),
    (r"\bamyloid(?: plaques?| pathology)?\b", "amyloid pathology", "pathway"),
    (r"\bAlzheimer'?s disease\b", "Alzheimer's disease", "disease"),
    (r"\bneuroinflammation\b", "neuroinflammation", "pathway"),
    (r"\bspatial transcriptomics\b", "spatial transcriptomics", "method"),
    (r"\bsingle-nucleus RNA(?:-seq| sequencing)\b", "single-nucleus RNA-seq", "method"),
    (r"\bsingle-cell RNA(?:-seq| sequencing)\b", "single-cell RNA-seq", "method"),
    (r"\btumou?r microenvironment\b", "tumor microenvironment", "disease"),
    (r"\bT cells?\b", "T cells", "cell_type"),
    (r"\bmacrophages?\b", "macrophage", "cell_type"),
    (r"\bCSF\b|\bcerebrospinal fluid\b", "CSF", "dataset"),
    (r"\bmouse model\b|\bmice\b", "mouse model", "organism"),
]

_METHOD_PATTERNS = [
    (r"\bspatial transcriptomics\b", "spatial transcriptomics"),
    (r"\bsingle-nucleus RNA(?:-seq| sequencing)\b", "single-nucleus RNA-seq"),
    (r"\bsingle-cell RNA(?:-seq| sequencing)\b", "single-cell RNA-seq"),
    (r"\bimmunostaining\b", "immunostaining"),
    (r"\bcohort study\b|\blongitudinal cohort\b", "cohort study"),
    (r"\bproteomics\b", "proteomics"),
]

_DATASET_PATTERNS = [
    (r"\bpost-mortem\b", "post-mortem tissue cohort"),
    (r"\bhuman\b", "human cohort or sample"),
    (r"\bmouse\b|\bmice\b", "animal model"),
    (r"\bCSF\b|\bcerebrospinal fluid\b", "CSF cohort"),
    (r"\bbiops(?:y|ies)\b", "biopsy cohort"),
]

_LIMITATION_PATTERNS = [
    (r"\blimits? causal\b|\bcausal interpretation\b", "Causal interpretation is limited."),
    (r"\bsmall (?:donor )?cohort\b|\blimited .*cohort\b", "Small cohort limits generalizability."),
    (r"\brequires? validation\b", "Requires independent validation."),
    (r"\banimal model\b|\bmouse model\b", "Animal model evidence may not translate to humans."),
    (r"\bweakened after adjustment\b", "Association weakened after confounder adjustment."),
]


class EvidenceExtractor:
    def extract(
        self,
        paper: BiomedicalPaper,
        *,
        research_question: str | None = None,
    ) -> EvidenceExtractionResult:
        if paper.source == "mock" and paper.paper_id in MOCK_EVIDENCE:
            return EvidenceExtractionResult(
                paper_id=paper.paper_id,
                evidence=MOCK_EVIDENCE[paper.paper_id],
                reason=None,
            )

        abstract = (paper.abstract or "").strip()
        if not abstract:
            return EvidenceExtractionResult(
                paper_id=paper.paper_id,
                evidence=[],
                reason="No abstract was available; evidence was not fabricated.",
            )

        sentences = _sentences(abstract)
        if not sentences:
            return EvidenceExtractionResult(
                paper_id=paper.paper_id,
                evidence=[],
                reason="Abstract did not contain extractable sentences.",
            )
        candidate = _select_candidate_sentence(sentences, research_question)
        entities = _merge_entities(
            _question_entities(candidate, research_question),
            _detect_entities(f"{paper.title} {candidate}"),
        )
        if not entities:
            return EvidenceExtractionResult(
                paper_id=paper.paper_id,
                evidence=[],
                reason="No recognizable biomedical entities were found in the abstract.",
            )
        direction = _classify_direction(candidate)
        limitations = _detect_limitations(abstract)
        item = EvidenceItem(
            evidence_id=_evidence_id(paper.paper_id, candidate),
            paper_id=paper.paper_id,
            claim=_claim_from_sentence(paper, candidate),
            finding=candidate,
            evidence_direction=direction,
            entities=entities,
            methods=_detect_methods(f"{paper.title} {abstract}"),
            datasets_or_cohorts=_detect_datasets(abstract),
            limitations=limitations or ["Heuristic extraction from abstract only."],
            confidence="low",
            evidence_span=candidate,
            requires_expert_review=True,
        )
        return EvidenceExtractionResult(paper_id=paper.paper_id, evidence=[item])


def _sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in split_sentences(text)
        if len(sentence.strip()) >= 25
    ]


def _select_candidate_sentence(
    sentences: list[str],
    research_question: str | None,
) -> str:
    question_terms = {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", research_question or "")
    }
    best_sentence = sentences[0]
    best_score = -1
    for sentence in sentences:
        low = sentence.lower()
        score = sum(1 for term in question_terms if term in low)
        score += sum(2 for marker in ("associated", "correlated", "linked", "identified", "enriched", "reduced", "increased", "lower incidence", "mortality", "risk") if marker in low)
        score += sum(1 for marker in ("limited", "inconclusive", "did not", "failed", "no benefit", "usual care") if marker in low)
        if score > best_score:
            best_score = score
            best_sentence = sentence
    return best_sentence


def _detect_entities(text: str) -> list[BiomedicalEntity]:
    found: list[BiomedicalEntity] = []
    seen: set[str] = set()
    for pattern, name, entity_type in _ENTITY_PATTERNS:
        if not re.search(pattern, text, re.IGNORECASE):
            continue
        key = f"{entity_type}:{name.lower()}"
        if key in seen:
            continue
        seen.add(key)
        found.append(BiomedicalEntity(name=name, entity_type=entity_type))
    return found


def _question_entities(sentence: str, research_question: str | None) -> list[BiomedicalEntity]:
    terms = [
        term.lower()
        for term in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", research_question or "")
        if term.lower() in sentence.lower()
    ]
    seen: set[str] = set()
    entities: list[BiomedicalEntity] = []
    for term in terms[:4]:
        if term in seen:
            continue
        seen.add(term)
        entities.append(BiomedicalEntity(name=term, entity_type="other"))
    return entities


def _merge_entities(*groups: list[BiomedicalEntity]) -> list[BiomedicalEntity]:
    seen: set[str] = set()
    merged: list[BiomedicalEntity] = []
    for group in groups:
        for entity in group:
            key = f"{entity.entity_type}:{entity.name.lower()}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(entity)
    return merged


def _detect_methods(text: str) -> list[str]:
    return _detect_strings(text, _METHOD_PATTERNS)


def _detect_datasets(text: str) -> list[str]:
    return _detect_strings(text, _DATASET_PATTERNS)


def _detect_limitations(text: str) -> list[str]:
    return _detect_strings(text, _LIMITATION_PATTERNS)


def _detect_strings(text: str, patterns: list[tuple[str, str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for pattern, label in patterns:
        if re.search(pattern, text, re.IGNORECASE) and label not in seen:
            seen.add(label)
            result.append(label)
    return result


def _classify_direction(sentence: str) -> EvidenceDirection:
    low = sentence.lower()
    if any(marker in low for marker in ("did not", "failed to", "no association", "not associated", "contradict", "no benefit", "not reduce", "not have a lower")):
        return "contradicts"
    if any(marker in low for marker in ("inconclusive", "weakened", "limited", "ambiguous")):
        return "inconclusive"
    if any(marker in low for marker in ("associated", "correlated", "linked", "identified", "enriched", "suggest", "reduced", "increased", "lower incidence", "risk")):
        return "supports"
    return "background"


def _claim_from_sentence(paper: BiomedicalPaper, sentence: str) -> str:
    clean = sentence.rstrip(".")
    if len(clean) > 180:
        clean = clean[:177].rstrip() + "..."
    return f"{paper.title}: {clean}"


def _evidence_id(paper_id: str, sentence: str) -> str:
    digest = hashlib.sha256(f"{paper_id}:{sentence}".encode("utf-8")).hexdigest()[:16]
    return f"ev-{digest}"
