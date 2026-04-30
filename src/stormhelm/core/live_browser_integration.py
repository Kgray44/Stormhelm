from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import threading
from time import perf_counter
from typing import Any, Mapping
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.core.screen_awareness.browser_playwright import PlaywrightBrowserSemanticAdapter
from stormhelm.core.screen_awareness.models import BrowserSemanticControl, BrowserSemanticObservation
from stormhelm.core.web_retrieval.cdp import ObscuraCDPCompatibilityProbe
from stormhelm.core.web_retrieval.models import (
    CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
    CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
    WebRetrievalRequest,
)
from stormhelm.core.web_retrieval.safety import safe_url_display, validate_public_url
from stormhelm.core.web_retrieval.service import WebRetrievalService
from stormhelm.shared.time import utc_now_iso


STATUS_PASSED = "passed"
STATUS_SKIPPED = "skipped"
STATUS_UNAVAILABLE = "unavailable"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_INCOMPATIBLE = "incompatible"

CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION = "browser_semantic_observation"
_REPORT_LIMIT = 500
_DETAIL_LIMIT = 40
_TEXT_LIMIT = 240
_SENSITIVE_RE = re.compile(
    r"(?i)(secret-token|password=[^&\s]+|token=[^&\s]+|api[_-]?key=[^&\s]+|credential[^&\s]*)"
)
_TRUTHFUL_LIMITATIONS = [
    "not_truth_verified",
    "not_user_visible_screen",
    "no_actions",
]


@dataclass(slots=True)
class LiveBrowserIntegrationGates:
    live_browser_tests: bool = False
    enable_obscura: bool = False
    enable_obscura_cdp: bool = False
    enable_playwright: bool = False
    playwright_allow_browser_launch: bool = False
    live_browser_test_url: str = ""
    obscura_binary: str = "obscura"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LiveBrowserIntegrationGates":
        values = os.environ if env is None else env
        return cls(
            live_browser_tests=_env_bool(values, "STORMHELM_LIVE_BROWSER_TESTS"),
            enable_obscura=_env_bool(values, "STORMHELM_ENABLE_LIVE_OBSCURA"),
            enable_obscura_cdp=_env_bool(values, "STORMHELM_ENABLE_LIVE_OBSCURA_CDP"),
            enable_playwright=_env_bool(values, "STORMHELM_ENABLE_LIVE_PLAYWRIGHT"),
            playwright_allow_browser_launch=_env_bool(values, "STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH"),
            live_browser_test_url=str(values.get("STORMHELM_LIVE_BROWSER_TEST_URL") or "").strip(),
            obscura_binary=str(
                values.get("STORMHELM_OBSCURA_BINARY")
                or values.get("STORMHELM_OBSCURA_BINARY_PATH")
                or "obscura"
            ).strip()
            or "obscura",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "live_browser_tests": self.live_browser_tests,
            "enable_obscura": self.enable_obscura,
            "enable_obscura_cdp": self.enable_obscura_cdp,
            "enable_playwright": self.enable_playwright,
            "playwright_allow_browser_launch": self.playwright_allow_browser_launch,
            "live_browser_test_url": safe_url_display(self.live_browser_test_url) if self.live_browser_test_url else "",
            "obscura_binary": _safe_path_display(self.obscura_binary),
        }


@dataclass(slots=True)
class LiveBrowserIntegrationResult:
    provider: str
    status: str
    enabled: bool = False
    duration_ms: float = 0.0
    claim_ceiling: str = ""
    error_code: str = ""
    bounded_error_message: str = ""
    limitations: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    cleanup_status: str = ""
    safety_gates_active: bool = True
    action_capabilities_disabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "enabled": self.enabled,
            "duration_ms": round(float(self.duration_ms or 0.0), 3),
            "claim_ceiling": self.claim_ceiling,
            "error_code": _bounded_safe(self.error_code, 120),
            "bounded_error_message": _bounded_safe(self.bounded_error_message, _REPORT_LIMIT),
            "limitations": _bounded_list(self.limitations),
            "details": _sanitize_mapping(self.details),
            "cleanup_status": _bounded_safe(self.cleanup_status, 120),
            "safety_gates_active": bool(self.safety_gates_active),
            "action_capabilities_disabled": bool(self.action_capabilities_disabled),
        }


@dataclass(slots=True)
class LiveBrowserIntegrationReport:
    report_id: str = field(default_factory=lambda: f"live-browser-{uuid4().hex[:12]}")
    started_at: str = field(default_factory=utc_now_iso)
    completed_at: str = ""
    gates: LiveBrowserIntegrationGates = field(default_factory=LiveBrowserIntegrationGates)
    results: dict[str, LiveBrowserIntegrationResult] = field(default_factory=dict)
    safety_gates_active: dict[str, Any] = field(default_factory=dict)
    action_capabilities_disabled: bool = True
    raw_output_redacted: bool = True

    @property
    def overall_status(self) -> str:
        if not self.results:
            return STATUS_SKIPPED
        statuses = {result.status for result in self.results.values()}
        if statuses == {STATUS_SKIPPED}:
            return STATUS_SKIPPED
        if (
            STATUS_INCOMPATIBLE in statuses
            and any(status == STATUS_PASSED for status in statuses)
            and any(
                result.provider == "obscura_cdp"
                and result.error_code == "cdp_navigation_unsupported"
                and bool(result.details.get("diagnostic_only", False) or result.status == STATUS_INCOMPATIBLE)
                for result in self.results.values()
            )
        ):
            return STATUS_PARTIAL
        if STATUS_FAILED in statuses:
            return STATUS_FAILED
        if STATUS_INCOMPATIBLE in statuses:
            return STATUS_INCOMPATIBLE
        if STATUS_PARTIAL in statuses:
            return STATUS_PARTIAL
        if STATUS_UNAVAILABLE in statuses:
            return STATUS_UNAVAILABLE
        if STATUS_PASSED in statuses:
            return STATUS_PASSED
        return STATUS_SKIPPED

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at or utc_now_iso(),
            "overall_status": self.overall_status,
            "gates": self.gates.to_dict(),
            "results": {key: value.to_dict() for key, value in self.results.items()},
            "safety_gates_active": _sanitize_mapping(self.safety_gates_active),
            "action_capabilities_disabled": self.action_capabilities_disabled,
            "claim_ceilings": {
                "obscura_cli": CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
                "obscura_cdp": CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                "playwright": CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
            },
            "limitations": [
                "live_provider_checks_are_opt_in",
                "normal_ci_skips_live_dependencies",
                "no_browser_actions",
                "no_logged_in_context",
                "not_visible_screen_verification",
                "not_truth_verified",
                *(
                    ["Obscura CDP endpoint exists, but navigation/page inspection is unsupported by this release."]
                    if any(
                        result.provider == "obscura_cdp" and result.error_code == "cdp_navigation_unsupported"
                        for result in self.results.values()
                    )
                    else []
                ),
            ],
            "raw_output_redacted": self.raw_output_redacted,
        }


def apply_live_browser_profile(config: AppConfig, gates: LiveBrowserIntegrationGates) -> AppConfig:
    live_config = deepcopy(config)
    if gates.enable_obscura or gates.enable_obscura_cdp:
        live_config.web_retrieval.enabled = True
        live_config.web_retrieval.obscura.enabled = gates.enable_obscura
        live_config.web_retrieval.obscura.binary_path = gates.obscura_binary
        live_config.web_retrieval.obscura.allow_js_eval = False
        live_config.web_retrieval.obscura.stealth_enabled = False
    if gates.enable_obscura_cdp:
        cdp = live_config.web_retrieval.obscura.cdp
        cdp.enabled = True
        cdp.binary_path = gates.obscura_binary
        cdp.host = "127.0.0.1"
        cdp.port = 0
        cdp.allow_runtime_eval = False
        cdp.allow_input_domain = False
        cdp.allow_cookies = False
        cdp.allow_logged_in_context = False
        cdp.allow_screenshots = False
    if gates.enable_playwright:
        playwright = live_config.screen_awareness.browser_adapters.playwright
        playwright.enabled = True
        playwright.provider = "playwright"
        playwright.mode = "semantic_observation"
        playwright.allow_dev_adapter = True
        playwright.allow_browser_launch = bool(gates.playwright_allow_browser_launch)
        playwright.allow_connect_existing = False
        playwright.allow_actions = False
        playwright.allow_click = False
        playwright.allow_focus = False
        playwright.allow_type_text = False
        playwright.allow_scroll = False
        playwright.allow_form_fill = False
        playwright.allow_form_submit = False
        playwright.allow_login = False
        playwright.allow_cookies = False
        playwright.allow_user_profile = False
        playwright.allow_screenshots = False
        playwright.allow_dev_actions = False
    return live_config


class LiveBrowserFixtureServer:
    def __init__(self, host: str = "127.0.0.1") -> None:
        self.host = host
        self.port = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "LiveBrowserFixtureServer":
        server = ThreadingHTTPServer((self.host, 0), _FixtureHandler)
        self._server = server
        self.port = int(server.server_port)
        self._thread = threading.Thread(target=server.serve_forever, name="stormhelm-live-fixture", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def url(self, path: str = "/static.html") -> str:
        suffix = path if str(path).startswith("/") else f"/{path}"
        return f"http://{self.host}:{self.port}{suffix}"


class LiveBrowserIntegrationRunner:
    def __init__(self, config: AppConfig, *, gates: LiveBrowserIntegrationGates | None = None) -> None:
        self.gates = gates or LiveBrowserIntegrationGates.from_env()
        self.config = apply_live_browser_profile(config, self.gates)

    def run_all(self) -> LiveBrowserIntegrationReport:
        report = LiveBrowserIntegrationReport(
            gates=self.gates,
            safety_gates_active={
                "live_browser_tests": self.gates.live_browser_tests,
                "obscura_enabled": self.gates.enable_obscura,
                "obscura_cdp_enabled": self.gates.enable_obscura_cdp,
                "playwright_enabled": self.gates.enable_playwright,
                "playwright_browser_launch_allowed": self.gates.playwright_allow_browser_launch,
                "actions_disabled": True,
                "localhost_binding_only": True,
            },
            action_capabilities_disabled=True,
        )
        report.results["obscura_cli"] = self.run_obscura_cli_check()
        report.results["obscura_cdp"] = self.run_obscura_cdp_check()
        report.results["playwright_readiness"] = self.run_playwright_readiness_check()
        report.results["playwright_semantic_observation"] = self.run_playwright_semantic_observation_check()
        report.completed_at = utc_now_iso()
        return report

    def run_obscura_cli_check(self) -> LiveBrowserIntegrationResult:
        started = perf_counter()
        if not self.gates.live_browser_tests or not self.gates.enable_obscura:
            return self._skipped("obscura_cli", CLAIM_CEILING_RENDERED_PAGE_EVIDENCE, "live_obscura_gate_not_enabled", started)
        binary = _resolve_binary(self.gates.obscura_binary)
        if not binary:
            return self._unavailable(
                "obscura_cli",
                CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
                "binary_missing",
                started,
                details={"binary_path": self.gates.obscura_binary, "binary_found": False},
            )
        safety = self._safe_public_test_url()
        if not safety["allowed"]:
            return self._skipped(
                "obscura_cli",
                CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
                safety["error_code"],
                started,
                details=safety,
            )
        request = WebRetrievalRequest(
            urls=[str(safety["normalized_url"])],
            intent="live_obscura_cli_smoke",
            preferred_provider="obscura",
            require_rendering=True,
            include_links=True,
            include_html=False,
            max_text_chars=4000,
        )
        bundle = WebRetrievalService(self.config.web_retrieval).retrieve(request)
        page = bundle.pages[0] if bundle.pages else None
        if page is None:
            return self._failed("obscura_cli", CLAIM_CEILING_RENDERED_PAGE_EVIDENCE, "no_page_result", started)
        status = STATUS_PASSED if page.status in {"success", "partial"} and (page.text_chars or page.link_count or page.title) else STATUS_FAILED
        return LiveBrowserIntegrationResult(
            provider="obscura_cli",
            status=status,
            enabled=True,
            duration_ms=_elapsed(started),
            claim_ceiling=CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
            error_code=page.error_code if status != STATUS_PASSED else "",
            bounded_error_message=page.error_message if status != STATUS_PASSED else "",
            limitations=_limit_truthfulness(page.limitations),
            details={
                "underlying_provider": page.provider,
                "page_status": page.status,
                "safe_url_display": safe_url_display(page.final_url or page.requested_url),
                "title_present": bool(page.title),
                "text_chars": page.text_chars,
                "links_found": page.link_count,
                "rendered_javascript": page.rendered_javascript,
            },
        )

    def run_obscura_cdp_check(self) -> LiveBrowserIntegrationResult:
        started = perf_counter()
        if not self.gates.live_browser_tests or not self.gates.enable_obscura_cdp:
            return self._skipped("obscura_cdp", CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE, "live_obscura_cdp_gate_not_enabled", started)
        binary = _resolve_binary(self.gates.obscura_binary)
        if not binary:
            return self._unavailable(
                "obscura_cdp",
                CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                "binary_missing",
                started,
                details={"binary_path": self.gates.obscura_binary, "binary_found": False},
            )
        compat = ObscuraCDPCompatibilityProbe(self.config.web_retrieval.obscura.cdp).run()
        compat_payload = compat.to_dict()
        details: dict[str, Any] = {
            "compatibility_level": compat.compatibility_level,
            "compatible": compat.compatible,
            "version_endpoint_status": compat.version_endpoint_status,
            "page_list_endpoint_status": compat.page_list_endpoint_status,
            "browser_websocket_url_found": compat.browser_websocket_url_found,
            "page_websocket_url_found": compat.page_websocket_url_found,
            "protocol_version": compat.protocol_version,
            "browser_name": compat.browser_name,
            "cleanup_status": compat.cleanup_status,
            "blocking_reasons": list(compat.blocking_reasons),
            "warnings": list(compat.warnings),
            "endpoint_discovered": bool(getattr(compat, "endpoint_discovered", False)),
            "navigation_supported": bool(getattr(compat, "navigation_supported", False)),
            "page_inspection_supported": bool(getattr(compat, "page_inspection_supported", False)),
            "extraction_supported": bool(getattr(compat, "extraction_supported", False)),
            "diagnostic_only": bool(getattr(compat, "diagnostic_only", False)),
            "recommended_fallback_provider": str(getattr(compat, "recommended_fallback_provider", "") or ""),
        }
        if not compat.compatible:
            status = STATUS_INCOMPATIBLE if compat.compatibility_level == "unsupported" else STATUS_PARTIAL
            return LiveBrowserIntegrationResult(
                provider="obscura_cdp",
                status=status,
                enabled=True,
                duration_ms=_elapsed(started),
                claim_ceiling=CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                error_code="cdp_incompatible",
                bounded_error_message=compat.bounded_error_message,
                limitations=_limit_truthfulness(["cdp_compatibility_not_ready", *compat.blocking_reasons]),
                details=details,
                cleanup_status=compat.cleanup_status,
            )
        safety = self._safe_public_test_url()
        if not safety["allowed"]:
            return self._skipped(
                "obscura_cdp",
                CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                safety["error_code"],
                started,
                details={**details, **safety},
                cleanup_status=compat.cleanup_status,
            )
        request = WebRetrievalRequest(
            urls=[str(safety["normalized_url"])],
            intent="cdp_inspect",
            preferred_provider="obscura_cdp",
            require_rendering=True,
            include_links=True,
            include_html=False,
            max_text_chars=4000,
        )
        bundle = WebRetrievalService(self.config.web_retrieval).retrieve(request)
        page = bundle.pages[0] if bundle.pages else None
        if page is None:
            return self._failed(
                "obscura_cdp",
                CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                "no_page_result",
                started,
                cleanup_status=compat.cleanup_status,
            )
        passed = page.status in {"success", "partial"} and (page.title or page.text_chars or page.link_count)
        status = STATUS_PASSED if passed else STATUS_FAILED
        if not passed and page.error_code == "cdp_navigation_unsupported":
            status = STATUS_INCOMPATIBLE
            details.update(
                {
                    "endpoint_discovered": True,
                    "navigation_supported": False,
                    "page_inspection_supported": False,
                    "extraction_supported": False,
                    "diagnostic_only": True,
                    "recommended_fallback_provider": "obscura_cli",
                    "compatibility_level": "diagnostic_only",
                    "compatible": False,
                }
            )
        return LiveBrowserIntegrationResult(
            provider="obscura_cdp",
            status=status,
            enabled=True,
            duration_ms=_elapsed(started),
            claim_ceiling=CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
            error_code="" if passed else page.error_code,
            bounded_error_message="" if passed else page.error_message,
            limitations=_limit_truthfulness(page.limitations),
            details={
                **details,
                "page_status": page.status,
                "safe_url_display": safe_url_display(page.final_url or page.requested_url),
                "title_present": bool(page.title),
                "dom_text_chars": page.text_chars,
                "links_found": page.link_count,
                "network_request_count": int((page.network_summary or {}).get("request_count", 0) or 0),
                "console_error_count": int((page.console_summary or {}).get("error_count", 0) or 0),
            },
            cleanup_status=compat.cleanup_status,
        )

    def run_playwright_readiness_check(self) -> LiveBrowserIntegrationResult:
        started = perf_counter()
        if not self.gates.live_browser_tests or not self.gates.enable_playwright:
            return self._skipped(
                "playwright",
                CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
                "live_playwright_gate_not_enabled",
                started,
            )
        if find_spec("playwright") is None:
            return self._unavailable(
                "playwright",
                CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
                "dependency_missing",
                started,
                details={
                    "dependency_installed": False,
                    "browser_engines_available": False,
                    "actions_enabled": False,
                    "launch_allowed": self.gates.playwright_allow_browser_launch,
                },
            )
        engines_available, engine_error = _playwright_browser_engine_available()
        if self.gates.playwright_allow_browser_launch and not engines_available:
            return self._unavailable(
                "playwright",
                CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
                "browsers_missing",
                started,
                details={
                    "dependency_installed": True,
                    "browser_engines_available": False,
                    "actions_enabled": False,
                    "launch_allowed": True,
                    "engine_error": engine_error,
                },
            )
        return LiveBrowserIntegrationResult(
            provider="playwright",
            status=STATUS_PASSED,
            enabled=True,
            duration_ms=_elapsed(started),
            claim_ceiling=CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
            limitations=["semantic_observation_only", *_TRUTHFUL_LIMITATIONS],
            details={
                "dependency_installed": True,
                "browser_engines_available": engines_available,
                "browser_launch_allowed": self.gates.playwright_allow_browser_launch,
                "actions_enabled": False,
                "connect_existing_allowed": False,
            },
        )

    def run_playwright_semantic_observation_check(self) -> LiveBrowserIntegrationResult:
        started = perf_counter()
        if not self.gates.live_browser_tests or not self.gates.enable_playwright:
            return self._skipped(
                "playwright_live_semantic",
                CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
                "live_playwright_gate_not_enabled",
                started,
            )
        if not self.gates.playwright_allow_browser_launch:
            return self._skipped(
                "playwright_live_semantic",
                CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
                "playwright_browser_launch_not_allowed",
                started,
            )
        if find_spec("playwright") is None:
            return self._unavailable(
                "playwright_live_semantic",
                CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
                "dependency_missing",
                started,
                details={
                    "dependency_installed": False,
                    "browser_engines_available": False,
                    "actions_enabled": False,
                    "launch_allowed": True,
                },
            )
        engines_available, engine_error = _playwright_browser_engine_available()
        if not engines_available:
            return self._unavailable(
                "playwright_live_semantic",
                CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
                "browsers_missing",
                started,
                details={
                    "dependency_installed": True,
                    "browser_engines_available": False,
                    "actions_enabled": False,
                    "launch_allowed": True,
                    "engine_error": engine_error,
                },
            )
        try:
            observation, guidance = self._run_live_playwright_observation()
        except Exception as exc:
            return self._failed(
                "playwright_live_semantic",
                CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
                "playwright_live_observation_failed",
                started,
                message=f"{type(exc).__name__}: {exc}",
                cleanup_status="attempted",
            )
        return LiveBrowserIntegrationResult(
            provider="playwright_live_semantic",
            status=STATUS_PASSED if observation.controls else STATUS_PARTIAL,
            enabled=True,
            duration_ms=_elapsed(started),
            claim_ceiling=CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION,
            limitations=_limit_truthfulness(observation.limitations),
            details={
                "browser_context_kind": observation.browser_context_kind,
                "page_url": safe_url_display(observation.page_url),
                "page_title": observation.page_title,
                "control_count": len(observation.controls),
                "controls_found": len(observation.controls),
                "links_found": sum(1 for control in observation.controls if control.role == "link"),
                "forms_found": len(observation.forms),
                "dialog_count": len(observation.dialogs),
                "dialogs_found": len(observation.dialogs),
                "guidance_status": guidance.get("status", ""),
                "guidance_message": guidance.get("message", ""),
                "grounding_result": guidance.get("status", ""),
                "guidance_result": guidance.get("message", ""),
                "action_supported": False,
                "verification_supported": False,
                "isolated_context": True,
                "isolated_context_used": observation.browser_context_kind == "isolated_playwright_context",
                "user_profile_used": False,
                "semantic_extraction_path": "screen_awareness.playwright_adapter",
            },
            cleanup_status="closed",
        )

    def _run_live_playwright_observation(self) -> tuple[BrowserSemanticObservation, dict[str, Any]]:
        target_url = self.gates.live_browser_test_url
        fixture_server: LiveBrowserFixtureServer | None = None
        if not target_url:
            fixture_server = LiveBrowserFixtureServer()
            fixture_server.__enter__()
            target_url = fixture_server.url("/form.html")
        try:
            adapter = PlaywrightBrowserSemanticAdapter(self.config.screen_awareness.browser_adapters.playwright)
            observation = adapter.observe_live_browser_page(
                target_url,
                fixture_mode=fixture_server is not None,
            )
            target = _live_grounding_target(observation.controls)
            candidates = adapter.ground_target(target, observation)
            guidance = adapter.produce_guidance_step(candidates, observation=observation)
            if guidance.get("message"):
                guidance["message"] = _live_guidance_message(guidance.get("message"))
            return observation, guidance
        finally:
            if fixture_server is not None:
                fixture_server.__exit__(None, None, None)

    def _safe_public_test_url(self) -> dict[str, Any]:
        if not self.gates.live_browser_test_url:
            return {"allowed": False, "error_code": "public_url_required", "message": "Set STORMHELM_LIVE_BROWSER_TEST_URL to run this public provider smoke."}
        safety = validate_public_url(self.gates.live_browser_test_url, self.config.web_retrieval)
        return {
            "allowed": safety.allowed,
            "error_code": safety.reason_code,
            "message": safety.message,
            "safe_url_display": safety.safe_url_display,
            "normalized_url": safety.normalized_url,
        }

    def _skipped(
        self,
        provider: str,
        claim_ceiling: str,
        code: str,
        started: float,
        *,
        details: dict[str, Any] | None = None,
        cleanup_status: str = "",
    ) -> LiveBrowserIntegrationResult:
        return LiveBrowserIntegrationResult(
            provider=provider,
            status=STATUS_SKIPPED,
            enabled=False,
            duration_ms=_elapsed(started),
            claim_ceiling=claim_ceiling,
            error_code=code,
            bounded_error_message=code,
            limitations=["live_check_not_run", *_TRUTHFUL_LIMITATIONS],
            details=details or {},
            cleanup_status=cleanup_status,
        )

    def _unavailable(
        self,
        provider: str,
        claim_ceiling: str,
        code: str,
        started: float,
        *,
        details: dict[str, Any] | None = None,
    ) -> LiveBrowserIntegrationResult:
        return LiveBrowserIntegrationResult(
            provider=provider,
            status=STATUS_UNAVAILABLE,
            enabled=True,
            duration_ms=_elapsed(started),
            claim_ceiling=claim_ceiling,
            error_code=code,
            bounded_error_message=code,
            limitations=["dependency_unavailable", *_TRUTHFUL_LIMITATIONS],
            details=details or {},
        )

    def _failed(
        self,
        provider: str,
        claim_ceiling: str,
        code: str,
        started: float,
        *,
        message: str = "",
        cleanup_status: str = "",
        details: dict[str, Any] | None = None,
    ) -> LiveBrowserIntegrationResult:
        return LiveBrowserIntegrationResult(
            provider=provider,
            status=STATUS_FAILED,
            enabled=True,
            duration_ms=_elapsed(started),
            claim_ceiling=claim_ceiling,
            error_code=code,
            bounded_error_message=message or code,
            limitations=["live_check_failed", *_TRUTHFUL_LIMITATIONS],
            details=details or {},
            cleanup_status=cleanup_status,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run opt-in Stormhelm live browser provider checks.")
    parser.add_argument("--config", type=Path, default=None, help="Optional Stormhelm config override path.")
    parser.add_argument("--url", default="", help="Optional public URL for Obscura provider smokes.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report path.")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero for enabled unavailable/failed/incompatible checks.")
    args = parser.parse_args(argv)

    env = dict(os.environ)
    if args.url:
        env["STORMHELM_LIVE_BROWSER_TEST_URL"] = args.url
    gates = LiveBrowserIntegrationGates.from_env(env)
    config = load_config(config_path=args.config, env=env)
    report = LiveBrowserIntegrationRunner(config, gates=gates).run_all()
    payload = report.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.strict and gates.live_browser_tests and report.overall_status in {STATUS_FAILED, STATUS_INCOMPATIBLE, STATUS_UNAVAILABLE}:
        return 2
    return 0


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/redirect-safe":
            self.send_response(302)
            self.send_header("Location", "/static.html")
            self.end_headers()
            return
        if path == "/redirect-blocked":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/private-target")
            self.end_headers()
            return
        if path == "/error":
            self._write("<html><title>Stormhelm Fixture Error</title><body>Error fixture</body></html>", status=500)
            return
        body = _fixture_body(path)
        self._write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def _write(self, body: str, *, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _fixture_body(path: str) -> str:
    if path == "/app-shell.html":
        return """<!doctype html><html><head><title>Stormhelm Fixture App Shell</title></head>
        <body><main role="main"><h1>App Shell</h1><button id="refresh">Refresh</button></main></body></html>"""
    if path == "/links.html":
        links = "\n".join(f'<a href="/item-{index}.html">Item {index}</a>' for index in range(1, 80))
        return f"<!doctype html><html><head><title>Stormhelm Fixture Links</title></head><body>{links}</body></html>"
    if path == "/form.html":
        return """<!doctype html><html><head><title>Stormhelm Fixture Form</title></head>
        <body><main><h1>Example Checkout</h1><label>Email <input id="email" name="email" placeholder="Email"></label>
        <label><input id="agree" type="checkbox"> I agree</label>
        <a href="/privacy.html">Privacy Policy</a><button id="continue">Continue</button></main></body></html>"""
    if path == "/dialog.html":
        return """<!doctype html><html><head><title>Stormhelm Fixture Dialog</title></head>
        <body><div role="alert">Session expired</div><button>Continue</button></body></html>"""
    if path == "/large.html":
        return "<!doctype html><html><head><title>Stormhelm Fixture Large</title></head><body>" + ("large text " * 20000) + "</body></html>"
    return """<!doctype html><html><head><title>Stormhelm Fixture Static</title></head>
    <body><h1>Stormhelm Fixture Static</h1><p>Deterministic public-provider fixture content.</p>
    <a href="/privacy.html">Privacy Policy</a><button id="continue">Continue</button></body></html>"""


def _env_bool(env: Mapping[str, str], key: str) -> bool:
    return str(env.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_binary(binary: str) -> str:
    candidate = str(binary or "obscura").strip() or "obscura"
    if any(sep in candidate for sep in ("/", "\\")) or (len(candidate) > 1 and candidate[1] == ":"):
        return candidate if Path(candidate).exists() else ""
    return shutil.which(candidate) or ""


def _elapsed(started: float) -> float:
    return (perf_counter() - started) * 1000


def _bounded_safe(value: Any, limit: int = _TEXT_LIMIT) -> str:
    text = _SENSITIVE_RE.sub("[redacted]", str(value or ""))
    text = safe_url_display(text) if "://" in text and len(text.split()) == 1 else text
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def _bounded_list(values: list[str]) -> list[str]:
    return [_bounded_safe(item, 120) for item in list(dict.fromkeys(values or []))[:_DETAIL_LIMIT]]


def _sanitize_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for raw_key, value in list(mapping.items())[:_DETAIL_LIMIT]:
        key = _bounded_safe(raw_key, 80)
        lowered = key.lower()
        if "raw" in lowered or lowered in {"html", "raw_html", "text", "raw_text", "dom"}:
            continue
        sanitized[key] = _sanitize_value(value)
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value[:_DETAIL_LIMIT]]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value[:_DETAIL_LIMIT]]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return value
    return _bounded_safe(value)


def _safe_path_display(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return Path(text).name if any(sep in text for sep in ("/", "\\")) else text


def _limit_truthfulness(limitations: list[str]) -> list[str]:
    return list(dict.fromkeys([*limitations, *_TRUTHFUL_LIMITATIONS]))


def _control_from_payload(payload: Mapping[str, Any]) -> BrowserSemanticControl:
    return BrowserSemanticControl(
        control_id=_bounded_safe(payload.get("control_id") or f"live-control-{uuid4().hex[:6]}", 80),
        role=_bounded_safe(payload.get("role"), 40),
        name=_bounded_safe(payload.get("name"), 120),
        label=_bounded_safe(payload.get("label"), 120),
        text=_bounded_safe(payload.get("text"), 120),
        selector_hint=_bounded_safe(payload.get("selector_hint"), 120),
        enabled=bool(payload.get("enabled")) if payload.get("enabled") is not None else None,
        visible=bool(payload.get("visible")) if payload.get("visible") is not None else None,
        checked=bool(payload.get("checked")) if payload.get("checked") is not None else None,
        required=bool(payload.get("required")) if payload.get("required") is not None else None,
        confidence=0.7,
    )


def _live_grounding_target(controls: list[BrowserSemanticControl]) -> str:
    for control in controls:
        if str(control.name or "").strip().lower() == "continue":
            return "Continue button"
    for control in controls:
        for value in (control.name, control.label, control.text):
            text = str(value or "").strip()
            if text:
                return text
    for control in controls:
        role = str(control.role or "").strip()
        if role:
            return role
    return "control"


def _live_guidance_message(value: Any) -> str:
    return str(value or "").replace("mock browser observation", "live browser semantic observation")


def _playwright_browser_engine_available() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = Path(str(playwright.chromium.executable_path or ""))
            return executable.exists(), "" if executable.exists() else "chromium_executable_missing"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


if __name__ == "__main__":
    raise SystemExit(main())
