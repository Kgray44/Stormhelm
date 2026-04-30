from __future__ import annotations

from pathlib import Path

import pytest

from stormhelm.core.adapters import default_adapter_contract_registry
from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.system.probe import SystemProbe
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins.system_state import AppControlTool


def _plan(prompt: str, *, active_request_state: dict[str, object] | None = None):
    return DeterministicPlanner().plan(
        prompt,
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state=active_request_state or {},
        recent_tool_results=[],
    )


def _window(
    *,
    title: str,
    process_name: str = "Arduino IDE",
    pid: int = 4242,
    handle: int = 7111,
    path: str = "C:/Users/test/AppData/Local/Programs/Arduino IDE/Arduino IDE.exe",
) -> dict[str, object]:
    return {
        "process_name": process_name,
        "window_title": title,
        "window_handle": handle,
        "pid": pid,
        "path": path,
        "x": 10,
        "y": 10,
        "width": 900,
        "height": 700,
        "monitor_index": 1,
    }


def _tool_context(temp_config, system_probe: object) -> ToolContext:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    preferences = PreferencesRepository(database)
    notes = NotesRepository(database)
    return ToolContext(
        job_id="app-close-test",
        config=temp_config,
        events=EventBuffer(capacity=16),
        notes=notes,
        preferences=preferences,
        safety_policy=SafetyPolicy(temp_config),
        system_probe=system_probe,  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _windows_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("stormhelm.core.system.probe.platform.system", lambda: "Windows")
    monkeypatch.setattr(SystemProbe, "_GRACEFUL_CLOSE_VERIFY_TIMEOUT_SECONDS", 0.0)


def test_close_app_routes_to_native_app_control_not_generic_provider() -> None:
    decision = _plan("close Arduino IDE")

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "app_control"
    assert decision.tool_requests[0].arguments == {"action": "close", "app_name": "arduino ide"}
    assert decision.tool_requests[0].tool_name != "generic_provider"


def test_exit_app_routes_to_native_app_control() -> None:
    decision = _plan("exit Arduino")

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "app_control"
    assert decision.tool_requests[0].arguments == {"action": "quit", "app_name": "arduino"}


def test_multi_window_app_close_requests_all_matching_app_windows(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    first = _window(title="OpenLoopControlKG | Arduino IDE 2.3.8", pid=1010, handle=2010)
    second = _window(title="sketch_apr29a | Arduino IDE 2.3.8", pid=1011, handle=2011)

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {
            "success": True,
            "close_request_sent": True,
            "graceful_close_requested": True,
            "graceful_close_supported": True,
            "request_ms": 11.0,
            "per_target": [
                {
                    "pid": 1011,
                    "process_name": "Arduino IDE",
                    "close_request_sent": True,
                    "window_handle": 2011,
                    "method": "wm_close",
                },
                {
                    "pid": 1010,
                    "process_name": "Arduino IDE",
                    "close_request_sent": True,
                    "window_handle": 2010,
                    "method": "wm_close",
                },
            ],
        },
    )
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {"focused_window": None, "windows": [first, second], "monitors": []},
    )

    result = probe.app_control(action="close", app_name="Arduino IDE")

    assert result["success"] is False
    assert result["reason"] == "close_failed"
    assert result["ambiguity"] is False
    assert result["graceful_close_requested"] is True
    assert result["close_requested_count"] == 2
    assert result["close_failed_count"] == 2
    assert [item["window_title"] for item in result["per_window_results"]] == [
        "sketch_apr29a | Arduino IDE 2.3.8",
        "OpenLoopControlKG | Arduino IDE 2.3.8",
    ]


def test_close_both_followup_binds_to_previous_app_close_candidate_set() -> None:
    active_request_state = {
        "family": "app_control",
        "subject": "Arduino IDE",
        "parameters": {
            "action": "close",
            "app_name": "Arduino IDE",
            "selection_mode": "ambiguous_candidate_set",
            "candidate_targets": [
                {"window_title": "OpenLoopControlKG | Arduino IDE 2.3.8"},
                {"window_title": "sketch_apr29a | Arduino IDE 2.3.8"},
            ],
        },
        "context_freshness": "current",
        "context_reusable": True,
    }

    for prompt in ("close both", "both", "close all", "all of them"):
        decision = _plan(prompt, active_request_state=active_request_state)

        assert decision.request_type == "direct_action"
        assert decision.tool_requests[0].tool_name == "app_control"
        assert decision.tool_requests[0].arguments == {
            "action": "close",
            "app_name": "Arduino IDE",
        }
        assert decision.tool_requests[0].arguments["app_name"].lower() != "both"


def test_close_that_window_routes_to_focused_window_control() -> None:
    decision = _plan("close that window")

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "window_control"
    assert decision.tool_requests[0].arguments == {"action": "close", "target_mode": "focused"}


def test_graceful_close_contract_declares_supported_states_on_windows(temp_config) -> None:
    capabilities = SystemProbe(temp_config).control_capabilities()
    contract = default_adapter_contract_registry().resolve_tool_contract(
        "app_control",
        {"action": "close", "app_name": "notepad"},
    )

    assert capabilities["app"]["graceful_close_supported"] is True
    assert capabilities["app"]["force_close_requires_approval"] is True
    assert contract is not None
    assert "graceful_close" in contract.action_modes
    assert "force_close_requires_approval" in contract.failure_posture
    assert contract.verification.posture == "close_request_with_postcheck"


def test_target_resolution_finds_fake_arduino_window_and_sends_close_request(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []
    arduino_window = _window(title="Sketchbook - Arduino IDE 2.3.4")
    calls = {"window_status": 0}

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])

    def fake_window_status(self):
        calls["window_status"] += 1
        if calls["window_status"] == 1:
            return {"focused_window": None, "windows": [arduino_window], "monitors": []}
        return {"focused_window": None, "windows": [], "monitors": []}

    def fake_run(self, script: str):
        scripts.append(script)
        return {
            "close_request_sent": True,
            "graceful_close_supported": True,
            "method": "wm_close",
            "request_ms": 12.5,
        }

    monkeypatch.setattr(SystemProbe, "window_status", fake_window_status)
    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="close", app_name="Arduino IDE")

    assert result["success"] is True
    assert result["close_result_state"] == "closed_verified"
    assert result["close_target_app"] == "Arduino IDE"
    assert result["close_target_process"] == "Arduino IDE"
    assert result["close_target_window_title"] == "Sketchbook - Arduino IDE 2.3.4"
    assert result["close_target_hwnd_present"] is True
    assert result["graceful_close_requested"] is True
    assert any("WM_CLOSE" in script and "SendMessageTimeout" in script for script in scripts)
    assert all("Stop-Process" not in script for script in scripts)


def test_closed_verified_when_matched_notepad_window_disappears(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    calls = {"window_status": 0}

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {"close_request_sent": True, "graceful_close_supported": True, "request_ms": 7.0},
    )

    def fake_window_status(self):
        calls["window_status"] += 1
        if calls["window_status"] == 1:
            return {"focused_window": None, "windows": [_window(title="Untitled - Notepad", process_name="Notepad", path="C:/Windows/System32/notepad.exe")], "monitors": []}
        return {"focused_window": None, "windows": [], "monitors": []}

    monkeypatch.setattr(SystemProbe, "window_status", fake_window_status)

    result = probe.app_control(action="close", app_name="Notepad")

    assert result["success"] is True
    assert result["close_result_state"] == "closed_verified"
    assert result["verification_observed"] == "window_and_process_absent"
    assert result["close_verification_ms"] >= 0


def test_confirmation_required_when_save_prompt_appears(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    calls = {"window_status": 0}
    target = _window(title="Unsaved Sketch - Arduino IDE", process_name="Arduino IDE")
    prompt = _window(title="Save changes to Unsaved Sketch?", process_name="Arduino IDE", handle=8111)

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {"close_request_sent": True, "graceful_close_supported": True, "request_ms": 9.0},
    )

    def fake_window_status(self):
        calls["window_status"] += 1
        if calls["window_status"] == 1:
            return {"focused_window": None, "windows": [target], "monitors": []}
        return {"focused_window": prompt, "windows": [target, prompt], "monitors": []}

    monkeypatch.setattr(SystemProbe, "window_status", fake_window_status)

    result = probe.app_control(action="close", app_name="Arduino IDE")

    assert result["success"] is False
    assert result["reason"] == "confirmation_required"
    assert result["close_result_state"] == "close_confirmation_required"
    assert result["confirmation_prompt_detected"] is True
    assert result["available_next_actions"] == ["save_and_close", "discard_and_close", "cancel_close"]
    assert result["force_close_offered"] is False


def test_multi_window_close_reports_partial_when_one_window_needs_confirmation(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    first = _window(title="OpenLoopControlKG | Arduino IDE 2.3.8", pid=1010, handle=2010)
    second = _window(title="sketch_apr29a | Arduino IDE 2.3.8", pid=1011, handle=2011)
    prompt = _window(title="Save changes to sketch_apr29a?", pid=1011, handle=3011)
    calls = {"window_status": 0}

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {
            "success": True,
            "close_request_sent": True,
            "graceful_close_requested": True,
            "graceful_close_supported": True,
            "request_ms": 10.0,
            "per_target": [
                {"pid": 1011, "close_request_sent": True, "window_handle": 2011},
                {"pid": 1010, "close_request_sent": True, "window_handle": 2010},
            ],
        },
    )

    def fake_window_status(self):
        calls["window_status"] += 1
        if calls["window_status"] == 1:
            return {"focused_window": None, "windows": [first, second], "monitors": []}
        return {"focused_window": prompt, "windows": [second, prompt], "monitors": []}

    monkeypatch.setattr(SystemProbe, "window_status", fake_window_status)

    result = probe.app_control(action="close", app_name="Arduino IDE")

    assert result["success"] is False
    assert result["reason"] == "confirmation_required"
    assert result["close_result_state"] == "partial_confirmation_required"
    assert result["closed_verified_count"] == 1
    assert result["confirmation_required_count"] == 1
    assert result["partial_close"] is True
    assert [item["result_state"] for item in result["per_window_results"]] == [
        "confirmation_required",
        "closed_verified",
    ]


def test_close_failed_when_window_remains_after_timeout(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    target = _window(title="Untitled - Notepad", process_name="Notepad", path="C:/Windows/System32/notepad.exe")

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {"close_request_sent": True, "graceful_close_supported": True, "request_ms": 8.0},
    )
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {"focused_window": None, "windows": [target], "monitors": []},
    )

    result = probe.app_control(action="close", app_name="Notepad")

    assert result["success"] is False
    assert result["reason"] == "close_failed"
    assert result["close_result_state"] == "close_failed"
    assert result["force_close_offered"] is True
    assert result["force_close_requires_approval"] is True


def test_verification_uses_active_app_titles_when_window_enumeration_misses_target(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    target = _window(
        title="packaged-note.txt - Notepad",
        process_name="Notepad",
        path="C:/Program Files/WindowsApps/Microsoft.WindowsNotepad/Notepad.exe",
    )

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": [target]})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(SystemProbe, "window_status", lambda self: {"focused_window": None, "windows": [], "monitors": []})
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {"close_request_sent": True, "graceful_close_supported": True, "request_ms": 8.0},
    )

    result = probe.app_control(action="close", app_name="packaged-note.txt")

    assert result["success"] is False
    assert result["close_result_state"] == "close_failed"
    assert result["verification_observed"] == "target_still_visible"


def test_force_close_is_only_offered_after_failed_graceful_close(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    target = _window(title="Untitled - Notepad", process_name="Notepad", path="C:/Windows/System32/notepad.exe")

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {"close_request_sent": False, "graceful_close_supported": True, "reason": "send_message_failed", "request_ms": 3.0},
    )
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {"focused_window": None, "windows": [target], "monitors": []},
    )

    result = probe.app_control(action="close", app_name="Notepad")

    assert result["success"] is False
    assert result["close_result_state"] == "close_failed"
    assert result["force_close_offered"] is True
    assert result["force_close_requires_approval"] is True
    assert result["graceful_close_requested"] is False


def test_system_process_close_is_blocked(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    explorer = _window(
        title="File Explorer",
        process_name="explorer",
        pid=2020,
        handle=9090,
        path="C:/Windows/explorer.exe",
    )

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {"focused_window": None, "windows": [explorer], "monitors": []},
    )

    result = probe.app_control(action="close", app_name="File Explorer")

    assert result["success"] is False
    assert result["reason"] == "system_process_blocked"
    assert result["close_result_state"] == "close_unsupported"
    assert result["graceful_close_requested"] is False


def test_stormhelm_document_title_does_not_block_normal_app_close(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    calls = {"window_status": 0}
    target = _window(
        title="stormhelm-l65-close-smoke.txt - Notepad",
        process_name="Notepad",
        path="C:/Program Files/WindowsApps/Microsoft.WindowsNotepad/Notepad.exe",
    )

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {"close_request_sent": True, "graceful_close_supported": True, "request_ms": 6.0},
    )

    def fake_window_status(self):
        calls["window_status"] += 1
        if calls["window_status"] == 1:
            return {"focused_window": None, "windows": [target], "monitors": []}
        return {"focused_window": None, "windows": [], "monitors": []}

    monkeypatch.setattr(SystemProbe, "window_status", fake_window_status)

    result = probe.app_control(action="close", app_name="stormhelm-l65-close-smoke.txt")

    assert result["success"] is True
    assert result["close_result_state"] == "closed_verified"


def test_post_close_verification_ignores_generic_windows_path_matches(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    calls = {"window_status": 0}
    notepad = _window(
        title="Untitled - Notepad",
        process_name="Notepad",
        pid=6161,
        handle=1717,
        path="C:/Program Files/WindowsApps/Microsoft.WindowsNotepad/Notepad.exe",
    )
    settings = _window(
        title="Settings",
        process_name="SystemSettings",
        pid=7171,
        handle=2727,
        path="C:/Windows/ImmersiveControlPanel/SystemSettings.exe",
    )

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {"close_request_sent": True, "graceful_close_supported": True, "request_ms": 5.0},
    )

    def fake_window_status(self):
        calls["window_status"] += 1
        if calls["window_status"] == 1:
            return {"focused_window": None, "windows": [notepad], "monitors": []}
        return {"focused_window": None, "windows": [settings], "monitors": []}

    monkeypatch.setattr(SystemProbe, "window_status", fake_window_status)

    result = probe.app_control(action="close", app_name="Notepad")

    assert result["success"] is True
    assert result["close_result_state"] == "closed_verified"
    assert result["verification_observed"] == "window_and_process_absent"


def test_response_does_not_claim_closed_without_verification(temp_config) -> None:
    class FakeProbe:
        def app_control(self, *, action: str, app_name: str | None = None, app_path: str | None = None) -> dict[str, object]:
            return {
                "success": False,
                "action": action,
                "requested_name": app_name,
                "process_name": "Notepad",
                "window_title": "Untitled - Notepad",
                "close_result_state": "close_failed",
                "reason": "close_failed",
                "graceful_close_requested": True,
                "force_close_offered": True,
                "force_close_requires_approval": True,
            }

    result = AppControlTool().execute_sync(
        _tool_context(temp_config, FakeProbe()),
        {"action": "close", "app_name": "Notepad", "app_path": None},
    )

    assert result.success is False
    assert "closed" not in result.summary.lower()
    assert "succeeded" not in result.summary.lower()
    assert "force-close" in result.summary.lower()
