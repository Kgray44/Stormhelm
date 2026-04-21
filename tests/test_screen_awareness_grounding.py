from __future__ import annotations

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


def _phase2_screen_config(temp_config):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase2"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    return temp_config.screen_awareness


def test_phase2_grounding_prefers_selected_warning_over_broader_screen_candidates(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Deploy Settings - Google Chrome",
                "window_handle": 501,
                "pid": 2440,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what does this warning mean",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-1", "title": "Deployment Troubleshooting"},
            "active_item": {
                "itemId": "settings-page",
                "title": "Deploy Settings",
                "url": "https://example.test/settings/deploy",
                "kind": "settings-page",
            },
            "opened_items": [
                {
                    "itemId": "warning-1",
                    "title": "Warning: Token expired",
                    "kind": "warning-banner",
                    "pane": "main",
                    "color": "red",
                },
                {
                    "itemId": "button-1",
                    "title": "Save",
                    "kind": "button",
                    "pane": "footer",
                },
            ],
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Warning: Token expired",
                "preview": "Warning: Token expired",
            },
            "clipboard": {},
        },
    )

    grounding = response.analysis.grounding_result

    assert grounding is not None
    assert grounding.ambiguity_status.value == "resolved"
    assert grounding.winning_target is not None
    assert grounding.winning_target.role.value == "warning"
    assert grounding.winning_target.label == "Warning: Token expired"
    assert grounding.ranked_candidates[0].candidate_id == grounding.winning_target.candidate_id
    assert grounding.ranked_candidates[0].score.final_score > grounding.ranked_candidates[1].score.final_score
    assert grounding.planner_result.resolved is True
    assert grounding.planner_result.winning_candidate_id == grounding.winning_target.candidate_id
    assert "selected" in grounding.explanation.summary.lower() or "selection" in grounding.explanation.summary.lower()
    assert response.telemetry["grounding"]["candidate_count"] >= 2


def test_phase2_grounding_preserves_ambiguity_for_duplicate_save_buttons(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Project Settings - Google Chrome",
                "window_handle": 511,
                "pid": 2550,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="which save button are you talking about",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-2", "title": "Project Settings"},
            "active_item": {
                "itemId": "settings-page",
                "title": "Project Settings",
                "kind": "settings-page",
            },
            "opened_items": [
                {
                    "itemId": "button-toolbar-save",
                    "title": "Save",
                    "kind": "button",
                    "pane": "toolbar",
                    "ordinal": 1,
                },
                {
                    "itemId": "button-dialog-save",
                    "title": "Save",
                    "kind": "button",
                    "pane": "dialog",
                    "ordinal": 2,
                },
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    grounding = response.analysis.grounding_result

    assert grounding is not None
    assert grounding.ambiguity_status.value == "ambiguous"
    assert grounding.winning_target is None
    assert len(grounding.ranked_candidates) >= 2
    assert grounding.clarification_need is not None
    assert grounding.clarification_need.needed is True
    assert "save" in grounding.clarification_need.prompt.lower()
    assert grounding.planner_result.resolved is False
    assert len(grounding.planner_result.alternative_candidate_ids) >= 2
    assert "which one" in response.assistant_response.lower() or "two plausible" in response.assistant_response.lower()
    assert "clicked" not in response.assistant_response.lower()


def test_phase2_grounding_fails_honestly_when_no_candidate_is_sufficiently_supported(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Project Settings - Google Chrome",
                "window_handle": 521,
                "pid": 2660,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="is the red warning what is blocking me",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-3", "title": "Project Settings"},
            "active_item": {
                "itemId": "settings-page",
                "title": "Project Settings",
                "kind": "settings-page",
            },
            "opened_items": [
                {"itemId": "button-save", "title": "Save", "kind": "button", "pane": "footer"},
                {"itemId": "button-cancel", "title": "Cancel", "kind": "button", "pane": "footer"},
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    grounding = response.analysis.grounding_result

    assert grounding is not None
    assert grounding.ambiguity_status.value == "unresolved_insufficient_evidence"
    assert grounding.winning_target is None
    assert grounding.clarification_need is not None
    assert grounding.clarification_need.needed is True
    assert "select" in grounding.clarification_need.prompt.lower() or "label" in grounding.clarification_need.prompt.lower()
    assert grounding.planner_result.resolved is False
    assert response.telemetry["grounding"]["outcome"] == "unresolved_insufficient_evidence"
    assert "enough grounded evidence" in response.assistant_response.lower() or "not confident" in response.assistant_response.lower()


def test_phase2_grounding_prefers_focused_field_for_selected_field_requests(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Account Security - Google Chrome",
                "window_handle": 531,
                "pid": 2770,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="explain the selected field",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-4", "title": "Account Security"},
            "active_item": {
                "itemId": "field-token",
                "title": "API token",
                "kind": "text-field",
                "focused": True,
                "selected": True,
            },
            "opened_items": [
                {"itemId": "field-token", "title": "API token", "kind": "text-field", "focused": True, "selected": True},
                {"itemId": "field-name", "title": "Workspace name", "kind": "text-field"},
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    grounding = response.analysis.grounding_result

    assert grounding is not None
    assert grounding.ambiguity_status.value == "resolved"
    assert grounding.winning_target is not None
    assert grounding.winning_target.role.value == "field"
    assert grounding.winning_target.label == "API token"
    assert grounding.planner_result.resolved is True
    assert "field" in response.assistant_response.lower()


def test_phase2_grounding_prefers_direct_selection_over_conflicting_active_item_metadata(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "code",
                "window_title": "main.py - Visual Studio Code",
                "window_handle": 541,
                "pid": 2880,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Microsoft VS Code\\Code.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what does this mean",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-5", "title": "Deploy Debugging"},
            "active_item": {
                "itemId": "page-errors",
                "title": "Deploy dashboard",
                "kind": "settings-page",
                "focused": True,
            },
            "opened_items": [
                {
                    "itemId": "warning-banner",
                    "title": "Warning: Deployment delayed",
                    "kind": "warning-banner",
                    "pane": "main",
                }
            ],
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "NameError: name 'token' is not defined",
                "preview": "NameError: name 'token' is not defined",
            },
            "clipboard": {},
        },
    )

    grounding = response.analysis.grounding_result

    assert grounding is not None
    assert grounding.ambiguity_status.value == "resolved"
    assert grounding.winning_target is not None
    assert grounding.winning_target.candidate_id == "selection"
    assert grounding.winning_target.visible_text == "NameError: name 'token' is not defined"
    assert grounding.ranked_candidates[0].score.final_score > grounding.ranked_candidates[1].score.final_score
    assert "selection" in grounding.explanation.summary.lower() or "selected" in grounding.explanation.summary.lower()
    assert "observed: i grounded this request" in response.assistant_response.lower()


def test_phase2_grounding_prefers_current_focus_over_stale_background_match(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Release Controls - Google Chrome",
                "window_handle": 551,
                "pid": 2990,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what does this button do",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-6", "title": "Release Controls"},
            "active_item": {
                "itemId": "button-ship",
                "title": "Ship release",
                "kind": "button",
                "focused": True,
                "pane": "main",
            },
            "opened_items": [
                {
                    "itemId": "button-ship-stale",
                    "title": "Ship release",
                    "kind": "button",
                    "pane": "history",
                },
                {
                    "itemId": "button-abort",
                    "title": "Abort release",
                    "kind": "button",
                    "pane": "footer",
                },
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    grounding = response.analysis.grounding_result

    assert grounding is not None
    assert grounding.ambiguity_status.value == "resolved"
    assert grounding.winning_target is not None
    assert grounding.winning_target.candidate_id == "button-ship"
    assert grounding.winning_target.semantic_metadata["active_item"] is True
    assert "focus" in grounding.explanation.summary.lower() or "current" in grounding.explanation.summary.lower()


def test_phase2_grounding_preserves_ambiguity_for_generic_button_reference_without_anchor(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Project Controls - Google Chrome",
                "window_handle": 561,
                "pid": 3001,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what is this button",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-7", "title": "Project Controls"},
            "active_item": {
                "itemId": "controls-page",
                "title": "Project Controls",
                "kind": "settings-page",
            },
            "opened_items": [
                {
                    "itemId": "button-run",
                    "title": "Run",
                    "kind": "button",
                    "pane": "toolbar",
                },
                {
                    "itemId": "button-stop",
                    "title": "Stop",
                    "kind": "button",
                    "pane": "footer",
                },
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    grounding = response.analysis.grounding_result

    assert grounding is not None
    assert grounding.ambiguity_status.value == "ambiguous"
    assert grounding.winning_target is None
    assert grounding.clarification_need is not None
    assert grounding.clarification_need.needed is True
    assert "which one" in grounding.clarification_need.prompt.lower() or "which" in grounding.clarification_need.prompt.lower()
    assert response.telemetry["grounding"]["outcome"] == "ambiguous"


def test_phase2_grounding_refuses_role_only_warning_guess_when_multiple_candidates_are_weak(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Admin Dashboard - Google Chrome",
                "window_handle": 571,
                "pid": 3112,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what is this warning",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-8", "title": "Admin Dashboard"},
            "active_item": {
                "itemId": "dashboard-page",
                "title": "Admin Dashboard",
                "kind": "settings-page",
            },
            "opened_items": [
                {
                    "itemId": "warning-rate-limit",
                    "title": "Rate limit warning",
                    "kind": "warning-banner",
                    "pane": "sidebar",
                },
                {
                    "itemId": "warning-token",
                    "title": "Token warning",
                    "kind": "warning-banner",
                    "pane": "footer",
                },
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    grounding = response.analysis.grounding_result

    assert grounding is not None
    assert grounding.ambiguity_status.value == "ambiguous"
    assert grounding.winning_target is None
    assert grounding.confidence.level.value in {"low", "medium"}
    assert "multiple plausible" in grounding.explanation.summary.lower() or "ambiguity" in grounding.explanation.ambiguity_note.lower()


def test_phase2_grounding_refuses_single_weak_deictic_candidate_without_direct_anchor(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(focused_window=None, windows=[]),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what is this warning",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-8b", "title": "Admin Dashboard"},
            "active_item": {
                "itemId": "dashboard-page",
                "title": "Admin Dashboard",
                "kind": "settings-page",
            },
            "opened_items": [
                {
                    "itemId": "warning-rate-limit",
                    "title": "Rate limit warning",
                    "kind": "warning-banner",
                    "pane": "sidebar",
                }
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    grounding = response.analysis.grounding_result

    assert grounding is not None
    assert grounding.ambiguity_status.value == "unresolved_insufficient_evidence"
    assert grounding.winning_target is None
    assert grounding.clarification_need is not None
    assert "stronger visible anchor" in grounding.explanation.summary.lower() or "direct anchor" in " ".join(
        grounding.explanation.evidence_summary
    ).lower()


def test_phase2_grounding_debug_payload_reports_honest_outcome_reason_and_non_visual_provenance(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase2_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Release Controls - Google Chrome",
                "window_handle": 581,
                "pid": 3223,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what does this warning mean",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-9", "title": "Release Controls"},
            "active_item": {
                "itemId": "release-page",
                "title": "Release Controls",
                "kind": "settings-page",
            },
            "opened_items": [
                {
                    "itemId": "warning-release",
                    "title": "Warning: Release blocked",
                    "kind": "warning-banner",
                    "pane": "main",
                }
            ],
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Warning: Release blocked",
                "preview": "Warning: Release blocked",
            },
            "clipboard": {},
        },
    )

    grounding_telemetry = response.telemetry["grounding"]

    assert grounding_telemetry["outcome"] == "resolved"
    assert grounding_telemetry["outcome_reason"]
    assert grounding_telemetry["dominant_channel"] == "native_observation"
    assert "native_observation" in grounding_telemetry["provenance_channels"]
    assert grounding_telemetry["candidate_count"] >= 2
    assert grounding_telemetry["confidence"]["level"] in {"medium", "high"}
    assert grounding_telemetry["ranked_candidates"][0]["score"] >= grounding_telemetry["ranked_candidates"][1]["score"]
    assert grounding_telemetry["ranked_candidates"][0]["relative_outcome"] == "winner"
    assert grounding_telemetry["ranked_candidates"][1]["relative_outcome"] == "alternative"
    assert grounding_telemetry["ranked_candidates"][0]["evidence_notes"]
    assert "visual_provider" not in grounding_telemetry["ranked_candidates"][0]["evidence_summary"]
    assert response.telemetry["grounding_visual_augmentation"]["used"] is False
    assert response.telemetry["grounding_visual_augmentation"]["reason"] != "provider_visual_grounding_deferred"
