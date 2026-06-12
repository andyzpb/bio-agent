from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from plugins.biomed_evidence.schemas import (
    BiomedProject,
    EvidencePacketSummary,
    ObsidianExportResult,
    ObsidianExportType,
    ObsidianNoteRecord,
    WatchTopic,
)


def ensure_obsidian_export_dir(
    *,
    workspace: Path,
    export_dir: str | None,
    enabled: bool,
) -> tuple[Path | None, str | None]:
    if not enabled:
        return None, "Obsidian export is disabled by policy."
    if not export_dir or not export_dir.strip():
        return None, "Obsidian export_dir is required."
    workspace_root = workspace.resolve()
    candidate = Path(export_dir).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = candidate.resolve()
    if resolved != workspace_root and workspace_root not in resolved.parents:
        return None, "Obsidian export_dir must be inside the configured workspace."
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved, None


def export_packet_note(
    *,
    packet: EvidencePacketSummary,
    export_dir: Path,
    run_id: str | None = None,
) -> ObsidianExportResult:
    export_id = f"obsidian-packet-{_digest(packet.packet_id)}"
    note_dir = export_dir / "evidence-packets"
    filename = f"evidence-packet-{_safe_slug(packet.packet_id)}.md"
    frontmatter = _base_frontmatter(
        note_type="evidence_packet",
        generated_at=packet.created_at,
        run_id=run_id or _run_id_from_packet(packet),
        project_id=None,
        retrieval_ids=packet.retrieval_manifest_ids,
        evidence_ids=packet.evidence_ids,
    )
    frontmatter.update(
        {
            "paper_id": packet.paper_ids,
            "pmid": [_pmid_from_paper_id(item) for item in packet.paper_ids],
            "doi": [],
            "claim_id": packet.supported_claims + packet.conflicting_claims,
            "audit_verdict": packet.stop_reason,
        }
    )
    links = _merge_links(
        [f"[[evidence-packet:{packet.packet_id}]]"],
        [f"[[answer-run:{frontmatter['run_id']}]]"] if frontmatter["run_id"] else [],
        [f"[[paper:{_paper_link_id(item)}]]" for item in packet.paper_ids],
        [f"[[claim:{_safe_link(item)}]]" for item in packet.supported_claims[:8]],
        [f"[[claim:{_safe_link(item)}]]" for item in packet.conflicting_claims[:8]],
        [f"[[gap:{row.subquestion_id}-{row.coverage_status}]]" for row in packet.coverage_gaps],
        [f"[[topic:{_safe_link(packet.question)}]]"],
    )
    body = [
        f"# Evidence Packet: {packet.packet_id}",
        "",
        f"Question: {packet.question}",
        "",
        "## Links",
        *[f"- {link}" for link in links],
        "",
        "## Coverage",
        *[
            f"- {row.subquestion_id}: {row.coverage_status} ({row.retrieval_intent})"
            for row in packet.coverage_matrix
        ],
        "",
        "## Limitations",
        *[f"- {item}" for item in packet.limitations],
        "",
        "> One-way reviewer export. This note is not imported as biomedical evidence.",
    ]
    note = _write_note(
        export_id=export_id,
        export_type="evidence_packet",
        entity_id=packet.packet_id,
        note_dir=note_dir,
        filename=filename,
        frontmatter=frontmatter,
        links=links,
        body=body,
    )
    return ObsidianExportResult(
        export_id=export_id,
        export_type="evidence_packet",
        export_dir=str(export_dir),
        notes=[note],
        note_count=1,
        idempotent_key=note.sha256,
    )


def export_project_note(
    *,
    project: BiomedProject,
    export_dir: Path,
) -> ObsidianExportResult:
    export_id = f"obsidian-project-{_digest(project.project_id)}"
    note_dir = export_dir / "projects"
    filename = f"project-{_safe_slug(project.project_id)}.md"
    frontmatter = _base_frontmatter(
        note_type="project",
        generated_at=project.updated_at,
        run_id=None,
        project_id=project.project_id,
        retrieval_ids=[],
        evidence_ids=[],
    )
    frontmatter.update(
        {
            "paper_id": [],
            "pmid": [],
            "doi": [],
            "claim_id": [],
            "audit_verdict": None,
        }
    )
    links = _merge_links(
        [f"[[topic:{_safe_link(project.research_question or project.name)}]]"],
        [f"[[project:{project.project_id}]]"],
        [f"[[topic:{_safe_link(item)}]]" for item in project.include_keywords],
    )
    body = [
        f"# Project: {project.name}",
        "",
        f"Research question: {project.research_question}",
        "",
        "## Links",
        *[f"- {link}" for link in links],
        "",
        "## Preferences",
        f"- Include: {', '.join(project.include_keywords) or 'none'}",
        f"- Exclude: {', '.join(project.exclude_keywords) or 'none'}",
        f"- Methods: {', '.join(project.preferred_methods) or 'none'}",
        "",
        "> One-way reviewer export. Project memory is context only, not evidence.",
    ]
    note = _write_note(
        export_id=export_id,
        export_type="project",
        entity_id=project.project_id,
        note_dir=note_dir,
        filename=filename,
        frontmatter=frontmatter,
        links=links,
        body=body,
    )
    return ObsidianExportResult(
        export_id=export_id,
        export_type="project",
        export_dir=str(export_dir),
        notes=[note],
        note_count=1,
        idempotent_key=note.sha256,
    )


def export_watch_note(
    *,
    watch: WatchTopic,
    export_dir: Path,
) -> ObsidianExportResult:
    export_id = f"obsidian-watch-{_digest(watch.watch_id)}"
    note_dir = export_dir / "watches"
    filename = f"watch-{_safe_slug(watch.watch_id)}.md"
    frontmatter = _base_frontmatter(
        note_type="watch",
        generated_at=watch.updated_at,
        run_id=None,
        project_id=None,
        retrieval_ids=[],
        evidence_ids=[],
    )
    frontmatter.update(
        {
            "paper_id": [],
            "pmid": [],
            "doi": [],
            "claim_id": [],
            "audit_verdict": None,
        }
    )
    links = _merge_links(
        [f"[[topic:{_safe_link(watch.topic)}]]"],
        [f"[[watch:{watch.watch_id}]]"],
        [f"[[topic:{_safe_link(item)}]]" for item in watch.include_keywords],
    )
    body = [
        f"# Watch: {watch.topic}",
        "",
        f"Schedule: {watch.schedule}",
        f"Enabled: {watch.enabled}",
        "",
        "## Links",
        *[f"- {link}" for link in links],
        "",
        "## Preferences",
        f"- Include: {', '.join(watch.include_keywords) or 'none'}",
        f"- Exclude: {', '.join(watch.exclude_keywords) or 'none'}",
        f"- Methods: {', '.join(watch.preferred_methods) or 'none'}",
        "",
        "> One-way reviewer export. Watch interests do not create evidence.",
    ]
    note = _write_note(
        export_id=export_id,
        export_type="watch",
        entity_id=watch.watch_id,
        note_dir=note_dir,
        filename=filename,
        frontmatter=frontmatter,
        links=links,
        body=body,
    )
    return ObsidianExportResult(
        export_id=export_id,
        export_type="watch",
        export_dir=str(export_dir),
        notes=[note],
        note_count=1,
        idempotent_key=note.sha256,
    )


def _write_note(
    *,
    export_id: str,
    export_type: ObsidianExportType,
    entity_id: str,
    note_dir: Path,
    filename: str,
    frontmatter: dict[str, Any],
    links: list[str],
    body: list[str],
) -> ObsidianNoteRecord:
    note_dir.mkdir(parents=True, exist_ok=True)
    path = note_dir / filename
    text = _frontmatter_text(frontmatter) + "\n".join(body).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return ObsidianNoteRecord(
        export_id=export_id,
        export_type=export_type,
        entity_id=entity_id,
        path=str(path),
        filename=filename,
        frontmatter=frontmatter,
        links=links,
        sha256=digest,
        generated_at=str(frontmatter["generated_at"]),
    )


def _base_frontmatter(
    *,
    note_type: ObsidianExportType,
    generated_at: str,
    run_id: str | None,
    project_id: str | None,
    retrieval_ids: list[str],
    evidence_ids: list[str],
) -> dict[str, Any]:
    return {
        "type": note_type,
        "paper_id": [],
        "pmid": [],
        "doi": [],
        "claim_id": [],
        "evidence_ids": evidence_ids,
        "retrieval_ids": retrieval_ids,
        "run_id": run_id,
        "project_id": project_id,
        "audit_verdict": None,
        "generated_at": generated_at,
        "source_of_truth": "biomed_sqlite",
        "imported_as_evidence": False,
    }


def _frontmatter_text(frontmatter: dict[str, Any]) -> str:
    lines = ["---"]
    for key in sorted(frontmatter):
        lines.append(f"{key}: {_yaml_value(frontmatter[key])}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _yaml_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[" + ", ".join(_yaml_scalar(item) for item in value) + "]"
    return _yaml_scalar(value)


def _yaml_scalar(value: Any) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower()
    return slug[:120] or "untitled"


def _safe_link(value: str) -> str:
    return re.sub(r"[\]\[\n\r]+", " ", value.strip())[:120] or "untitled"


def _paper_link_id(paper_id: str) -> str:
    pmid = _pmid_from_paper_id(paper_id)
    return f"pmid-{pmid}" if pmid else _safe_slug(paper_id)


def _pmid_from_paper_id(paper_id: str) -> str:
    clean = paper_id.strip()
    if clean.isdigit():
        return clean
    match = re.search(r"(?:pmid[:/-]?|mock-pmid-)(\d+)", paper_id, flags=re.I)
    return match.group(1) if match else ""


def _run_id_from_packet(packet: EvidencePacketSummary) -> str | None:
    prefix = "-retrieval-bundle"
    for retrieval_id in packet.retrieval_manifest_ids:
        if prefix in retrieval_id:
            return retrieval_id.split(prefix, 1)[0]
    return None


def _merge_links(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for item in group:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
    return result


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
