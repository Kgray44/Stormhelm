from __future__ import annotations

from dataclasses import replace

from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenLimitationCode
from stormhelm.core.screen_awareness import ScreenSensitivityLevel
from stormhelm.core.screen_awareness import ScreenSourceType
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.core.screen_awareness.visual_capture import ScreenCaptureResult


class L64Probe:
    def __init__(self, *, focused_window: dict[str, object] | None = None, windows: list[dict[str, object]] | None = None) -> None:
        self._focused_window = focused_window
        self._windows = list(windows or ([focused_window] if focused_window else []))

    def window_status(self) -> dict[str, object]:
        return {
            "focused_window": self._focused_window,
            "windows": list(self._windows),
            "monitors": [{"index": 1, "device_name": "\\\\.\\DISPLAY1", "is_primary": True, "bounds_width": 1920, "bounds_height": 1080}],
        }


class FakeScreenCaptureProvider:
    def __init__(self, result: ScreenCaptureResult | None = None, *, available: bool = True) -> None:
        self.result = result or ScreenCaptureResult(
            captured=False,
            captured_at="2026-04-29T12:00:00+00:00",
            scope="active_window",
            reason="fake_capture_unconfigured",
        )
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


def _phase12_l64_config(temp_config):
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


def _focused_window(title: str = "Stormhelm Notes - Code") -> dict[str, object]:
    return {
        "process_name": "code",
        "window_title": title,
        "window_handle": 777,
        "pid": 4440,
        "monitor_index": 1,
        "path": "C:\\Program Files\\Microsoft VS Code\\Code.exe",
        "is_focused": True,
        "minimized": False,
    }


def test_l64_screen_capture_disabled_reports_unavailable_capability_for_screen_question(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=_focused_window()),
    )

    response = subsystem.handle_request(
        session_id="l64-disabled",
        operator_text="what am I looking at?",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    limitation_codes = {limitation.code for limitation in response.analysis.limitations}
    assert ScreenLimitationCode.SCREEN_CAPTURE_DISABLED in limitation_codes
    assert ScreenLimitationCode.LOW_CONFIDENCE in limitation_codes
    assert "screen capture is disabled" in response.assistant_response.lower()
    assert "focused window metadata" in response.assistant_response.lower()
    assert ScreenSourceType.SCREEN_CAPTURE not in response.analysis.observation.source_types_used
    assert response.telemetry["observation"]["screen_capture"]["reason"] == "screen_capture_disabled"
    assert response.telemetry["observation"]["confidence_label"] == "low"


def test_l64_screen_content_question_with_metadata_only_reports_insufficient_evidence(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=_focused_window("Stormhelm Docs - Code")),
    )

    response = subsystem.handle_request(
        session_id="l64-metadata-only",
        operator_text="what is on my screen",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    lowered = response.assistant_response.lower()
    assert "current window appears on display 1" not in lowered
    assert "only have window/display metadata" in lowered
    assert "cannot honestly describe the screen contents" in lowered
    assert response.response_contract["evidence_kind"] == "window_metadata"
    assert response.telemetry["observation"]["evidence_kind"] == "window_metadata"


def test_l64_fake_screenshot_ocr_becomes_primary_screen_observation_and_trace_source(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = True
    fake_capture = FakeScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-04-29T12:00:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:fake-1",
            text="Stormhelm Phase L6.4 visual grounding test screen",
            text_source="local_ocr",
            confidence_score=0.86,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=_focused_window("Visual Grounding Test - Code")),
        screen_capture_provider=fake_capture,
    )

    response = subsystem.handle_request(
        session_id="l64-ocr",
        operator_text="what am I looking at?",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {"value": "stale clipboard text"}},
    )

    observation = response.analysis.observation
    assert observation is not None
    assert observation.visual_text == "Stormhelm Phase L6.4 visual grounding test screen"
    assert ScreenSourceType.SCREEN_CAPTURE in observation.source_types_used
    assert ScreenSourceType.LOCAL_OCR in observation.source_types_used
    assert "l6.4 visual grounding" in response.assistant_response.lower()
    assert "screenshot captured" in response.assistant_response.lower()
    assert "2026-04-29T12:00:00+00:00" in response.assistant_response
    assert response.telemetry["observation"]["screen_capture"]["captured"] is True
    assert response.telemetry["observation"]["screen_capture"]["raw_screenshot_logged"] is False
    assert response.telemetry["observation"]["screen_capture"]["scope"] == "active_window"
    assert response.telemetry["observation"]["visual_text_source"] == "local_ocr"
    assert response.response_contract["evidence_kind"] == "visual_content"
    assert response.telemetry["observation"]["evidence_kind"] == "visual_content"
    assert response.telemetry["trace"]["source_labels"][:3] == ["screen_capture", "local_ocr", "focus_state"]
    assert any(stage["stage"] == "visual_grounding" for stage in response.telemetry["timing"]["stage_timings"])

    snapshot = subsystem.status_snapshot()
    assert snapshot["visual_grounding"]["screen_capture"]["available"] is True
    assert snapshot["visual_grounding"]["screen_capture"]["enabled"] is True
    assert snapshot["hardening"]["latest_trace"]["source_labels"][:3] == ["screen_capture", "local_ocr", "focus_state"]


def test_l64_what_is_on_my_screen_with_visual_content_returns_content_summary(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = True
    fake_capture = FakeScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-04-29T12:03:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:fake-content",
            text="Stormhelm visual content summary from OCR",
            text_source="local_ocr",
            confidence_score=0.88,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=_focused_window("Visual Content - Code")),
        screen_capture_provider=fake_capture,
    )

    response = subsystem.handle_request(
        session_id="l64-visual-content-screen-question",
        operator_text="what is on my screen",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {"value": "old clipboard"}},
    )

    lowered = response.assistant_response.lower()
    assert "stormhelm visual content summary from ocr" in lowered
    assert "current window appears on display 1" not in lowered
    assert response.response_contract["evidence_kind"] == "visual_content"


def test_l64_capture_can_fall_back_to_primary_monitor_when_focus_bounds_are_missing(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = True
    fake_capture = FakeScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-04-29T12:01:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:fake-monitor",
            text="Primary monitor visual fallback",
            text_source="local_ocr",
            confidence_score=0.8,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=None, windows=[]),
        screen_capture_provider=fake_capture,
    )

    response = subsystem.handle_request(
        session_id="l64-monitor-fallback",
        operator_text="what am I looking at?",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    assert fake_capture.calls[0]["monitor_metadata"]["index"] == 1
    assert response.telemetry["observation"]["screen_capture"]["captured"] is True
    assert response.telemetry["observation"]["live_signal_available"] is True
    assert "primary monitor visual fallback" in response.assistant_response.lower()


def test_l64_captured_screenshot_without_ocr_reports_source_but_low_content_confidence(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = True
    fake_capture = FakeScreenCaptureProvider(
        ScreenCaptureResult(
            captured=True,
            captured_at="2026-04-29T12:02:00+00:00",
            scope="active_window",
            capture_reference="screen-capture:fake-no-ocr",
            text=None,
            text_source=None,
            confidence_score=0.0,
            metadata={"backend": "fake", "raw_screenshot_logged": False, "image_retained": False},
        )
    )
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=None, windows=[]),
        screen_capture_provider=fake_capture,
    )

    response = subsystem.handle_request(
        session_id="l64-no-ocr",
        operator_text="what am I looking at?",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    limitation_codes = {limitation.code for limitation in response.analysis.limitations}
    assert ScreenLimitationCode.OBSERVATION_UNAVAILABLE not in limitation_codes
    assert ScreenLimitationCode.LOW_CONFIDENCE in limitation_codes
    assert response.telemetry["observation"]["screen_capture"]["captured"] is True
    assert response.telemetry["observation"]["source_labels"] == ["screen_capture"]
    assert "screenshot captured at 2026-04-29t12:02:00+00:00" in response.assistant_response.lower()
    assert "low-confidence" in response.assistant_response.lower()


def test_l64_clipboard_only_path_is_labeled_clipboard_only_not_screen_truth(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=None, windows=[]),
    )

    response = subsystem.handle_request(
        session_id="l64-clipboard",
        operator_text="what am I looking at?",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {"kind": "text", "value": "copied build log"}},
    )

    assert response.telemetry["observation"]["clipboard_only"] is True
    assert response.telemetry["observation"]["live_signal_available"] is False
    assert "clipboard contains" in response.assistant_response.lower()
    assert "can't confirm" in response.assistant_response.lower()
    assert "looking at copied build log" not in response.assistant_response.lower()


def test_l64_focused_window_only_is_low_confidence_metadata(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=_focused_window("Untitled - Notepad")),
    )

    response = subsystem.handle_request(
        session_id="l64-focus-only",
        operator_text="what am I looking at?",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    limitation_codes = {limitation.code for limitation in response.analysis.limitations}
    assert ScreenLimitationCode.LOW_CONFIDENCE in limitation_codes
    assert response.analysis.confidence.level.value == "low"
    assert response.telemetry["observation"]["confidence_label"] == "low"
    assert "focused window metadata" in response.assistant_response.lower()
    assert "low-confidence" in response.assistant_response.lower()


def test_l64_popup_meaning_without_visual_content_requires_capture(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = False
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=_focused_window("Installer Popup - Setup")),
    )

    response = subsystem.handle_request(
        session_id="l64-popup-no-visual-content",
        operator_text="what does this popup mean",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    lowered = response.assistant_response.lower()
    assert "only have window/display metadata" in lowered or "screen capture is disabled" in lowered
    assert "cannot honestly describe" in lowered or "can't safely describe" in lowered
    assert response.response_contract["evidence_kind"] == "window_metadata"


def test_l64_sensitive_window_blocks_screenshot_capture(temp_config) -> None:
    config = _phase12_l64_config(temp_config)
    config.screen_capture_enabled = True
    fake_capture = FakeScreenCaptureProvider()
    subsystem = build_screen_awareness_subsystem(
        config,
        system_probe=L64Probe(focused_window=_focused_window("Password Manager - Bank Login")),
        screen_capture_provider=fake_capture,
    )

    response = subsystem.handle_request(
        session_id="l64-sensitive",
        operator_text="what am I looking at?",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    limitation_codes = {limitation.code for limitation in response.analysis.limitations}
    assert fake_capture.calls == []
    assert ScreenLimitationCode.SENSITIVE_CONTENT_RESTRICTED in limitation_codes
    assert response.analysis.observation.sensitivity == ScreenSensitivityLevel.RESTRICTED
    assert response.telemetry["observation"]["screen_capture"]["reason"] == "sensitive_window_blocked"
    assert "sensitive" in response.assistant_response.lower()
    assert "did not capture" in response.assistant_response.lower()
