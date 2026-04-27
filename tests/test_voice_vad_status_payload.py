from __future__ import annotations

from stormhelm.ui.voice_surface import build_voice_ui_state


def test_voice_ui_payload_surfaces_vad_activity_without_semantic_claims() -> None:
    payload = build_voice_ui_state(
        {
            "voice": {
                "availability": {"available": True},
                "state": {"state": "capturing"},
                "capture": {
                    "enabled": True,
                    "available": True,
                    "provider": "mock",
                    "active_capture_id": "capture-1",
                    "active_capture_status": "recording",
                },
                "vad": {
                    "enabled": True,
                    "provider": "mock",
                    "provider_kind": "mock",
                    "available": True,
                    "active": True,
                    "active_capture_id": "capture-1",
                    "last_activity_event": {
                        "status": "speech_started",
                        "activity_event_id": "activity-1",
                    },
                    "semantic_completion_claimed": False,
                    "command_authority": False,
                    "realtime_vad": False,
                },
            }
        }
    )

    assert payload["vad_enabled"] is True
    assert payload["vad_active"] is True
    assert payload["vad_last_activity_status"] == "speech_started"
    assert payload["truth_flags"]["vad_semantic_completion_claimed"] is False
    assert payload["truth_flags"]["vad_command_authority"] is False
    assert payload["truth_flags"]["realtime_vad"] is False
    rendered = str(payload).lower()
    assert "i understood" not in rendered
    assert "command complete" not in rendered
    assert "semantic turn complete" not in rendered
    assert "realtime active" not in rendered
