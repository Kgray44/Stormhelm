from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import json
from typing import Any, Iterable, Mapping, Sequence

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.core.screen_awareness.models import ScreenResponse
from stormhelm.core.screen_awareness.visual_capture import ScreenCaptureResult
from stormhelm.ui.command_surface_v2 import _stations


RAW_PAYLOAD_SENTINEL = "RAW_SCREENSHOT_PIXEL_PAYLOAD_SHOULD_NOT_LEAK"
DEFAULT_PROMPTS = (
    "what is on my screen right now?",
    "what do you see?",
    "what am I looking at?",
    "can you help with this?",
)
RAW_PAYLOAD_MARKERS = (
    RAW_PAYLOAD_SENTINEL,
    "raw_pixels",
    "pixel_bytes",
    "data:image",
    "base64_png",
    "iVBORw0KGgo",
)


@dataclass(frozen=True, slots=True)
class CurrentScreenCaptureFixture:
    captured: bool = True
    text: str | None = None
    text_source: str | None = "local_ocr"
    confidence_score: float = 0.9
    scope: str = "active_window"
    capture_reference: str = "screen-capture:kraken-fixture"
    captured_at: str = "2026-05-04T14:00:00+00:00"
    reason: str | None = None

    def to_capture_result(self, scenario_id: str) -> ScreenCaptureResult:
        return ScreenCaptureResult(
            captured=self.captured,
            captured_at=self.captured_at,
            scope=self.scope,
            capture_reference=f"{self.capture_reference}:{scenario_id}" if self.captured else None,
            text=self.text,
            text_source=self.text_source if self.text else None,
            confidence_score=self.confidence_score,
            reason=self.reason,
            metadata={
                "backend": "fixture",
                "raw_screenshot_logged": False,
                "image_retained": False,
                "raw_pixels": RAW_PAYLOAD_SENTINEL,
            },
        )


@dataclass(frozen=True, slots=True)
class CurrentScreenUsabilityCase:
    scenario_id: str
    scenario_family: str
    evidence_mode: str
    prompt: str
    window_title: str = ""
    process_name: str = "ApplicationFrameHost"
    windows: tuple[dict[str, Any], ...] = ()
    capture: CurrentScreenCaptureFixture | None = None
    capture_available: bool = True
    screen_capture_enabled: bool = True
    active_context: Mapping[str, Any] = field(default_factory=dict)
    workspace_context: Mapping[str, Any] = field(default_factory=dict)
    expected_route_family: str = "screen_awareness"
    expected_top_source: str | None = None
    expected_answered_from_source: str | None = None
    expected_observation_attempted: bool | None = None
    expect_visible_context_summary: bool = True
    expect_weak_fallback: bool = False
    expect_no_visual_evidence_reason: bool = False
    expected_keywords: tuple[str, ...] = ()
    forbidden_phrases: tuple[str, ...] = ()
    require_task_hypothesis: bool = False
    golden_response_snapshot: str = ""
    before_example: str = ""

    def focused_window(self) -> dict[str, Any] | None:
        if self.window_title:
            return _window(self.window_title, process_name=self.process_name, focused=True, handle=710)
        return None

    def all_windows(self) -> list[dict[str, Any]]:
        if self.windows:
            return [dict(item) for item in self.windows]
        focused = self.focused_window()
        return [focused] if focused else []


@dataclass(slots=True)
class CurrentScreenUsabilityRow:
    prompt: str
    scenario_id: str
    scenario_family: str
    evidence_mode: str
    expected_route_family: str
    evidence_before_observation: list[dict[str, Any]]
    observation_attempted: bool
    evidence_after_observation: list[dict[str, Any]]
    answered_from_source: str
    visible_context_summary_present: bool
    key_text_quality: str
    task_hypothesis_quality: str
    ghost_compact: bool
    deck_trace_complete: bool
    raw_payload_leak_detected: bool
    pass_fail_reason: str
    passed: bool
    weak_fallback_used: bool = False
    no_visual_evidence_reason: str | None = None
    observation_available: bool = False
    observation_allowed: bool = False
    observation_blocked_reason: str | None = None
    observation_source: str | None = None
    observation_freshness: str | None = None
    observation_confidence: dict[str, Any] = field(default_factory=dict)
    visible_context_summary: dict[str, Any] = field(default_factory=dict)
    assistant_response: str = ""
    micro_response: str = ""
    deck_trace_text: str = ""
    ui_action_attempted: bool = False
    golden_response_snapshot: str = ""
    before_example: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _KrakenSystemProbe:
    def __init__(self, *, focused_window: dict[str, Any] | None, windows: Sequence[dict[str, Any]]) -> None:
        self._focused_window = dict(focused_window or {}) if focused_window else None
        self._windows = [dict(item) for item in windows]

    def window_status(self) -> dict[str, Any]:
        return {
            "focused_window": self._focused_window,
            "windows": list(self._windows),
            "monitors": [
                {
                    "index": 1,
                    "device_name": "\\\\.\\DISPLAY1",
                    "is_primary": True,
                    "bounds_x": 0,
                    "bounds_y": 0,
                    "bounds_width": 1920,
                    "bounds_height": 1080,
                }
            ],
        }


class _KrakenScreenCaptureProvider:
    def __init__(self, result: ScreenCaptureResult, *, available: bool = True) -> None:
        self.result = result
        self.available = available
        self.calls: list[dict[str, Any]] = []

    def capability_status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "platform": "Windows",
            "backend": "fixture",
            "local_ocr_available": True,
            "provider_vision_available": False,
        }

    def capture(self, **kwargs: Any) -> ScreenCaptureResult:
        self.calls.append(dict(kwargs))
        return replace(self.result)


class _KrakenActionExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, request: Any) -> Any:
        self.calls.append({"request": request})
        raise AssertionError("Current-screen usability Kraken must not execute UI actions.")


class CurrentScreenUsabilityKrakenHarness:
    def __init__(self, screen_config: ScreenAwarenessConfig) -> None:
        self.screen_config = screen_config

    def run(self, cases: Iterable[CurrentScreenUsabilityCase]) -> list[CurrentScreenUsabilityRow]:
        return [self.run_case(case) for case in cases]

    def run_case(self, case: CurrentScreenUsabilityCase) -> CurrentScreenUsabilityRow:
        config = _configured_screen_awareness(self.screen_config, case)
        focused_window = case.focused_window()
        windows = case.all_windows()
        capture_fixture = case.capture or CurrentScreenCaptureFixture(
            captured=False,
            text=None,
            text_source=None,
            confidence_score=0.0,
            reason="screen_capture_unavailable",
        )
        capture_provider = _KrakenScreenCaptureProvider(
            capture_fixture.to_capture_result(case.scenario_id),
            available=case.capture_available,
        )
        action_executor = _KrakenActionExecutor()
        subsystem = build_screen_awareness_subsystem(
            config,
            system_probe=_KrakenSystemProbe(focused_window=focused_window, windows=windows),
            screen_capture_provider=capture_provider,
            action_executor=action_executor,
        )
        response = subsystem.handle_request(
            session_id=f"current-screen-usability-kraken-{case.scenario_id}",
            operator_text=case.prompt,
            intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
            surface_mode="ghost",
            active_module="chartroom",
            active_context=_active_context(case),
            workspace_context=dict(case.workspace_context),
        )
        status_snapshot = subsystem.status_snapshot()
        return _score_case(
            case=case,
            response=response,
            status_snapshot=status_snapshot,
            action_executor=action_executor,
        )


def default_current_screen_usability_cases() -> list[CurrentScreenUsabilityCase]:
    return [
        CurrentScreenUsabilityCase(
            scenario_id="clipping_tool_error",
            scenario_family="clipping_tool_error",
            evidence_mode="fresh_ocr",
            prompt="what is on my screen right now?",
            window_title="Screenshot 2026-05-04 090000.png - Clipping Tool",
            process_name="SnippingTool",
            capture=CurrentScreenCaptureFixture(
                text="Connection Error Failed to connect to server ECONNREFUSED 127.0.0.1:8000 Retry Cancel",
                confidence_score=0.92,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="local_ocr",
            expected_observation_attempted=True,
            expected_keywords=("connection", "failed", "troubleshoot"),
            forbidden_phrases=("screenshot 2026-05-04 090000.png",),
            require_task_hypothesis=True,
            golden_response_snapshot="Connection error screenshot summarized before Clipping Tool metadata.",
            before_example="Weak metadata would only say Clipping Tool had a screenshot filename.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="clipping_tool_homework_math",
            scenario_family="clipping_tool_homework_math",
            evidence_mode="fresh_ocr",
            prompt="can you help with this?",
            window_title="Screenshot 2026-05-04 091500.png - Clipping Tool",
            process_name="SnippingTool",
            capture=CurrentScreenCaptureFixture(
                text="Homework Solve for x 2x + 5 = 17 Show your work",
                confidence_score=0.89,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="local_ocr",
            expected_observation_attempted=True,
            expected_keywords=("homework", "2x", "help"),
            golden_response_snapshot="Homework/math screenshot is described as visible content, not a filename.",
            before_example="Weak metadata would name the Clipping Tool screenshot.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="browser_article",
            scenario_family="browser_article",
            evidence_mode="fresh_ocr",
            prompt="what do you see?",
            window_title="New battery materials improve fast charging - Chrome",
            process_name="chrome",
            capture=CurrentScreenCaptureFixture(
                text="Article New battery materials improve fast charging Researchers report a safer silicon anode design By Maya Chen",
                confidence_score=0.9,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="local_ocr",
            expected_observation_attempted=True,
            expected_keywords=("battery materials", "article"),
            golden_response_snapshot="Browser article topic and help option are summarized compactly.",
            before_example="Weak metadata would only say Chrome is involved.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="file_explorer_folder",
            scenario_family="file_explorer",
            evidence_mode="fresh_ocr",
            prompt="what am I looking at?",
            window_title="Downloads - File Explorer",
            process_name="explorer",
            capture=CurrentScreenCaptureFixture(
                text="Downloads File Explorer Name Date modified release_notes.pdf installer.exe screenshots folder stormhelm_report.docx",
                confidence_score=0.87,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="local_ocr",
            expected_observation_attempted=True,
            expected_keywords=("downloads", "file explorer", "release_notes.pdf"),
            golden_response_snapshot="File Explorer folder context includes useful filenames.",
            before_example="Weak metadata would only say Downloads - File Explorer.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="terminal_error_log",
            scenario_family="terminal_error_log",
            evidence_mode="fresh_ocr",
            prompt="can you help with this?",
            window_title="Terminal - pytest",
            process_name="WindowsTerminal",
            capture=CurrentScreenCaptureFixture(
                text="pytest failed NameError name rank_screen_evidence is not defined tests/test_screen_awareness_current_screen.py",
                confidence_score=0.9,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="local_ocr",
            expected_observation_attempted=True,
            expected_keywords=("pytest", "nameerror", "troubleshoot"),
            require_task_hypothesis=True,
            golden_response_snapshot="Terminal error is recognized as troubleshooting context.",
            before_example="Weak metadata would only say Terminal - pytest.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="settings_control_panel",
            scenario_family="settings_control_panel",
            evidence_mode="fresh_ocr",
            prompt="what is on my screen right now?",
            window_title="Windows Update - Settings",
            process_name="SystemSettings",
            capture=CurrentScreenCaptureFixture(
                text="Windows Update Updates available Restart required Check for updates Advanced options",
                confidence_score=0.88,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="local_ocr",
            expected_observation_attempted=True,
            expected_keywords=("windows update", "restart"),
            golden_response_snapshot="Settings page summary leads with update/restart content.",
            before_example="Weak metadata would only say Windows Update - Settings.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="multiple_overlapping_windows",
            scenario_family="multiple_overlapping_windows",
            evidence_mode="multiple_windows",
            prompt="what am I looking at?",
            process_name="WindowsTerminal",
            windows=(
                _window("Terminal - pytest", process_name="WindowsTerminal", focused=True, handle=801),
                _window("Chrome - Release Notes", process_name="chrome", focused=False, handle=802),
                _window("Stormhelm Notes - Code", process_name="Code", focused=False, handle=803),
            ),
            capture=CurrentScreenCaptureFixture(
                text="pytest failed NameError in screen_awareness response summary quality",
                confidence_score=0.89,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="local_ocr",
            expected_observation_attempted=True,
            expected_keywords=("pytest", "chrome", "release notes"),
            golden_response_snapshot="Primary terminal content is ranked before secondary windows.",
            before_example="Weak metadata would collapse the screen to one title.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="blank_low_information_desktop",
            scenario_family="blank_low_information_desktop",
            evidence_mode="screenshot_pixels",
            prompt="what do you see?",
            window_title="Desktop",
            process_name="explorer",
            capture=CurrentScreenCaptureFixture(
                text=None,
                text_source=None,
                confidence_score=0.74,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="screen_capture",
            expected_observation_attempted=True,
            expected_keywords=("screenshot", "incomplete"),
            require_task_hypothesis=False,
            golden_response_snapshot="Fresh pixels without readable content are labeled partial.",
            before_example="Weak metadata would only say Desktop.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="ocr_heavy_screen",
            scenario_family="ocr_heavy_screen",
            evidence_mode="fresh_ocr",
            prompt="what is on my screen right now?",
            window_title="Stormhelm Docs - Chrome",
            process_name="chrome",
            capture=CurrentScreenCaptureFixture(
                text=(
                    "Home Search Settings Profile Menu Help Back Forward Reload "
                    "Stormhelm Screen Awareness Observe On Demand guide explains current-screen summaries and evidence ranking. "
                    "Footer Terms Privacy Copyright 2026 Cookie notice Sidebar Related Articles Subscribe Newsletter"
                ),
                confidence_score=0.9,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="local_ocr",
            expected_observation_attempted=True,
            expected_keywords=("observe on demand", "summarize"),
            forbidden_phrases=(
                "home search settings profile menu help back forward reload",
                "cookie notice sidebar related articles subscribe newsletter",
            ),
            golden_response_snapshot="OCR-heavy screen is condensed to the useful article/topic text.",
            before_example="Weak metadata or raw OCR would be noisy and unhelpful.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="image_heavy_low_ocr",
            scenario_family="image_heavy_low_ocr",
            evidence_mode="screenshot_pixels",
            prompt="what do you see?",
            window_title="Presentation diagram - Photos",
            process_name="Photos",
            capture=CurrentScreenCaptureFixture(
                text=None,
                text_source=None,
                confidence_score=0.74,
            ),
            expected_top_source="screen_capture",
            expected_answered_from_source="screen_capture",
            expected_observation_attempted=True,
            expected_keywords=("screenshot", "incomplete"),
            require_task_hypothesis=False,
            golden_response_snapshot="Image-heavy screen notes fresh pixels but limited readable text.",
            before_example="Weak metadata would only say Photos.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="weak_metadata_only",
            scenario_family="weak_metadata_only",
            evidence_mode="weak_metadata",
            prompt="what is on my screen right now?",
            window_title="Screenshot 2026-05-04 090000.png - Clipping Tool",
            process_name="SnippingTool",
            screen_capture_enabled=False,
            expect_visible_context_summary=False,
            expect_weak_fallback=True,
            expect_no_visual_evidence_reason=True,
            expected_observation_attempted=True,
            expected_keywords=("weak window metadata", "not visual content"),
            forbidden_phrases=("the main thing on screen is",),
            golden_response_snapshot="Weak metadata is rejected as insufficient visual evidence.",
            before_example="Before hardening this could answer with only the Clipping Tool filename.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="capture_unavailable",
            scenario_family="capture_unavailable",
            evidence_mode="weak_metadata",
            prompt="what do you see?",
            window_title="Untitled - Notepad",
            process_name="notepad",
            capture_available=False,
            expect_visible_context_summary=False,
            expect_weak_fallback=True,
            expect_no_visual_evidence_reason=True,
            expected_observation_attempted=True,
            expected_keywords=("weak window metadata", "unavailable"),
            golden_response_snapshot="Capture unavailable falls back truthfully to weak evidence.",
            before_example="A confident screen description would be unsafe without capture.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="clipboard_stale_hints",
            scenario_family="clipboard_stale_hints",
            evidence_mode="stale_and_clipboard_hints",
            prompt="can you help with this?",
            screen_capture_enabled=False,
            active_context={
                "selection": {},
                "clipboard": {"value": "Clipboard says: deploy token failed", "preview": "deploy token failed"},
                "recent_context_resolutions": [
                    {
                        "kind": "screen_awareness",
                        "summary": "Earlier screen showed a login form.",
                        "freshness": "stale",
                    }
                ],
            },
            expect_visible_context_summary=False,
            expect_weak_fallback=True,
            expect_no_visual_evidence_reason=True,
            expected_observation_attempted=True,
            expected_keywords=("clipboard", "can't confirm"),
            golden_response_snapshot="Clipboard and stale context stay labeled as hints, not live screen truth.",
            before_example="A bad answer would treat clipboard text as the visible screen.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="selected_visible_text",
            scenario_family="browser_article",
            evidence_mode="selected_visible_text",
            prompt="what am I looking at?",
            window_title="Stormhelm API docs - Chrome",
            process_name="chrome",
            active_context={
                "selection": {"value": "Selected docs text: ScreenObservation ranks fresh OCR above window metadata."},
                "clipboard": {},
            },
            expected_top_source="selected_text",
            expected_answered_from_source="selected_text",
            expected_observation_attempted=False,
            expected_keywords=("selected text", "screenobservation"),
            golden_response_snapshot="Selected visible text is treated as direct current content.",
            before_example="Weak metadata would only say Chrome.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="ui_automation_context",
            scenario_family="settings_control_panel",
            evidence_mode="ui_automation",
            prompt="what is on my screen right now?",
            window_title="Windows Update - Settings",
            process_name="SystemSettings",
            active_context={
                "selection": {},
                "clipboard": {},
                "accessibility": {
                    "focused_label": "Restart now",
                    "control_type": "Button",
                    "window_title": "Windows Update - Settings",
                    "visible_text": "Restart required",
                },
            },
            expected_top_source="accessibility_ui_tree",
            expected_answered_from_source="accessibility_ui_tree",
            expected_observation_attempted=False,
            expected_keywords=("settings", "windows update"),
            golden_response_snapshot="UI Automation context can ground a compact current-screen bearing.",
            before_example="Weak metadata would only say Settings.",
        ),
        CurrentScreenUsabilityCase(
            scenario_id="browser_semantic_context",
            scenario_family="browser_article",
            evidence_mode="app_semantic_context",
            prompt="what do you see?",
            window_title="Stormhelm Screen Awareness Guide - Chrome",
            process_name="chrome",
            capture_available=False,
            active_context={
                "selection": {},
                "clipboard": {},
                "adapter_semantics": {
                    "browser": {
                        "page": {
                            "title": "Stormhelm Screen Awareness Guide",
                            "url": "https://docs.local/stormhelm/screen-awareness",
                        },
                        "loading_state": "complete",
                        "metadata": {
                            "source_provider": "fixture_browser_adapter",
                            "claim_ceiling": "browser_semantic_context",
                        },
                    }
                },
            },
            workspace_context={
                "active_item": {
                    "title": "Stormhelm Screen Awareness Guide",
                    "url": "https://docs.local/stormhelm/screen-awareness",
                }
            },
            expected_top_source="app_semantic_adapter",
            expected_answered_from_source="app_semantic_adapter",
            expected_observation_attempted=True,
            expected_keywords=("browser semantics", "screen awareness guide"),
            golden_response_snapshot="Browser semantic adapter context is labeled below pixels/OCR but still useful.",
            before_example="Weak metadata would only say Chrome.",
        ),
    ]


def summarize_current_screen_usability_rows(rows: Sequence[CurrentScreenUsabilityRow]) -> dict[str, Any]:
    passed = [row for row in rows if row.passed]
    failed = [row for row in rows if not row.passed]
    return {
        "total": len(rows),
        "passed": len(passed),
        "failed": len(failed),
        "families_covered": len({row.scenario_family for row in rows}),
        "evidence_modes_covered": len({row.evidence_mode for row in rows}),
        "raw_payload_leaks": sum(1 for row in rows if row.raw_payload_leak_detected),
        "ui_action_attempts": sum(1 for row in rows if row.ui_action_attempted),
        "failures": [
            {
                "scenario_id": row.scenario_id,
                "reason": row.pass_fail_reason,
            }
            for row in failed
        ],
        "representative_outputs": {
            row.scenario_id: {
                "before": row.before_example,
                "after": row.assistant_response,
                "golden": row.golden_response_snapshot,
            }
            for row in rows
        },
    }


def _configured_screen_awareness(
    base_config: ScreenAwarenessConfig,
    case: CurrentScreenUsabilityCase,
) -> ScreenAwarenessConfig:
    config = deepcopy(base_config)
    config.enabled = True
    config.phase = "phase12"
    config.planner_routing_enabled = True
    config.observation_enabled = True
    config.interpretation_enabled = True
    config.grounding_enabled = True
    config.guidance_enabled = True
    config.verification_enabled = True
    config.action_enabled = True
    config.memory_enabled = True
    config.adapters_enabled = True
    config.problem_solving_enabled = True
    config.workflow_learning_enabled = True
    config.brain_integration_enabled = True
    config.power_features_enabled = True
    config.action_policy_mode = "confirm_before_act"
    config.screen_capture_enabled = case.screen_capture_enabled
    config.screen_capture_scope = "active_window"
    config.screen_capture_ocr_enabled = True
    config.screen_capture_provider_vision_enabled = False
    config.screen_capture_store_raw_images = False
    return config


def _window(
    title: str,
    *,
    process_name: str,
    focused: bool | None,
    handle: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "process_name": process_name,
        "window_title": title,
        "window_handle": handle,
        "pid": 4000 + handle,
        "monitor_index": 1,
        "path": f"C:\\Program Files\\{process_name}\\{process_name}.exe",
        "minimized": False,
    }
    if focused is not None:
        payload["is_focused"] = focused
    return payload


def _active_context(case: CurrentScreenUsabilityCase) -> dict[str, Any]:
    context = {
        "selection": {},
        "clipboard": {},
    }
    context.update(deepcopy(dict(case.active_context)))
    return context


def _score_case(
    *,
    case: CurrentScreenUsabilityCase,
    response: ScreenResponse,
    status_snapshot: Mapping[str, Any],
    action_executor: _KrakenActionExecutor,
) -> CurrentScreenUsabilityRow:
    observation = dict(response.telemetry.get("observation") or {})
    trace = dict(response.telemetry.get("trace") or {})
    evidence_before = _dict_list(observation.get("evidence_before_observation"))
    evidence_after = _dict_list(observation.get("evidence_after_observation") or observation.get("evidence_ranking"))
    answered_from_source = str(observation.get("answered_from_source") or "")
    visible_context = dict(observation.get("visible_context_summary") or {})
    assistant_response = str(response.assistant_response or "")
    micro_response = str(response.response_contract.get("micro_response") or "")
    deck_trace_text = _deck_trace_text(trace)
    raw_payload_leak = _raw_payload_leak_detected(response=response, status_snapshot=status_snapshot, deck_trace_text=deck_trace_text)
    ui_action_attempted = bool(action_executor.calls or response.telemetry.get("action", {}).get("requested"))
    ghost_compact = _ghost_compact(response)
    deck_trace_complete = _deck_trace_complete(trace=trace, deck_trace_text=deck_trace_text, visible_context=visible_context, case=case)
    visible_context_present = bool(str(visible_context.get("summary") or "").strip())
    key_text_quality = _key_text_quality(case=case, response=response, visible_context=visible_context)
    task_hypothesis_quality = _task_hypothesis_quality(case=case, response=response, visible_context=visible_context)
    weak_fallback_used = bool(observation.get("weak_fallback_used"))
    no_visual_evidence_reason = str(observation.get("no_visual_evidence_reason") or "") or None

    failures: list[str] = []
    if case.expected_observation_attempted is not None and bool(observation.get("observation_attempted")) != case.expected_observation_attempted:
        failures.append(
            f"observation_attempted expected {case.expected_observation_attempted} got {bool(observation.get('observation_attempted'))}"
        )
    if case.expected_top_source:
        top_source = str(evidence_after[0].get("source") or "") if evidence_after else ""
        if top_source != case.expected_top_source:
            failures.append(f"top evidence source expected {case.expected_top_source} got {top_source or 'none'}")
    if case.expected_answered_from_source and answered_from_source != case.expected_answered_from_source:
        failures.append(
            f"answered_from_source expected {case.expected_answered_from_source} got {answered_from_source or 'none'}"
        )
    if case.expect_visible_context_summary != visible_context_present:
        failures.append(
            f"visible_context_summary_present expected {case.expect_visible_context_summary} got {visible_context_present}"
        )
    if case.expect_weak_fallback != weak_fallback_used:
        failures.append(f"weak_fallback_used expected {case.expect_weak_fallback} got {weak_fallback_used}")
    if case.expect_no_visual_evidence_reason and not no_visual_evidence_reason:
        failures.append("expected no_visual_evidence_reason")
    if not _contains_all(assistant_response, case.expected_keywords):
        failures.append(f"assistant response missing expected keyword(s): {case.expected_keywords}")
    forbidden = _present_forbidden(assistant_response, case.forbidden_phrases)
    if forbidden:
        failures.append(f"assistant response included forbidden phrase(s): {forbidden}")
    if key_text_quality == "fail":
        failures.append("key text quality failed")
    if task_hypothesis_quality == "fail":
        failures.append("task hypothesis quality failed")
    if not ghost_compact:
        failures.append("Ghost response was not compact")
    if not deck_trace_complete:
        failures.append("Deck trace was incomplete")
    if raw_payload_leak:
        failures.append("raw screenshot/pixel payload leaked")
    if ui_action_attempted:
        failures.append("UI action execution was attempted")

    return CurrentScreenUsabilityRow(
        prompt=case.prompt,
        scenario_id=case.scenario_id,
        scenario_family=case.scenario_family,
        evidence_mode=case.evidence_mode,
        expected_route_family=case.expected_route_family,
        evidence_before_observation=evidence_before,
        observation_attempted=bool(observation.get("observation_attempted")),
        evidence_after_observation=evidence_after,
        answered_from_source=answered_from_source,
        visible_context_summary_present=visible_context_present,
        key_text_quality=key_text_quality,
        task_hypothesis_quality=task_hypothesis_quality,
        ghost_compact=ghost_compact,
        deck_trace_complete=deck_trace_complete,
        raw_payload_leak_detected=raw_payload_leak,
        pass_fail_reason="pass" if not failures else "; ".join(failures),
        passed=not failures,
        weak_fallback_used=weak_fallback_used,
        no_visual_evidence_reason=no_visual_evidence_reason,
        observation_available=bool(observation.get("observation_available")),
        observation_allowed=bool(observation.get("observation_allowed")),
        observation_blocked_reason=str(observation.get("observation_blocked_reason") or "") or None,
        observation_source=str(observation.get("observation_source") or "") or None,
        observation_freshness=str(observation.get("observation_freshness") or "") or None,
        observation_confidence=dict(observation.get("observation_confidence") or {}),
        visible_context_summary=visible_context,
        assistant_response=assistant_response,
        micro_response=micro_response,
        deck_trace_text=deck_trace_text,
        ui_action_attempted=ui_action_attempted,
        golden_response_snapshot=case.golden_response_snapshot,
        before_example=case.before_example,
    )


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _contains_all(text: str, keywords: Sequence[str]) -> bool:
    lowered = text.lower()
    return all(str(keyword).lower() in lowered for keyword in keywords)


def _present_forbidden(text: str, phrases: Sequence[str]) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in phrases if str(phrase).lower() in lowered]


def _ghost_compact(response: ScreenResponse) -> bool:
    text = str(response.assistant_response or "")
    micro = str(response.response_contract.get("micro_response") or "")
    lowered = text.lower()
    return (
        len(micro) <= 220
        and len(text) <= 520
        and "evidence_ranking" not in lowered
        and "evidence_after_observation" not in lowered
        and RAW_PAYLOAD_SENTINEL.lower() not in lowered
    )


def _deck_trace_text(trace: Mapping[str, Any]) -> str:
    trace_payload = dict(trace)
    trace_payload.setdefault("durationMs", 0.0)
    stations = _stations(
        "screen_awareness",
        "Visual Context - Kraken",
        "Holding screen-awareness Kraken trace.",
        "Prepared",
        "prepared",
        "current screen",
        {},
        {},
        {},
        {"present": False, "tone": "steady", "summary": "", "posture": "", "freshness": ""},
        {"present": False, "count": "Support memory", "contributors": []},
        {
            "present": True,
            "headline": "Live",
            "tone": "steady",
            "watch": {"present": False},
            "lifecycle": {"present": False},
            "screenAwareness": {
                "phase": "phase12",
                "policy": {"action_policy_mode": "confirm_before_act"},
                "trace": trace_payload,
            },
        },
        [],
        [],
    )
    pieces: list[str] = []
    for station in stations:
        for section in station.get("sections", []):
            for entry in section.get("entries", []):
                pieces.extend(str(entry.get(key) or "") for key in ("primary", "secondary", "detail"))
    return " ".join(part for part in pieces if part).strip()


def _deck_trace_complete(
    *,
    trace: Mapping[str, Any],
    deck_trace_text: str,
    visible_context: Mapping[str, Any],
    case: CurrentScreenUsabilityCase,
) -> bool:
    ranking = _dict_list(trace.get("evidence_ranking"))
    has_rank_detail = bool(
        ranking
        and all("source" in item and "freshness" in item and "confidence" in item for item in ranking[:1])
    )
    has_observation_status = "observation_attempted" in trace and "answered_from_source" in trace
    lowered = deck_trace_text.lower()
    has_deck_entries = "observation" in lowered and "evidence" in lowered
    if case.expect_visible_context_summary:
        has_deck_entries = has_deck_entries and "visible context" in lowered and bool(visible_context.get("summary"))
    return has_rank_detail and has_observation_status and has_deck_entries


def _key_text_quality(
    *,
    case: CurrentScreenUsabilityCase,
    response: ScreenResponse,
    visible_context: Mapping[str, Any],
) -> str:
    if not case.expect_visible_context_summary:
        return "not_applicable"
    key_text = [str(item) for item in visible_context.get("key_text") or [] if str(item).strip()]
    if len(key_text) > 3:
        return "fail"
    assistant = str(response.assistant_response or "")
    if _present_forbidden(assistant, case.forbidden_phrases):
        return "fail"
    if case.expected_keywords and not _contains_all(assistant, case.expected_keywords):
        return "fail"
    return "pass"


def _task_hypothesis_quality(
    *,
    case: CurrentScreenUsabilityCase,
    response: ScreenResponse,
    visible_context: Mapping[str, Any],
) -> str:
    lowered = str(response.assistant_response or "").lower()
    if "you are " in lowered and "it looks like you may be" not in lowered:
        return "fail"
    likely_task = visible_context.get("likely_task") if isinstance(visible_context.get("likely_task"), dict) else {}
    if case.require_task_hypothesis:
        if not likely_task:
            return "fail"
        if "it looks like you may be" not in lowered and not likely_task.get("label"):
            return "fail"
    return "pass"


def _raw_payload_leak_detected(
    *,
    response: ScreenResponse,
    status_snapshot: Mapping[str, Any],
    deck_trace_text: str,
) -> bool:
    payload = {
        "response_contract": response.response_contract,
        "telemetry": response.telemetry,
        "status_snapshot": status_snapshot,
        "deck_trace_text": deck_trace_text,
    }
    serialized = json.dumps(payload, default=str).lower()
    return any(marker.lower() in serialized for marker in RAW_PAYLOAD_MARKERS)


__all__ = [
    "CurrentScreenCaptureFixture",
    "CurrentScreenUsabilityCase",
    "CurrentScreenUsabilityKrakenHarness",
    "CurrentScreenUsabilityRow",
    "default_current_screen_usability_cases",
    "summarize_current_screen_usability_rows",
]
