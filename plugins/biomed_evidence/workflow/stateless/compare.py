from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from asv_eval.core import TrajectoryRecord
from plugins.biomed_evidence.workflow.stateless.types import (
    ProjectionComparisonIssue,
    ProjectionComparisonSummary,
)

_CORE_STEPS = ("classify", "retrieve")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[^\s,;&]+"),
    re.compile(r"(?i)\bapi[_-]?key\s*=\s*[^&\s,;]+"),
    re.compile(r"(?i)\bbearer\s+(?!\[redacted\])[^\s,;&]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def compare_projections(
    old_projection: TrajectoryRecord,
    stateless_projection: TrajectoryRecord,
) -> ProjectionComparisonSummary:
    issues: list[ProjectionComparisonIssue] = []
    _check_task_surface(old_projection, stateless_projection, issues)
    _check_core_steps(stateless_projection, issues)
    _check_step_projection_fields(stateless_projection, issues)
    _check_quality_flags(stateless_projection, issues)
    return ProjectionComparisonSummary(
        ok=not any(issue.severity == "error" for issue in issues),
        old_step_count=len(old_projection.steps),
        stateless_step_count=len(stateless_projection.steps),
        issues=issues,
    )


def _check_task_surface(
    old_projection: TrajectoryRecord,
    stateless_projection: TrajectoryRecord,
    issues: list[ProjectionComparisonIssue],
) -> None:
    if old_projection.task.question != stateless_projection.task.question:
        issues.append(
            ProjectionComparisonIssue(
                code="question_mismatch",
                message="Old and stateless projections use different questions.",
            )
        )
    if asdict(old_projection.task.candidate_space) != asdict(
        stateless_projection.task.candidate_space
    ):
        issues.append(
            ProjectionComparisonIssue(
                code="candidate_space_mismatch",
                message="Old and stateless projections use different candidate spaces.",
            )
        )


def _check_core_steps(
    stateless_projection: TrajectoryRecord,
    issues: list[ProjectionComparisonIssue],
) -> None:
    stateless_step_names = [
        str(step.action.get("type") or step.step_id)
        for step in stateless_projection.steps
    ]
    for required_step in _CORE_STEPS:
        if required_step not in stateless_step_names:
            issues.append(
                ProjectionComparisonIssue(
                    code="missing_core_step",
                    message=f"Stateless projection is missing {required_step}.",
                )
            )


def _check_step_projection_fields(
    stateless_projection: TrajectoryRecord,
    issues: list[ProjectionComparisonIssue],
) -> None:
    for step in stateless_projection.steps:
        if not step.state_before or not step.state_after:
            issues.append(
                ProjectionComparisonIssue(
                    code="missing_state",
                    message=f"Step {step.step_id} is missing state_before/state_after.",
                )
            )
        if not step.action or not step.observation:
            issues.append(
                ProjectionComparisonIssue(
                    code="missing_projection_fields",
                    message=f"Step {step.step_id} is missing action or observation.",
                )
            )


def _check_quality_flags(
    stateless_projection: TrajectoryRecord,
    issues: list[ProjectionComparisonIssue],
) -> None:
    for step in stateless_projection.steps:
        leaked_value = _first_secret_like_quality_flag_value(step.quality_flags)
        if leaked_value is not None:
            issues.append(
                ProjectionComparisonIssue(
                    code="quality_flag_marker_leak",
                    message=(
                        f"Step {step.step_id} quality flags contain secret-like data."
                    ),
                )
            )
            break


def _first_secret_like_quality_flag_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for item in value.values():
            leaked = _first_secret_like_quality_flag_value(item)
            if leaked is not None:
                return leaked
        return None
    if isinstance(value, list | tuple):
        for item in value:
            leaked = _first_secret_like_quality_flag_value(item)
            if leaked is not None:
                return leaked
        return None
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
            return value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict | list):
            return _first_secret_like_quality_flag_value(parsed)
    return None
