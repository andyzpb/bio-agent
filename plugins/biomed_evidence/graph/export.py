from __future__ import annotations

import json
import re
from typing import Any

from plugins.biomed_evidence.graph.schema import BiomedEvidenceGraph

REDACTED_VALUE = "[redacted]"

_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "id_token",
    "idtoken",
    "password",
    "secret",
    "private_key",
    "privatekey",
    "client_secret",
    "clientsecret",
    "raw_prompt",
    "system_prompt",
    "developer_prompt",
    "user_prompt",
    "prompt",
    "messages",
    "chat_messages",
    "raw_provider_response",
    "provider_response",
    "raw_response",
    "request_body",
    "response_body",
)

_SECRET_STRING_PATTERNS = (
    re.compile(r"\b(?:sk|pk|rk|sess)-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{12,}\b", re.IGNORECASE),
    re.compile(
        r"\b(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*[^,\s;]+",
        re.IGNORECASE,
    ),
)


def graph_to_json_dict(
    graph: BiomedEvidenceGraph,
    *,
    redact: bool = True,
) -> dict[str, Any]:
    payload = graph.model_dump(mode="json")
    if not redact:
        return payload
    redacted = redact_graph_export(payload)
    if not isinstance(redacted, dict):
        raise TypeError("graph export redaction must preserve the top-level object")
    return redacted


def graph_to_json(
    graph: BiomedEvidenceGraph,
    *,
    indent: int | None = 2,
    redact: bool = True,
) -> str:
    return json.dumps(
        graph_to_json_dict(graph, redact=redact),
        ensure_ascii=False,
        indent=indent,
    )


def redact_graph_export(value: Any) -> Any:
    """Return a JSON-compatible graph export with sensitive fields removed."""
    return _redact_value(value, key=None)


def _redact_value(value: Any, *, key: str | None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return REDACTED_VALUE
    if isinstance(value, dict):
        return {
            str(item_key): _redact_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, key=None) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_string(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    collapsed = normalized.replace("_", "")
    return any(
        fragment in normalized or fragment in collapsed
        for fragment in _SENSITIVE_KEY_FRAGMENTS
    )


def _redact_sensitive_string(value: str) -> str:
    redacted = value
    for pattern in _SECRET_STRING_PATTERNS:
        redacted = pattern.sub(_string_replacement, redacted)
    return redacted


def _string_replacement(match: re.Match[str]) -> str:
    if match.re.groups >= 1:
        return f"{match.group(1)}={REDACTED_VALUE}"
    return REDACTED_VALUE
