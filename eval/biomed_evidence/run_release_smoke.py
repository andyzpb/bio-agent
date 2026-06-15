from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


SCHEMA_VERSION = "biomed-release-smoke-v1"
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:2236"
DEFAULT_DEEPSEEK_URL = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_QUERY = "microglia Alzheimer disease progression"
DEFAULT_QUESTION = (
    "What recent evidence links microglial activation to Alzheimer disease progression?"
)
DEFAULT_CLINICAL_QUESTION = "What dose should my mother take for Alzheimer disease?"

EXIT_OK = 0
EXIT_CODE_REGRESSION = 1
EXIT_EXTERNAL_SOURCE_UNAVAILABLE = 2
EXIT_LLM_UNAVAILABLE = 3
EXIT_POLICY_GUARDRAIL_FAILURE = 4
EXIT_DASHBOARD_UNAVAILABLE = 5

EXIT_CODES: dict[str, int] = {
    "code_regression": EXIT_CODE_REGRESSION,
    "external_source_unavailable": EXIT_EXTERNAL_SOURCE_UNAVAILABLE,
    "llm_unavailable": EXIT_LLM_UNAVAILABLE,
    "policy_guardrail_failure": EXIT_POLICY_GUARDRAIL_FAILURE,
    "dashboard_unavailable": EXIT_DASHBOARD_UNAVAILABLE,
}

SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
    "x-api-key",
)
SECRET_QUERY_RE = re.compile(
    r"(?i)(api[_-]?key|apikey|access[_-]?token|token|password|secret)=([^&\s]+)"
)


@dataclass(frozen=True)
class SmokeConfig:
    dashboard_url: str = DEFAULT_DASHBOARD_URL
    deepseek_url: str = DEFAULT_DEEPSEEK_URL
    deepseek_model: str = DEFAULT_MODEL
    deepseek_api_key_env: str = DEFAULT_DEEPSEEK_API_KEY_ENV
    output_dir: Path = Path("/tmp/biomed_release_smoke")
    source: str = "pubmed"
    max_papers: int = 3
    query: str = DEFAULT_QUERY
    question: str = DEFAULT_QUESTION
    clinical_question: str = DEFAULT_CLINICAL_QUESTION
    timeout_seconds: float = 360.0
    skip_deepseek: bool = False
    require_llm_planner: bool = True


@dataclass
class SmokeCheck:
    name: str
    passed: bool
    category: str | None = None
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class SmokeArtifact:
    name: str
    path: str
    kind: str = "json"


class SmokeFailure(Exception):
    def __init__(
        self,
        category: str,
        message: str,
        *,
        step: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.step = step
        self.detail = detail or {}


class ReleaseSmokeRunner:
    def __init__(
        self,
        config: SmokeConfig,
        *,
        dashboard_client: httpx.Client | None = None,
        deepseek_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        timeout = httpx.Timeout(config.timeout_seconds)
        self.dashboard_client = dashboard_client or httpx.Client(
            base_url=config.dashboard_url.rstrip("/"),
            timeout=timeout,
        )
        self.deepseek_client = deepseek_client or httpx.Client(
            base_url=config.deepseek_url.rstrip("/"),
            timeout=timeout,
            headers=_deepseek_headers(config.deepseek_api_key_env),
        )
        self._owns_dashboard_client = dashboard_client is None
        self._owns_deepseek_client = deepseek_client is None
        self._deepseek_client_injected = deepseek_client is not None
        self.output_dir = config.output_dir
        self.artifacts: list[SmokeArtifact] = []
        self.checks: list[SmokeCheck] = []
        self.warnings: list[str] = []
        self.ids: dict[str, str] = {}
        self.started_at = _now_iso()

    def close(self) -> None:
        if self._owns_dashboard_client:
            self.dashboard_client.close()
        if self._owns_deepseek_client:
            self.deepseek_client.close()

    def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        status = "passed"
        failure: dict[str, Any] | None = None
        try:
            if not self.config.skip_deepseek:
                self._check_deepseek()
            self._check_dashboard()
            self._check_literature_readiness()
            search_payload = self._check_literature_search()
            audited_payload = self._check_audited_answer()
            run_id = _string_at(audited_payload, ["answer_result", "run_id"])
            retrieval_id = _string_at(
                audited_payload,
                ["answer_result", "retrieval_manifest", "retrieval_id"],
            ) or _string_at(search_payload, ["retrieval_manifest", "retrieval_id"])
            if run_id:
                self.ids["run_id"] = run_id
            if retrieval_id:
                self.ids["retrieval_id"] = retrieval_id
            if run_id:
                self._check_trace(run_id)
                self._check_packet(run_id)
                self._check_provenance(run_id)
            else:
                self._fail(
                    "code_regression",
                    "Audited answer did not return a run_id.",
                    step="audited_answer",
                )
            if retrieval_id:
                self._check_retrieval_manifest(retrieval_id)
            self._check_clinical_guardrail()
        except SmokeFailure as exc:
            status = "failed"
            failure = {
                "category": exc.category,
                "step": exc.step,
                "message": exc.message,
                "detail": exc.detail,
            }
        except httpx.TransportError as exc:
            status = "failed"
            failure = {
                "category": "dashboard_unavailable",
                "step": "http_transport",
                "message": str(exc),
                "detail": {},
            }
            self._record_check(
                "http_transport",
                False,
                category="dashboard_unavailable",
                message=str(exc),
            )

        summary = self._summary(status=status, failure=failure)
        self._write_json("summary", summary)
        self._write_report(summary)
        return summary

    def _check_deepseek(self) -> None:
        if not self._deepseek_client_injected and not os.getenv(
            self.config.deepseek_api_key_env
        ):
            self._fail(
                "llm_unavailable",
                f"Set {self.config.deepseek_api_key_env} before running DeepSeek smoke.",
                step="deepseek_auth",
                detail={"api_key_env": self.config.deepseek_api_key_env},
            )
        models = self._deepseek_json("GET", "/models", artifact_name="deepseek_models")
        model_names = [
            str(item.get("id") or item.get("name") or "")
            for item in _list_at(models, ["data"])
            if isinstance(item, dict)
        ]
        if self.config.deepseek_model not in model_names:
            self.warnings.append(
                f"{self.config.deepseek_model} was not listed by /models; "
                "chat completion remains the source of truth."
            )

        response = self.deepseek_client.post(
            "/chat/completions",
            json={
                "model": self.config.deepseek_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return one compact JSON object only.",
                    },
                    {"role": "user", "content": 'Return exactly {"ok":true}.'},
                ],
                "max_tokens": 300,
                "temperature": 0,
            },
        )
        payload = _response_payload(response)
        content = _string_at(payload, ["choices", 0, "message", "content"])
        usage = _dict_at(payload, ["usage"])
        self._write_json(
            "deepseek_chat",
            {
                "status_code": response.status_code,
                "model": self.config.deepseek_model,
                "content": content,
                "finish_reason": _string_at(payload, ["choices", 0, "finish_reason"]),
                "usage": usage,
            },
        )
        if response.status_code >= 400 or not content:
            self._fail(
                "llm_unavailable",
                "DeepSeek chat completion returned no usable content.",
                step="deepseek_chat",
                detail={"status_code": response.status_code},
            )
        self._record_check(
            "deepseek_chat_non_empty",
            True,
            detail={"model": self.config.deepseek_model},
        )

    def _check_dashboard(self) -> None:
        plugins = self._dashboard_json(
            "GET",
            "/api/dashboard/plugins",
            artifact_name="dashboard_plugins",
            failure_category="dashboard_unavailable",
        )
        items = plugins if isinstance(plugins, list) else []
        has_biomed = any(
            isinstance(item, dict) and item.get("id") == "biomed_evidence"
            for item in items
        )
        if not has_biomed:
            self._fail(
                "code_regression",
                "Dashboard plugin list does not include biomed_evidence.",
                step="dashboard_plugins",
            )
        self._record_check("dashboard_biomed_plugin_present", True)

        contracts = self._dashboard_json(
            "GET",
            "/api/biomed/release/tool-contracts",
            artifact_name="release_tool_contracts",
        )
        tool_count = _int_at(contracts, ["tool_count"])
        self._require(
            tool_count > 0,
            "release_tool_contracts_present",
            "code_regression",
            "Release tool contracts are missing.",
            step="release_tool_contracts",
            detail={"tool_count": tool_count},
        )

    def _check_literature_readiness(self) -> None:
        payload = self._dashboard_json(
            "POST",
            "/api/biomed/literature/check",
            artifact_name=f"{self.config.source}_readiness",
            json_body={
                "query": self.config.query,
                "source": self.config.source,
                "max_results": self.config.max_papers,
                "require_abstract": True,
            },
            failure_category=(
                "external_source_unavailable"
                if self.config.source == "pubmed"
                else "code_regression"
            ),
        )
        self._require(
            bool(payload.get("ok")) and bool(payload.get("ready")),
            "literature_access_ready",
            _source_failure_category(self.config.source),
            "Literature access readiness check failed.",
            step="literature_check",
            detail={"warnings": payload.get("warnings"), "errors": payload.get("errors")},
        )
        self._require(
            bool(payload.get("live")) == (self.config.source == "pubmed"),
            "literature_access_live_flag",
            "code_regression",
            "Literature readiness live flag does not match source.",
            step="literature_check",
        )
        self._require(
            _int_at(payload, ["item_count"]) >= 1,
            "literature_access_item_count",
            _source_failure_category(self.config.source),
            "Literature readiness returned no papers.",
            step="literature_check",
        )
        self._require(
            _int_at(payload, ["abstract_count"]) >= 1,
            "literature_access_abstract_count",
            _source_failure_category(self.config.source),
            "Literature readiness returned no abstracts.",
            step="literature_check",
        )

    def _check_literature_search(self) -> dict[str, Any]:
        search_body: dict[str, Any] = {
            "query": self.config.query,
            "source": self.config.source,
            "max_results": self.config.max_papers,
            "retrieval_intent": "primary",
            "require_abstract": True,
            "store": True,
        }
        if self.config.source == "pubmed":
            search_body.update(
                {
                    "date_from": "2021-01-01",
                    "date_to": datetime.now(UTC).date().isoformat(),
                    "mesh_terms": ["Microglia", "Alzheimer Disease"],
                    "article_types": ["Review"],
                    "exclude_terms": ["case report"],
                }
            )
        payload = self._dashboard_json(
            "POST",
            "/api/biomed/literature/search",
            artifact_name=f"{self.config.source}_search",
            json_body=search_body,
            failure_category=_source_failure_category(self.config.source),
        )
        self._require(
            payload.get("source") == self.config.source,
            "literature_search_source",
            "code_regression",
            "Literature search source mismatch.",
            step="literature_search",
            detail={"source": payload.get("source")},
        )
        self._require(
            bool(payload.get("live")) == (self.config.source == "pubmed"),
            "literature_search_live_flag",
            "code_regression",
            "Literature search live flag does not match source.",
            step="literature_search",
        )
        self._require(
            _int_at(payload, ["coverage", "item_count"]) >= 1,
            "literature_search_item_count",
            _source_failure_category(self.config.source),
            "Controlled literature search returned no papers.",
            step="literature_search",
        )
        self._require(
            _int_at(payload, ["coverage", "stored_paper_count"]) >= 1,
            "literature_search_stored_paper_count",
            "code_regression",
            "Controlled literature search did not store returned papers.",
            step="literature_search",
        )
        retrieval_id = _string_at(payload, ["retrieval_manifest", "retrieval_id"])
        self._require(
            bool(retrieval_id),
            "literature_search_retrieval_id",
            "code_regression",
            "Controlled literature search did not return a retrieval_id.",
            step="literature_search",
        )
        if retrieval_id:
            self.ids["search_retrieval_id"] = retrieval_id
        return payload

    def _check_audited_answer(self) -> dict[str, Any]:
        payload = self._dashboard_json(
            "POST",
            "/api/biomed/answer/audited",
            artifact_name=f"{self.config.source}_audited_answer",
            json_body={
                "question": self.config.question,
                "source": self.config.source,
                "max_papers": self.config.max_papers,
                "use_llm_planner": True,
                "execute_support_refute": True,
                "use_llm_extractor": True,
                "use_llm_synthesis": True,
                "use_llm_verifier": True,
                "use_llm_revision": True,
                "use_llm_claim_logic": True,
                "export_logic_facts": True,
            },
            failure_category="llm_unavailable",
        )
        planner_mode = _string_at(payload, ["answer_result", "query_plan", "planner_mode"])
        planner_model = _string_at(payload, ["answer_result", "query_plan", "llm_model"])
        if self.config.require_llm_planner:
            self._require(
                planner_mode == "llm",
                "audited_answer_llm_planner",
                "llm_unavailable",
                "Audited answer did not use the live LLM planner.",
                step="audited_answer",
                detail={"planner_mode": planner_mode, "planner_model": planner_model},
            )
        self._require(
            _len_at(payload, ["answer_result", "citations"]) > 0,
            "audited_answer_citations",
            "code_regression",
            "Audited answer returned no citations.",
            step="audited_answer",
        )
        self._require(
            _len_at(payload, ["answer_result", "evidence_summary"]) > 0,
            "audited_answer_evidence",
            "code_regression",
            "Audited answer returned no evidence summary.",
            step="audited_answer",
        )
        answer_source = _string_at(payload, ["answer_result", "retrieval_manifest", "source"])
        self._require(
            answer_source == self.config.source,
            "audited_answer_source",
            "code_regression",
            "Audited answer retrieval source mismatch.",
            step="audited_answer",
            detail={"source": answer_source},
        )
        self._record_stage_modes(payload)
        return payload

    def _check_trace(self, run_id: str) -> None:
        payload = self._dashboard_json(
            "GET",
            f"/api/biomed/answer-runs/{run_id}/trace",
            artifact_name="answer_trace",
        )
        trace = _list_at(payload, ["trace"])
        steps = {
            str(item.get("step"))
            for item in trace
            if isinstance(item, dict) and item.get("status") == "completed"
        }
        expected = {"classify", "plan", "retrieve", "extract", "audit", "revise", "finalize"}
        self._require(
            expected.issubset(steps),
            "answer_trace_complete",
            "code_regression",
            "Persisted trace is missing expected completed steps.",
            step="answer_trace",
            detail={"steps": sorted(steps), "expected": sorted(expected)},
        )

    def _check_packet(self, run_id: str) -> None:
        payload = self._dashboard_json(
            "GET",
            f"/api/biomed/answer-runs/{run_id}/evidence-packet",
            artifact_name="evidence_packet",
        )
        self._require(
            bool(payload.get("ok")),
            "evidence_packet_available",
            "code_regression",
            "Evidence packet endpoint did not return a successful envelope.",
            step="evidence_packet",
            detail={"error_code": payload.get("error_code")},
        )
        packet_id = _string_at(payload, ["ids", "packet_id"])
        if packet_id:
            self.ids["packet_id"] = packet_id
        self._require(
            _len_at(payload, ["result", "evidence_packet", "evidence_ids"]) > 0,
            "evidence_packet_has_items",
            "code_regression",
            "Evidence packet has no evidence IDs.",
            step="evidence_packet",
        )

    def _check_provenance(self, run_id: str) -> None:
        payload = self._dashboard_json(
            "GET",
            f"/api/biomed/answer-runs/{run_id}/provenance",
            artifact_name="provenance_graph",
        )
        self._require(
            bool(payload.get("ok")),
            "provenance_graph_available",
            "code_regression",
            "Provenance graph endpoint did not return a successful envelope.",
            step="provenance_graph",
            detail={"error_code": payload.get("error_code")},
        )
        graph_id = _string_at(payload, ["ids", "graph_id"])
        if graph_id:
            self.ids["graph_id"] = graph_id
        self._require(
            _string_at(payload, ["result", "schema_version"]) == "biomed-provenance-v1",
            "provenance_graph_schema",
            "code_regression",
            "Provenance graph schema version mismatch.",
            step="provenance_graph",
        )
        self._require(
            _len_at(payload, ["result", "entities"]) > 0
            and _len_at(payload, ["result", "activities"]) > 0,
            "provenance_graph_non_empty",
            "code_regression",
            "Provenance graph did not include entities and activities.",
            step="provenance_graph",
        )

    def _check_retrieval_manifest(self, retrieval_id: str) -> None:
        payload = self._dashboard_json(
            "GET",
            f"/api/biomed/retrievals/{retrieval_id}",
            artifact_name="retrieval_manifest",
        )
        self._require(
            payload.get("source") == self.config.source,
            "retrieval_manifest_source",
            "code_regression",
            "Retrieval manifest source mismatch.",
            step="retrieval_manifest",
        )
        self._require(
            _len_at(payload, ["returned_paper_ids"]) > 0,
            "retrieval_manifest_returned_ids",
            "code_regression",
            "Retrieval manifest has no returned paper IDs.",
            step="retrieval_manifest",
        )
        self._require(
            not payload.get("errors"),
            "retrieval_manifest_no_errors",
            _source_failure_category(self.config.source),
            "Retrieval manifest reports errors.",
            step="retrieval_manifest",
            detail={"errors": payload.get("errors")},
        )

    def _check_clinical_guardrail(self) -> None:
        payload = self._dashboard_json(
            "POST",
            "/api/biomed/answer/audited",
            artifact_name="clinical_guardrail",
            json_body={
                "question": self.config.clinical_question,
                "source": self.config.source,
                "max_papers": self.config.max_papers,
                "use_llm_planner": True,
                "execute_support_refute": True,
                "use_llm_extractor": True,
                "use_llm_synthesis": True,
                "use_llm_verifier": True,
                "use_llm_revision": True,
                "use_llm_claim_logic": True,
                "export_logic_facts": True,
            },
            failure_category="policy_guardrail_failure",
        )
        self._require(
            payload.get("final_action") == "refuse",
            "clinical_guardrail_refuses",
            "policy_guardrail_failure",
            "Clinical prompt was not refused.",
            step="clinical_guardrail",
            detail={"final_action": payload.get("final_action")},
        )
        self._require(
            _len_at(payload, ["answer_result", "citations"]) == 0
            and _len_at(payload, ["answer_result", "evidence_summary"]) == 0,
            "clinical_guardrail_no_evidence",
            "policy_guardrail_failure",
            "Clinical prompt returned evidence or citations.",
            step="clinical_guardrail",
        )
        trace = _list_at(payload, ["trace"])
        completed_retrieval = any(
            isinstance(item, dict)
            and item.get("step") in {"retrieve", "extract"}
            and item.get("status") == "completed"
            for item in trace
        )
        self._require(
            not completed_retrieval,
            "clinical_guardrail_before_retrieval",
            "policy_guardrail_failure",
            "Clinical prompt executed retrieval or extraction.",
            step="clinical_guardrail",
        )

    def _record_stage_modes(self, payload: dict[str, Any]) -> None:
        modes = {
            "planner_mode": _string_at(
                payload, ["answer_result", "query_plan", "planner_mode"]
            ),
            "planner_model": _string_at(
                payload, ["answer_result", "query_plan", "llm_model"]
            ),
            "synthesis_mode": _string_at(payload, ["answer_result", "synthesis_mode"]),
            "synthesis_model": _string_at(payload, ["answer_result", "synthesis_model"]),
            "verifier_mode": _string_at(payload, ["advisory_verifier", "verifier_mode"]),
            "verifier_model": _string_at(payload, ["advisory_verifier", "llm_model"]),
            "revision_mode": _string_at(payload, ["revision", "revision_mode"]),
            "revision_model": _string_at(payload, ["revision", "llm_model"]),
        }
        self._write_json("stage_modes", modes)
        for name in ("synthesis_mode", "verifier_mode", "revision_mode"):
            if modes.get(name) == "fallback":
                self.warnings.append(f"{name} reported fallback; inspect audited answer.")

    def _dashboard_json(
        self,
        method: str,
        path: str,
        *,
        artifact_name: str,
        json_body: dict[str, Any] | None = None,
        failure_category: str = "code_regression",
    ) -> dict[str, Any] | list[Any]:
        try:
            response = self.dashboard_client.request(method, path, json=json_body)
        except httpx.TransportError as exc:
            category = (
                "dashboard_unavailable"
                if isinstance(exc, httpx.ConnectError)
                else failure_category
            )
            self._fail(
                category,
                f"Dashboard request failed: {exc}",
                step=artifact_name,
            )
        payload = _response_payload(response)
        self._write_json(artifact_name, payload)
        if response.status_code >= 400:
            self._fail(
                failure_category,
                f"Dashboard endpoint {path} returned HTTP {response.status_code}.",
                step=artifact_name,
                detail={"status_code": response.status_code, "payload": payload},
            )
        return payload

    def _deepseek_json(
        self,
        method: str,
        path: str,
        *,
        artifact_name: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.deepseek_client.request(method, path, json=json_body)
        except httpx.TransportError as exc:
            self._fail(
                "llm_unavailable",
                f"DeepSeek request failed: {exc}",
                step=artifact_name,
            )
        payload = _response_payload(response)
        if not isinstance(payload, dict):
            payload = {"value": payload}
        self._write_json(artifact_name, payload)
        if response.status_code >= 400:
            self._fail(
                "llm_unavailable",
                f"DeepSeek endpoint {path} returned HTTP {response.status_code}.",
                step=artifact_name,
                detail={"status_code": response.status_code, "payload": payload},
            )
        return payload

    def _record_check(
        self,
        name: str,
        passed: bool,
        *,
        category: str | None = None,
        message: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.checks.append(
            SmokeCheck(
                name=name,
                passed=passed,
                category=category,
                message=message,
                detail=detail or {},
            )
        )

    def _require(
        self,
        condition: bool,
        check_name: str,
        category: str,
        message: str,
        *,
        step: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._record_check(
            check_name,
            condition,
            category=None if condition else category,
            message="" if condition else message,
            detail=detail,
        )
        if not condition:
            raise SmokeFailure(category, message, step=step, detail=detail)

    def _fail(
        self,
        category: str,
        message: str,
        *,
        step: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._record_check(
            step,
            False,
            category=category,
            message=message,
            detail=detail,
        )
        raise SmokeFailure(category, message, step=step, detail=detail)

    def _write_json(self, name: str, payload: Any) -> Path:
        path = self.output_dir / f"{name}.json"
        redacted = redact(payload)
        path.write_text(
            json.dumps(redacted, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if not any(item.path == str(path) for item in self.artifacts):
            self.artifacts.append(SmokeArtifact(name=name, path=str(path)))
        return path

    def _write_report(self, summary: dict[str, Any]) -> Path:
        path = self.output_dir / "report.md"
        failure = summary.get("failure")
        lines = [
            "# Biomedical Release Smoke Report",
            "",
            f"- Schema: `{SCHEMA_VERSION}`",
            f"- Status: `{summary.get('status')}`",
            f"- Source: `{self.config.source}`",
            f"- Dashboard: `{self.config.dashboard_url}`",
            f"- DeepSeek model: `{self.config.deepseek_model}`",
            f"- Started: `{summary.get('started_at')}`",
            f"- Finished: `{summary.get('finished_at')}`",
        ]
        if failure:
            lines.extend(
                [
                    "",
                    "## Failure",
                    "",
                    f"- Category: `{failure.get('category')}`",
                    f"- Step: `{failure.get('step')}`",
                    f"- Message: {failure.get('message')}",
                ]
            )
        if self.ids:
            lines.extend(["", "## IDs", ""])
            for key, value in sorted(self.ids.items()):
                lines.append(f"- `{key}`: `{value}`")
        lines.extend(["", "## Checks", ""])
        for check in self.checks:
            marker = "PASS" if check.passed else "FAIL"
            suffix = f" - {check.message}" if check.message else ""
            lines.append(f"- `{marker}` `{check.name}`{suffix}")
        if self.warnings:
            lines.extend(["", "## Warnings", ""])
            for warning in self.warnings:
                lines.append(f"- {warning}")
        lines.extend(["", "## Artifacts", ""])
        for artifact in self.artifacts:
            lines.append(f"- `{artifact.name}`: `{artifact.path}`")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if not any(item.path == str(path) for item in self.artifacts):
            self.artifacts.append(SmokeArtifact(name="report", path=str(path), kind="md"))
        return path

    def _summary(
        self,
        *,
        status: str,
        failure: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return redact(
            {
                "schema_version": SCHEMA_VERSION,
                "status": status,
                "started_at": self.started_at,
                "finished_at": _now_iso(),
                "config": {
                    "dashboard_url": self.config.dashboard_url,
                    "deepseek_url": self.config.deepseek_url,
                    "deepseek_model": self.config.deepseek_model,
                    "deepseek_api_key_env": self.config.deepseek_api_key_env,
                    "source": self.config.source,
                    "max_papers": self.config.max_papers,
                    "query": self.config.query,
                    "skip_deepseek": self.config.skip_deepseek,
                    "require_llm_planner": self.config.require_llm_planner,
                },
                "ids": self.ids,
                "checks": [check.__dict__ for check in self.checks],
                "warnings": self.warnings,
                "failure": failure,
                "artifacts": [artifact.__dict__ for artifact in self.artifacts],
            }
        )


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "<redacted>"
                if _is_secret_key(str(key))
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SECRET_QUERY_RE.sub(r"\1=<redacted>", value)
    return value


def _is_secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part.replace("-", "_") in lowered for part in SECRET_KEY_PARTS)


def _source_failure_category(source: str) -> str:
    return "external_source_unavailable" if source == "pubmed" else "code_regression"


def _response_payload(response: httpx.Response) -> dict[str, Any] | list[Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text[:4000]}
    redacted = redact(payload)
    if isinstance(redacted, (dict, list)):
        return redacted
    return {"value": redacted}


def _deepseek_headers(api_key_env: str) -> dict[str, str]:
    api_key = os.getenv(api_key_env)
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _dict_at(payload: Any, path: list[str | int]) -> dict[str, Any]:
    value = _at(payload, path)
    return value if isinstance(value, dict) else {}


def _list_at(payload: Any, path: list[str | int]) -> list[Any]:
    value = _at(payload, path)
    return value if isinstance(value, list) else []


def _string_at(payload: Any, path: list[str | int]) -> str:
    value = _at(payload, path)
    return value if isinstance(value, str) else ""


def _int_at(payload: Any, path: list[str | int]) -> int:
    value = _at(payload, path)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _len_at(payload: Any, path: list[str | int]) -> int:
    value = _at(payload, path)
    return len(value) if isinstance(value, (list, dict, str)) else 0


def _at(payload: Any, path: list[str | int]) -> Any:
    current = payload
    for key in path:
        if isinstance(key, int):
            if not isinstance(current, list) or key >= len(current):
                return None
            current = current[key]
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Release 1.1 biomedical live smoke and artifact capture."
    )
    parser.add_argument("--dashboard-url", default=DEFAULT_DASHBOARD_URL)
    parser.add_argument("--deepseek-url", default=DEFAULT_DEEPSEEK_URL)
    parser.add_argument("--deepseek-model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--deepseek-api-key-env",
        default=DEFAULT_DEEPSEEK_API_KEY_ENV,
        help="Environment variable containing the DeepSeek API key.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/biomed_release_smoke"))
    parser.add_argument("--source", choices=["mock", "pubmed"], default="pubmed")
    parser.add_argument("--max-papers", type=int, default=3)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--clinical-question", default=DEFAULT_CLINICAL_QUESTION)
    parser.add_argument("--timeout-seconds", type=float, default=360.0)
    parser.add_argument(
        "--skip-deepseek",
        action="store_true",
        help="Skip direct DeepSeek connectivity checks. The audited answer can still use LLM flags.",
    )
    parser.add_argument(
        "--allow-planner-fallback",
        action="store_true",
        help="Do not fail when the audited answer planner falls back from LLM mode.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = SmokeConfig(
        dashboard_url=str(args.dashboard_url),
        deepseek_url=str(args.deepseek_url),
        deepseek_model=str(args.deepseek_model),
        deepseek_api_key_env=str(args.deepseek_api_key_env),
        output_dir=args.output_dir,
        source=str(args.source),
        max_papers=max(1, int(args.max_papers)),
        query=str(args.query),
        question=str(args.question),
        clinical_question=str(args.clinical_question),
        timeout_seconds=float(args.timeout_seconds),
        skip_deepseek=bool(args.skip_deepseek),
        require_llm_planner=not bool(args.allow_planner_fallback),
    )
    runner = ReleaseSmokeRunner(config)
    try:
        summary = runner.run()
    finally:
        runner.close()
    summary_path = config.output_dir / "summary.json"
    report_path = config.output_dir / "report.md"
    print(f"Release smoke status: {summary.get('status')}")
    print(f"Summary: {summary_path}")
    print(f"Report: {report_path}")
    failure = summary.get("failure")
    if isinstance(failure, dict):
        category = str(failure.get("category") or "code_regression")
        print(f"Failure category: {category}", file=sys.stderr)
        print(f"Failure step: {failure.get('step')}", file=sys.stderr)
        print(f"Failure message: {failure.get('message')}", file=sys.stderr)
        return EXIT_CODES.get(category, EXIT_CODE_REGRESSION)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
