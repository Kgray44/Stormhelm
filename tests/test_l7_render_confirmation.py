from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.latency import UiEventRenderLatencySummary
from stormhelm.ui.latency import UiRenderConfirmation


def _route_event(
    cursor: int,
    *,
    request_id: str = "req-l71",
    stage: str = "route_selected",
) -> dict[str, object]:
    return {
        "cursor": cursor,
        "event_id": cursor,
        "event_family": "route",
        "event_type": "route.selected",
        "severity": "info",
        "subsystem": "planner",
        "visibility_scope": "ghost_hint",
        "message": "Route selected.",
        "ui_stream_timing": {
            "frame_received_monotonic_ms": 1000.0 + cursor,
            "event_parsed_monotonic_ms": 1001.0 + cursor,
        },
        "payload": {
            "request_id": request_id,
            "route_family": "software_control",
            "subject": "Calculator",
            "stage": stage,
            "summary": "Software route selected.",
        },
    }


def test_ui_render_confirmation_serializes_safely_and_keeps_model_only_honest() -> None:
    confirmation = UiRenderConfirmation(
        confirmation_id="confirm-1",
        request_id="request-1",
        event_id="event-1",
        event_type="route.selected",
        surface="ghost_primary",
        model_revision=3,
        qml_component_id="ghostPrimaryCommandCard",
        visible_state_key="route_label",
        visible_state_value="sk-test-secret raw_audio private payload",
        rendered_at_monotonic_ms=123.4,
        rendered_at_wall_time="2026-04-30T12:00:00Z",
        render_confirmed=True,
        render_confirmation_status="confirmed",
        confirmation_source="qml_component",
        reason="authorization bearer should not leak",
    )

    payload = confirmation.to_dict()
    encoded = json.dumps(payload)

    assert payload["render_confirmed"] is True
    assert payload["render_confirmation_status"] == "confirmed"
    assert "sk-test-secret" not in encoded
    assert "raw_audio" not in encoded
    assert "authorization" not in encoded.lower()

    hidden = UiRenderConfirmation(
        confirmation_id="confirm-hidden",
        surface="deck_event_spine",
        model_revision=1,
        visible_state_key="connection_state",
        rendered_at_monotonic_ms=140.0,
        rendered_at_wall_time="2026-04-30T12:00:01Z",
        render_confirmed=False,
        render_confirmation_status="hidden",
        confirmation_source="qml_test_hook",
        reason="surface collapsed",
    ).to_dict()

    assert hidden["render_confirmed"] is False
    assert hidden["render_confirmation_status"] == "hidden"

    summary = UiEventRenderLatencySummary(
        request_id="request-1",
        event_id="event-1",
        event_type="route.selected",
        surface="ghost_primary",
        event_received_at_monotonic_ms=100.0,
        event_parsed_at_monotonic_ms=101.0,
        bridge_update_at_monotonic_ms=110.0,
        model_notify_at_monotonic_ms=115.0,
        render_confirmed_at_monotonic_ms=None,
        received_to_bridge_update_ms=10.0,
        bridge_update_to_model_notify_ms=5.0,
        model_notify_to_render_confirmed_ms=None,
        received_to_render_confirmed_ms=None,
        render_confirmation_status="model_only",
        render_confirmation_source="bridge_probe",
        used_polling_fallback=False,
        used_snapshot_reconciliation=False,
        gap_recovered=False,
        duplicate_ignored_count=0,
        out_of_order_ignored_count=0,
        render_confirmed="unknown",
    ).to_dict()

    assert summary["render_confirmation_status"] == "model_only"
    assert summary["render_confirmed"] == "unknown"
    assert summary["received_to_render_confirmed_ms"] is None


def test_bridge_records_render_confirmation_and_updates_matching_summary(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_stream_event(_route_event(1201))

    revision = bridge.renderSurfaceRevision("ghost_primary")
    assert revision > 0
    assert any(
        summary["surface"] == "ghost_primary"
        and summary["render_confirmation_status"] in {"unknown", "not_measured"}
        for summary in bridge.uiEventRenderLatencySummaries
    )

    bridge.confirmRenderVisible(
        {
            "surface": "ghost_primary",
            "model_revision": revision,
            "event_id": "1201",
            "visible_state_key": "routeLabel",
            "visible_state_value": "Software Control",
            "qml_component_id": "ghostPrimaryCommandCard",
            "confirmation_source": "qml_test_hook",
            "visible": True,
        }
    )

    confirmation = bridge.uiRenderConfirmations[-1]
    assert confirmation["surface"] == "ghost_primary"
    assert confirmation["event_id"] == "1201"
    assert confirmation["request_id"] == "req-l71"
    assert confirmation["render_confirmation_status"] == "confirmed"
    assert confirmation["confirmation_source"] == "qml_test_hook"

    summary = next(
        summary
        for summary in reversed(bridge.uiEventRenderLatencySummaries)
        if summary["surface"] == "ghost_primary" and summary["event_id"] == "1201"
    )
    assert summary["render_confirmation_status"] == "confirmed"
    assert summary["render_confirmation_source"] == "qml_test_hook"
    assert summary["received_to_render_confirmed_ms"] >= summary["received_to_bridge_update_ms"]
    assert summary["model_notify_to_render_confirmed_ms"] >= 0


def test_bridge_ignores_stale_and_dedupes_duplicate_render_confirmations(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_stream_event(_route_event(1210, stage="planning"))
    old_revision = bridge.renderSurfaceRevision("ghost_primary")
    bridge.apply_stream_event(_route_event(1211, stage="running"))
    new_revision = bridge.renderSurfaceRevision("ghost_primary")

    bridge.confirmRenderVisible(
        {
            "confirmation_id": "new-confirm",
            "surface": "ghost_primary",
            "model_revision": new_revision,
            "event_id": "1211",
            "visible_state_key": "resultState",
            "visible_state_value": "running",
            "confirmation_source": "qml_test_hook",
            "visible": True,
        }
    )
    bridge.confirmRenderVisible(
        {
            "confirmation_id": "new-confirm",
            "surface": "ghost_primary",
            "model_revision": new_revision,
            "event_id": "1211",
            "visible_state_key": "resultState",
            "visible_state_value": "running",
            "confirmation_source": "qml_test_hook",
            "visible": True,
        }
    )
    bridge.confirmRenderVisible(
        {
            "confirmation_id": "old-confirm",
            "surface": "ghost_primary",
            "model_revision": old_revision,
            "event_id": "1210",
            "visible_state_key": "resultState",
            "visible_state_value": "planning",
            "confirmation_source": "qml_test_hook",
            "visible": True,
        }
    )

    matching = [
        item
        for item in bridge.uiRenderConfirmations
        if item["confirmation_id"] == "new-confirm"
    ]
    assert len(matching) == 1
    assert bridge.uiRenderConfirmations[-1]["confirmation_id"] == "old-confirm"
    assert bridge.uiRenderConfirmations[-1]["stale"] is True
    assert bridge.uiRenderConfirmations[-1]["render_confirmation_status"] == "stale"

    latest_summary = next(
        summary
        for summary in reversed(bridge.uiEventRenderLatencySummaries)
        if summary["surface"] == "ghost_primary" and summary["event_id"] == "1211"
    )
    assert latest_summary["render_confirmation_status"] == "confirmed"


def test_prompt_voice_and_deck_render_confirmations_bind_to_visible_surfaces(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_stream_event(
        {
            "cursor": 1220,
            "event_id": 1220,
            "event_family": "approval",
            "event_type": "approval_required",
            "severity": "warning",
            "subsystem": "trust",
            "visibility_scope": "operator_blocking",
            "message": "Approval required.",
            "payload": {
                "request_id": "req-approval-l71",
                "approval_id": "approval-l71",
                "route_family": "trust_approvals",
                "subject": "Discord dispatch",
                "operator_message": "Approval needed.",
            },
        }
    )
    bridge.confirmRenderVisible(
        {
            "surface": "approval_prompt",
            "model_revision": bridge.renderSurfaceRevision("approval_prompt"),
            "event_id": "1220",
            "visible_state_key": "actionable",
            "visible_state_value": "true",
            "confirmation_source": "qml_test_hook",
            "visible": True,
        }
    )
    assert bridge.uiRenderConfirmations[-1]["surface"] == "approval_prompt"
    assert bridge.uiRenderConfirmations[-1]["render_confirmation_status"] == "confirmed"

    bridge.apply_stream_event(
        {
            "cursor": 1221,
            "event_id": 1221,
            "event_family": "voice",
            "event_type": "voice.synthesis_started",
            "severity": "info",
            "subsystem": "voice",
            "visibility_scope": "deck_context",
            "message": "TTS started.",
            "payload": {
                "turn_id": "voice-turn-l71",
                "speech_request_id": "speech-l71",
                "status": "started",
                "raw_audio_present": False,
            },
        }
    )
    bridge.confirmRenderVisible(
        {
            "surface": "voice_core",
            "model_revision": bridge.renderSurfaceRevision("voice_core"),
            "event_id": "1221",
            "visible_state_key": "voice_current_phase",
            "visible_state_value": "synthesizing",
            "confirmation_source": "qml_test_hook",
            "visible": True,
        }
    )
    assert bridge.voiceState["voice_current_phase"] == "synthesizing"
    assert bridge.voiceState.get("active_playback_status") is None
    assert bridge.uiRenderConfirmations[-1]["surface"] == "voice_core"

    bridge.apply_stream_state({"source": "client", "phase": "reconnecting", "cursor": 1221})
    bridge.confirmRenderVisible(
        {
            "surface": "deck_event_spine",
            "model_revision": bridge.renderSurfaceRevision("deck_event_spine"),
            "visible_state_key": "ui_connection_state",
            "visible_state_value": "reconnecting",
            "confirmation_source": "qml_test_hook",
            "visible": True,
        }
    )
    assert bridge.uiRenderConfirmations[-1]["surface"] == "deck_event_spine"
    assert bridge.uiRenderConfirmations[-1]["render_confirmation_status"] == "confirmed"


def test_l7_render_smoke_script_writes_headless_report(tmp_path: Path) -> None:
    output = tmp_path / "l7_render_smoke.json"

    subprocess.run(
        [
            sys.executable,
            "scripts/run_l7_render_smoke.py",
            "--samples",
            "3",
            "--mode",
            "headless",
            "--output",
            str(output),
        ],
        cwd=Path.cwd(),
        check=True,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["phase"] == "L7.1"
    assert report["mode"] == "headless"
    assert report["samples"] == 3
    assert "ghost_primary" in report["surfaces"]
    assert report["surfaces"]["ghost_primary"]["received_to_bridge_p95_ms"] is not None
    assert report["surfaces"]["ghost_primary"]["render_status"] == "not_measured"
    assert report["unknown_or_not_measured_count"] >= 1
