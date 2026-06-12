from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

from plugins.biomed_evidence.claim_logic_rules import (
    PREDICATE_NO_ENTAILMENTS,
    RULE_METADATA,
)
from plugins.biomed_evidence.schemas import (
    LogicAuditResult,
    LogicFact,
    LogicFactExport,
    LogicFactFormat,
    LogicalClaimFrame,
    LogicalEvidenceFrame,
)


def normalize_symbol(text: str) -> str:
    normalized = text.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        return "unspecified"
    if normalized[0].isdigit():
        return f"id_{normalized}"
    return normalized


def make_fact(
    predicate: str,
    *arguments: str,
    quoted: set[int] | None = None,
) -> LogicFact:
    quoted_indexes = quoted or set()
    return LogicFact(
        predicate=normalize_symbol(predicate),
        arguments=list(arguments),
        quoted_arguments=[index in quoted_indexes for index in range(len(arguments))],
    )


def render_fact_text(facts: list[LogicFact]) -> str:
    return "\n".join(_render_fact(fact) for fact in facts)


def export_logic_facts(
    claim_frame: LogicalClaimFrame,
    evidence_frames: list[LogicalEvidenceFrame],
    audit_result: LogicAuditResult,
    *,
    format: LogicFactFormat = "text",
) -> LogicFactExport:
    facts = _claim_facts(claim_frame)
    for evidence in evidence_frames:
        facts.extend(_evidence_facts(evidence))
        facts.append(
            make_fact("aligned_with", claim_frame.claim_id, evidence.evidence_id)
        )
    facts.extend(_rule_definition_facts(audit_result.rules_triggered))
    facts.extend(_mismatch_facts(claim_frame.claim_id, audit_result))
    for evidence_id in audit_result.evidence_ids:
        for rule in audit_result.rules_triggered:
            facts.append(
                make_fact("triggered_rule", claim_frame.claim_id, evidence_id, rule)
            )
    facts.append(
        make_fact("logic_verdict", claim_frame.claim_id, audit_result.logic_verdict)
    )
    for warning in audit_result.warnings:
        facts.append(
            make_fact("logic_warning", claim_frame.claim_id, warning, quoted={1})
        )

    text = render_fact_text(facts) if format == "text" else None
    return LogicFactExport(
        export_id=_export_id(
            claim_frame.claim_id, evidence_frames, audit_result, facts
        ),
        claim_id=claim_frame.claim_id,
        evidence_ids=[item.evidence_id for item in evidence_frames],
        facts=facts,
        text=text,
        format=format,
        warnings=_export_warnings(facts),
    )


def _claim_facts(frame: LogicalClaimFrame) -> list[LogicFact]:
    return [
        make_fact("claim", frame.claim_id),
        make_fact("claim_text", frame.claim_id, frame.claim_text, quoted={1}),
        make_fact(
            "claim_subject", frame.claim_id, normalize_symbol(frame.subject.text)
        ),
        make_fact("claim_subject_text", frame.claim_id, frame.subject.text, quoted={1}),
        make_fact("claim_predicate", frame.claim_id, frame.predicate),
        make_fact("claim_object", frame.claim_id, normalize_symbol(frame.object.text)),
        make_fact("claim_object_text", frame.claim_id, frame.object.text, quoted={1}),
        make_fact("claim_population", frame.claim_id, frame.population),
        make_fact("claim_modality", frame.claim_id, frame.modality),
        make_fact("claim_polarity", frame.claim_id, frame.polarity),
        make_fact("claim_strength", frame.claim_id, frame.claim_strength),
        make_fact("claim_hedging", frame.claim_id, str(frame.hedging).lower()),
        make_fact("claim_parser_mode", frame.claim_id, frame.parser_mode),
    ]


def _evidence_facts(frame: LogicalEvidenceFrame) -> list[LogicFact]:
    facts = [
        make_fact("evidence", frame.evidence_id),
        make_fact("evidence_paper", frame.evidence_id, frame.paper_id, quoted={1}),
        make_fact("evidence_text", frame.evidence_id, frame.evidence_text, quoted={1}),
        make_fact(
            "evidence_subject", frame.evidence_id, normalize_symbol(frame.subject.text)
        ),
        make_fact(
            "evidence_subject_text", frame.evidence_id, frame.subject.text, quoted={1}
        ),
        make_fact("evidence_predicate", frame.evidence_id, frame.predicate),
        make_fact(
            "evidence_object", frame.evidence_id, normalize_symbol(frame.object.text)
        ),
        make_fact(
            "evidence_object_text", frame.evidence_id, frame.object.text, quoted={1}
        ),
        make_fact("evidence_population", frame.evidence_id, frame.population),
        make_fact("evidence_modality", frame.evidence_id, frame.modality),
        make_fact("evidence_study_design", frame.evidence_id, frame.study_design),
        make_fact("evidence_strength", frame.evidence_id, frame.evidence_strength),
        make_fact("evidence_parser_mode", frame.evidence_id, frame.parser_mode),
    ]
    if frame.model_system:
        facts.append(
            make_fact(
                "evidence_model_system",
                frame.evidence_id,
                normalize_symbol(frame.model_system),
            )
        )
    return facts


def _rule_definition_facts(rules: Iterable[str]) -> list[LogicFact]:
    facts: list[LogicFact] = []
    for evidence_predicate, claim_predicate, rule_id in PREDICATE_NO_ENTAILMENTS:
        if rule_id in rules:
            facts.append(
                make_fact("no_entailment", evidence_predicate, claim_predicate)
            )
    if "animal_evidence_does_not_entail_human_claim" in rules:
        facts.append(make_fact("no_entailment_population", "animal", "human"))
    if "in_vitro_evidence_does_not_entail_human_claim" in rules:
        facts.append(make_fact("no_entailment_population", "in_vitro", "human"))
    if "weak_evidence_does_not_support_definitive_claim" in rules:
        facts.append(make_fact("no_entailment_modality", "suggestive", "strong"))
        facts.append(make_fact("no_entailment_modality", "inconclusive", "strong"))
    for rule in rules:
        metadata = RULE_METADATA.get(rule)
        if metadata is None:
            continue
        facts.append(make_fact("no_entailment_rule", rule))
        facts.append(make_fact("rule_category", rule, metadata.category))
        facts.append(make_fact("rule_severity", rule, metadata.severity))
        facts.append(
            make_fact("rule_explanation", rule, metadata.explanation, quoted={1})
        )
    return facts


def _mismatch_facts(
    claim_id: str,
    audit_result: LogicAuditResult,
) -> list[LogicFact]:
    facts: list[LogicFact] = []
    for mismatch in audit_result.predicate_mismatches:
        facts.append(_mismatch_fact("predicate_mismatch", claim_id, mismatch))
    for mismatch in audit_result.scope_mismatches:
        facts.append(_mismatch_fact("scope_mismatch", claim_id, mismatch))
    for mismatch in audit_result.modality_mismatches:
        facts.append(_mismatch_fact("modality_mismatch", claim_id, mismatch))
    for mismatch in audit_result.population_mismatches:
        facts.append(_mismatch_fact("population_mismatch", claim_id, mismatch))
    return facts


def _mismatch_fact(
    predicate: str,
    claim_id: str,
    mismatch: dict[str, object],
) -> LogicFact:
    return make_fact(
        predicate,
        claim_id,
        str(mismatch.get("evidence_id") or "unknown_evidence"),
        normalize_symbol(str(mismatch.get("axis") or "unspecified")),
        normalize_symbol(str(mismatch.get("claim_value") or "unspecified")),
        normalize_symbol(str(mismatch.get("evidence_value") or "unspecified")),
    )


def _render_fact(fact: LogicFact) -> str:
    rendered_args = []
    quoted = fact.quoted_arguments or [False for _ in fact.arguments]
    for index, argument in enumerate(fact.arguments):
        is_quoted = quoted[index] if index < len(quoted) else False
        rendered_args.append(
            json.dumps(argument) if is_quoted else normalize_symbol(argument)
        )
    return f"{normalize_symbol(fact.predicate)}({', '.join(rendered_args)})."


def _export_id(
    claim_id: str,
    evidence_frames: list[LogicalEvidenceFrame],
    audit_result: LogicAuditResult,
    facts: list[LogicFact],
) -> str:
    payload = {
        "claim_id": claim_id,
        "evidence_ids": [item.evidence_id for item in evidence_frames],
        "verdict": audit_result.logic_verdict,
        "facts": [fact.model_dump(mode="json") for fact in facts],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    return f"logic-facts-{digest}"


def _export_warnings(facts: list[LogicFact]) -> list[str]:
    warnings: list[str] = []
    for fact in facts:
        quoted = fact.quoted_arguments or []
        for index, argument in enumerate(fact.arguments):
            if index < len(quoted) and quoted[index]:
                continue
            if re.search(r"[^a-zA-Z0-9_:\-]", argument):
                warnings.append(
                    f"Unquoted symbolic argument required normalization in {fact.predicate}."
                )
                break
    return sorted(set(warnings))
