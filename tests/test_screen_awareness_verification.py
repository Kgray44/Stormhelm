from __future__ import annotations

from stormhelm.config.models import CalculationsConfig
from stormhelm.core.calculations import build_calculations_subsystem
from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem


class FakeObservationProbe:
    def __init__(self, *, focused_window: dict[str, object] | None = None, windows: list[dict[str, object]] | None = None) -> None:
        self._focused_window = focused_window
        self._windows = list(windows or ([focused_window] if focused_window else []))

    def window_status(self) -> dict[str, object]:
        return {
            "focused_window": self._focused_window,
            "windows": list(self._windows),
            "monitors": [{"index": 1, "device_name": "\\\\.\\DISPLAY1", "is_primary": True}],
        }


def _phase4_screen_config(temp_config):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase4"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    return temp_config.screen_awareness


def _focused_browser_window(title: str, *, window_handle: int) -> dict[str, object]:
    return {
        "process_name": "chrome",
        "window_title": title,
        "window_handle": window_handle,
        "pid": 5000 + window_handle,
        "monitor_index": 1,
        "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "is_focused": True,
        "minimized": False,
    }


def _build_phase4_subsystem(temp_config, *, title: str, window_handle: int, calculations=None) -> object:
    return build_screen_awareness_subsystem(
        _phase4_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_browser_window(title, window_handle=window_handle),
        ),
        calculations=calculations,
    )


def _screen_resolution(*, intent: str, analysis_result: dict[str, object]) -> dict[str, object]:
    return {
        "kind": "screen_awareness",
        "intent": intent,
        "analysis_result": analysis_result,
    }


def test_phase4_verification_marks_step_completed_from_strong_current_evidence(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Deploy Settings - Google Chrome",
        window_handle=801,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="did that work?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-1", "title": "Deploy Settings"},
            "active_item": {
                "itemId": "save-success",
                "title": "Saved successfully",
                "kind": "status-banner",
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    verification = response.analysis.verification_result

    assert verification is not None
    assert verification.completion_status.value == "completed"
    assert verification.comparison.change_classification.value == "insufficient_evidence"
    assert verification.explanation.summary
    assert response.telemetry["verification"]["outcome"] == "completed"
    assert "appears completed" in response.assistant_response.lower()
    assert "clicked" not in response.assistant_response.lower()


def test_phase4_verification_reports_error_still_present_and_no_visible_change(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="API Settings - Google Chrome",
        window_handle=802,
    )

    prior_resolution = _screen_resolution(
        intent="explain_visible_content",
        analysis_result={
            "interpretation": {
                "visible_errors": ["Error: API token is required"],
                "visible_messages": ["Error: API token is required"],
            },
            "current_screen_context": {
                "summary": "Chrome is focused on API Settings. Visible cue: Error: API token is required.",
                "blockers_or_prompts": ["Error: API token is required"],
            },
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="did the error go away?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-2", "title": "API Settings"},
            "active_item": {
                "itemId": "settings-page",
                "title": "API Settings",
                "kind": "settings-page",
            },
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Error: API token is required",
                "preview": "Error: API token is required",
            },
            "clipboard": {},
            "recent_context_resolutions": [prior_resolution],
        },
    )

    verification = response.analysis.verification_result

    assert verification is not None
    assert verification.completion_status.value == "not_completed"
    assert verification.comparison.change_classification.value == "no_visible_change"
    assert verification.unresolved_conditions
    assert "still present" in verification.unresolved_conditions[0].summary.lower()
    assert response.telemetry["verification"]["comparison_basis"] == "prior_screen_bearing"
    assert "still present" in response.assistant_response.lower()


def test_phase4_verification_refuses_change_claim_without_prior_bearing(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="CI Dashboard - Google Chrome",
        window_handle=803,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what changed on my screen?",
        intent=ScreenIntentType.DETECT_VISIBLE_CHANGE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-3", "title": "CI Dashboard"},
            "active_item": {
                "itemId": "build-banner",
                "title": "Build failed with 2 test failures.",
                "kind": "warning-banner",
            },
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    verification = response.analysis.verification_result
    limitation_codes = {limitation.code.value for limitation in response.analysis.limitations}

    assert verification is not None
    assert verification.comparison.change_classification.value == "insufficient_evidence"
    assert "prior_observation_required" in limitation_codes
    assert "unverified_change" in limitation_codes
    assert response.telemetry["verification"]["comparison_ready"] is False
    assert "can't verify a meaningful change" in response.assistant_response.lower()


def test_phase4_verification_detects_warning_disappearance_from_prior_screen_bearing(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Deploy Settings - Google Chrome",
        window_handle=804,
    )

    prior_resolution = _screen_resolution(
        intent="guide_navigation",
        analysis_result={
            "interpretation": {
                "visible_errors": ["Warning: Token expired"],
                "visible_messages": ["Warning: Token expired"],
            },
            "current_screen_context": {
                "summary": "Chrome is focused on Deploy Settings. Visible cue: Warning: Token expired.",
                "blockers_or_prompts": ["Warning: Token expired"],
            },
            "grounding_result": {
                "winning_target": {"candidate_id": "warning-token", "label": "Warning: Token expired"},
            },
            "navigation_result": {
                "step_state": {"status": "blocked", "wrong_page": False},
                "blocker": {"summary": "Warning: Token expired is still visible."},
            },
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="did that work?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-4", "title": "Deploy Settings"},
            "active_item": {
                "itemId": "save-success",
                "title": "Saved successfully",
                "kind": "status-banner",
            },
        },
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [prior_resolution],
        },
    )

    verification = response.analysis.verification_result

    assert verification is not None
    assert verification.comparison.change_classification.value == "verified_change"
    assert verification.completion_status.value == "completed"
    assert verification.change_observations
    assert "disappeared" in verification.change_observations[0].summary.lower()
    assert response.telemetry["verification"]["navigation_reused"] is True
    assert response.telemetry["verification"]["grounding_reused"] is True


def test_phase4_verification_preserves_ambiguity_when_change_is_visible_but_not_yet_understood(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Account Overview - Google Chrome",
        window_handle=805,
    )

    prior_resolution = _screen_resolution(
        intent="guide_navigation",
        analysis_result={
            "current_screen_context": {
                "summary": "Chrome is focused on Account Overview.",
                "blockers_or_prompts": ["Open Security settings to continue."],
            },
            "navigation_result": {
                "step_state": {
                    "status": "wrong_page",
                    "expected_target_label": "Security settings",
                    "wrong_page": True,
                },
                "recovery_hint": {"summary": "Look for the Security settings page next."},
            },
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="did anything change?",
        intent=ScreenIntentType.DETECT_VISIBLE_CHANGE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-5", "title": "Notifications Overview"},
            "active_item": {
                "itemId": "notifications-overview",
                "title": "Notifications Overview",
                "kind": "settings-page",
            },
        },
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [prior_resolution],
        },
    )

    verification = response.analysis.verification_result

    assert verification is not None
    assert verification.comparison.change_classification.value == "changed_but_not_understood"
    assert verification.completion_status.value == "ambiguous"
    assert response.telemetry["verification"]["outcome"] == "ambiguous"
    assert "can't yet tell what that change means" in response.assistant_response.lower()


def test_phase4_verification_reuses_prior_navigation_target_for_page_alignment_check(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Security Settings - Google Chrome",
        window_handle=806,
    )

    prior_resolution = _screen_resolution(
        intent="guide_navigation",
        analysis_result={
            "current_screen_context": {
                "summary": "Chrome is focused on Account Overview.",
            },
            "navigation_result": {
                "step_state": {
                    "status": "wrong_page",
                    "expected_target_label": "Security settings",
                    "wrong_page": True,
                },
                "recovery_hint": {"summary": "Look for the Security settings page next."},
            },
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="is this the page I was trying to get to?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-6", "title": "Security Settings"},
            "active_item": {
                "itemId": "security-settings",
                "title": "Security settings",
                "kind": "settings-page",
            },
        },
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [prior_resolution],
        },
    )

    verification = response.analysis.verification_result

    assert verification is not None
    assert verification.completion_status.value == "completed"
    assert verification.context.navigation_reused is True
    assert verification.expectation is not None
    assert verification.expectation.target_label == "Security settings"
    assert response.telemetry["verification"]["navigation_reused"] is True
    assert "matches the page you were aiming for" in response.assistant_response.lower()


def test_phase4_verification_telemetry_stays_native_first_and_honest(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Deploy Settings - Google Chrome",
        window_handle=807,
    )

    prior_resolution = _screen_resolution(
        intent="explain_visible_content",
        analysis_result={
            "interpretation": {
                "visible_errors": ["Warning: Token expired"],
                "visible_messages": ["Warning: Token expired"],
            },
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="did that work?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-7", "title": "Deploy Settings"},
            "active_item": {
                "itemId": "save-success",
                "title": "Saved successfully",
                "kind": "status-banner",
            },
        },
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [prior_resolution],
        },
    )

    telemetry = response.telemetry["verification"]

    assert telemetry["requested"] is True
    assert telemetry["dominant_channel"] in {"workspace_context", "native_observation"}
    assert "visual_provider" not in telemetry["provenance_channels"]
    assert telemetry["comparison_basis"] == "prior_screen_bearing"
    assert telemetry["comparison_ready"] is True
    assert telemetry["grounding_reused"] is False


def test_phase41_verification_keeps_warning_cleanup_separate_from_step_completion(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Deploy Settings - Google Chrome",
        window_handle=808,
    )

    prior_resolution = _screen_resolution(
        intent="verify_screen_state",
        analysis_result={
            "interpretation": {
                "visible_errors": ["Warning: Token expired"],
                "visible_messages": ["Warning: Token expired"],
            },
            "current_screen_context": {
                "summary": "Chrome is focused on Deploy Settings. Visible cue: Warning: Token expired.",
                "blockers_or_prompts": ["Warning: Token expired"],
            },
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="did that work?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-8", "title": "Deploy Settings"},
            "active_item": {
                "itemId": "deploy-settings",
                "title": "Deploy Settings",
                "kind": "settings-page",
            },
        },
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [prior_resolution],
        },
    )

    verification = response.analysis.verification_result

    assert verification is not None
    assert verification.comparison.change_classification.value == "verified_change"
    assert verification.completion_status.value == "ambiguous"
    assert "no longer visible" in response.assistant_response.lower()
    assert "cannot yet verify that the step completed" in response.assistant_response.lower()


def test_phase41_verification_rejects_thin_prior_bearing_as_change_basis(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Security Settings - Google Chrome",
        window_handle=809,
    )

    prior_resolution = _screen_resolution(
        intent="inspect_visible_state",
        analysis_result={
            "current_screen_context": {
                "summary": "The current screen context is only partially available.",
                "blockers_or_prompts": [],
            },
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="did anything change?",
        intent=ScreenIntentType.DETECT_VISIBLE_CHANGE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-9", "title": "Security Settings"},
            "active_item": {
                "itemId": "security-settings",
                "title": "Security Settings",
                "kind": "settings-page",
            },
        },
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [prior_resolution],
        },
    )

    verification = response.analysis.verification_result
    telemetry = response.telemetry["verification"]

    assert verification is not None
    assert verification.comparison.change_classification.value == "insufficient_evidence"
    assert verification.comparison.comparison_ready is False
    assert telemetry["comparison_basis"] == "current_state_only"
    assert telemetry["comparison_basis_reason"] == "prior_bearing_too_thin"
    assert "enough comparison basis" in response.assistant_response.lower()


def test_phase41_verification_rejects_stale_prior_bearing_for_generic_result_check(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Deploy Settings - Google Chrome",
        window_handle=810,
    )

    prior_resolution = {
        **_screen_resolution(
            intent="inspect_visible_state",
            analysis_result={
                "current_screen_context": {
                    "summary": 'Chrome is focused on "Billing Settings".',
                    "blockers_or_prompts": [],
                },
            },
        ),
        "captured_at": "2026-04-20T00:00:00+00:00",
    }

    response = subsystem.handle_request(
        session_id="default",
        operator_text="did that work?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-10", "title": "Deploy Settings"},
            "active_item": {
                "itemId": "save-success",
                "title": "Saved successfully",
                "kind": "status-banner",
            },
        },
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [prior_resolution],
        },
    )

    verification = response.analysis.verification_result
    telemetry = response.telemetry["verification"]

    assert verification is not None
    assert verification.comparison.change_classification.value == "insufficient_evidence"
    assert verification.comparison.comparison_ready is False
    assert verification.completion_status.value == "completed"
    assert telemetry["comparison_basis"] == "current_state_only"
    assert telemetry["comparison_basis_reason"] == "stale_prior_bearing"
    assert "based on the current screen state" in response.assistant_response.lower()


def test_phase41_verification_tracks_modal_cleanup_without_claiming_success(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Deploy Settings - Google Chrome",
        window_handle=811,
    )

    prior_resolution = _screen_resolution(
        intent="verify_screen_state",
        analysis_result={
            "observation": {
                "workspace_snapshot": {
                    "active_item": {
                        "itemId": "confirm-dialog",
                        "title": "Confirm save changes",
                        "kind": "dialog",
                    },
                    "opened_items": [],
                },
            },
            "current_screen_context": {
                "summary": "Chrome is focused on Deploy Settings. Visible cue: Confirm save changes dialog.",
                "blockers_or_prompts": ["Confirm save changes dialog."],
            },
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="did that work?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-11", "title": "Deploy Settings"},
            "active_item": {
                "itemId": "deploy-settings",
                "title": "Deploy Settings",
                "kind": "settings-page",
            },
        },
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [prior_resolution],
        },
    )

    verification = response.analysis.verification_result

    assert verification is not None
    assert verification.change_observations
    assert verification.change_observations[0].change_type == "modal_disappeared"
    assert verification.completion_status.value == "ambiguous"
    assert "dialog" in response.assistant_response.lower()
    assert "is no longer visible" in response.assistant_response.lower()
    assert "cannot yet verify that the step completed" in response.assistant_response.lower()


def test_phase4_verification_reuses_shared_calculations_seam_for_visible_numeric_claims(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Invoice Totals - Google Chrome",
        window_handle=812,
        calculations=build_calculations_subsystem(CalculationsConfig()),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="do these numbers add up?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-12", "title": "Invoice Totals"},
            "active_item": {
                "itemId": "invoice-totals",
                "title": "Invoice Totals",
                "kind": "document",
            },
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "2 + 2 + 4 + 4 + 4 + 4 + 5 + 10 = 28",
                "preview": "2 + 2 + 4 + 4 + 4 + 4 + 5 + 10 = 28",
            },
            "clipboard": {},
        },
    )

    verification = response.analysis.verification_result
    calculation = response.analysis.calculation_activity

    assert verification is not None
    assert calculation is not None
    assert calculation.status == "resolved"
    assert calculation.internal_validation is True
    assert calculation.result_visibility == "silent_internal"
    assert calculation.calculation_trace["caller_subsystem"] == "screen_awareness"
    assert calculation.calculation_trace["caller_intent"] == "numeric_screen_verification"
    assert calculation.calculation_trace["route_selected"] == "deterministic_local_verification"
    assert calculation.calculation_trace["verification_match"] is False
    assert response.telemetry["calculation"]["used"] is True
    assert "35" in response.assistant_response
    assert "28" in response.assistant_response


def test_phase4_verification_keeps_weak_visible_numeric_input_ambiguous(temp_config) -> None:
    subsystem = _build_phase4_subsystem(
        temp_config,
        title="Invoice Totals - Google Chrome",
        window_handle=813,
        calculations=build_calculations_subsystem(CalculationsConfig()),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="do these numbers add up?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-13", "title": "Invoice Totals"},
            "active_item": {
                "itemId": "invoice-summary",
                "title": "Invoice Totals",
                "kind": "document",
            },
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Subtotal, taxes, and shipping are listed below.",
                "preview": "Subtotal, taxes, and shipping are listed below.",
            },
            "clipboard": {},
        },
    )

    verification = response.analysis.verification_result
    calculation = response.analysis.calculation_activity

    assert verification is not None
    assert verification.completion_status.value == "ambiguous"
    assert calculation is not None
    assert calculation.status == "ambiguous"
    assert calculation.calculation_failure is None
    assert response.telemetry["calculation"]["used"] is False
    assert "couldn't isolate enough visible numeric input" in response.assistant_response.lower()
