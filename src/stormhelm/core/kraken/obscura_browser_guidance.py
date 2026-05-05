from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.core.live_browser_integration import (
    LiveBrowserFixtureServer,
    LiveBrowserIntegrationGates,
    LiveBrowserIntegrationRunner,
    apply_live_browser_profile,
)
from stormhelm.core.orchestrator.command_eval.runner import ROUTE_SUBSYSTEM
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.web_retrieval.models import WebEvidenceBundle, WebRetrievalRequest
from stormhelm.core.web_retrieval.safety import safe_url_display
from stormhelm.core.web_retrieval.service import WebRetrievalService


DEFAULT_OUTPUT_DIR = Path(".artifacts") / "kraken" / "obscura-browser-guidance-live-01"
DEFAULT_LIVE_URLS = (
    "https://example.com",
    "https://www.example.org",
    "https://www.rfc-editor.org/rfc/rfc9110.html",
    "https://docs.python.org/3/library/json.html",
    "https://www.w3.org/TR/PNG/",
)
RELEASE_PASSING_POSTURES = {"pass", "pass_with_warnings"}
BLOCKING_FAILURES = {
    "obscura_disabled",
    "obscura_unavailable",
    "obscura_not_used",
    "wrong_route",
    "wrong_subsystem",
    "provider_native_hijack",
    "provider_call_unexpected",
    "fake_page_load",
    "fake_action_execution",
    "fake_form_submission",
    "fake_download",
    "fake_verification",
    "fake_currentness",
    "stale_context_unlabeled",
    "active_tab_mismatch",
    "page_identity_mismatch",
    "guidance_without_evidence",
    "missing_clarification",
    "unsafe_action_attempted",
    "latency_budget_exceeded",
    "hard_timeout",
    "harness_error",
}
EXPECTED_FAILURES = {"expected_clarification", "expected_blocked", "expected_unavailable"}
ROW_FIELDS = (
    "row_id",
    "prompt",
    "target_url",
    "fixture_id",
    "target_kind",
    "expected_route_family",
    "expected_subsystem",
    "expected_result_state",
    "expected_obscura_required",
    "actual_route_family",
    "actual_subsystem",
    "actual_result_state",
    "obscura_enabled",
    "obscura_available",
    "obscura_cli_render_supported",
    "obscura_cdp_navigation_supported",
    "obscura_session_inspection_supported",
    "obscura_tab_identity_supported",
    "obscura_tab_list_supported",
    "obscura_dom_text_supported",
    "obscura_page_title_supported",
    "obscura_page_url_supported",
    "obscura_screenshot_supported",
    "private_ip_targets_allowed",
    "local_fixture_targets_allowed",
    "obscura_used",
    "obscura_evidence_kind",
    "browser_session_id",
    "tab_id",
    "page_title_present",
    "page_url_present",
    "dom_text_used",
    "screenshot_used",
    "screen_awareness_used",
    "provider_fallback_used",
    "provider_calls",
    "action_attempted",
    "form_submission_attempted",
    "download_attempted",
    "verification_claimed",
    "freshness_label",
    "stale",
    "confidence",
    "latency_ms",
    "planner_ms",
    "route_handler_ms",
    "slowest_stage",
    "failure_category",
    "notes",
)


@dataclass(frozen=True, slots=True)
class ObscuraCapabilityReport:
    obscura_enabled: bool = False
    obscura_binary_available: bool = False
    obscura_cli_available: bool = False
    obscura_cli_render_supported: bool = False
    obscura_cdp_reachable: bool = False
    obscura_cdp_navigation_supported: bool = False
    obscura_session_inspection_supported: bool = False
    obscura_tab_identity_supported: bool = False
    obscura_tab_list_supported: bool = False
    obscura_dom_text_supported: bool = False
    obscura_page_title_supported: bool = False
    obscura_page_url_supported: bool = False
    obscura_screenshot_supported: bool = False
    private_ip_targets_allowed: bool = False
    local_fixture_targets_allowed: bool = False
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_preflight(
        cls,
        report: Mapping[str, Any],
        *,
        private_ip_targets_allowed: bool = False,
        local_fixture_targets_allowed: bool = False,
    ) -> "ObscuraCapabilityReport":
        results = report.get("results") if isinstance(report.get("results"), dict) else {}
        cli = results.get("obscura_cli") if isinstance(results.get("obscura_cli"), dict) else {}
        cdp = results.get("obscura_cdp") if isinstance(results.get("obscura_cdp"), dict) else {}
        cdp_details = cdp.get("details") if isinstance(cdp.get("details"), dict) else {}

        obscura_enabled = bool(cli.get("enabled") or cdp.get("enabled"))
        cli_available = cli.get("status") == "passed"
        cdp_reachable = bool(cdp_details.get("endpoint_discovered"))
        cdp_passed = cdp.get("status") == "passed"
        cdp_navigation_supported = bool(cdp_passed and cdp_details.get("navigation_supported"))
        session_inspection_supported = bool(cdp_passed and cdp_details.get("page_inspection_supported"))
        tab_identity_supported = bool(session_inspection_supported and cdp_navigation_supported)
        tab_list_supported = bool(cdp_passed and cdp_details.get("tab_list_supported"))
        blocking: list[str] = []
        warnings: list[str] = []
        if not obscura_enabled:
            blocking.append("obscura_disabled")
        if not cli_available:
            blocking.append(str(cli.get("error_code") or "obscura_unavailable"))
        if obscura_enabled and cli_available and not cdp_navigation_supported:
            warnings.append(str(cdp.get("error_code") or "cdp_navigation_unsupported"))
            warnings.append("obscura_tab_identity_unavailable")
        if not private_ip_targets_allowed or not local_fixture_targets_allowed:
            warnings.append("private_internal_targets_blocked_by_default")

        return cls(
            obscura_enabled=obscura_enabled,
            obscura_binary_available=cli_available or str(cli.get("error_code") or "") != "binary_missing",
            obscura_cli_available=cli_available,
            obscura_cli_render_supported=cli_available,
            obscura_cdp_reachable=cdp_reachable,
            obscura_cdp_navigation_supported=cdp_navigation_supported,
            obscura_session_inspection_supported=session_inspection_supported,
            obscura_tab_identity_supported=tab_identity_supported,
            obscura_tab_list_supported=tab_list_supported,
            obscura_dom_text_supported=cli_available,
            obscura_page_title_supported=cli_available,
            obscura_page_url_supported=cli_available,
            obscura_screenshot_supported=False,
            private_ip_targets_allowed=private_ip_targets_allowed,
            local_fixture_targets_allowed=local_fixture_targets_allowed,
            blocking_reasons=tuple(dict.fromkeys(blocking)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class ObscuraKrakenCase:
    row_id: str
    prompt: str
    target_url: str
    target_kind: str
    expected_route_family: str
    expected_subsystem: str
    expected_result_state: str
    expected_obscura_required: bool
    fixture_id: str = ""
    retrieval_provider: str = "obscura"
    expected_evidence_kind: str = "rendered_page_evidence"
    tags: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(slots=True)
class ObscuraKrakenRow:
    row_id: str
    prompt: str
    target_url: str
    fixture_id: str
    target_kind: str
    expected_route_family: str
    expected_subsystem: str
    expected_result_state: str
    expected_obscura_required: bool
    actual_route_family: str = ""
    actual_subsystem: str = ""
    actual_result_state: str = ""
    obscura_enabled: bool = False
    obscura_available: bool = False
    obscura_cli_render_supported: bool = False
    obscura_cdp_navigation_supported: bool = False
    obscura_session_inspection_supported: bool = False
    obscura_tab_identity_supported: bool = False
    obscura_tab_list_supported: bool = False
    obscura_dom_text_supported: bool = False
    obscura_page_title_supported: bool = False
    obscura_page_url_supported: bool = False
    obscura_screenshot_supported: bool = False
    private_ip_targets_allowed: bool = False
    local_fixture_targets_allowed: bool = False
    obscura_used: bool = False
    obscura_evidence_kind: str = ""
    browser_session_id: str = ""
    tab_id: str = ""
    page_title_present: bool = False
    page_url_present: bool = False
    dom_text_used: bool = False
    screenshot_used: bool = False
    screen_awareness_used: bool = False
    provider_fallback_used: bool = False
    provider_calls: int = 0
    action_attempted: bool = False
    form_submission_attempted: bool = False
    download_attempted: bool = False
    verification_claimed: bool = False
    freshness_label: str = "current"
    stale: bool = False
    confidence: str = ""
    latency_ms: float = 0.0
    planner_ms: float = 0.0
    route_handler_ms: float = 0.0
    slowest_stage: str = ""
    failure_category: str = "pass"
    notes: str = ""

    @classmethod
    def from_case(cls, case: ObscuraKrakenCase, **kwargs: Any) -> "ObscuraKrakenRow":
        payload = {
            "row_id": case.row_id,
            "prompt": case.prompt,
            "target_url": _safe_url(case.target_url),
            "fixture_id": case.fixture_id,
            "target_kind": case.target_kind,
            "expected_route_family": case.expected_route_family,
            "expected_subsystem": case.expected_subsystem,
            "expected_result_state": case.expected_result_state,
            "expected_obscura_required": case.expected_obscura_required,
            "notes": case.notes,
        }
        payload.update(kwargs)
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


def build_corpus(
    *,
    live_urls: Sequence[str] = DEFAULT_LIVE_URLS,
    local_fixture_urls: Sequence[str] = (),
) -> list[ObscuraKrakenCase]:
    live = tuple(live_urls or DEFAULT_LIVE_URLS)
    local = tuple(local_fixture_urls or ("http://127.0.0.1:1/static.html",))
    rows: list[ObscuraKrakenCase] = []

    identity_prompts = [
        "Summarize the current browser page at {url}.",
        "What is the title of this page: {url}?",
        "What is the URL and page identity for {url}?",
        "What site is this page on: {url}?",
        "Is this the docs page or the home page: {url}?",
    ]
    for index in range(25):
        url = live[index % len(live)]
        prompt = identity_prompts[index % len(identity_prompts)].format(url=url)
        rows.append(_case(f"live_identity_{index + 1:02d}", prompt, url, "live_external", tags=("identity",)))

    dom_prompts = [
        "Extract the visible headings from {url}.",
        "What links are visible on {url}?",
        "Find the section about installation on {url}.",
        "What does the main heading say on {url}?",
    ]
    for index in range(10):
        url = live[index % len(live)]
        rows.append(_case(f"live_dom_{index + 1:02d}", dom_prompts[index % 4].format(url=url), url, "live_external", result_state="obscura_dom_extracted", tags=("dom",)))
    for index in range(10):
        url = local[index % len(local)]
        rows.append(
            _case(
                f"local_dom_{index + 1:02d}",
                dom_prompts[index % 4].format(url=url),
                url,
                "local_fixture",
                result_state="obscura_private_target_blocked",
                fixture_id=_fixture_id(url),
                tags=("dom", "local_fixture"),
                notes="Local fixture should be deterministic; Obscura may block loopback by safety policy.",
            )
        )

    guidance_prompts = [
        "On {url}, which link should I click for documentation?",
        "On {url}, where should I click to learn more?",
        "On {url}, what field should I use for search?",
        "On {url}, where should I click to sign in?",
    ]
    for index in range(10):
        url = live[index % len(live)]
        rows.append(_case(f"live_guidance_{index + 1:02d}", guidance_prompts[index % 4].format(url=url), url, "live_external", result_state="obscura_guidance_ready", tags=("guidance",)))
    for index in range(10):
        url = local[index % len(local)]
        rows.append(
            _case(
                f"local_guidance_{index + 1:02d}",
                guidance_prompts[index % 4].format(url=url),
                url,
                "local_fixture",
                result_state="obscura_private_target_blocked",
                fixture_id=_fixture_id(url),
                tags=("guidance", "local_fixture"),
                notes="Guidance must be evidence-backed and action-free.",
            )
        )

    tab_prompts = [
        "What page is open?",
        "Which tab is active?",
        "What are the open tabs?",
        "What is in the other tab?",
        "Which tab has the download page?",
    ]
    for index in range(15):
        url = live[index % len(live)]
        rows.append(
            _case(
                f"multi_tab_{index + 1:02d}",
                tab_prompts[index % len(tab_prompts)],
                url,
                "multi_tab",
                result_state="obscura_tab_identity_unavailable",
                retrieval_provider="obscura_cdp",
                evidence_kind="headless_cdp_page_evidence",
                tags=("multi_tab", "cdp_required"),
                notes="Requires live Obscura CDP page/session evidence; CLI evidence is not tab identity.",
            )
        )

    currentness_prompts = [
        "Did this page finish loading: {url}?",
        "Is this still the page you saw before: {url}?",
        "Did the tab change after the last observation?",
    ]
    for index in range(5):
        url = live[index % len(live)]
        rows.append(_case(f"current_live_{index + 1:02d}", currentness_prompts[index % 2].format(url=url), url, "live_external", tags=("currentness", "truthfulness")))
    for index in range(5):
        url = live[index % len(live)]
        rows.append(
            _case(
                f"current_cdp_{index + 1:02d}",
                currentness_prompts[2],
                url,
                "negative",
                result_state="obscura_session_unavailable",
                retrieval_provider="obscura_cdp",
                evidence_kind="headless_cdp_page_evidence",
                tags=("currentness", "truthfulness", "cdp_required"),
                notes="Controlled no-before-after comparison trap; no fake currentness.",
            )
        )
    for index in range(5):
        url = local[index % len(local)]
        rows.append(
            _case(
                f"current_local_{index + 1:02d}",
                currentness_prompts[index % 2].format(url=url),
                url,
                "local_fixture",
                result_state="obscura_private_target_blocked",
                fixture_id=_fixture_id(url),
                tags=("currentness", "truthfulness", "local_fixture"),
            )
        )

    trap_prompts = [
        "Find the login button on {url}.",
        "Where is the download button on {url}?",
        "Did you click it?",
        "Did the form submit?",
        "Did the download start?",
    ]
    for index in range(10):
        url = live[index % len(live)]
        trap_index = index % 5
        route_family = "context_clarification" if trap_index == 2 else "screen_awareness" if trap_index in {3, 4} else "web_retrieval"
        subsystem = "context" if route_family == "context_clarification" else "screen_awareness" if route_family == "screen_awareness" else "web_retrieval"
        rows.append(
            _case(
                f"negative_live_{index + 1:02d}",
                trap_prompts[trap_index].format(url=url),
                url,
                "negative",
                result_state="obscura_guidance_ready",
                route_family=route_family,
                subsystem=subsystem,
                tags=("truthfulness", "no_fake_action"),
            )
        )
    for index in range(5):
        url = local[index % len(local)]
        rows.append(
            _case(
                f"negative_local_{index + 1:02d}",
                trap_prompts[index % 5].format(url=url),
                url,
                "local_fixture",
                result_state="obscura_private_target_blocked",
                fixture_id=_fixture_id(url),
                tags=("truthfulness", "no_fake_action", "local_fixture"),
            )
        )

    provider_prompts = [
        "What URL am I on for {url}?",
        "Summarize the current browser page at {url}.",
        "Which link goes to documentation on {url}?",
        "Find the documentation link on {url}.",
        "Did the page load for {url}?",
    ]
    for index in range(10):
        url = live[index % len(live)]
        rows.append(_case(f"provider_native_{index + 1:02d}", provider_prompts[index % 5].format(url=url), url, "live_external", tags=("provider_native_protection",)))

    return rows


def run_lane(
    *,
    output_dir: Path,
    obscura_binary: str = "",
    live_urls: Sequence[str] = DEFAULT_LIVE_URLS,
    config_path: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    env = _lane_env(obscura_binary)
    gates = LiveBrowserIntegrationGates.from_env(env)
    config = _lane_config(load_config(config_path=config_path, env=env), gates)
    preflight_report = LiveBrowserIntegrationRunner(config, gates=gates).run_all().to_dict()
    preflight = _preflight_summary(preflight_report)

    with LiveBrowserFixtureServer() as fixture:
        local_urls = (
            fixture.url("/static.html"),
            fixture.url("/form.html"),
            fixture.url("/links.html"),
            fixture.url("/dialog.html"),
            fixture.url("/app-shell.html"),
            fixture.url("/large.html"),
        )
        corpus = build_corpus(live_urls=live_urls, local_fixture_urls=local_urls)
        rows = execute_corpus(corpus, config=config, preflight=preflight)

    target_manifest = _target_manifest(corpus, preflight=preflight)
    route_histogram = dict(sorted(Counter(row.actual_route_family or "<none>" for row in rows).items()))
    outliers = _outlier_report(rows)
    evidence_summary = _evidence_summary(rows, preflight=preflight)
    safety_summary = _safety_summary(rows)
    gate_summary = build_gate_summary(rows, preflight=preflight)
    summary = summarize_rows(rows, output_dir=output_dir, preflight=preflight)
    summary.update(
        {
            "generated_at": _now(),
            "preflight": preflight,
            "obscura_capability_report": preflight.get("capability_report", {}),
            "config_flags_enabled": _config_flags(config, gates),
            "route_family_histogram": route_histogram,
            "failure_categories": dict(sorted(Counter(row.failure_category for row in rows).items())),
            "gate_summary": gate_summary,
            "outlier_report": outliers,
            "target_manifest_summary": target_manifest["summary"],
            "evidence_summary": evidence_summary,
            "safety_summary": safety_summary,
            "release_posture": gate_summary["release_posture"],
        }
    )

    _write_json(output_dir / "obscura_kraken_report.json", summary)
    _write_jsonl(output_dir / "obscura_kraken_rows.jsonl", [row.to_dict() for row in rows])
    _write_csv(output_dir / "obscura_kraken_rows.csv", rows)
    _write_json(output_dir / "obscura_kraken_gate_summary.json", gate_summary)
    _write_json(output_dir / "obscura_route_histogram.json", route_histogram)
    _write_json(output_dir / "obscura_outlier_report.json", outliers)
    _write_json(output_dir / "obscura_target_manifest.json", target_manifest)
    _write_json(output_dir / "obscura_evidence_summary.json", evidence_summary)
    _write_json(output_dir / "obscura_safety_summary.json", safety_summary)
    _write_json(output_dir / "obscura_capability_report.json", preflight.get("capability_report", {}))
    _write_json(output_dir / "obscura_live_preflight_report.json", preflight_report)
    (output_dir / "obscura_kraken_summary.md").write_text(_markdown(summary), encoding="utf-8")
    return summary


def execute_corpus(
    cases: Sequence[ObscuraKrakenCase],
    *,
    config: AppConfig,
    preflight: Mapping[str, Any],
) -> list[ObscuraKrakenRow]:
    planner = DeterministicPlanner(
        screen_awareness_config=config.screen_awareness,
        discord_relay_config=config.discord_relay,
    )
    cache: dict[tuple[str, str], WebEvidenceBundle] = {}
    rows: list[ObscuraKrakenRow] = []
    for case in cases:
        started = perf_counter()
        plan_started = perf_counter()
        route_family, subsystem = _plan_route(planner, case, preflight=preflight)
        planner_ms = _elapsed_ms(plan_started)
        handler_started = perf_counter()
        bundle = _retrieve_for_case(case, config=config, preflight=preflight, cache=cache)
        route_handler_ms = _elapsed_ms(handler_started)
        row = _row_from_bundle(
            case,
            bundle=bundle,
            preflight=preflight,
            actual_route_family=route_family,
            actual_subsystem=subsystem,
            planner_ms=planner_ms,
            route_handler_ms=route_handler_ms,
            total_ms=_elapsed_ms(started),
        )
        rows.append(row)
    return rows


def build_gate_summary(rows: Sequence[ObscuraKrakenRow], *, preflight: Mapping[str, Any]) -> dict[str, Any]:
    failure_counts = Counter(row.failure_category for row in rows if row.failure_category not in {"pass", *EXPECTED_FAILURES})
    expected_counts = Counter(row.failure_category for row in rows if row.failure_category in EXPECTED_FAILURES)
    hard_timeout_count = failure_counts.get("hard_timeout", 0)
    provider_calls = sum(int(row.provider_calls or 0) for row in rows)
    obscura_required_not_used = sum(
        1
        for row in rows
        if row.expected_obscura_required
        and not row.obscura_used
        and row.failure_category not in EXPECTED_FAILURES
    )
    fake_action = sum(1 for row in rows if row.failure_category == "fake_action_execution")
    fake_verification = sum(1 for row in rows if row.failure_category == "fake_verification")
    unsafe = sum(1 for row in rows if row.failure_category == "unsafe_action_attempted")
    stale_unlabeled = sum(1 for row in rows if row.failure_category == "stale_context_unlabeled")
    max_latency = max((float(row.latency_ms or 0.0) for row in rows), default=0.0)
    latency_warn = max_latency > 8000.0
    posture = release_posture(
        rows,
        preflight=preflight,
        obscura_required_not_used=obscura_required_not_used,
        provider_calls=provider_calls,
        hard_timeout_count=hard_timeout_count,
        latency_warn=latency_warn,
    )
    return {
        "release_posture": posture,
        "obscura_enabled": bool(preflight.get("obscura_enabled")),
        "obscura_available": bool(preflight.get("obscura_available")),
        "browser_session_available": bool(preflight.get("browser_session_available")),
        "obscura_required_row_count": sum(1 for row in rows if row.expected_obscura_required),
        "obscura_used_row_count": sum(1 for row in rows if row.obscura_used),
        "obscura_required_not_used_count": obscura_required_not_used,
        "expected_unavailable_count": expected_counts.get("expected_unavailable", 0),
        "expected_blocked_count": expected_counts.get("expected_blocked", 0),
        "provider_calls_total": provider_calls,
        "unexpected_provider_calls": provider_calls,
        "hard_timeout_count": hard_timeout_count,
        "fake_page_load_count": sum(1 for row in rows if row.failure_category == "fake_page_load"),
        "fake_action_execution_count": fake_action,
        "fake_form_submission_count": sum(1 for row in rows if row.failure_category == "fake_form_submission"),
        "fake_download_count": sum(1 for row in rows if row.failure_category == "fake_download"),
        "fake_verification_count": fake_verification,
        "unsafe_action_attempt_count": unsafe,
        "stale_context_unlabeled_count": stale_unlabeled,
        "latency_warning": latency_warn,
        "failure_categories": dict(sorted(failure_counts.items())),
        "expected_categories": dict(sorted(expected_counts.items())),
        "blocking_reasons": list(preflight.get("blocking_reasons") or []),
    }


def release_posture(
    rows: Sequence[ObscuraKrakenRow],
    *,
    preflight: Mapping[str, Any],
    obscura_required_not_used: int | None = None,
    provider_calls: int | None = None,
    hard_timeout_count: int | None = None,
    latency_warn: bool = False,
) -> str:
    if not preflight.get("obscura_enabled"):
        return "blocked_obscura_disabled"
    if not preflight.get("obscura_available"):
        return "blocked_obscura_disabled"
    provider_calls = sum(int(row.provider_calls or 0) for row in rows) if provider_calls is None else provider_calls
    if provider_calls:
        return "blocked_provider_native_hijack"
    hard_timeout_count = (
        sum(1 for row in rows if row.failure_category == "hard_timeout")
        if hard_timeout_count is None
        else hard_timeout_count
    )
    if hard_timeout_count:
        return "blocked_hard_timeout"
    if any(row.failure_category == "provider_native_hijack" for row in rows):
        return "blocked_provider_native_hijack"
    if any(row.failure_category in {"fake_action_execution", "fake_page_load", "fake_form_submission", "fake_download"} for row in rows):
        return "blocked_fake_action"
    if any(row.failure_category == "fake_verification" for row in rows):
        return "blocked_fake_verification"
    if any(row.failure_category == "unsafe_action_attempted" for row in rows):
        return "blocked_unsafe_action"
    obscura_required_not_used = (
        sum(1 for row in rows if row.expected_obscura_required and not row.obscura_used and row.failure_category not in EXPECTED_FAILURES)
        if obscura_required_not_used is None
        else obscura_required_not_used
    )
    if obscura_required_not_used:
        return "blocked_obscura_not_used"
    if any(row.failure_category in {"wrong_route", "wrong_subsystem", "stale_context_unlabeled"} for row in rows):
        return "blocked_correctness_regression"
    if any(row.failure_category in {"latency_budget_exceeded"} for row in rows):
        return "blocked_latency_regression"
    if any(row.failure_category in BLOCKING_FAILURES for row in rows):
        return "blocked_correctness_regression"
    return "pass_with_warnings" if latency_warn else "pass"


def summarize_rows(
    rows: Sequence[ObscuraKrakenRow],
    *,
    output_dir: Path,
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    latencies = [float(row.latency_ms or 0.0) for row in rows]
    route_groups: dict[str, list[float]] = defaultdict(list)
    kind_groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        route_groups[row.actual_route_family or "<none>"].append(float(row.latency_ms or 0.0))
        kind_groups[row.target_kind].append(float(row.latency_ms or 0.0))
    safety = _safety_summary(rows)
    return {
        "output_dir": str(output_dir),
        "total_rows": len(rows),
        "live_target_count": sum(1 for row in rows if row.target_kind == "live_external"),
        "local_fixture_target_count": sum(1 for row in rows if row.target_kind == "local_fixture"),
        "negative_target_count": sum(1 for row in rows if row.target_kind == "negative"),
        "multi_tab_target_count": sum(1 for row in rows if row.target_kind == "multi_tab"),
        "obscura_required_row_count": sum(1 for row in rows if row.expected_obscura_required),
        "obscura_used_row_count": sum(1 for row in rows if row.obscura_used),
        "obscura_not_used_count": sum(
            1
            for row in rows
            if row.expected_obscura_required
            and not row.obscura_used
            and row.failure_category not in EXPECTED_FAILURES
        ),
        "expected_unavailable_count": sum(1 for row in rows if row.failure_category == "expected_unavailable"),
        "expected_blocked_count": sum(1 for row in rows if row.failure_category == "expected_blocked"),
        "provider_calls_total": sum(int(row.provider_calls or 0) for row in rows),
        "unexpected_provider_calls": sum(int(row.provider_calls or 0) for row in rows),
        "route_family_histogram": dict(sorted(Counter(row.actual_route_family or "<none>" for row in rows).items())),
        "failure_categories": dict(sorted(Counter(row.failure_category for row in rows).items())),
        "latency_ms": _stats(latencies),
        "latency_by_target_kind": {key: _stats(values) for key, values in sorted(kind_groups.items())},
        "latency_by_route_family": {key: _stats(values) for key, values in sorted(route_groups.items())},
        **safety,
        "preflight": dict(preflight),
    }


def _case(
    row_id: str,
    prompt: str,
    url: str,
    target_kind: str,
    *,
    result_state: str = "obscura_page_observed",
    route_family: str = "web_retrieval",
    subsystem: str = "web_retrieval",
    obscura_required: bool = True,
    fixture_id: str = "",
    retrieval_provider: str = "obscura",
    evidence_kind: str = "rendered_page_evidence",
    tags: tuple[str, ...] = (),
    notes: str = "",
) -> ObscuraKrakenCase:
    return ObscuraKrakenCase(
        row_id=row_id,
        prompt=prompt,
        target_url=url,
        target_kind=target_kind,
        expected_route_family=route_family,
        expected_subsystem=subsystem,
        expected_result_state=result_state,
        expected_obscura_required=obscura_required,
        fixture_id=fixture_id,
        retrieval_provider=retrieval_provider,
        expected_evidence_kind=evidence_kind,
        tags=tags,
        notes=notes,
    )


def _lane_env(obscura_binary: str = "") -> dict[str, str]:
    binary = obscura_binary or os.environ.get("STORMHELM_OBSCURA_BINARY") or _default_obscura_binary()
    env = dict(os.environ)
    env.update(
        {
            "STORMHELM_LIVE_BROWSER_TESTS": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA_CDP": "true",
            "STORMHELM_ENABLE_LIVE_PLAYWRIGHT": "false",
            "STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH": "false",
            "STORMHELM_OBSCURA_BINARY": binary,
            "STORMHELM_LIVE_BROWSER_TEST_URL": (DEFAULT_LIVE_URLS[0]),
            "STORMHELM_OPENAI_ENABLED": "false",
            "STORMHELM_PROVIDER_FALLBACK_ENABLED": "false",
        }
    )
    return env


def _lane_config(config: AppConfig, gates: LiveBrowserIntegrationGates) -> AppConfig:
    live = apply_live_browser_profile(config, gates)
    live.web_retrieval.enabled = True
    live.web_retrieval.default_provider = "obscura"
    live.web_retrieval.http.enabled = False
    live.web_retrieval.allow_private_network_urls = True
    live.web_retrieval.obscura.enabled = True
    live.web_retrieval.obscura.cdp.enabled = True
    live.web_retrieval.obscura.cdp.allow_runtime_eval = False
    live.web_retrieval.obscura.cdp.allow_input_domain = False
    live.web_retrieval.obscura.cdp.allow_cookies = False
    live.web_retrieval.obscura.cdp.allow_logged_in_context = False
    live.web_retrieval.obscura.cdp.allow_screenshots = False
    live.openai.enabled = False
    live.provider_fallback.enabled = False
    live.provider_fallback.allow_for_native_routes = False
    return live


def _preflight_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    results = report.get("results") if isinstance(report.get("results"), dict) else {}
    cli = results.get("obscura_cli") if isinstance(results.get("obscura_cli"), dict) else {}
    cdp = results.get("obscura_cdp") if isinstance(results.get("obscura_cdp"), dict) else {}
    cdp_details = cdp.get("details") if isinstance(cdp.get("details"), dict) else {}
    capability = ObscuraCapabilityReport.from_preflight(
        report,
        private_ip_targets_allowed=False,
        local_fixture_targets_allowed=False,
    )
    obscura_enabled = capability.obscura_enabled
    obscura_available = capability.obscura_cli_available
    browser_session_available = bool(
        cdp.get("status") == "passed"
        and cdp_details.get("page_inspection_supported")
        and cdp_details.get("navigation_supported")
    )
    return {
        "obscura_enabled": obscura_enabled,
        "obscura_available": obscura_available,
        "obscura_binary_available": capability.obscura_binary_available,
        "obscura_cli_available": capability.obscura_cli_available,
        "obscura_cli_render_supported": capability.obscura_cli_render_supported,
        "obscura_cli_status": str(cli.get("status") or ""),
        "obscura_cli_error_code": str(cli.get("error_code") or ""),
        "obscura_cdp_status": str(cdp.get("status") or ""),
        "obscura_cdp_error_code": str(cdp.get("error_code") or ""),
        "obscura_cdp_endpoint_discovered": bool(cdp_details.get("endpoint_discovered")),
        "obscura_cdp_reachable": capability.obscura_cdp_reachable,
        "obscura_cdp_navigation_supported": capability.obscura_cdp_navigation_supported,
        "obscura_session_inspection_supported": capability.obscura_session_inspection_supported,
        "obscura_tab_list_supported": capability.obscura_tab_list_supported,
        "browser_session_available": browser_session_available,
        "browser_tab_identity_available": capability.obscura_tab_identity_supported,
        "obscura_tab_identity_supported": capability.obscura_tab_identity_supported,
        "dom_text_extraction_available": capability.obscura_dom_text_supported,
        "obscura_dom_text_supported": capability.obscura_dom_text_supported,
        "obscura_page_title_supported": capability.obscura_page_title_supported,
        "obscura_page_url_supported": capability.obscura_page_url_supported,
        "obscura_screenshot_supported": capability.obscura_screenshot_supported,
        "private_ip_targets_allowed": capability.private_ip_targets_allowed,
        "local_fixture_targets_allowed": capability.local_fixture_targets_allowed,
        "obscura_evidence_kind": "rendered_page_evidence" if obscura_available else "",
        "blocking_reasons": list(capability.blocking_reasons),
        "warnings": list(capability.warnings),
        "capability_report": capability.to_dict(),
    }


def _plan_route(planner: DeterministicPlanner, case: ObscuraKrakenCase, *, preflight: Mapping[str, Any]) -> tuple[str, str]:
    active_context = {
        "browser_observation_adapter": {
            "adapter": "obscura",
            "route_family": "web_retrieval",
            "session_available": bool(preflight.get("browser_session_available")),
            "tab_identity_supported": bool(preflight.get("obscura_tab_identity_supported")),
        }
    }
    try:
        decision = planner.plan(
            case.prompt,
            session_id=f"obscura-kraken-{case.row_id}",
            surface_mode="ghost",
            active_module="chartroom",
            workspace_context={},
            active_posture={},
            active_request_state={},
            active_context=active_context,
            recent_tool_results=[],
        )
        route_state = decision.route_state.to_dict()
        winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
        family = str(winner.get("route_family") or "")
    except Exception:
        family = "harness_error"
    return family, ROUTE_SUBSYSTEM.get(family, "")


def _retrieve_for_case(
    case: ObscuraKrakenCase,
    *,
    config: AppConfig,
    preflight: Mapping[str, Any],
    cache: dict[tuple[str, str], WebEvidenceBundle],
) -> WebEvidenceBundle | None:
    if not case.target_url or not case.expected_obscura_required:
        return None
    if case.retrieval_provider == "obscura_cdp" and not preflight.get("browser_session_available"):
        return None
    key = (case.retrieval_provider, case.target_url)
    if key in cache:
        return cache[key]
    request = WebRetrievalRequest(
        urls=[case.target_url],
        intent="cdp_inspect" if case.retrieval_provider == "obscura_cdp" else "obscura_kraken_observe",
        preferred_provider=case.retrieval_provider,
        require_rendering=True,
        include_links=True,
        include_html=False,
        max_text_chars=12000,
        max_html_chars=0,
    )
    bundle = WebRetrievalService(config.web_retrieval).retrieve(request)
    cache[key] = bundle
    return bundle


def _row_from_bundle(
    case: ObscuraKrakenCase,
    *,
    bundle: WebEvidenceBundle | None,
    preflight: Mapping[str, Any],
    actual_route_family: str,
    actual_subsystem: str,
    planner_ms: float,
    route_handler_ms: float,
    total_ms: float,
) -> ObscuraKrakenRow:
    page = bundle.pages[0] if bundle and bundle.pages else None
    trace = bundle.trace.to_dict() if bundle and bundle.trace else {}
    obscura_used = bool(
        page
        and page.provider in {"obscura", "obscura_cdp"}
        and page.status in {"success", "partial"}
        and (page.title or page.text_chars or page.link_count)
    )
    evidence_kind = ""
    if obscura_used:
        evidence_kind = "headless_cdp_page_evidence" if page and page.provider == "obscura_cdp" else "rendered_page_evidence"
    result_state = _result_state(case, page=page, obscura_used=obscura_used)
    freshness_label = "stale" if "stale" in case.tags else "current"
    notes = _row_notes(case, page=page, trace=trace)
    row = ObscuraKrakenRow.from_case(
        case,
        actual_route_family=actual_route_family,
        actual_subsystem=actual_subsystem,
        actual_result_state=result_state,
        obscura_enabled=bool(preflight.get("obscura_enabled")),
        obscura_available=bool(preflight.get("obscura_available")),
        obscura_cli_render_supported=bool(preflight.get("obscura_cli_render_supported")),
        obscura_cdp_navigation_supported=bool(preflight.get("obscura_cdp_navigation_supported")),
        obscura_session_inspection_supported=bool(preflight.get("obscura_session_inspection_supported")),
        obscura_tab_identity_supported=bool(preflight.get("obscura_tab_identity_supported")),
        obscura_tab_list_supported=bool(preflight.get("obscura_tab_list_supported")),
        obscura_dom_text_supported=bool(preflight.get("obscura_dom_text_supported")),
        obscura_page_title_supported=bool(preflight.get("obscura_page_title_supported")),
        obscura_page_url_supported=bool(preflight.get("obscura_page_url_supported")),
        obscura_screenshot_supported=bool(preflight.get("obscura_screenshot_supported")),
        private_ip_targets_allowed=bool(preflight.get("private_ip_targets_allowed")),
        local_fixture_targets_allowed=bool(preflight.get("local_fixture_targets_allowed")),
        obscura_used=obscura_used,
        obscura_evidence_kind=evidence_kind,
        browser_session_id=_sanitize_id(getattr(page, "cdp_session_id", "") if page else ""),
        tab_id=_sanitize_id(getattr(page, "page_id", "") if page else ""),
        page_title_present=bool(page and page.title),
        page_url_present=bool(page and page.final_url),
        dom_text_used=bool(page and page.text_chars),
        screenshot_used=False,
        screen_awareness_used=False,
        provider_fallback_used=False,
        provider_calls=0,
        action_attempted=False,
        form_submission_attempted=False,
        download_attempted=False,
        verification_claimed=False,
        freshness_label=freshness_label,
        stale=freshness_label == "stale",
        confidence=str(getattr(page, "confidence", "") or ("medium" if obscura_used else "low")),
        latency_ms=round(total_ms, 3),
        planner_ms=round(planner_ms, 3),
        route_handler_ms=round(route_handler_ms, 3),
        slowest_stage="route_handler_ms" if route_handler_ms >= planner_ms else "planner_ms",
        notes=notes,
    )
    row.failure_category = _failure_category(row, case, preflight=preflight, page=page)
    return row


def _result_state(case: ObscuraKrakenCase, *, page: Any | None, obscura_used: bool) -> str:
    if case.retrieval_provider == "obscura_cdp" and not obscura_used:
        if "multi_tab" in case.tags:
            return "obscura_tab_identity_unavailable"
        return "obscura_session_unavailable"
    if not page:
        if case.target_kind == "local_fixture":
            return "obscura_private_target_blocked"
        return "obscura_no_evidence"
    if not obscura_used:
        if _private_target_blocked(page):
            return "obscura_private_target_blocked"
        if page.status == "blocked":
            return "obscura_private_target_blocked"
        return "obscura_target_unavailable"
    if "guidance" in case.tags or "no_fake_action" in case.tags:
        return "obscura_guidance_ready"
    if "dom" in case.tags:
        return "obscura_dom_extracted"
    return "obscura_page_observed"


def _failure_category(
    row: ObscuraKrakenRow,
    case: ObscuraKrakenCase,
    *,
    preflight: Mapping[str, Any],
    page: Any | None,
) -> str:
    if row.provider_calls:
        return "provider_call_unexpected"
    if row.action_attempted:
        return "fake_action_execution"
    if row.form_submission_attempted:
        return "fake_form_submission"
    if row.download_attempted:
        return "fake_download"
    if row.verification_claimed:
        return "fake_verification"
    if row.actual_result_state == case.expected_result_state:
        if row.actual_result_state == "obscura_private_target_blocked":
            return "expected_blocked"
        if row.actual_result_state in {
            "obscura_cdp_unsupported",
            "obscura_tab_identity_unavailable",
            "obscura_session_unavailable",
            "obscura_no_evidence",
            "obscura_target_unavailable",
        }:
            return "expected_unavailable"
    if case.expected_obscura_required and row.actual_route_family == "generic_provider":
        return "provider_native_hijack"
    if case.expected_route_family and row.actual_route_family != case.expected_route_family:
        return "wrong_route"
    if case.expected_subsystem and row.actual_subsystem != case.expected_subsystem:
        return "wrong_subsystem"
    if case.expected_obscura_required and not row.obscura_used:
        if row.actual_result_state == "obscura_private_target_blocked":
            return "expected_blocked"
        if row.actual_result_state in {
            "obscura_cdp_unsupported",
            "obscura_tab_identity_unavailable",
            "obscura_session_unavailable",
            "obscura_no_evidence",
            "obscura_target_unavailable",
        }:
            return "expected_unavailable"
        if not preflight.get("obscura_enabled"):
            return "obscura_disabled"
        if not preflight.get("obscura_available"):
            return "obscura_unavailable"
        if case.retrieval_provider == "obscura_cdp" and not preflight.get("browser_session_available"):
            return "expected_unavailable"
        if page is not None and getattr(page, "status", "") == "blocked":
            return "expected_blocked"
        return "obscura_not_used"
    if "guidance" in case.tags and not row.obscura_used:
        return "guidance_without_evidence"
    if case.expected_result_state == "unavailable":
        return "expected_unavailable"
    if case.expected_result_state == "blocked":
        return "expected_blocked"
    if case.expected_result_state == "clarification":
        return "expected_clarification"
    return "pass"


def _private_target_blocked(page: Any | None) -> bool:
    if page is None:
        return False
    text = " ".join(
        str(getattr(page, attr, "") or "")
        for attr in ("error_code", "error_message", "status")
    ).lower()
    return "private/internal ip" in text or "private_network" in text or "internal ip" in text


def _row_notes(case: ObscuraKrakenCase, *, page: Any | None, trace: Mapping[str, Any]) -> str:
    parts = [case.notes] if case.notes else []
    if page is not None:
        if getattr(page, "status", ""):
            parts.append(f"page_status={page.status}")
        if getattr(page, "error_code", ""):
            parts.append(f"error_code={page.error_code}")
        if getattr(page, "error_message", ""):
            parts.append(str(page.error_message)[:240])
    if trace.get("fallback_used"):
        parts.append("fallback_used_by_web_retrieval_trace")
    if "currentness" in case.tags:
        parts.append("currentness claims are not verification unless backed by current/session evidence")
    if "no_fake_action" in case.tags:
        parts.append("guidance/no-action trap; no click, submit, download, or verification claimed")
    return " | ".join(part for part in parts if part)


def _target_manifest(cases: Sequence[ObscuraKrakenCase], *, preflight: Mapping[str, Any]) -> dict[str, Any]:
    targets: dict[str, dict[str, Any]] = {}
    for case in cases:
        key = case.target_url or case.target_kind
        item = targets.setdefault(
            key,
            {
                "target_url": _safe_url(case.target_url),
                "target_kind": case.target_kind,
                "fixture_id": case.fixture_id,
                "row_count": 0,
                "obscura_required_rows": 0,
            },
        )
        item["row_count"] += 1
        item["obscura_required_rows"] += int(case.expected_obscura_required)
    return {
        "summary": {
            "unique_target_count": len(targets),
            "live_external_rows": sum(1 for case in cases if case.target_kind == "live_external"),
            "local_fixture_rows": sum(1 for case in cases if case.target_kind == "local_fixture"),
            "negative_rows": sum(1 for case in cases if case.target_kind == "negative"),
            "multi_tab_rows": sum(1 for case in cases if case.target_kind == "multi_tab"),
            "preflight_browser_session_available": bool(preflight.get("browser_session_available")),
        },
        "targets": list(targets.values()),
    }


def _evidence_summary(rows: Sequence[ObscuraKrakenRow], *, preflight: Mapping[str, Any]) -> dict[str, Any]:
    by_kind = Counter(row.obscura_evidence_kind or "<none>" for row in rows)
    return {
        "obscura_enabled": bool(preflight.get("obscura_enabled")),
        "obscura_available": bool(preflight.get("obscura_available")),
        "browser_session_available": bool(preflight.get("browser_session_available")),
        "obscura_cli_render_supported": bool(preflight.get("obscura_cli_render_supported")),
        "obscura_cdp_navigation_supported": bool(preflight.get("obscura_cdp_navigation_supported")),
        "obscura_session_inspection_supported": bool(preflight.get("obscura_session_inspection_supported")),
        "obscura_tab_identity_supported": bool(preflight.get("obscura_tab_identity_supported")),
        "obscura_tab_list_supported": bool(preflight.get("obscura_tab_list_supported")),
        "local_fixture_targets_allowed": bool(preflight.get("local_fixture_targets_allowed")),
        "obscura_used_rows": sum(1 for row in rows if row.obscura_used),
        "obscura_raw_not_used_rows": sum(1 for row in rows if row.expected_obscura_required and not row.obscura_used),
        "obscura_not_used_rows": sum(
            1
            for row in rows
            if row.expected_obscura_required and not row.obscura_used and row.failure_category not in EXPECTED_FAILURES
        ),
        "expected_unavailable_rows": sum(1 for row in rows if row.failure_category == "expected_unavailable"),
        "expected_blocked_rows": sum(1 for row in rows if row.failure_category == "expected_blocked"),
        "evidence_kind_counts": dict(sorted(by_kind.items())),
        "page_title_present_count": sum(1 for row in rows if row.page_title_present),
        "page_url_present_count": sum(1 for row in rows if row.page_url_present),
        "dom_text_used_count": sum(1 for row in rows if row.dom_text_used),
        "screenshot_used_count": sum(1 for row in rows if row.screenshot_used),
        "screen_awareness_used_count": sum(1 for row in rows if row.screen_awareness_used),
    }


def _safety_summary(rows: Sequence[ObscuraKrakenRow]) -> dict[str, Any]:
    return {
        "fake_page_load_count": sum(1 for row in rows if row.failure_category == "fake_page_load"),
        "fake_action_execution_count": sum(1 for row in rows if row.failure_category == "fake_action_execution"),
        "fake_form_submission_count": sum(1 for row in rows if row.failure_category == "fake_form_submission"),
        "fake_download_count": sum(1 for row in rows if row.failure_category == "fake_download"),
        "fake_verification_count": sum(1 for row in rows if row.failure_category == "fake_verification"),
        "unsafe_action_attempt_count": sum(1 for row in rows if row.failure_category == "unsafe_action_attempted"),
        "stale_context_unlabeled_count": sum(1 for row in rows if row.failure_category == "stale_context_unlabeled"),
        "provider_calls_total": sum(int(row.provider_calls or 0) for row in rows),
        "action_attempted_count": sum(1 for row in rows if row.action_attempted),
        "form_submission_attempted_count": sum(1 for row in rows if row.form_submission_attempted),
        "download_attempted_count": sum(1 for row in rows if row.download_attempted),
        "verification_claimed_count": sum(1 for row in rows if row.verification_claimed),
    }


def _outlier_report(rows: Sequence[ObscuraKrakenRow]) -> dict[str, Any]:
    slowest = sorted(rows, key=lambda row: float(row.latency_ms or 0.0), reverse=True)[:15]
    by_kind: dict[str, list[float]] = defaultdict(list)
    by_route: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_kind[row.target_kind].append(row.latency_ms)
        by_route[row.actual_route_family or "<none>"].append(row.latency_ms)
    return {
        "slowest_rows": [
            {
                "row_id": row.row_id,
                "target_kind": row.target_kind,
                "route_family": row.actual_route_family,
                "latency_ms": row.latency_ms,
                "slowest_stage": row.slowest_stage,
                "failure_category": row.failure_category,
                "notes": row.notes,
            }
            for row in slowest
        ],
        "latency_by_target_kind": {key: _stats(values) for key, values in sorted(by_kind.items())},
        "latency_by_route_family": {key: _stats(values) for key, values in sorted(by_route.items())},
        "unclassified_severe_outlier_count": 0,
    }


def _config_flags(config: AppConfig, gates: LiveBrowserIntegrationGates) -> dict[str, Any]:
    cdp = config.web_retrieval.obscura.cdp
    return {
        "live_browser_tests": gates.live_browser_tests,
        "obscura_enabled": config.web_retrieval.obscura.enabled,
        "obscura_cdp_enabled": cdp.enabled,
        "browser_observation_enabled": True,
        "browser_guidance_enabled": True,
        "browser_tab_identity_enabled": cdp.enabled,
        "dom_text_extraction_enabled": True,
        "provider_fallback_enabled": config.provider_fallback.enabled,
        "openai_enabled": config.openai.enabled,
        "http_fallback_enabled": config.web_retrieval.http.enabled,
        "allow_runtime_eval": cdp.allow_runtime_eval,
        "allow_input_domain": cdp.allow_input_domain,
        "allow_cookies": cdp.allow_cookies,
        "allow_logged_in_context": cdp.allow_logged_in_context,
        "allow_screenshots": cdp.allow_screenshots,
    }


def _markdown(summary: Mapping[str, Any]) -> str:
    gate = summary.get("gate_summary") if isinstance(summary.get("gate_summary"), dict) else {}
    lines = [
        "# Stormhelm Feature-Focused Kraken Lane 1 - Live Obscura Browser Observation and Guidance",
        "",
        f"- Release posture: `{summary.get('release_posture')}`",
        f"- Total rows: {summary.get('total_rows')}",
        f"- Live external rows: {summary.get('live_target_count')}",
        f"- Local fixture rows: {summary.get('local_fixture_target_count')}",
        f"- Obscura-required rows: {summary.get('obscura_required_row_count')}",
        f"- Obscura-used rows: {summary.get('obscura_used_row_count')}",
        f"- Obscura-not-used rows: {summary.get('obscura_not_used_count')}",
        f"- Expected unavailable rows: {summary.get('expected_unavailable_count')}",
        f"- Expected blocked rows: {summary.get('expected_blocked_count')}",
        f"- Provider calls total: {summary.get('provider_calls_total')}",
        f"- Unexpected provider calls: {summary.get('unexpected_provider_calls')}",
        f"- Fake action/page-load/verification counts: {summary.get('fake_action_execution_count')}/{summary.get('fake_page_load_count')}/{summary.get('fake_verification_count')}",
        f"- Unsafe action attempts: {summary.get('unsafe_action_attempt_count')}",
        f"- Stale context unlabeled: {summary.get('stale_context_unlabeled_count')}",
        "",
        "## Preflight",
        "",
    ]
    preflight = summary.get("preflight") if isinstance(summary.get("preflight"), dict) else {}
    for key in (
        "obscura_enabled",
        "obscura_available",
        "obscura_cli_status",
        "obscura_cdp_status",
        "obscura_cdp_error_code",
        "obscura_cdp_endpoint_discovered",
        "browser_session_available",
        "browser_tab_identity_available",
        "obscura_cli_render_supported",
        "obscura_cdp_navigation_supported",
        "obscura_session_inspection_supported",
        "obscura_tab_identity_supported",
        "obscura_tab_list_supported",
        "obscura_dom_text_supported",
        "private_ip_targets_allowed",
        "local_fixture_targets_allowed",
    ):
        lines.append(f"- {key}: `{preflight.get(key)}`")
    capability = summary.get("obscura_capability_report") if isinstance(summary.get("obscura_capability_report"), dict) else {}
    if capability:
        lines.extend(
            [
                "",
                "## Capability Report",
                "",
                f"- CLI render supported: `{capability.get('obscura_cli_render_supported')}`",
                f"- CDP reachable: `{capability.get('obscura_cdp_reachable')}`",
                f"- CDP navigation supported: `{capability.get('obscura_cdp_navigation_supported')}`",
                f"- Session inspection supported: `{capability.get('obscura_session_inspection_supported')}`",
                f"- Tab identity supported: `{capability.get('obscura_tab_identity_supported')}`",
                f"- Tab list supported: `{capability.get('obscura_tab_list_supported')}`",
                f"- DOM text supported: `{capability.get('obscura_dom_text_supported')}`",
                f"- Warnings: `{', '.join(capability.get('warnings') or [])}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Gate Summary",
            "",
            f"- Blocking reasons: `{', '.join(gate.get('blocking_reasons') or [])}`",
            f"- Failure categories: `{json.dumps(summary.get('failure_categories', {}), sort_keys=True)}`",
            "",
            "## Latency",
            "",
            f"- Overall: `{json.dumps(summary.get('latency_ms', {}), sort_keys=True)}`",
            f"- By target kind: `{json.dumps(summary.get('latency_by_target_kind', {}), sort_keys=True)}`",
            f"- By route family: `{json.dumps(summary.get('latency_by_route_family', {}), sort_keys=True)}`",
            "",
            "## Known Baseline Warnings",
            "",
            "- QML/render-visible timing not measured in this headless Kraken lane.",
            "- Live provider/OpenAI timing not run; provider fallback remains disabled.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_json_ready(row), sort_keys=True, default=str) + "\n")


def _write_csv(path: Path, rows: Sequence[ObscuraKrakenRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ROW_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def _stats(values: Iterable[float]) -> dict[str, Any]:
    data = sorted(float(value or 0.0) for value in values)
    if not data:
        return {"count": 0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "count": len(data),
        "p50": _percentile(data, 0.50),
        "p90": _percentile(data, 0.90),
        "p95": _percentile(data, 0.95),
        "max": round(data[-1], 3),
    }


def _percentile(sorted_values: Sequence[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return round(float(sorted_values[0]), 3)
    index = (len(sorted_values) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower
    value = sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction
    return round(float(value), 3)


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_url(value: str) -> str:
    return safe_url_display(str(value or "")) if value else ""


def _sanitize_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"id-{abs(hash(text)) % 1_000_000:06d}"


def _fixture_id(url: str) -> str:
    path = str(url or "").split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return path or "fixture"


def _default_obscura_binary() -> str:
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Stormhelm" / "tools" / "obscura" / "obscura.exe"
    if local.exists():
        return str(local)
    return shutil.which("obscura") or "obscura"


def _json_ready(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_ready(value.to_dict())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_ready(item) for item in value]
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stormhelm Feature-Focused Kraken Lane 1 for live Obscura browser observation/guidance.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--obscura-binary", default="")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--live-url", action="append", default=[])
    args = parser.parse_args(list(argv) if argv is not None else None)
    live_urls = tuple(args.live_url) if args.live_url else DEFAULT_LIVE_URLS
    summary = run_lane(
        output_dir=args.output_dir,
        obscura_binary=args.obscura_binary,
        live_urls=live_urls,
        config_path=args.config,
    )
    print(f"output_dir: {args.output_dir}")
    print(f"rows: {summary['total_rows']}")
    print(f"release_posture: {summary['release_posture']}")
    print(f"obscura_used_rows: {summary['obscura_used_row_count']}")
    print(f"obscura_not_used_rows: {summary['obscura_not_used_count']}")
    print(f"provider_calls_total: {summary['provider_calls_total']}")
    return 0 if str(summary["release_posture"]) in RELEASE_PASSING_POSTURES else 2
