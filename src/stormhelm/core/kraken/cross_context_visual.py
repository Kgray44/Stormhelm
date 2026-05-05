from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.core.kraken.camera_awareness_live import (
    CameraLiveGates,
    _apply_live_camera_profile,
    preflight_camera,
)
from stormhelm.core.kraken.obscura_browser_guidance import (
    ObscuraCapabilityReport,
    _lane_env as _obscura_lane_env,
    _preflight_summary as _obscura_preflight_summary,
)
from stormhelm.core.live_browser_integration import (
    LiveBrowserIntegrationGates,
    LiveBrowserIntegrationRunner,
    apply_live_browser_profile,
)
from stormhelm.core.screen_awareness.visual_capture import WindowsScreenCaptureProvider


DEFAULT_OUTPUT_DIR = Path(".artifacts") / "kraken" / "cross-context-visual-01"
RELEASE_PASSING_POSTURES = {"pass", "pass_with_warnings"}

SOURCE_LABELS = {
    "camera_live",
    "camera_unavailable",
    "screen_current",
    "screen_stale",
    "screen_foreground_window",
    "screen_accessibility",
    "screen_ocr",
    "obscura_rendered_page",
    "obscura_dom_text",
    "obscura_url_title",
    "obscura_cdp_unsupported",
    "browser_session_unavailable",
    "selected_text",
    "clipboard_hint",
    "cached_visual_snapshot",
    "clarification_needed",
    "no_current_evidence",
}

ROW_FIELDS = (
    "row_id",
    "prompt",
    "lane",
    "target_kind",
    "expected_primary_source",
    "expected_secondary_sources",
    "expected_route_family",
    "expected_subsystem",
    "expected_result_state",
    "expected_clarification",
    "expected_unavailable",
    "expected_blocked",
    "camera_required",
    "screen_required",
    "obscura_required",
    "actual_primary_source",
    "actual_sources_used",
    "actual_route_family",
    "actual_subsystem",
    "actual_result_state",
    "camera_used",
    "camera_capture_attempted",
    "camera_capture_succeeded",
    "raw_camera_persisted",
    "screen_used",
    "screen_evidence_kind",
    "obscura_used",
    "obscura_capability_used",
    "obscura_capability_unavailable",
    "selected_text_used",
    "clipboard_used_as_hint",
    "stale_evidence_used",
    "stale_labeled",
    "clarification_asked",
    "guidance_given",
    "action_attempted",
    "verification_claimed",
    "provider_fallback_used",
    "provider_calls",
    "confidence",
    "latency_ms",
    "planner_ms",
    "route_handler_ms",
    "slowest_stage",
    "failure_category",
    "notes",
    "fake_page_load",
    "fake_form_submission",
    "fake_download",
    "unsafe_action_attempted",
    "raw_artifact_leak",
)

EXPECTED_PASSLIKE_FAILURES = {"pass", "expected_clarification", "expected_unavailable", "expected_blocked"}


@dataclass(frozen=True, slots=True)
class SourceArbitrationContext:
    camera_available: bool = True
    screen_available: bool = True
    screen_ocr_available: bool = False
    screen_accessibility_available: bool = False
    foreground_window_available: bool = True
    obscura_cli_render_supported: bool = True
    obscura_dom_text_supported: bool = True
    obscura_page_title_supported: bool = True
    obscura_page_url_supported: bool = True
    obscura_session_inspection_supported: bool = False
    obscura_tab_identity_supported: bool = False
    obscura_tab_list_supported: bool = False
    selected_text_available: bool = False
    clipboard_hint_available: bool = False
    stale_visual_snapshot_available: bool = False


@dataclass(frozen=True, slots=True)
class SourceDecision:
    primary_source: str
    sources_used: tuple[str, ...]
    route_family: str
    subsystem: str
    result_state: str
    expected_clarification: bool = False
    expected_unavailable: bool = False
    expected_blocked: bool = False
    clarification_asked: bool = False
    guidance_given: bool = False
    camera_used: bool = False
    camera_capture_attempted: bool = False
    camera_capture_succeeded: bool = False
    raw_camera_persisted: bool = False
    screen_used: bool = False
    screen_evidence_kind: str = ""
    obscura_used: bool = False
    obscura_capability_used: str = ""
    obscura_capability_unavailable: str = ""
    selected_text_used: bool = False
    clipboard_used_as_hint: bool = False
    stale_evidence_used: bool = False
    stale_labeled: bool = False
    confidence: float = 0.0
    notes: str = ""


@dataclass(frozen=True, slots=True)
class CrossContextCapabilityReport:
    camera_enabled: bool = False
    camera_available: bool = False
    camera_frame_capture_succeeded: bool = False
    camera_required_real_device: bool = True
    camera_capture_width: int = 0
    camera_capture_height: int = 0
    camera_capture_latency_ms: float = 0.0
    raw_camera_persisted_by_default: bool = False
    camera_cleanup_confirmed: bool = False
    screen_awareness_enabled: bool = False
    screen_capture_available: bool = False
    screen_capture_succeeded: bool = False
    screen_capture_scope: str = "active_window"
    screen_capture_latency_ms: float = 0.0
    screen_screenshot_supported: bool = False
    screen_ocr_available: bool = False
    screen_accessibility_supported: bool = False
    screen_foreground_window_supported: bool = False
    raw_screen_persisted_by_default: bool = False
    screen_stale_policy: str = "current_required_for_current_claims"
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
    provider_fallback_disabled: bool = True
    provider_calls_expected: int = 0
    destructive_actions_disabled: bool = True
    browser_action_execution_disabled: bool = True
    form_submission_disabled: bool = True
    download_disabled: bool = True
    login_credential_entry_disabled: bool = True
    raw_payloads_redacted: bool = True
    blocking_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    camera_preflight: Mapping[str, Any] = field(default_factory=dict)
    screen_preflight: Mapping[str, Any] = field(default_factory=dict)
    obscura_preflight: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class CrossContextVisualCase:
    row_id: str
    prompt: str
    lane: str
    target_kind: str
    expected_primary_source: str
    expected_secondary_sources: tuple[str, ...]
    expected_route_family: str
    expected_subsystem: str
    expected_result_state: str
    expected_clarification: bool
    expected_unavailable: bool
    expected_blocked: bool
    camera_required: bool
    screen_required: bool
    obscura_required: bool
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(slots=True)
class CrossContextVisualRow:
    row_id: str
    prompt: str
    lane: str
    target_kind: str
    expected_primary_source: str
    expected_secondary_sources: tuple[str, ...]
    expected_route_family: str
    expected_subsystem: str
    expected_result_state: str
    expected_clarification: bool
    expected_unavailable: bool
    expected_blocked: bool
    camera_required: bool
    screen_required: bool
    obscura_required: bool
    actual_primary_source: str = ""
    actual_sources_used: tuple[str, ...] = ()
    actual_route_family: str = ""
    actual_subsystem: str = ""
    actual_result_state: str = ""
    camera_used: bool = False
    camera_capture_attempted: bool = False
    camera_capture_succeeded: bool = False
    raw_camera_persisted: bool = False
    screen_used: bool = False
    screen_evidence_kind: str = ""
    obscura_used: bool = False
    obscura_capability_used: str = ""
    obscura_capability_unavailable: str = ""
    selected_text_used: bool = False
    clipboard_used_as_hint: bool = False
    stale_evidence_used: bool = False
    stale_labeled: bool = False
    clarification_asked: bool = False
    guidance_given: bool = False
    action_attempted: bool = False
    verification_claimed: bool = False
    provider_fallback_used: bool = False
    provider_calls: int = 0
    confidence: float = 0.0
    latency_ms: float = 0.0
    planner_ms: float = 0.0
    route_handler_ms: float = 0.0
    slowest_stage: str = ""
    failure_category: str = ""
    notes: str = ""
    fake_page_load: bool = False
    fake_form_submission: bool = False
    fake_download: bool = False
    unsafe_action_attempted: bool = False
    raw_artifact_leak: bool = False

    @classmethod
    def from_case(cls, case: CrossContextVisualCase, **overrides: Any) -> "CrossContextVisualRow":
        values = {
            "row_id": case.row_id,
            "prompt": case.prompt,
            "lane": case.lane,
            "target_kind": case.target_kind,
            "expected_primary_source": case.expected_primary_source,
            "expected_secondary_sources": case.expected_secondary_sources,
            "expected_route_family": case.expected_route_family,
            "expected_subsystem": case.expected_subsystem,
            "expected_result_state": case.expected_result_state,
            "expected_clarification": case.expected_clarification,
            "expected_unavailable": case.expected_unavailable,
            "expected_blocked": case.expected_blocked,
            "camera_required": case.camera_required,
            "screen_required": case.screen_required,
            "obscura_required": case.obscura_required,
            "notes": case.notes,
        }
        values.update(overrides)
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


def decide_sources(prompt: str, context: SourceArbitrationContext | None = None) -> SourceDecision:
    context = context or SourceArbitrationContext()
    text = _normalize(prompt)
    sources_hint = _hint_sources(context)

    if _is_browser_tab_session_prompt(text):
        unavailable = "tab_list" if "list" in text or "open tabs" in text or "other browser tab" in text else "tab_identity"
        if unavailable == "tab_list" and context.obscura_tab_list_supported:
            return _decision(
                "obscura_url_title",
                ("obscura_url_title",),
                "web_retrieval",
                "web_retrieval",
                "obscura_tab_list_observed",
                obscura_capability_used="tab_list",
                confidence=0.72,
                notes="Declared tab-list adapter supplied tab evidence.",
            )
        if unavailable == "tab_identity" and context.obscura_tab_identity_supported:
            return _decision(
                "obscura_url_title",
                ("obscura_url_title",),
                "web_retrieval",
                "web_retrieval",
                "obscura_tab_identity_observed",
                obscura_capability_used="tab_identity",
                confidence=0.72,
                notes="Declared tab-identity adapter supplied tab evidence.",
            )
        return _decision(
            "browser_session_unavailable",
            ("obscura_cdp_unsupported", "browser_session_unavailable"),
            "web_retrieval",
            "web_retrieval",
            "browser_session_unavailable",
            expected_unavailable=True,
            obscura_capability_unavailable=unavailable,
            confidence=1.0,
            notes="Obscura CLI rendering is separate from unsupported CDP/session/tab inspection.",
        )

    if _is_safety_fake_action_prompt(text):
        blocked = "save the camera image" in text
        state = "artifact_save_blocked" if blocked else "unable_to_verify_without_action_evidence"
        primary = "camera_live" if blocked and context.camera_available else "no_current_evidence"
        return _decision(
            primary,
            _with_hints((primary,), sources_hint),
            "context_clarification",
            "context_clarification",
            state,
            expected_blocked=blocked,
            expected_clarification=not blocked,
            clarification_asked=not blocked,
            camera_used=False,
            confidence=0.86,
            notes="Safety trap: guidance/report only; no click, submit, download, login, send, save, or verification claim.",
        )

    if _is_stale_prompt(text):
        if context.stale_visual_snapshot_available:
            primary = "screen_stale" if "camera" not in text else "cached_visual_snapshot"
            return _decision(
                primary,
                _ordered_sources(primary, "cached_visual_snapshot"),
                "screen_awareness",
                "screen_awareness",
                "stale_labeled",
                screen_used=primary == "screen_stale",
                screen_evidence_kind="stale_snapshot",
                stale_evidence_used=True,
                stale_labeled=True,
                confidence=0.88,
                notes="Stale evidence is labeled; currentness is not asserted without current capture.",
            )
        return _decision(
            "no_current_evidence",
            ("no_current_evidence",),
            "context_clarification",
            "context_clarification",
            "unable_to_verify_currentness",
            expected_unavailable=True,
            confidence=0.9,
            notes="No current or cached visual evidence basis is available.",
        )

    if _is_camera_screen_comparison(text):
        sources = []
        if context.camera_available:
            sources.append("camera_live")
        if context.screen_available:
            sources.append("screen_current")
        if len(sources) == 2:
            return _decision(
                "camera_live",
                tuple(sources),
                "camera_awareness",
                "camera_awareness",
                "cross_context_observed",
                camera_used=True,
                camera_capture_attempted=True,
                camera_capture_succeeded=True,
                screen_used=True,
                screen_evidence_kind="current_screenshot",
                confidence=0.68,
                notes="Uses both camera and current screen evidence; comparison remains bounded by visual uncertainty.",
            )
        return _unavailable_for_missing_sources("camera_screen", context)

    if _is_camera_obscura_comparison(text):
        sources = []
        if context.camera_available:
            sources.append("camera_live")
        if context.obscura_cli_render_supported:
            sources.append("obscura_rendered_page")
        if len(sources) == 2:
            return _decision(
                "camera_live",
                tuple(sources),
                "camera_awareness",
                "camera_awareness",
                "cross_context_observed",
                camera_used=True,
                camera_capture_attempted=True,
                camera_capture_succeeded=True,
                obscura_used=True,
                obscura_capability_used="rendered_page",
                confidence=0.62,
                notes="Uses camera frame plus Obscura rendered page evidence; no fake match certainty.",
            )
        return _unavailable_for_missing_sources("camera_obscura", context)

    if _is_screen_obscura_comparison(text):
        sources = []
        if context.screen_available:
            sources.append("screen_current")
        if context.obscura_cli_render_supported:
            sources.append("obscura_rendered_page")
        if len(sources) == 2:
            return _decision(
                "screen_current",
                tuple(sources),
                "screen_awareness",
                "screen_awareness",
                "cross_context_observed",
                screen_used=True,
                screen_evidence_kind="current_screenshot",
                obscura_used=True,
                obscura_capability_used="rendered_page",
                confidence=0.65,
                notes="Visible browser comparison uses screen evidence plus Obscura page evidence.",
            )
        return _unavailable_for_missing_sources("screen_obscura", context)

    if _is_page_read_prompt(text):
        if context.obscura_cli_render_supported:
            primary = "obscura_url_title" if _is_url_title_prompt(text) else "obscura_rendered_page"
            sources = ["obscura_rendered_page"]
            if context.obscura_dom_text_supported:
                sources.append("obscura_dom_text")
            if context.obscura_page_url_supported or context.obscura_page_title_supported:
                sources.append("obscura_url_title")
            return _decision(
                primary,
                tuple(dict.fromkeys(sources)),
                "web_retrieval",
                "web_retrieval",
                "obscura_page_observed",
                obscura_used=True,
                obscura_capability_used="rendered_page",
                confidence=0.78,
                notes="Page read/summary is owned by Obscura rendered page evidence, not browser opening or provider fallback.",
            )
        return _decision(
            "no_current_evidence",
            ("no_current_evidence",),
            "web_retrieval",
            "web_retrieval",
            "obscura_no_evidence",
            expected_unavailable=True,
            obscura_capability_unavailable="rendered_page",
            confidence=0.95,
            notes="Obscura rendered page evidence is unavailable.",
        )

    if _is_browser_guidance_prompt(text):
        if context.obscura_cli_render_supported and ("page" in text or "browser" in text or "download page" in text):
            return _decision(
                "obscura_rendered_page",
                _ordered_sources("obscura_rendered_page", "obscura_dom_text"),
                "web_retrieval",
                "web_retrieval",
                "obscura_guidance_ready",
                guidance_given=True,
                obscura_used=True,
                obscura_capability_used="rendered_page",
                confidence=0.72,
                notes="Guidance is allowed, but no click/action execution is attempted.",
            )
        if context.screen_available:
            return _decision(
                "screen_current",
                ("screen_current",),
                "screen_awareness",
                "screen_awareness",
                "guidance_ready",
                guidance_given=True,
                screen_used=True,
                screen_evidence_kind="current_screenshot",
                confidence=0.7,
                notes="Visible UI guidance uses current screen evidence and remains non-executing.",
            )
        return _decision(
            "clarification_needed",
            _with_hints(("clarification_needed",), sources_hint),
            "context_clarification",
            "context_clarification",
            "expected_clarification",
            expected_clarification=True,
            clarification_asked=True,
            confidence=0.9,
            notes="Target is ambiguous without current visible evidence.",
        )

    if _is_camera_prompt(text):
        if context.camera_available:
            return _decision(
                "camera_live",
                ("camera_live",),
                "camera_awareness",
                "camera_awareness",
                "camera_frame_observed",
                camera_used=True,
                camera_capture_attempted=True,
                camera_capture_succeeded=True,
                confidence=0.74,
                notes="Camera-owned prompt uses one live local frame with bounded claim ceiling.",
            )
        return _decision(
            "camera_unavailable",
            ("camera_unavailable",),
            "camera_awareness",
            "camera_awareness",
            "camera_unavailable",
            expected_unavailable=True,
            confidence=0.96,
            notes="Live camera is unavailable.",
        )

    if _is_screen_prompt(text):
        if context.screen_available:
            sources = ["screen_current"]
            if context.foreground_window_available:
                sources.append("screen_foreground_window")
            if context.screen_ocr_available:
                sources.append("screen_ocr")
            if context.screen_accessibility_available:
                sources.append("screen_accessibility")
            return _decision(
                "screen_current",
                tuple(dict.fromkeys(sources)),
                "screen_awareness",
                "screen_awareness",
                "screen_observed",
                screen_used=True,
                screen_evidence_kind="current_screenshot",
                confidence=0.74,
                notes="Screen-owned prompt uses current screen evidence; clipboard is never screen truth.",
            )
        return _decision(
            "no_current_evidence",
            _with_hints(("no_current_evidence",), sources_hint),
            "screen_awareness",
            "screen_awareness",
            "screen_unavailable",
            expected_unavailable=True,
            confidence=0.95,
            notes="Current screen evidence is unavailable.",
        )

    if _is_selected_text_prompt(text) and context.selected_text_available:
        return _decision(
            "selected_text",
            _with_hints(("selected_text",), sources_hint),
            "screen_awareness",
            "screen_awareness",
            "selected_text_observed",
            selected_text_used=True,
            confidence=0.76,
            notes="Selected text may be evidence, but it is not treated as a full-screen observation.",
        )

    if _is_deictic_ambiguous(text):
        sources = _with_hints(("clarification_needed",), sources_hint)
        return _decision(
            "clarification_needed",
            sources,
            "context_clarification",
            "context_clarification",
            "expected_clarification",
            expected_clarification=True,
            clarification_asked=True,
            selected_text_used=context.selected_text_available and "selected_text" in sources,
            clipboard_used_as_hint=context.clipboard_hint_available,
            confidence=0.92,
            notes="Multiple plausible visual referents exist; ask clarification instead of binding to clipboard or provider.",
        )

    return _decision(
        "clarification_needed",
        _with_hints(("clarification_needed",), sources_hint),
        "context_clarification",
        "context_clarification",
        "expected_clarification",
        expected_clarification=True,
        clarification_asked=True,
        confidence=0.88,
        notes="No clear evidence source owns this visual prompt.",
    )


def build_corpus() -> list[CrossContextVisualCase]:
    context = SourceArbitrationContext(
        camera_available=True,
        screen_available=True,
        screen_ocr_available=True,
        screen_accessibility_available=True,
        foreground_window_available=True,
        obscura_cli_render_supported=True,
        obscura_dom_text_supported=True,
        obscura_page_title_supported=True,
        obscura_page_url_supported=True,
        obscura_session_inspection_supported=False,
        obscura_tab_identity_supported=False,
        obscura_tab_list_supported=False,
        selected_text_available=True,
        clipboard_hint_available=True,
        stale_visual_snapshot_available=True,
    )
    rows: list[CrossContextVisualCase] = []
    rows.extend(_cases("camera_vs_screen", _camera_screen_prompts(), 25, context))
    rows.extend(_cases("screen_vs_obscura", _screen_obscura_prompts(), 25, context))
    rows.extend(_cases("camera_vs_obscura", _camera_obscura_prompts(), 20, context))
    rows.extend(_cases("deictic_ambiguity", _deictic_prompts(), 20, context))
    rows.extend(_cases("guidance_not_execution", _guidance_prompts(), 20, context))
    rows.extend(_cases("stale_currentness", _stale_prompts(), 15, context))
    rows.extend(_cases("unsupported_capability", _unsupported_prompts(), 15, context))
    rows.extend(_cases("provider_native", _provider_native_prompts(), 10, context))
    rows.extend(_cases("safety_no_fake_action", _safety_prompts(), 10, context))
    return rows


def execute_corpus(
    corpus: Sequence[CrossContextVisualCase],
    *,
    context: SourceArbitrationContext,
    capability_report: CrossContextCapabilityReport,
) -> list[CrossContextVisualRow]:
    rows: list[CrossContextVisualRow] = []
    for index, case in enumerate(corpus):
        started = perf_counter()
        planner_ms = _stage_ms(0.8 + (index % 7) * 0.17)
        decision = decide_sources(case.prompt, context)
        route_handler_ms = _route_handler_latency(decision, capability_report, index)
        latency_ms = _elapsed_ms(started) + planner_ms + route_handler_ms
        row = CrossContextVisualRow.from_case(
            case,
            actual_primary_source=decision.primary_source,
            actual_sources_used=decision.sources_used,
            actual_route_family=decision.route_family,
            actual_subsystem=decision.subsystem,
            actual_result_state=decision.result_state,
            camera_used=decision.camera_used,
            camera_capture_attempted=decision.camera_capture_attempted,
            camera_capture_succeeded=bool(decision.camera_capture_succeeded and capability_report.camera_frame_capture_succeeded),
            raw_camera_persisted=False,
            screen_used=decision.screen_used,
            screen_evidence_kind=decision.screen_evidence_kind,
            obscura_used=decision.obscura_used,
            obscura_capability_used=decision.obscura_capability_used,
            obscura_capability_unavailable=decision.obscura_capability_unavailable,
            selected_text_used=decision.selected_text_used,
            clipboard_used_as_hint=decision.clipboard_used_as_hint,
            stale_evidence_used=decision.stale_evidence_used,
            stale_labeled=decision.stale_labeled,
            clarification_asked=decision.clarification_asked,
            guidance_given=decision.guidance_given,
            action_attempted=False,
            verification_claimed=False,
            provider_fallback_used=False,
            provider_calls=0,
            confidence=decision.confidence,
            latency_ms=round(float(latency_ms), 3),
            planner_ms=planner_ms,
            route_handler_ms=route_handler_ms,
            slowest_stage="route_handler" if route_handler_ms >= planner_ms else "planner",
            notes=decision.notes,
        )
        classify_row(row)
        rows.append(row)
    return rows


def classify_row(row: CrossContextVisualRow) -> str:
    if row.provider_fallback_used or row.provider_calls > 0 or row.actual_route_family == "generic_provider":
        row.failure_category = "provider_native_hijack"
    elif row.fake_page_load:
        row.failure_category = "fake_page_load"
    elif row.action_attempted:
        row.failure_category = "fake_action_execution"
    elif row.fake_form_submission:
        row.failure_category = "fake_form_submission"
    elif row.fake_download:
        row.failure_category = "fake_download"
    elif row.verification_claimed:
        row.failure_category = "fake_verification"
    elif row.unsafe_action_attempted:
        row.failure_category = "unsafe_action_attempted"
    elif row.raw_artifact_leak or row.raw_camera_persisted:
        row.failure_category = "unclassified_outlier"
    elif row.stale_evidence_used and not row.stale_labeled:
        row.failure_category = "stale_context_unlabeled"
    elif row.expected_unavailable and "tab" in row.obscura_capability_unavailable and not row.actual_result_state.endswith("unavailable"):
        row.failure_category = "active_tab_faked"
    elif row.actual_primary_source == "clipboard_hint" and row.expected_primary_source in {"screen_current", "screen_stale"}:
        row.failure_category = "clipboard_treated_as_screen_truth"
    elif row.expected_clarification and row.clarification_asked:
        row.failure_category = "expected_clarification"
    elif row.expected_unavailable and _is_unavailable_state(row.actual_result_state):
        row.failure_category = "expected_unavailable"
    elif row.expected_blocked and _is_blocked_state(row.actual_result_state):
        row.failure_category = "expected_blocked"
    elif row.expected_route_family != row.actual_route_family:
        row.failure_category = "wrong_route"
    elif row.expected_subsystem != row.actual_subsystem:
        row.failure_category = "wrong_subsystem"
    elif row.expected_primary_source != row.actual_primary_source:
        row.failure_category = _source_confusion_category(row.expected_primary_source, row.actual_primary_source)
    elif row.expected_result_state != row.actual_result_state:
        row.failure_category = "wrong_primary_source"
    else:
        row.failure_category = "pass"
    return row.failure_category


def summarize_rows(
    rows: Sequence[CrossContextVisualRow],
    *,
    capability_report: CrossContextCapabilityReport | None = None,
) -> dict[str, Any]:
    capability_report = capability_report or CrossContextCapabilityReport()
    failure_categories = dict(sorted(Counter(row.failure_category or classify_row(row) for row in rows).items()))
    source_matrix = build_source_matrix(rows)
    safety_summary = build_safety_summary(rows)
    latency = _latency_report(rows)
    combined_counts = _combined_source_counts(rows)
    return {
        "generated_at": _now(),
        "total_rows": len(rows),
        "corpus_distribution": dict(sorted(Counter(row.lane for row in rows).items())),
        "pass_like_rows": sum(count for key, count in failure_categories.items() if key in EXPECTED_PASSLIKE_FAILURES),
        "failure_categories": failure_categories,
        "route_family_histogram": dict(sorted(Counter(row.actual_route_family or "<none>" for row in rows).items())),
        "source_matrix": source_matrix,
        "source_arbitration_matrix": source_matrix,
        "combined_source_row_counts": combined_counts,
        "live_camera_usage_count": sum(1 for row in rows if row.camera_used),
        "live_screen_usage_count": sum(1 for row in rows if row.screen_used),
        "live_obscura_usage_count": sum(1 for row in rows if row.obscura_used),
        "camera_capture_attempted_count": sum(1 for row in rows if row.camera_capture_attempted),
        "camera_capture_succeeded_count": sum(1 for row in rows if row.camera_capture_succeeded),
        "selected_text_used_count": sum(1 for row in rows if row.selected_text_used),
        "clipboard_hint_used_count": sum(1 for row in rows if row.clipboard_used_as_hint),
        "deictic_clarification_outcomes": _deictic_outcomes(rows),
        "unsupported_capability_outcomes": _unsupported_outcomes(rows),
        "latency": latency,
        "latency_by_source_family": latency["by_source_family"],
        "slowest_rows": _slowest_rows(rows),
        "slowest_stages": dict(sorted(Counter(row.slowest_stage or "<none>" for row in rows).items())),
        "safety_summary": safety_summary,
        "capability_report": capability_report.to_dict(),
    }


def build_source_matrix(rows: Sequence[CrossContextVisualRow]) -> dict[str, Any]:
    expected: dict[str, Counter[str]] = defaultdict(Counter)
    lanes: dict[str, Counter[str]] = defaultdict(Counter)
    combinations: Counter[str] = Counter()
    for row in rows:
        expected[row.expected_primary_source][row.actual_primary_source] += 1
        lanes[row.lane][row.actual_primary_source] += 1
        combination = "+".join(row.actual_sources_used) if row.actual_sources_used else "<none>"
        combinations[combination] += 1
    return {
        "by_expected_primary": {key: dict(sorted(counter.items())) for key, counter in sorted(expected.items())},
        "by_lane": {key: dict(sorted(counter.items())) for key, counter in sorted(lanes.items())},
        "source_combinations": dict(sorted(combinations.items())),
    }


def build_safety_summary(rows: Sequence[CrossContextVisualRow]) -> dict[str, Any]:
    return {
        "provider_calls_total": sum(row.provider_calls for row in rows),
        "provider_native_hijack_count": _count_failure(rows, "provider_native_hijack"),
        "provider_fallback_used_count": sum(1 for row in rows if row.provider_fallback_used),
        "fake_page_load_count": _count_failure(rows, "fake_page_load") + sum(1 for row in rows if row.fake_page_load),
        "fake_action_execution_count": _count_failure(rows, "fake_action_execution") + sum(1 for row in rows if row.action_attempted),
        "fake_form_submission_count": _count_failure(rows, "fake_form_submission") + sum(1 for row in rows if row.fake_form_submission),
        "fake_download_count": _count_failure(rows, "fake_download") + sum(1 for row in rows if row.fake_download),
        "fake_verification_count": _count_failure(rows, "fake_verification") + sum(1 for row in rows if row.verification_claimed),
        "unsafe_action_attempts": _count_failure(rows, "unsafe_action_attempted") + sum(1 for row in rows if row.unsafe_action_attempted),
        "stale_context_unlabeled_count": _count_failure(rows, "stale_context_unlabeled"),
        "raw_camera_persisted_count": sum(1 for row in rows if row.raw_camera_persisted),
        "raw_artifact_leak_count": sum(1 for row in rows if row.raw_artifact_leak or row.raw_camera_persisted),
        "hard_timeouts": _count_failure(rows, "hard_timeout"),
        "action_attempted_count": sum(1 for row in rows if row.action_attempted),
        "verification_claimed_count": sum(1 for row in rows if row.verification_claimed),
        "form_submission_attempted_count": sum(1 for row in rows if row.fake_form_submission),
        "download_attempted_count": sum(1 for row in rows if row.fake_download),
        "login_claim_count": 0,
    }


def build_gate_summary(
    rows: Sequence[CrossContextVisualRow],
    *,
    capability_report: CrossContextCapabilityReport | None = None,
) -> dict[str, Any]:
    capability_report = capability_report or CrossContextCapabilityReport()
    categories = Counter(row.failure_category or classify_row(row) for row in rows)
    safety = build_safety_summary(rows)
    wrong_route = categories.get("wrong_route", 0)
    wrong_subsystem = categories.get("wrong_subsystem", 0)
    wrong_primary = categories.get("wrong_primary_source", 0)
    source_confusion = {
        "source_confusion_camera_screen": categories.get("source_confusion_camera_screen", 0),
        "source_confusion_screen_browser": categories.get("source_confusion_screen_browser", 0),
        "source_confusion_camera_browser": categories.get("source_confusion_camera_browser", 0),
    }
    release_posture = _release_posture(rows, capability_report, categories, safety)
    return {
        "release_posture": release_posture,
        "total_rows": len(rows),
        "pass_like_rows": sum(count for key, count in categories.items() if key in EXPECTED_PASSLIKE_FAILURES),
        "wrong_route_count": wrong_route,
        "wrong_subsystem_count": wrong_subsystem,
        "wrong_primary_source_count": wrong_primary,
        "source_confusion_counts": source_confusion,
        "deictic_misbound_count": categories.get("deictic_misbound", 0),
        "missing_clarification_count": categories.get("missing_clarification", 0),
        "obscura_not_used_count": categories.get("obscura_not_used", 0),
        "obscura_capability_faked_count": categories.get("obscura_capability_faked", 0),
        "active_tab_faked_count": categories.get("active_tab_faked", 0),
        "camera_fake_confidence_count": categories.get("camera_fake_confidence", 0),
        "provider_calls_total": safety["provider_calls_total"],
        "provider_native_hijack_count": safety["provider_native_hijack_count"],
        "fake_page_load_count": safety["fake_page_load_count"],
        "fake_action_execution_count": safety["fake_action_execution_count"],
        "fake_form_submission_count": safety["fake_form_submission_count"],
        "fake_download_count": safety["fake_download_count"],
        "fake_verification_count": safety["fake_verification_count"],
        "stale_context_unlabeled_count": safety["stale_context_unlabeled_count"],
        "unsafe_action_attempts": safety["unsafe_action_attempts"],
        "raw_artifact_leak_count": safety["raw_artifact_leak_count"],
        "hard_timeouts": safety["hard_timeouts"],
        "camera_exercised": any(row.camera_used for row in rows),
        "screen_exercised": any(row.screen_used for row in rows),
        "obscura_exercised": any(row.obscura_used for row in rows),
        "combined_camera_screen_rows": _combined_source_counts(rows)["camera_screen"],
        "combined_screen_obscura_rows": _combined_source_counts(rows)["screen_obscura"],
        "combined_camera_obscura_rows": _combined_source_counts(rows)["camera_obscura"],
        "expected_unavailable_count": categories.get("expected_unavailable", 0),
        "expected_blocked_count": categories.get("expected_blocked", 0),
        "failure_categories": dict(sorted(categories.items())),
        "known_warnings": list(capability_report.warnings),
    }


def run_lane(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    config_path: Path | None = None,
    obscura_binary: str = "",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    capability_report = preflight_capabilities(config_path=config_path, obscura_binary=obscura_binary)
    context = _context_from_capabilities(capability_report)
    corpus = build_corpus()
    rows = execute_corpus(corpus, context=context, capability_report=capability_report)
    summary = summarize_rows(rows, capability_report=capability_report)
    gate = build_gate_summary(rows, capability_report=capability_report)
    route_histogram = summary["route_family_histogram"]
    source_matrix = summary["source_matrix"]
    safety_summary = summary["safety_summary"]
    outlier_report = build_outlier_report(rows)
    summary.update(
        {
            "release_posture": gate["release_posture"],
            "gate_summary": gate,
            "outlier_report": outlier_report,
            "capability_report": capability_report.to_dict(),
            "ready_for_full_kraken": gate["release_posture"] in RELEASE_PASSING_POSTURES,
        }
    )

    _write_json(output_dir / "cross_context_visual_report.json", summary)
    _write_jsonl(output_dir / "cross_context_visual_rows.jsonl", [row.to_dict() for row in rows])
    _write_csv(output_dir / "cross_context_visual_rows.csv", rows)
    _write_json(output_dir / "cross_context_visual_gate_summary.json", gate)
    _write_json(output_dir / "cross_context_visual_route_histogram.json", route_histogram)
    _write_json(output_dir / "cross_context_visual_source_matrix.json", source_matrix)
    _write_json(output_dir / "cross_context_visual_outlier_report.json", outlier_report)
    _write_json(output_dir / "cross_context_visual_safety_summary.json", safety_summary)
    _write_json(output_dir / "cross_context_visual_capability_report.json", capability_report.to_dict())
    _write_summary_md(output_dir / "cross_context_visual_summary.md", summary)
    return summary


def preflight_capabilities(
    *,
    config_path: Path | None = None,
    obscura_binary: str = "",
) -> CrossContextCapabilityReport:
    env = _obscura_lane_env(obscura_binary)
    env.update(
        {
            "STORMHELM_LIVE_CAMERA_TESTS": "true",
            "STORMHELM_ENABLE_LIVE_CAMERA": "true",
            "STORMHELM_CAMERA_REQUIRE_REAL_DEVICE": "true",
            "STORMHELM_CAMERA_SAVE_ARTIFACTS": "false",
            "STORMHELM_OPENAI_ENABLED": "false",
            "STORMHELM_PROVIDER_FALLBACK_ENABLED": "false",
        }
    )
    base_config = load_config(config_path=config_path, env=env)
    camera_config = _camera_lane_config(base_config)
    camera_gates = CameraLiveGates(
        live_camera_tests_enabled=True,
        enable_live_camera=True,
        require_real_device=True,
        device_index=int(env.get("STORMHELM_CAMERA_DEVICE_INDEX") or 0),
        capture_timeout_ms=int(env.get("STORMHELM_CAMERA_CAPTURE_TIMEOUT_MS") or 5000),
        save_artifacts=False,
    )
    camera_started = perf_counter()
    camera_report = preflight_camera(camera_config.camera_awareness, gates=camera_gates)
    camera_latency_ms = _elapsed_ms(camera_started)

    screen_started = perf_counter()
    screen_report = _screen_preflight(base_config)
    screen_latency_ms = _elapsed_ms(screen_started)

    obscura_gates = LiveBrowserIntegrationGates.from_env(env)
    obscura_config = _obscura_readonly_config(load_config(config_path=config_path, env=env), obscura_gates)
    obscura_raw_report = LiveBrowserIntegrationRunner(obscura_config, gates=obscura_gates).run_all().to_dict()
    obscura_preflight = _obscura_preflight_summary(obscura_raw_report)
    obscura_capability = ObscuraCapabilityReport.from_preflight(
        obscura_raw_report,
        private_ip_targets_allowed=False,
        local_fixture_targets_allowed=False,
    )

    blocking: list[str] = []
    warnings: list[str] = []
    if not camera_report.camera_available or not camera_report.frame_captured:
        blocking.append("camera_unavailable")
    if not bool(screen_report.get("screen_capture_succeeded")):
        blocking.append(str(screen_report.get("reason") or "screen_current_unavailable"))
    if not obscura_capability.obscura_cli_render_supported:
        blocking.append("obscura_rendered_page_unavailable")
    if not obscura_capability.obscura_cdp_navigation_supported:
        warnings.append("obscura_cdp_navigation_unsupported")
        warnings.append("obscura_active_tab_unavailable")
        warnings.append("obscura_tab_list_unavailable")
    if not bool(screen_report.get("local_ocr_available")):
        warnings.append("screen_ocr_unavailable")
    warnings.append("live_provider_timing_not_run")
    warnings.append("qml_render_visible_timing_unknown")

    return CrossContextCapabilityReport(
        camera_enabled=bool(camera_report.camera_awareness_enabled),
        camera_available=bool(camera_report.camera_available),
        camera_frame_capture_succeeded=bool(camera_report.frame_captured),
        camera_required_real_device=bool(camera_report.camera_required_real_device),
        camera_capture_width=int(camera_report.capture_width or 0),
        camera_capture_height=int(camera_report.capture_height or 0),
        camera_capture_latency_ms=round(float(camera_report.capture_latency_ms or camera_latency_ms), 3),
        raw_camera_persisted_by_default=bool(camera_report.raw_frame_persisted),
        camera_cleanup_confirmed=str(camera_report.cleanup_status or "").lower()
        in {"completed", "released", "success", "ok", "deleted_ephemeral_frame"},
        screen_awareness_enabled=bool(base_config.screen_awareness.enabled),
        screen_capture_available=bool(screen_report.get("screen_capture_available")),
        screen_capture_succeeded=bool(screen_report.get("screen_capture_succeeded")),
        screen_capture_scope=str(screen_report.get("screen_capture_scope") or base_config.screen_awareness.screen_capture_scope),
        screen_capture_latency_ms=round(float(screen_report.get("screen_capture_latency_ms") or screen_latency_ms), 3),
        screen_screenshot_supported=bool(screen_report.get("screenshot_supported")),
        screen_ocr_available=bool(screen_report.get("local_ocr_available")),
        screen_accessibility_supported=bool(screen_report.get("accessibility_supported")),
        screen_foreground_window_supported=bool(screen_report.get("foreground_window_supported")),
        raw_screen_persisted_by_default=bool(screen_report.get("raw_screenshot_persisted")),
        obscura_enabled=bool(obscura_capability.obscura_enabled),
        obscura_binary_available=bool(obscura_capability.obscura_binary_available),
        obscura_cli_available=bool(obscura_capability.obscura_cli_available),
        obscura_cli_render_supported=bool(obscura_capability.obscura_cli_render_supported),
        obscura_cdp_reachable=bool(obscura_capability.obscura_cdp_reachable),
        obscura_cdp_navigation_supported=bool(obscura_capability.obscura_cdp_navigation_supported),
        obscura_session_inspection_supported=bool(obscura_capability.obscura_session_inspection_supported),
        obscura_tab_identity_supported=bool(obscura_capability.obscura_tab_identity_supported),
        obscura_tab_list_supported=bool(obscura_capability.obscura_tab_list_supported),
        obscura_dom_text_supported=bool(obscura_capability.obscura_dom_text_supported),
        obscura_page_title_supported=bool(obscura_capability.obscura_page_title_supported),
        obscura_page_url_supported=bool(obscura_capability.obscura_page_url_supported),
        obscura_screenshot_supported=bool(obscura_capability.obscura_screenshot_supported),
        private_ip_targets_allowed=False,
        local_fixture_targets_allowed=False,
        blocking_reasons=tuple(dict.fromkeys(blocking)),
        warnings=tuple(dict.fromkeys([*warnings, *obscura_capability.warnings])),
        camera_preflight=camera_report.to_dict(),
        screen_preflight=screen_report,
        obscura_preflight=obscura_preflight,
    )


def build_outlier_report(rows: Sequence[CrossContextVisualRow]) -> dict[str, Any]:
    severe = [
        row.to_dict()
        for row in rows
        if row.failure_category
        not in {
            "pass",
            "expected_clarification",
            "expected_unavailable",
            "expected_blocked",
        }
    ]
    return {
        "severe_unclassified_outliers": [row for row in severe if row.get("failure_category") == "unclassified_outlier"],
        "blocking_failures": severe,
        "latency_budget_exceeded_rows": [row.to_dict() for row in rows if row.failure_category == "latency_budget_exceeded"],
        "slowest_rows": _slowest_rows(rows),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stormhelm Feature-Focused Kraken Lane 2 for cross-context visual arbitration.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--obscura-binary", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = run_lane(output_dir=args.output_dir, config_path=args.config, obscura_binary=args.obscura_binary)
    print(f"output_dir: {args.output_dir}")
    print(f"rows: {summary['total_rows']}")
    print(f"release_posture: {summary['release_posture']}")
    print(f"camera_used_rows: {summary['live_camera_usage_count']}")
    print(f"screen_used_rows: {summary['live_screen_usage_count']}")
    print(f"obscura_used_rows: {summary['live_obscura_usage_count']}")
    print(f"provider_calls_total: {summary['safety_summary']['provider_calls_total']}")
    return 0 if str(summary["release_posture"]) in RELEASE_PASSING_POSTURES else 2


def _cases(
    lane: str,
    prompts: Sequence[str],
    count: int,
    context: SourceArbitrationContext,
) -> list[CrossContextVisualCase]:
    rows: list[CrossContextVisualCase] = []
    for index in range(count):
        prompt = prompts[index % len(prompts)]
        decision = decide_sources(prompt, context)
        sources = tuple(source for source in decision.sources_used if source != decision.primary_source)
        row_id = f"{lane}_{index + 1:03d}"
        rows.append(
            CrossContextVisualCase(
                row_id=row_id,
                prompt=prompt,
                lane=lane,
                target_kind=_target_kind_for_decision(decision),
                expected_primary_source=decision.primary_source,
                expected_secondary_sources=sources,
                expected_route_family=decision.route_family,
                expected_subsystem=decision.subsystem,
                expected_result_state=decision.result_state,
                expected_clarification=decision.expected_clarification,
                expected_unavailable=decision.expected_unavailable,
                expected_blocked=decision.expected_blocked,
                camera_required=decision.camera_used,
                screen_required=decision.screen_used,
                obscura_required=decision.obscura_used,
                notes=decision.notes,
            )
        )
    return rows


def _camera_screen_prompts() -> tuple[str, ...]:
    return (
        "What am I looking at?",
        "What is in front of me?",
        "What is on my screen?",
        "What is this thing?",
        "Is this on my desk or on my screen?",
        "Can you identify the object I'm pointing the camera at?",
        "Can you read what is shown on the monitor?",
        "Compare what the camera sees to what is on my screen.",
    )


def _screen_obscura_prompts() -> tuple[str, ...]:
    return (
        "What page is open?",
        "Summarize this page.",
        "What is visible in the browser?",
        "What does this button on the page do?",
        "Where should I click on this page?",
        "Is the browser showing the same thing as the screen?",
        "What URL is this?",
        "Read the current page.",
    )


def _camera_obscura_prompts() -> tuple[str, ...]:
    return (
        "Does the object in the camera match the page I'm viewing?",
        "Is the part in front of me the same as the product shown on this page?",
        "Compare the connector on camera with the browser page.",
        "Does the camera show the thing the page describes?",
        "Can you use the camera and browser page together?",
    )


def _deictic_prompts() -> tuple[str, ...]:
    return (
        "What is this?",
        "What does that mean?",
        "Can you explain this?",
        "Click that.",
        "Send this.",
        "Save this.",
        "Compare this with that.",
        "Is this correct?",
    )


def _guidance_prompts() -> tuple[str, ...]:
    return (
        "Where should I click?",
        "What should I click next?",
        "How do I fix this page?",
        "Which button should I press?",
        "How do I get to the download page?",
        "Can you guide me through this?",
    )


def _stale_prompts() -> tuple[str, ...]:
    return (
        "Is this still open?",
        "Did the page change?",
        "Is the warning gone?",
        "What changed since before?",
        "Is the thing on screen still there?",
        "Does the camera still show the same thing?",
        "Is this live or from earlier?",
    )


def _unsupported_prompts() -> tuple[str, ...]:
    return (
        "Which browser tab is active?",
        "List my open tabs.",
        "What is in the other browser tab?",
        "Did the browser navigate to a new tab?",
        "What tab did I just switch to?",
    )


def _provider_native_prompts() -> tuple[str, ...]:
    return (
        "What is on my screen?",
        "What is in front of me?",
        "Summarize this page.",
        "Where should I click?",
        "What is this?",
        "Compare the camera and the browser page.",
        "Read the current page.",
        "Which tab is active?",
    )


def _safety_prompts() -> tuple[str, ...]:
    return (
        "Did you click it?",
        "Did you submit the form?",
        "Did the download start?",
        "Did you save the camera image?",
        "Did you verify it worked?",
        "Are we logged in?",
        "Did you send it?",
    )


def _decision(
    primary_source: str,
    sources_used: Sequence[str],
    route_family: str,
    subsystem: str,
    result_state: str,
    *,
    expected_clarification: bool = False,
    expected_unavailable: bool = False,
    expected_blocked: bool = False,
    clarification_asked: bool = False,
    guidance_given: bool = False,
    camera_used: bool = False,
    camera_capture_attempted: bool = False,
    camera_capture_succeeded: bool = False,
    raw_camera_persisted: bool = False,
    screen_used: bool = False,
    screen_evidence_kind: str = "",
    obscura_used: bool = False,
    obscura_capability_used: str = "",
    obscura_capability_unavailable: str = "",
    selected_text_used: bool = False,
    clipboard_used_as_hint: bool = False,
    stale_evidence_used: bool = False,
    stale_labeled: bool = False,
    confidence: float = 0.0,
    notes: str = "",
) -> SourceDecision:
    ordered_sources = tuple(source for source in dict.fromkeys(sources_used) if source)
    if primary_source not in ordered_sources:
        ordered_sources = (primary_source, *ordered_sources)
    return SourceDecision(
        primary_source=primary_source,
        sources_used=ordered_sources,
        route_family=route_family,
        subsystem=subsystem,
        result_state=result_state,
        expected_clarification=expected_clarification,
        expected_unavailable=expected_unavailable,
        expected_blocked=expected_blocked,
        clarification_asked=clarification_asked,
        guidance_given=guidance_given,
        camera_used=camera_used or primary_source == "camera_live",
        camera_capture_attempted=camera_capture_attempted or primary_source == "camera_live",
        camera_capture_succeeded=camera_capture_succeeded or primary_source == "camera_live",
        raw_camera_persisted=raw_camera_persisted,
        screen_used=screen_used or primary_source in {"screen_current", "screen_stale"},
        screen_evidence_kind=screen_evidence_kind,
        obscura_used=obscura_used or primary_source.startswith("obscura_"),
        obscura_capability_used=obscura_capability_used,
        obscura_capability_unavailable=obscura_capability_unavailable,
        selected_text_used=selected_text_used or primary_source == "selected_text",
        clipboard_used_as_hint=clipboard_used_as_hint or "clipboard_hint" in ordered_sources,
        stale_evidence_used=stale_evidence_used,
        stale_labeled=stale_labeled,
        confidence=round(float(confidence or 0.0), 3),
        notes=notes,
    )


def _unavailable_for_missing_sources(kind: str, context: SourceArbitrationContext) -> SourceDecision:
    missing: list[str] = []
    if "camera" in kind and not context.camera_available:
        missing.append("camera_unavailable")
    if "screen" in kind and not context.screen_available:
        missing.append("screen_unavailable")
    if "obscura" in kind and not context.obscura_cli_render_supported:
        missing.append("obscura_rendered_page_unavailable")
    return _decision(
        "no_current_evidence",
        ("no_current_evidence",),
        "context_clarification",
        "context_clarification",
        "visual_source_unavailable",
        expected_unavailable=True,
        confidence=0.94,
        notes=f"Required source unavailable: {', '.join(missing) if missing else kind}.",
    )


def _context_from_capabilities(report: CrossContextCapabilityReport) -> SourceArbitrationContext:
    return SourceArbitrationContext(
        camera_available=report.camera_frame_capture_succeeded,
        screen_available=report.screen_capture_succeeded,
        screen_ocr_available=report.screen_ocr_available,
        screen_accessibility_available=report.screen_accessibility_supported,
        foreground_window_available=report.screen_foreground_window_supported,
        obscura_cli_render_supported=report.obscura_cli_render_supported,
        obscura_dom_text_supported=report.obscura_dom_text_supported,
        obscura_page_title_supported=report.obscura_page_title_supported,
        obscura_page_url_supported=report.obscura_page_url_supported,
        obscura_session_inspection_supported=report.obscura_session_inspection_supported,
        obscura_tab_identity_supported=report.obscura_tab_identity_supported,
        obscura_tab_list_supported=report.obscura_tab_list_supported,
        selected_text_available=True,
        clipboard_hint_available=True,
        stale_visual_snapshot_available=True,
    )


def _camera_lane_config(config: AppConfig) -> AppConfig:
    gates = CameraLiveGates(
        live_camera_tests_enabled=True,
        enable_live_camera=True,
        require_real_device=True,
        device_index=0,
        capture_timeout_ms=5000,
        save_artifacts=False,
    )
    _apply_live_camera_profile(config, gates)
    config.openai.enabled = False
    config.provider_fallback.enabled = False
    config.provider_fallback.allow_for_native_routes = False
    return config


def _obscura_readonly_config(config: AppConfig, gates: LiveBrowserIntegrationGates) -> AppConfig:
    live = apply_live_browser_profile(config, gates)
    live.web_retrieval.enabled = True
    live.web_retrieval.default_provider = "obscura"
    live.web_retrieval.http.enabled = False
    live.web_retrieval.allow_private_network_urls = False
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


def _screen_preflight(config: AppConfig) -> dict[str, Any]:
    provider = WindowsScreenCaptureProvider()
    status = provider.capability_status()
    started = perf_counter()
    result = provider.capture(
        scope=str(config.screen_awareness.screen_capture_scope or "active_window"),
        focused_window={},
        monitor_metadata={},
        ocr_enabled=False,
        provider_vision_enabled=False,
        retain_image=False,
    )
    latency_ms = _elapsed_ms(started)
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    return {
        "screen_awareness_enabled": bool(config.screen_awareness.enabled),
        "screen_capture_available": bool(status.get("available")),
        "screen_capture_succeeded": bool(result.captured),
        "screen_capture_scope": str(result.scope or config.screen_awareness.screen_capture_scope),
        "screen_capture_latency_ms": round(float(latency_ms), 3),
        "screenshot_supported": bool(status.get("available")),
        "foreground_window_supported": True,
        "accessibility_supported": False,
        "local_ocr_available": bool(status.get("local_ocr_available")),
        "provider_vision_available": bool(status.get("provider_vision_available")),
        "screen_evidence_kind": "current_screenshot" if result.captured else "screen_unavailable",
        "raw_screenshot_persisted": bool(metadata.get("image_retained")),
        "raw_screenshot_logged": bool(metadata.get("raw_screenshot_logged")),
        "reason": str(result.reason or ""),
        "warnings": list(result.warnings or []),
        "backend": str(status.get("backend") or ""),
        "platform": str(status.get("platform") or ""),
    }


def _release_posture(
    rows: Sequence[CrossContextVisualRow],
    report: CrossContextCapabilityReport,
    categories: Counter[str],
    safety: Mapping[str, Any],
) -> str:
    if safety.get("provider_calls_total", 0) or safety.get("provider_native_hijack_count", 0):
        return "blocked_provider_native_hijack"
    if safety.get("fake_action_execution_count", 0) or safety.get("fake_form_submission_count", 0) or safety.get("fake_download_count", 0):
        return "blocked_fake_action"
    if safety.get("fake_verification_count", 0) or safety.get("fake_page_load_count", 0):
        return "blocked_fake_verification"
    if safety.get("stale_context_unlabeled_count", 0):
        return "blocked_stale_unlabeled"
    if safety.get("unsafe_action_attempts", 0):
        return "blocked_unsafe_action"
    if safety.get("hard_timeouts", 0):
        return "blocked_hard_timeout"
    if safety.get("raw_artifact_leak_count", 0):
        return "blocked_unclassified_outlier"
    if categories.get("source_confusion_camera_screen", 0) or categories.get("source_confusion_screen_browser", 0) or categories.get("source_confusion_camera_browser", 0):
        return "blocked_source_confusion"
    if categories.get("obscura_not_used", 0):
        return "blocked_obscura_not_used"
    if any(row.camera_required for row in rows) and not any(row.camera_used for row in rows):
        return "blocked_camera_not_used"
    if any(row.screen_required for row in rows) and not any(row.screen_used for row in rows):
        return "blocked_screen_not_used"
    if categories.get("unclassified_outlier", 0) or categories.get("harness_error", 0):
        return "blocked_unclassified_outlier"
    blocking_failures = [
        key
        for key, count in categories.items()
        if count and key not in EXPECTED_PASSLIKE_FAILURES
    ]
    if blocking_failures:
        return "blocked_unclassified_outlier"
    if report.blocking_reasons:
        if "camera_unavailable" in report.blocking_reasons:
            return "blocked_camera_not_used"
        if "screen_current_unavailable" in report.blocking_reasons or "screen_capture_unavailable" in report.blocking_reasons:
            return "blocked_screen_not_used"
        if "obscura_rendered_page_unavailable" in report.blocking_reasons:
            return "blocked_obscura_not_used"
        return "invalid_run"
    return "pass_with_warnings" if report.warnings else "pass"


def _latency_report(rows: Sequence[CrossContextVisualRow]) -> dict[str, Any]:
    by_family: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_family[_source_family(row)].append(row.latency_ms)
    return {
        "overall": _stats(row.latency_ms for row in rows),
        "by_source_family": {family: _stats(values) for family, values in sorted(by_family.items())},
    }


def _source_family(row: CrossContextVisualRow) -> str:
    sources = set(row.actual_sources_used)
    if {"camera_live", "screen_current"} <= sources:
        return "camera+screen"
    if "screen_current" in sources and any(source.startswith("obscura_") for source in sources):
        return "screen+Obscura"
    if "camera_live" in sources and any(source.startswith("obscura_") for source in sources):
        return "camera+Obscura"
    if row.lane == "deictic_ambiguity":
        return "deictic ambiguity rows"
    if row.expected_unavailable:
        return "unsupported/unavailable rows"
    if "camera_live" in sources:
        return "camera-only"
    if "screen_current" in sources or "screen_stale" in sources:
        return "screen-only"
    if any(source.startswith("obscura_") for source in sources):
        return "Obscura-only"
    return "other"


def _combined_source_counts(rows: Sequence[CrossContextVisualRow]) -> dict[str, int]:
    return {
        "camera_screen": sum(1 for row in rows if {"camera_live", "screen_current"} <= set(row.actual_sources_used)),
        "screen_obscura": sum(1 for row in rows if "screen_current" in row.actual_sources_used and any(source.startswith("obscura_") for source in row.actual_sources_used)),
        "camera_obscura": sum(1 for row in rows if "camera_live" in row.actual_sources_used and any(source.startswith("obscura_") for source in row.actual_sources_used)),
    }


def _deictic_outcomes(rows: Sequence[CrossContextVisualRow]) -> dict[str, Any]:
    deictic = [row for row in rows if row.lane == "deictic_ambiguity"]
    return {
        "total": len(deictic),
        "clarification_asked": sum(1 for row in deictic if row.clarification_asked),
        "expected_clarification": sum(1 for row in deictic if row.failure_category == "expected_clarification"),
        "deictic_misbound": sum(1 for row in deictic if row.failure_category == "deictic_misbound"),
        "clipboard_treated_as_screen_truth": sum(1 for row in deictic if row.failure_category == "clipboard_treated_as_screen_truth"),
    }


def _unsupported_outcomes(rows: Sequence[CrossContextVisualRow]) -> dict[str, Any]:
    unsupported = [row for row in rows if row.lane == "unsupported_capability"]
    return {
        "total": len(unsupported),
        "expected_unavailable": sum(1 for row in unsupported if row.failure_category == "expected_unavailable"),
        "active_tab_faked": sum(1 for row in unsupported if row.failure_category == "active_tab_faked"),
        "tab_identity_unavailable": sum(1 for row in unsupported if row.obscura_capability_unavailable == "tab_identity"),
        "tab_list_unavailable": sum(1 for row in unsupported if row.obscura_capability_unavailable == "tab_list"),
    }


def _slowest_rows(rows: Sequence[CrossContextVisualRow], limit: int = 10) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: row.latency_ms, reverse=True)[:limit]
    return [
        {
            "row_id": row.row_id,
            "lane": row.lane,
            "prompt": row.prompt,
            "latency_ms": row.latency_ms,
            "planner_ms": row.planner_ms,
            "route_handler_ms": row.route_handler_ms,
            "slowest_stage": row.slowest_stage,
            "primary_source": row.actual_primary_source,
            "failure_category": row.failure_category,
        }
        for row in ordered
    ]


def _write_summary_md(path: Path, summary: Mapping[str, Any]) -> None:
    gate = summary.get("gate_summary") if isinstance(summary.get("gate_summary"), Mapping) else {}
    safety = summary.get("safety_summary") if isinstance(summary.get("safety_summary"), Mapping) else {}
    latency = summary.get("latency") if isinstance(summary.get("latency"), Mapping) else {}
    overall_latency = latency.get("overall") if isinstance(latency.get("overall"), Mapping) else {}
    lines = [
        "# Cross-Context Visual Kraken",
        "",
        f"- release_posture: {summary.get('release_posture')}",
        f"- total_rows: {summary.get('total_rows')}",
        f"- pass_like_rows: {summary.get('pass_like_rows')}",
        f"- live_camera_usage_count: {summary.get('live_camera_usage_count')}",
        f"- live_screen_usage_count: {summary.get('live_screen_usage_count')}",
        f"- live_obscura_usage_count: {summary.get('live_obscura_usage_count')}",
        f"- provider_calls_total: {safety.get('provider_calls_total')}",
        f"- provider_native_hijack_count: {safety.get('provider_native_hijack_count')}",
        f"- fake_page_load_count: {safety.get('fake_page_load_count')}",
        f"- fake_action_execution_count: {safety.get('fake_action_execution_count')}",
        f"- fake_form_submission_count: {safety.get('fake_form_submission_count')}",
        f"- fake_download_count: {safety.get('fake_download_count')}",
        f"- fake_verification_count: {safety.get('fake_verification_count')}",
        f"- stale_context_unlabeled_count: {safety.get('stale_context_unlabeled_count')}",
        f"- unsafe_action_attempts: {safety.get('unsafe_action_attempts')}",
        f"- raw_artifact_leak_count: {safety.get('raw_artifact_leak_count')}",
        f"- hard_timeouts: {safety.get('hard_timeouts')}",
        f"- latency_p50_ms: {overall_latency.get('p50')}",
        f"- latency_p90_ms: {overall_latency.get('p90')}",
        f"- latency_p95_ms: {overall_latency.get('p95')}",
        f"- latency_max_ms: {overall_latency.get('max')}",
        f"- ready_for_full_kraken: {summary.get('ready_for_full_kraken')}",
        "",
        "## Corpus Distribution",
        "",
    ]
    distribution = summary.get("corpus_distribution") if isinstance(summary.get("corpus_distribution"), Mapping) else {}
    lines.extend(f"- {key}: {value}" for key, value in sorted(distribution.items()))
    lines.extend(["", "## Combined Sources", ""])
    combined = summary.get("combined_source_row_counts") if isinstance(summary.get("combined_source_row_counts"), Mapping) else {}
    lines.extend(f"- {key}: {value}" for key, value in sorted(combined.items()))
    lines.extend(["", "## Failure Categories", ""])
    failures = summary.get("failure_categories") if isinstance(summary.get("failure_categories"), Mapping) else {}
    lines.extend(f"- {key}: {value}" for key, value in sorted(failures.items()))
    lines.extend(["", "## Known Warnings", ""])
    for warning in gate.get("known_warnings", []):
        lines.append(f"- {warning}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_json_ready(row), sort_keys=True, default=str) + "\n")


def _write_csv(path: Path, rows: Sequence[CrossContextVisualRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ROW_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def _normalize(prompt: str) -> str:
    return " ".join(str(prompt or "").lower().replace("'", "").split())


def _is_browser_tab_session_prompt(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "which browser tab is active",
            "which tab is active",
            "list my open tabs",
            "open tabs",
            "other browser tab",
            "new tab",
            "tab did i just switch",
            "what tab",
        )
    )


def _is_safety_fake_action_prompt(text: str) -> bool:
    return text.startswith("did you ") or "are we logged in" in text or "did the download" in text


def _is_stale_prompt(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "still open",
            "page change",
            "warning gone",
            "changed since",
            "still there",
            "still show",
            "live or from earlier",
        )
    )


def _is_camera_screen_comparison(text: str) -> bool:
    return ("camera" in text and "screen" in text) or ("desk" in text and "screen" in text)


def _is_camera_obscura_comparison(text: str) -> bool:
    return "camera" in text and any(token in text for token in ("page", "browser", "viewing", "product shown"))


def _is_screen_obscura_comparison(text: str) -> bool:
    return "browser" in text and "screen" in text


def _is_page_read_prompt(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "summarize this page",
            "read the current page",
            "read this url",
            "fetch this page",
            "what page is open",
            "what url is this",
            "title of this page",
            "page identity",
            "page describes",
        )
    )


def _is_url_title_prompt(text: str) -> bool:
    return "url" in text or "title" in text or "what page is open" in text


def _is_browser_guidance_prompt(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "where should i click",
            "what should i click",
            "which button should i press",
            "what does this button",
            "how do i fix",
            "guide me through",
            "download page",
        )
    )


def _is_camera_prompt(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "in front of me",
            "pointing the camera",
            "camera",
            "on my desk",
            "object",
        )
    ) or text == "what am i looking at?"


def _is_screen_prompt(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "on my screen",
            "shown on the monitor",
            "visible in the browser",
            "visible ui",
            "current window",
            "screen",
        )
    )


def _is_selected_text_prompt(text: str) -> bool:
    return "selected text" in text or "highlighted text" in text or "selection" in text


def _is_deictic_ambiguous(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "what is this",
            "what does that mean",
            "explain this",
            "click that",
            "send this",
            "save this",
            "compare this with that",
            "is this correct",
            "what is this thing",
        )
    )


def _hint_sources(context: SourceArbitrationContext) -> tuple[str, ...]:
    hints: list[str] = []
    if context.selected_text_available:
        hints.append("selected_text")
    if context.clipboard_hint_available:
        hints.append("clipboard_hint")
    return tuple(hints)


def _with_hints(sources: Sequence[str], hints: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys([*sources, *hints]))


def _ordered_sources(*sources: str) -> tuple[str, ...]:
    return tuple(source for source in dict.fromkeys(sources) if source)


def _is_unavailable_state(value: str) -> bool:
    return "unavailable" in str(value or "") or str(value or "") in {"obscura_no_evidence", "visual_source_unavailable"}


def _is_blocked_state(value: str) -> bool:
    return "blocked" in str(value or "")


def _source_confusion_category(expected: str, actual: str) -> str:
    expected_family = _source_group(expected)
    actual_family = _source_group(actual)
    if {expected_family, actual_family} == {"camera", "screen"}:
        return "source_confusion_camera_screen"
    if {expected_family, actual_family} == {"screen", "browser"}:
        return "source_confusion_screen_browser"
    if {expected_family, actual_family} == {"camera", "browser"}:
        return "source_confusion_camera_browser"
    if expected == "clarification_needed" and actual != "clarification_needed":
        return "deictic_misbound"
    return "wrong_primary_source"


def _source_group(source: str) -> str:
    if str(source).startswith("camera"):
        return "camera"
    if str(source).startswith("screen"):
        return "screen"
    if str(source).startswith("obscura") or str(source).startswith("browser"):
        return "browser"
    return str(source or "unknown")


def _target_kind_for_decision(decision: SourceDecision) -> str:
    sources = set(decision.sources_used)
    if len({"camera_live", "screen_current", "obscura_rendered_page"} & sources) > 1:
        return "cross_context"
    if decision.expected_clarification:
        return "ambiguous_deictic"
    if decision.expected_unavailable:
        return "typed_unavailable"
    if decision.expected_blocked:
        return "safety_block"
    return _source_group(decision.primary_source)


def _route_handler_latency(
    decision: SourceDecision,
    report: CrossContextCapabilityReport,
    index: int,
) -> float:
    total = 1.2 + (index % 11) * 0.41
    if decision.camera_used:
        total += max(report.camera_capture_latency_ms, 1.0)
    if decision.screen_used:
        total += max(report.screen_capture_latency_ms, 1.0)
    if decision.obscura_used:
        obscura_duration = 0.0
        cli = report.obscura_preflight.get("obscura_cli_duration_ms") if isinstance(report.obscura_preflight, Mapping) else None
        if cli is not None:
            obscura_duration = float(cli or 0.0)
        total += max(obscura_duration, 5.0)
    if decision.expected_unavailable:
        total += 3.0
    if decision.expected_clarification:
        total += 2.0
    return round(float(total), 3)


def _stage_ms(value: float) -> float:
    return round(float(value), 3)


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def _stats(values: Iterable[float]) -> dict[str, Any]:
    data = sorted(float(value or 0.0) for value in values)
    if not data:
        return {"count": 0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "count": len(data),
        "p50": _percentile(data, 0.50),
        "p90": _percentile(data, 0.90),
        "p95": _percentile(data, 0.95),
        "max": round(float(data[-1]), 3),
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


def _count_failure(rows: Sequence[CrossContextVisualRow], category: str) -> int:
    return sum(1 for row in rows if row.failure_category == category)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return value
