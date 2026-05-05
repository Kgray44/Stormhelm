from __future__ import annotations

from dataclasses import replace
import json

from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenLimitationCode
from stormhelm.core.screen_awareness import ScreenAwarenessPlannerSeam
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.core.screen_awareness.visual_capture import ScreenCaptureResult
from stormhelm.ui.command_surface_v2 import _stations


class CurrentScreenProbe:
    def __init__(
        self,
        *,
        focused_window: dict[str, object] | None = None,
        windows: list[dict[str, object]] | None = None,
    ) -> None:
        self._focused_window = focused_window
        self._windows = list(windows or ([focused_window] if focused_window else []))

    def window_status(self) -> dict[str, object]:
        return {
            "focused_window": self._focused_window,
            "windows": list(self._windows),
            "monitors": [
                {
                    "index": 1,
                    "device_name": "\\\\.\\DISPLAY1",
                    "is_primary": True,
                    "bounds_width": 1920,
                    "bounds_height": 1080,
                }
            ],
        }


class CurrentScreenCaptureProvider:
    def __init__(self, result: ScreenCaptureResult, *, available: bool = True) -> None:
        self.result = result
        self.available = available
        self.calls: list[dict[str, object]] = []

    def capability_status(self) -> dict[str, object]:
        return {
            "available": self.available,
            "platform": "Windows",
            "backend": "fake",
            "local_ocr_available": True,
            "provider_vision_available": False,
        }

    def capture(self, **kwargs: object) -> ScreenCaptureResult:
        self.calls.append(dict(kwargs))
        return replace(self.result)


class CurrentScreenActionExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute(self, request):
        self.calls.append({"request": request})
        raise AssertionError("Current-screen observe-on-demand must not execute UI actions.")


def _phase12_current_screen_config(temp_config):
    config = temp_config.screen_awareness
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
    config.screen_capture_scope = "active_window"
    config.screen_capture_ocr_enabled = True
    config.screen_capture_provider_vision_enabled = False
    config.screen_capture_store_raw_images = False
    return config


def _window(
    title: str,
    *,
    process_name: str = "ApplicationFrameHost",
    focused: bool | None = True,
    handle: int = 700,
    minimized: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "process_name": process_name,
        "window_title": title,
        "window_handle": handle,
        "pid": 4000 + handle,
        "monitor_index": 1,
        "path": f"C:\\Program Files\\{process_name}\\{process_name}.exe",
        "minimized": minimized,
    }
    if focused is not None:
        payload["is_focused"] = focused
    return payload


def _ask_current_screen(
    subsystem,
    *,
    active_context: dict[str, object] | None = None,
    surface_mode: str = "ghost",
):
    return subsystem.handle_request(
        session_id="current-screen-hardening",
        operator_text="what is on my screen right now?",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode=surface_mode,
        active_module="chartroom",
        workspace_context={},
        active_context=active_context or {"selection": {}, "clipboard": {}},
    )


def test_current_screen_planner_classifies_what_do_you_see_as_observation_request(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    evaluation = ScreenAwarenessPlannerSeam(config).evaluate(
        raw_text="what do you see?",
        normalized_text="what do you see?",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
    )

    assert evaluation.candidate is True
    assert evaluation.feature_enabled is True
    assert evaluation.intent == ScreenIntentType.INSPECT_VISIBLE_STATE
    assert evaluation.route_confidence >= 0.9


def test_broad_screen_prompt_with_weak_metadata_attempts_fresh_observation_when_capture_available(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-01T14:00:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:observe-on-demand",
            text="Release checklist window with Deploy button",
            text_source="local_ocr",
            confidence_score=0.88,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("Checklist.png - Clipping Tool", process_name="SnippingTool")),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    observation_state = response.telemetry["observation"]

    assert len(capture.calls) == 1
    assert response.analysis.observation_attempted is True
    assert response.analysis.observation_available is True
    assert response.analysis.observation_allowed is True
    assert response.analysis.observation_source == "screen_capture"
    assert response.analysis.observation_freshness == "current"
    assert response.analysis.evidence_before_observation[0]["source"] in {"foreground_window_stack", "active_window_title"}
    assert response.analysis.evidence_after_observation[0]["source"] == "screen_capture"
    assert response.analysis.answered_from_source == "local_ocr"
    assert response.analysis.weak_fallback_used is False
    assert observation_state["observation_attempted"] is True
    assert observation_state["evidence_before_observation"][0]["source"] in {"foreground_window_stack", "active_window_title"}
    assert observation_state["evidence_after_observation"][0]["source"] == "screen_capture"
    assert "release checklist" in response.assistant_response.lower()


def test_broad_screen_prompt_with_existing_strong_live_text_does_not_capture_again(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-01T14:01:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:should-not-run",
            text="Unexpected capture text",
            text_source="local_ocr",
            confidence_score=0.88,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("Stormhelm Notes - Code")),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(
        subsystem,
        active_context={
            "selection": {
                "kind": "text",
                "value": "Selected live error text from the current screen",
                "preview": "Selected live error text from the current screen",
            },
            "clipboard": {},
        },
    )

    assert capture.calls == []
    assert response.analysis.observation_attempted is False
    assert response.analysis.observation_available is True
    assert response.analysis.evidence_before_observation[0]["source"] == "selected_text"
    assert response.analysis.evidence_after_observation[0]["source"] == "selected_text"
    assert response.analysis.answered_from_source == "selected_text"
    assert "selected live error text" in response.assistant_response.lower()
    assert "unexpected capture text" not in response.assistant_response.lower()


def test_broad_screen_prompt_with_capture_unavailable_records_observation_block_and_weak_fallback(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=False,
            captured_at="2026-05-01T14:02:00+00:00",
            scope="active_window",
            reason="screen_capture_unavailable",
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        ),
        available=False,
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("Clipping Tool", process_name="SnippingTool")),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()
    observation_state = response.telemetry["observation"]

    assert response.analysis.observation_attempted is True
    assert response.analysis.observation_available is False
    assert response.analysis.observation_allowed is True
    assert response.analysis.observation_blocked_reason == "screen_capture_unavailable"
    assert response.analysis.weak_fallback_used is True
    assert response.analysis.no_visual_evidence_reason == "screen_capture_unavailable"
    assert "visual capture was requested but unavailable" in lowered
    assert "do not have enough visual detail" in lowered
    assert observation_state["weak_fallback_used"] is True
    assert observation_state["no_visual_evidence_reason"] == "screen_capture_unavailable"


def test_current_screen_with_only_active_window_title_reports_insufficient_visual_evidence(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(
            focused_window=_window("Screenshot 2026-05-01 091500.png - Clipping Tool", focused=None)
        ),
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()

    assert ScreenLimitationCode.LOW_CONFIDENCE in {limitation.code for limitation in response.analysis.limitations}
    assert "only have weak window metadata" in lowered
    assert "do not have enough visual detail" in lowered
    assert "screenshot 2026-05-01 091500.png" in lowered
    assert "active window is" not in lowered
    assert "focused window" not in lowered
    assert response.response_contract["evidence_kind"] == "window_metadata"


def test_clipping_tool_filename_only_metadata_is_not_treated_as_screen_content(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(
            focused_window=_window("Invoice_Error.png - Clipping Tool", process_name="SnippingTool")
        ),
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()

    assert "invoice_error.png" in lowered
    assert "do not have enough visual detail" in lowered
    assert "invoice error" not in lowered.replace("invoice_error.png", "")
    assert response.telemetry["observation"]["evidence_kind"] == "window_metadata"


def test_fresh_screenshot_evidence_outranks_conflicting_active_window_title(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-01T13:00:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:current-screen-1",
            text="Readable setup wizard: Choose install location",
            text_source="local_ocr",
            confidence_score=0.9,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(
            focused_window=_window("Screenshot 2026-05-01 091500.png - Clipping Tool", process_name="SnippingTool")
        ),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()

    assert lowered.index("readable setup wizard") < lowered.index("clipping tool")
    assert "screenshot 2026-05-01 091500.png" not in lowered
    assert response.telemetry["observation"]["evidence_ranking"][0]["source"] == "screen_capture"
    assert response.telemetry["observation"]["evidence_ranking"][1]["source"] == "local_ocr"
    assert response.response_contract["evidence_kind"] == "visual_content"


def test_stale_prior_observation_is_not_described_as_current_screen(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=None, windows=[]),
    )

    response = _ask_current_screen(
        subsystem,
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [
                {
                    "kind": "screen_awareness",
                    "summary": "Old Dashboard with build failures was visible earlier.",
                    "freshness": "stale",
                }
            ],
        },
    )

    assert "old dashboard" not in response.assistant_response.lower()
    ranking = response.telemetry["observation"]["evidence_ranking"]
    assert any(item["source"] == "stale_recent_context" and item["freshness"] == "stale" for item in ranking)
    assert all(not item["used_for_summary"] for item in ranking if item["source"] == "stale_recent_context")


def test_clipboard_text_is_ranked_as_hint_not_visible_screen_truth(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=None, windows=[]),
    )

    response = _ask_current_screen(
        subsystem,
        active_context={"selection": {}, "clipboard": {"kind": "text", "value": "Copied API token"}},
    )

    lowered = response.assistant_response.lower()
    assert "clipboard contains copied api token" in lowered
    assert "can't confirm" in lowered
    assert "looking at copied api token" not in lowered
    ranking = response.telemetry["observation"]["evidence_ranking"]
    assert ranking[-1]["source"] == "clipboard_hint"
    assert ranking[-1]["used_for_summary"] is False


def test_multiple_visible_windows_produce_ranked_metadata_summary_not_single_title(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = False
    windows = [
        _window("Stormhelm Notes - Code", process_name="Code", focused=True, handle=701),
        _window("Chrome - Release Checklist", process_name="chrome", focused=False, handle=702),
        _window("Clipping Tool", process_name="SnippingTool", focused=False, handle=703),
    ]
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=windows[0], windows=windows),
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()

    assert "window stack metadata" in lowered
    assert "stormhelm notes" in lowered
    assert "release checklist" in lowered
    assert "clipping tool" in lowered
    assert response.telemetry["observation"]["evidence_ranking"][0]["source"] == "foreground_window_stack"


def test_screenshot_inside_clipping_tool_summarizes_captured_image_content(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-01T13:03:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:clipping-tool-content",
            text="Checkout form shows Card number field and Pay button",
            text_source="local_ocr",
            confidence_score=0.87,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(
            focused_window=_window("Screenshot 2026-05-01 091500.png - Clipping Tool", process_name="SnippingTool")
        ),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()

    assert "clipping tool" in lowered
    assert "screenshot" in lowered
    assert "checkout form" in lowered
    assert "pay button" in lowered
    assert "screenshot 2026-05-01 091500.png" not in lowered


def test_ghost_mode_current_screen_response_stays_compact_and_hides_raw_trace(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-01T13:04:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:ghost-compact",
            text="Settings page with Enable voice checkbox",
            text_source="local_ocr",
            confidence_score=0.86,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("Settings - Stormhelm")),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem, surface_mode="ghost")

    assert len(response.response_contract["micro_response"]) <= 180
    assert "evidence_ranking" not in response.assistant_response
    assert "trace_id" not in response.assistant_response


def test_command_deck_screen_trace_shows_evidence_sources_ranking_freshness_and_confidence() -> None:
    stations = _stations(
        "screen_awareness",
        "Visual Context - Prepared",
        "Holding screen-awareness state.",
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
                "trace": {
                    "durationMs": 12.4,
                    "summary": "Current-screen inspection used ranked evidence.",
                    "evidence_ranking": [
                        {
                            "rank": 1,
                            "source": "screen_capture",
                            "freshness": "current",
                            "confidence": {"level": "high", "score": 0.92},
                        },
                        {
                            "rank": 2,
                            "source": "active_window_title",
                            "freshness": "current",
                            "confidence": {"level": "low", "score": 0.2},
                        },
                    ],
                },
            },
        },
        [],
        [],
    )

    entries = {
        entry["primary"]: entry
        for section in stations[0]["sections"]
        for entry in section["entries"]
    }

    assert entries["Evidence"]["secondary"] == "1. screen_capture"
    assert "current" in entries["Evidence"]["detail"].lower()
    assert "high" in entries["Evidence"]["detail"].lower()
    assert "2. active_window_title" in entries["Evidence"]["detail"]


def test_command_deck_screen_trace_shows_observation_attempt_status() -> None:
    stations = _stations(
        "screen_awareness",
        "Visual Context - Prepared",
        "Holding screen-awareness state.",
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
                "trace": {
                    "durationMs": 12.4,
                    "summary": "Current-screen inspection used observe-on-demand.",
                    "observation_attempted": True,
                    "observation_available": True,
                    "observation_allowed": True,
                    "observation_source": "screen_capture",
                    "observation_freshness": "current",
                    "answered_from_source": "local_ocr",
                    "weak_fallback_used": False,
                    "evidence_ranking": [
                        {
                            "rank": 1,
                            "source": "screen_capture",
                            "freshness": "current",
                            "confidence": {"level": "high", "score": 0.92},
                        },
                    ],
                },
            },
        },
        [],
        [],
    )

    entries = {
        entry["primary"]: entry
        for section in stations[0]["sections"]
        for entry in section["entries"]
    }

    assert entries["Observation"]["secondary"] == "Attempted"
    assert "screen_capture" in entries["Observation"]["detail"]
    assert "answered from local_ocr" in entries["Observation"]["detail"]


def test_no_raw_screenshot_or_pixel_payload_leaks_into_response_trace_or_status_json(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-01T14:03:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:no-raw-leak",
            text="Visible OCR text without raw image data",
            text_source="local_ocr",
            confidence_score=0.88,
            metadata={
                "backend": "fake",
                "raw_screenshot_logged": False,
                "image_retained": False,
                "pixel_bytes": "RAW_PIXEL_SENTINEL",
                "raw_screenshot_base64": "RAW_BASE64_SENTINEL",
            },
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("Visible Content - Test")),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    serialized = json.dumps(
        {
            "response": response.to_dict(),
            "status": subsystem.status_snapshot(),
        },
        sort_keys=True,
        default=str,
    )

    assert "RAW_PIXEL_SENTINEL" not in serialized
    assert "RAW_BASE64_SENTINEL" not in serialized
    assert "pixel_bytes" not in serialized
    assert "raw_screenshot_base64" not in serialized
    assert response.telemetry["observation"]["screen_capture"]["raw_screenshot_logged"] is False
    assert response.telemetry["observation"]["screen_capture"]["image_retained"] is False


def test_observe_on_demand_does_not_introduce_direct_ui_actions(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-01T14:04:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:no-action",
            text="Dialog with Continue button",
            text_source="local_ocr",
            confidence_score=0.87,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    executor = CurrentScreenActionExecutor()
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("Installer Dialog")),
        screen_capture_provider=capture,
        action_executor=executor,
    )

    response = _ask_current_screen(subsystem)

    assert capture.calls
    assert executor.calls == []
    assert response.analysis.action_result is None
    assert response.telemetry["action"]["requested"] is False


def test_ocr_heavy_screen_produces_concise_summary_not_raw_ocr_dump(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    noisy_ocr = (
        "Home Search Settings Profile Menu Help Back Forward Reload "
        "Stormhelm Screen Awareness Observe On Demand guide explains current-screen summaries and evidence ranking. "
        "Footer Terms Privacy Copyright 2026 Cookie notice Sidebar Related Articles Subscribe Newsletter"
    )
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-04T13:00:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:ocr-heavy",
            text=noisy_ocr,
            text_source="local_ocr",
            confidence_score=0.9,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("Stormhelm Docs - Chrome", process_name="chrome")),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()
    summary = response.telemetry["observation"]["visible_context_summary"]

    assert "observe on demand" in lowered
    assert "home search settings profile menu help back forward reload" not in lowered
    assert "cookie notice sidebar related articles subscribe newsletter" not in lowered
    assert len(response.response_contract["micro_response"]) <= 180
    assert len(response.assistant_response) <= 420
    assert len(summary["key_text"]) <= 3


def test_error_dialog_screen_identifies_main_error_and_offers_troubleshooting(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-04T13:01:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:error-dialog",
            text="Connection Error Failed to connect to server ECONNREFUSED 127.0.0.1:8000 Retry Cancel",
            text_source="local_ocr",
            confidence_score=0.91,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("Connection Error", process_name="ApplicationFrameHost")),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()
    visible_context = response.telemetry["observation"]["visible_context_summary"]

    assert "failed to connect" in lowered or "connection error" in lowered
    assert "troubleshoot" in lowered
    assert "it looks like you may be" in lowered
    assert "you are debugging" not in lowered
    assert visible_context["likely_task"]["label"] == "troubleshooting a visible error"


def test_browser_article_screen_identifies_topic_and_next_step(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-04T13:02:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:browser-article",
            text="Article New battery materials improve fast charging Researchers report a safer silicon anode design By Maya Chen",
            text_source="local_ocr",
            confidence_score=0.88,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("New battery materials improve fast charging - Chrome", process_name="chrome")),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()
    visible_context = response.telemetry["observation"]["visible_context_summary"]

    assert "battery materials" in lowered
    assert "article" in lowered or visible_context["primary_content"]["kind"] == "browser_page"
    assert any("summarize" in option.lower() or "extract" in option.lower() for option in visible_context["help_options"])


def test_file_explorer_screen_summarizes_folder_and_file_context(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-04T13:03:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:file-explorer",
            text="Downloads File Explorer Name Date modified release_notes.pdf installer.exe screenshots folder stormhelm_report.docx",
            text_source="local_ocr",
            confidence_score=0.87,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=_window("Downloads - File Explorer", process_name="explorer")),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()
    visible_context = response.telemetry["observation"]["visible_context_summary"]

    assert "downloads" in lowered
    assert "file explorer" in lowered
    assert "release_notes.pdf" in lowered or "installer.exe" in lowered
    assert visible_context["primary_content"]["kind"] == "file_explorer"


def test_multiple_windows_summary_ranks_primary_focus_and_mentions_secondary_context(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    windows = [
        _window("Terminal - pytest", process_name="WindowsTerminal", focused=True, handle=801),
        _window("Chrome - Release Notes", process_name="chrome", focused=False, handle=802),
        _window("Stormhelm Notes - Code", process_name="Code", focused=False, handle=803),
    ]
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-04T13:04:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:multiple-windows",
            text="pytest failed NameError in screen_awareness response summary quality",
            text_source="local_ocr",
            confidence_score=0.89,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(focused_window=windows[0], windows=windows),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()
    visible_context = response.telemetry["observation"]["visible_context_summary"]

    assert lowered.index("pytest") < lowered.index("chrome")
    assert "release notes" in lowered or "stormhelm notes" in lowered
    assert visible_context["windows"]["primary"] == "Terminal - pytest"
    assert "Chrome - Release Notes" in visible_context["windows"]["secondary"]


def test_clipping_tool_summary_mentions_image_content_before_title_metadata(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = True
    capture = CurrentScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-05-04T13:05:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:clipping-quality",
            text="Bug report dialog shows TypeError missing required argument and Copy details button",
            text_source="local_ocr",
            confidence_score=0.9,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(
            focused_window=_window("Screenshot 2026-05-04 090000.png - Clipping Tool", process_name="SnippingTool")
        ),
        screen_capture_provider=capture,
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()

    assert lowered.index("bug report") < lowered.index("clipping tool")
    assert "screenshot 2026-05-04 090000.png" not in lowered
    assert response.telemetry["observation"]["visible_context_summary"]["primary_content"]["kind"] == "screenshot_content"


def test_command_deck_trace_includes_visible_context_details() -> None:
    stations = _stations(
        "screen_awareness",
        "Visual Context - Prepared",
        "Holding screen-awareness state.",
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
                "trace": {
                    "durationMs": 12.4,
                    "summary": "Current-screen inspection used summary quality.",
                    "observation_attempted": True,
                    "observation_source": "screen_capture",
                    "answered_from_source": "local_ocr",
                    "visible_context_summary": {
                        "summary": "A browser article about fast-charging battery materials is visible.",
                        "key_text": ["New battery materials improve fast charging"],
                        "entities": ["Chrome", "battery materials"],
                        "likely_task": {"label": "reading an article", "confidence": "medium"},
                        "help_options": ["I can summarize the article."],
                    },
                    "evidence_ranking": [
                        {
                            "rank": 1,
                            "source": "screen_capture",
                            "freshness": "current",
                            "confidence": {"level": "high", "score": 0.92},
                        },
                    ],
                },
            },
        },
        [],
        [],
    )

    entries = {
        entry["primary"]: entry
        for section in stations[0]["sections"]
        for entry in section["entries"]
    }

    assert entries["Visible Context"]["secondary"] == "A browser article about fast-charging battery materials is visible."
    assert "New battery materials improve fast charging" in entries["Key Text"]["detail"]
    assert "reading an article" in entries["Task Hypothesis"]["secondary"]


def test_no_active_window_claim_without_focus_evidence(temp_config) -> None:
    config = _phase12_current_screen_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=CurrentScreenProbe(
            focused_window=_window("Possibly Active - Untitled", process_name="notepad", focused=None)
        ),
    )

    response = _ask_current_screen(subsystem)
    lowered = response.assistant_response.lower()
    ranking = response.telemetry["observation"]["evidence_ranking"]

    assert "active window" not in lowered
    assert "focused window" not in lowered
    assert any(item["source"] == "active_window_title" and item["confidence"]["level"] == "low" for item in ranking)
