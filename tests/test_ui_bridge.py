from __future__ import annotations

import os

from PySide6 import QtGui, QtTest, QtWidgets

from stormhelm.ui.bridge import UiBridge


def _ensure_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_ui_bridge_defaults_to_ghost_mode_and_tracks_rail_state(temp_config) -> None:
    bridge = UiBridge(temp_config)

    assert bridge.mode_value == "ghost"
    assert bridge.assistant_state_value == "idle"
    assert bridge.active_module_key == "chartroom"
    assert any(item["key"] == "chartroom" and item["active"] for item in bridge.command_rail_items)

    bridge.setMode("deck")
    bridge.activateModule("signals")

    assert bridge.mode_value == "deck"
    assert bridge.active_module_key == "signals"
    assert any(item["key"] == "signals" and item["active"] for item in bridge.command_rail_items)


def test_ui_bridge_suppresses_high_rate_voice_stream_collection_rebuilds(temp_config) -> None:
    bridge = UiBridge(temp_config)
    collection_emits = 0
    voice_emits = 0

    def mark_collection() -> None:
        nonlocal collection_emits
        collection_emits += 1

    def mark_voice() -> None:
        nonlocal voice_emits
        voice_emits += 1

    bridge.collectionsChanged.connect(mark_collection)
    bridge.voiceStateChanged.connect(mark_voice)

    for index in range(25):
        bridge.apply_stream_event(
            {
                "cursor": index + 1,
                "event_type": "voice.tts_stream_chunk",
                "visibility_scope": "watch_surface",
                "severity": "info",
                "message": "Voice chunk envelope updated.",
                "payload": {
                    "chunk_index": index,
                    "payload_keys": ["envelope"],
                },
            }
        )

    assert collection_emits == 0
    assert voice_emits == 0


def test_ui_bridge_applies_stream_chunk_voice_envelope_without_collection_rebuild(temp_config) -> None:
    bridge = UiBridge(temp_config)
    collection_emits = 0
    voice_emits = 0

    def mark_collection() -> None:
        nonlocal collection_emits
        collection_emits += 1

    def mark_voice() -> None:
        nonlocal voice_emits
        voice_emits += 1

    bridge.collectionsChanged.connect(mark_collection)
    bridge.voiceStateChanged.connect(mark_voice)

    bridge.apply_stream_event(
        {
            "cursor": 101,
            "event_type": "voice.tts_stream_chunk",
            "visibility_scope": "watch_surface",
            "severity": "info",
            "message": "Voice chunk envelope updated.",
            "payload": {
                "metadata": {
                    "voice": {
                        "enabled": True,
                        "voice_output_envelope": {
                            "source": "playback_output_envelope",
                            "rms_level": 0.44,
                            "peak_level": 0.78,
                            "smoothed_level": 0.63,
                            "speech_energy": 0.7,
                            "visual_drive_level": 0.81,
                            "visual_drive_peak": 0.9,
                            "center_blob_drive": 0.73,
                            "center_blob_scale_drive": 0.73,
                            "center_blob_scale": 1.2336,
                            "outer_speaking_motion": 0.82,
                            "visual_gain": 1.85,
                            "raw_audio_present": False,
                        },
                        "playback": {
                            "active_playback_status": "playing",
                            "live_playback_status": "playing",
                            "first_audio_started": True,
                        },
                    }
                }
            },
        }
    )

    assert collection_emits == 0
    assert voice_emits == 1
    assert bridge.voiceState["voice_anchor_state"] == "speaking"
    assert bridge.voiceState["voice_smoothed_output_level"] == 0.63
    assert bridge.voiceState["voice_visual_drive_level"] == 0.81
    assert bridge.voiceState["voice_visual_drive_peak"] == 0.9
    assert bridge.voiceState["voice_center_blob_drive"] == 0.73
    assert bridge.voiceState["voice_center_blob_scale_drive"] == 0.73
    assert bridge.voiceState["voice_center_blob_scale"] == 1.2336
    assert bridge.voiceState["voice_outer_speaking_motion"] == 0.82
    assert bridge.voiceState["audioDriveLevel"] == 0.73
    assert bridge.voiceState["voice_audio_reactive_source"] == "playback_output_envelope"


def test_ui_bridge_visualizer_updates_use_voice_hot_path_only(temp_config) -> None:
    bridge = UiBridge(temp_config)
    collection_emits = 0
    voice_emits = 0

    def mark_collection() -> None:
        nonlocal collection_emits
        collection_emits += 1

    def mark_voice() -> None:
        nonlocal voice_emits
        voice_emits += 1

    bridge.collectionsChanged.connect(mark_collection)
    bridge.voiceStateChanged.connect(mark_voice)

    for index, drive in enumerate([0.0, 0.22, 0.74, 0.18, 0.0], start=1):
        bridge.apply_stream_event(
            {
                "cursor": 200 + index,
                "event_type": "voice.visualizer_update",
                "visibility_scope": "watch_surface",
                "severity": "debug",
                "message": "Voice visualizer updated.",
                "payload": {
                    "metadata": {
                        "visualizer_only": True,
                        "voice": {
                            "enabled": True,
                            "voice_anchor": {
                                "state": "speaking",
                                "speaking_visual_active": True,
                                "smoothed_output_level": drive,
                                "visual_drive_level": drive,
                                "visual_drive_peak": min(1.0, drive + 0.08),
                                "center_blob_drive": drive,
                                "center_blob_scale_drive": drive,
                                "center_blob_scale": 1.0 + drive * 0.32,
                                "outer_speaking_motion": 0.12,
                                "audio_reactive_available": True,
                                "audio_reactive_source": "playback_output_envelope",
                            },
                            "voice_anchor_state": "speaking",
                            "speaking_visual_active": True,
                            "voice_smoothed_output_level": drive,
                            "voice_visual_drive_level": drive,
                            "voice_visual_drive_peak": min(1.0, drive + 0.08),
                            "voice_center_blob_drive": drive,
                            "voice_center_blob_scale_drive": drive,
                            "voice_center_blob_scale": 1.0 + drive * 0.32,
                            "voice_outer_speaking_motion": 0.12,
                            "audioDriveLevel": drive,
                            "voice_audio_reactive_available": True,
                            "voice_audio_reactive_source": "playback_output_envelope",
                            "voice_visualizer": {
                                "visualizer_updates_received": index,
                                "visualizer_updates_coalesced": 2,
                                "visualizer_updates_dropped": 0,
                                "raw_audio_present": False,
                            },
                            "raw_audio_present": False,
                        },
                    }
                },
            }
        )

    assert collection_emits == 0
    assert voice_emits == 5
    assert bridge.voiceState["voice_center_blob_scale_drive"] == 0.0
    assert bridge.voiceState["visualizer_updates_received"] == 5
    assert bridge.voiceState["visualizer_updates_coalesced"] == 2
    assert bridge.voiceState["visualizer_updates_dropped"] == 0
    assert bridge.voiceState["visualizer_frames_received_by_bridge"] == 5
    assert bridge.voiceState["bridge_receive_rate_hz"] > 0
    assert bridge.voiceState["max_bridge_frame_gap_ms"] >= 0
    assert bridge.voiceState["status_polling_used_for_visualizer"] is False
    assert bridge.voiceState["collection_rebuilds_during_visualizer_updates"] == 0
    assert bridge.voiceState["bridge_collection_rebuilds_during_speech"] == 0
    assert bridge.voiceState["qml_anchor_updates_during_speech"] == 5


def test_ui_bridge_coalesces_visible_stream_collection_rebuilds(temp_config) -> None:
    _ensure_app()
    bridge = UiBridge(temp_config)
    collection_emits = 0

    def mark_collection() -> None:
        nonlocal collection_emits
        collection_emits += 1

    bridge.collectionsChanged.connect(mark_collection)

    for index in range(25):
        bridge.apply_stream_event(
            {
                "cursor": index + 1,
                "event_type": "runtime.progress",
                "visibility_scope": "watch_surface",
                "severity": "info",
                "message": f"Progress {index}",
                "payload": {"index": index},
            }
        )

    assert collection_emits == 0
    QtTest.QTest.qWait(150)
    assert collection_emits == 1


def test_ui_bridge_l7_route_event_updates_ghost_without_polling_and_marks_latency(temp_config) -> None:
    bridge = UiBridge(temp_config)
    collection_emits = 0
    status_emits = 0

    def mark_collection() -> None:
        nonlocal collection_emits
        collection_emits += 1

    def mark_status() -> None:
        nonlocal status_emits
        status_emits += 1

    bridge.collectionsChanged.connect(mark_collection)
    bridge.statusChanged.connect(mark_status)

    bridge.apply_stream_event(
        {
            "cursor": 501,
            "event_id": 501,
            "event_family": "route",
            "event_type": "route.selected",
            "severity": "info",
            "subsystem": "planner",
            "visibility_scope": "ghost_hint",
            "message": "Route selected.",
            "payload": {
                "request_id": "req-l7-route",
                "route_family": "software_control",
                "result_state": "planning",
                "summary": "Preparing a safe software route.",
            },
            "ui_stream_timing": {
                "frame_received_monotonic_ms": 1000.0,
                "event_parsed_monotonic_ms": 1001.0,
            },
        }
    )

    assert bridge.statusLine == "Route selected."
    assert bridge.ghostPrimaryCard["routeLabel"] == "Software Control"
    assert bridge.requestComposer["chips"][0]["value"] == "Software Control"
    assert collection_emits == 1
    assert status_emits >= 1

    marks = bridge.uiLatencyMarks
    mark_names = {mark["mark_name"] for mark in marks}
    assert "event_stream_frame_received" in mark_names
    assert "bridge_event_parsed" in mark_names
    assert "bridge_state_updated" in mark_names
    assert "qml_model_changed" in mark_names
    assert "ghost_state_updated" in mark_names
    assert all("secret" not in str(mark).lower() for mark in marks)

    summary = bridge.uiEventRenderLatencySummaries[-1]
    assert summary["event_id"] == "501"
    assert summary["received_to_bridge_update_ms"] >= 0
    assert summary["received_to_render_visible_ms"] is None
    assert summary["render_confirmed"] == "unknown"
    assert summary["used_polling_fallback"] is False


def test_ui_bridge_l7_http_chat_marks_are_sanitized_and_request_bound(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_chat_result(
        {
            "ui_http_timing": {
                "user_submitted_message_monotonic_ms": 100.0,
                "http_send_started_monotonic_ms": 101.0,
                "http_response_received_monotonic_ms": 145.0,
            },
            "user_message": {
                "message_id": "user-http",
                "role": "user",
                "content": "private text should not appear in marks",
            },
            "assistant_message": {
                "message_id": "assistant-http",
                "role": "assistant",
                "content": "Ready.",
                "metadata": {"latency_trace": {"request_id": "req-http-l7"}},
            },
        }
    )

    marks = bridge.uiLatencyMarks
    mark_names = {mark["mark_name"] for mark in marks}
    assert {"user_submitted_message", "ui_http_send_started", "ui_http_response_received"} <= mark_names
    assert {mark["request_id"] for mark in marks} == {"req-http-l7"}
    assert "private text" not in str(marks).lower()


def test_ui_bridge_l7_clarification_and_approval_prompts_are_push_first_and_expire(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_stream_event(
        {
            "cursor": 610,
            "event_id": 610,
            "event_family": "route",
            "event_type": "clarification_required",
            "severity": "info",
            "subsystem": "planner",
            "visibility_scope": "operator_blocking",
            "message": "Clarification required.",
            "payload": {
                "request_id": "req-l7-prompt",
                "route_family": "discord_relay",
                "subject": "relay payload",
                "clarification_choices": ["selected text", "current page"],
                "summary": "Choose what should be relayed.",
            },
        }
    )

    assert bridge.statusLine == "Clarification required."
    assert bridge.ghostPrimaryCard["resultState"] == "unresolved"
    assert [choice["sendText"] for choice in bridge.requestComposer["clarificationChoices"]] == [
        "selected text",
        "current page",
    ]

    bridge.apply_stream_event(
        {
            "cursor": 611,
            "event_id": 611,
            "event_family": "approval",
            "event_type": "approval_required",
            "severity": "warning",
            "subsystem": "trust",
            "visibility_scope": "operator_blocking",
            "message": "Approval required.",
            "payload": {
                "request_id": "req-l7-prompt",
                "approval_id": "approval-l7",
                "route_family": "trust_approvals",
                "subject": "Discord dispatch",
                "available_scopes": ["once", "task"],
                "operator_message": "Dispatch needs operator approval.",
            },
        }
    )

    assert bridge.statusLine == "Approval required."
    assert bridge.ghostPrimaryCard["resultState"] == "awaiting_approval"
    assert any(action["category"] == "approve" for action in bridge.ghostActionStrip)

    bridge.apply_stream_event(
        {
            "cursor": 612,
            "event_id": 612,
            "event_family": "approval",
            "event_type": "approval.consumed",
            "severity": "info",
            "subsystem": "trust",
            "visibility_scope": "deck_context",
            "message": "Approval consumed.",
            "payload": {
                "request_id": "req-l7-prompt",
                "approval_id": "approval-l7",
                "route_family": "trust_approvals",
                "approval_state": "consumed",
                "operator_message": "Approval was consumed by the backend.",
            },
        }
    )

    assert not any(action["category"] == "approve" for action in bridge.ghostActionStrip)
    assert bridge.routeInspector["provenance"][0]["label"] == "Trust"


def test_ui_bridge_l7_job_and_verification_events_update_models_without_claiming_false_success(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_stream_event(
        {
            "cursor": 701,
            "event_id": 701,
            "event_family": "job",
            "event_type": "job.progress",
            "severity": "info",
            "subsystem": "job_manager",
            "visibility_scope": "deck_context",
            "message": "Verification queued.",
            "payload": {
                "request_id": "req-l7-verify",
                "job_id": "job-l7",
                "task_id": "task-l7",
                "tool_name": "software_control",
                "status": "running",
                "progress_summary": "Verification running.",
            },
        }
    )

    watch_module = next(module for module in bridge.deckModules if module["key"] == "watch")
    watch_entries = watch_module["entries"]
    assert watch_entries[0]["secondary"] == "Running"
    assert watch_entries[0]["secondary"] != "Completed"

    bridge.apply_stream_event(
        {
            "cursor": 702,
            "event_id": 702,
            "event_family": "verification",
            "event_type": "verification.result",
            "severity": "info",
            "subsystem": "verification",
            "visibility_scope": "deck_context",
            "message": "Verification returned without evidence.",
            "payload": {
                "request_id": "req-l7-verify",
                "route_family": "software_control",
                "verification_state": "not_verified",
                "result_state": "completed",
                "verification_evidence_count": 0,
            },
        }
    )

    assert bridge.ghostPrimaryCard["resultState"] != "verified"

    bridge.apply_stream_event(
        {
            "cursor": 703,
            "event_id": 703,
            "event_family": "verification",
            "event_type": "verification.result",
            "severity": "info",
            "subsystem": "verification",
            "visibility_scope": "deck_context",
            "message": "Verification complete.",
            "payload": {
                "request_id": "req-l7-verify",
                "route_family": "software_control",
                "verification_state": "verified",
                "result_state": "verified",
                "verification_evidence_count": 2,
                "evidence": ["installed binary found"],
            },
        }
    )

    assert bridge.ghostPrimaryCard["resultState"] == "verified"
    assert bridge.routeInspector["statusLabel"] == "Verified"


def test_ui_bridge_l7_voice_stage_events_remain_distinct_and_truthful(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_stream_event(
        {
            "cursor": 801,
            "event_id": 801,
            "event_family": "voice",
            "event_type": "voice.synthesis_started",
            "severity": "info",
            "subsystem": "voice",
            "visibility_scope": "deck_context",
            "message": "TTS started.",
            "payload": {
                "turn_id": "voice-turn-l7",
                "speech_request_id": "speech-l7",
                "status": "started",
                "raw_audio_present": False,
            },
        }
    )

    assert bridge.voiceState["voice_current_phase"] == "synthesizing"
    assert bridge.voiceState["last_synthesis_status"] == "started"
    assert bridge.voiceState.get("active_playback_status") is None
    assert bridge.assistantState != "speaking"

    bridge.apply_stream_event(
        {
            "cursor": 802,
            "event_id": 802,
            "event_family": "voice",
            "event_type": "voice.tts_first_chunk_received",
            "severity": "info",
            "subsystem": "voice",
            "visibility_scope": "deck_context",
            "message": "First TTS chunk received.",
            "payload": {
                "turn_id": "voice-turn-l7",
                "synthesis_id": "synth-l7",
                "status": "first_chunk",
                "raw_audio_present": False,
            },
        }
    )

    assert bridge.voiceState["last_synthesis_status"] == "first_chunk"
    assert bridge.voiceState.get("active_playback_status") is None
    assert bridge.assistantState != "speaking"

    bridge.apply_stream_event(
        {
            "cursor": 803,
            "event_id": 803,
            "event_family": "voice",
            "event_type": "voice.playback_started",
            "severity": "info",
            "subsystem": "voice",
            "visibility_scope": "deck_context",
            "message": "Playback started.",
            "payload": {
                "turn_id": "voice-turn-l7",
                "playback_id": "playback-l7",
                "status": "started",
                "raw_audio_present": False,
                "user_heard_claimed": False,
            },
        }
    )

    assert bridge.voiceState["voice_current_phase"] == "playback_active"
    assert bridge.voiceState["active_playback_status"] == "started"
    assert bridge.voiceState["user_heard_claimed"] is False
    assert bridge.assistantState == "speaking"


def test_ui_bridge_l7_duplicate_and_out_of_order_events_do_not_downgrade_state(temp_config) -> None:
    bridge = UiBridge(temp_config)

    verified_event = {
        "cursor": 901,
        "event_id": 901,
        "event_family": "verification",
        "event_type": "verification.result",
        "severity": "info",
        "subsystem": "verification",
        "visibility_scope": "deck_context",
        "message": "Verified.",
        "payload": {
            "request_id": "req-l7-order",
            "route_family": "software_control",
            "verification_state": "verified",
            "result_state": "verified",
            "verification_evidence_count": 1,
            "evidence": ["post-check succeeded"],
        },
    }
    bridge.apply_stream_event(verified_event)
    bridge.apply_stream_event(verified_event)
    bridge.apply_stream_event(
        {
            "cursor": 900,
            "event_id": 900,
            "event_family": "route",
            "event_type": "route.selected",
            "severity": "info",
            "subsystem": "planner",
            "visibility_scope": "ghost_hint",
            "message": "Route selected.",
            "payload": {
                "request_id": "req-l7-order",
                "route_family": "software_control",
                "result_state": "planning",
            },
        }
    )

    assert bridge.ghostPrimaryCard["resultState"] == "verified"
    diagnostics = bridge.eventStreamConnectionState
    assert diagnostics["duplicate_ignored_count"] == 1
    assert diagnostics["out_of_order_ignored_count"] == 1


def test_ui_bridge_applies_snapshot_to_context_cards_and_modules(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "health": {
                "status": "ok",
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "runtime_mode": "source",
            },
            "status": {
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "environment": temp_config.environment,
                "runtime_mode": "source",
                "max_workers": temp_config.concurrency.max_workers,
                "recent_jobs": 1,
                "data_dir": str(temp_config.storage.data_dir),
                "install_root": str(temp_config.runtime.install_root),
                "system_state": {
                    "machine": {"machine_name": "STORMHELM-RIG", "system": "Windows", "release": "11", "timezone": "EDT"},
                    "power": {"available": True, "battery_percent": 86, "ac_line_status": "online"},
                    "resources": {
                        "cpu": {"name": "AMD Ryzen", "cores": 8, "logical_processors": 16},
                        "memory": {"total_bytes": 34359738368, "used_bytes": 17179869184, "free_bytes": 17179869184},
                        "gpu": [{"name": "NVIDIA RTX", "driver_version": "555.10"}],
                    },
                    "storage": {"drives": [{"drive": "C:\\", "total_bytes": 1000, "free_bytes": 400, "used_bytes": 600}]},
                    "network": {"hostname": "stormhelm", "interfaces": [{"interface_alias": "Wi-Fi", "ipv4": ["192.168.1.14"]}]},
                },
                "provider_state": {"enabled": True, "configured": True, "planner_model": "gpt-5.4-mini", "reasoning_model": "gpt-5.4"},
                "tool_state": {"enabled_count": 8, "enabled_tools": ["machine_status", "power_status", "storage_status"]},
                "watch_state": {"active_jobs": 0, "queued_jobs": 0, "recent_failures": 0, "completed_recently": 1},
            },
            "history": [
                {
                    "message_id": "1",
                    "role": "assistant",
                    "content": "Bearing acquired.",
                    "created_at": "2026-04-18T12:00:00Z",
                }
            ],
            "jobs": [
                {
                    "job_id": "job-1",
                    "tool_name": "echo",
                    "status": "completed",
                    "created_at": "2026-04-18T12:00:01Z",
                    "finished_at": "2026-04-18T12:00:02Z",
                    "result": {"summary": "Echoed test payload."},
                }
            ],
            "events": [
                {
                    "event_id": 7,
                    "level": "INFO",
                    "source": "core",
                    "message": "Stormhelm core started.",
                    "created_at": "2026-04-18T12:00:00Z",
                }
            ],
            "notes": [
                {
                    "note_id": "note-1",
                    "title": "Bearing",
                    "content": "Marked safe harbor.",
                    "created_at": "2026-04-18T12:01:00Z",
                }
            ],
            "settings": {
                "safety": {"allowed_read_dirs": [str(temp_config.project_root)]},
            },
        }
    )

    assert bridge.connection_state == "connected"
    assert bridge.ghost_messages[0]["content"] == "Bearing acquired."
    assert any(card["title"] == "Echo" for card in bridge.context_cards)

    modules = {module["key"]: module for module in bridge.deck_modules}
    assert modules["logbook"]["kind"] == "notes"
    assert modules["logbook"]["entries"][0]["primary"] == "Bearing"
    assert modules["watch"]["kind"] == "jobs"
    assert bridge.workspaceCanvas["columns"][0]["title"] == "Active Thread"


def test_ui_bridge_applies_snapshot_active_workspace_restore_on_cold_start(temp_config) -> None:
    bridge = UiBridge(temp_config)
    active_workspace = {
        "workspace": {
            "workspaceId": "ws-research",
            "name": "Research Workspace",
            "topic": "research",
            "summary": "Hold active references and findings together.",
        },
        "opened_items": [
            {
                "itemId": "page-1",
                "kind": "browser",
                "viewer": "browser",
                "title": "OpenAI Docs",
                "url": "https://platform.openai.com/docs",
                "module": "browser",
                "section": "open-pages",
            },
            {
                "itemId": "file-1",
                "kind": "markdown",
                "viewer": "markdown",
                "title": "notes.md",
                "path": "C:/Stormhelm/notes.md",
                "module": "files",
                "section": "opened-items",
            },
        ],
        "active_item": {
            "itemId": "page-1",
            "kind": "browser",
            "viewer": "browser",
            "title": "OpenAI Docs",
            "url": "https://platform.openai.com/docs",
            "module": "browser",
            "section": "open-pages",
        },
        "action": {
            "type": "workspace_restore",
            "module": "browser",
            "section": "open-pages",
            "workspace": {
                "workspaceId": "ws-research",
                "name": "Research Workspace",
                "topic": "research",
                "summary": "Hold active references and findings together.",
            },
            "items": [
                {
                    "itemId": "page-1",
                    "kind": "browser",
                    "viewer": "browser",
                    "title": "OpenAI Docs",
                    "url": "https://platform.openai.com/docs",
                    "module": "browser",
                    "section": "open-pages",
                },
                {
                    "itemId": "file-1",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "notes.md",
                    "path": "C:/Stormhelm/notes.md",
                    "module": "files",
                    "section": "opened-items",
                },
            ],
            "active_item_id": "page-1",
        },
    }

    bridge.apply_snapshot({"active_workspace": active_workspace})

    assert bridge.mode_value == "deck"
    assert bridge.active_module_key == "browser"
    assert bridge.workspaceCanvas["title"] == "Research Workspace"
    assert bridge.activeOpenedItem["itemId"] == "page-1"
    assert bridge.workspace_context_payload()["workspace"]["workspaceId"] == "ws-research"


def test_ui_bridge_surfaces_active_task_in_ghost_and_command_deck(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "active_task": {
                "taskId": "task-1",
                "title": "Package the portable build",
                "state": "paused",
                "whereLeftOff": "Stormhelm last completed Package and had not yet started Verify.",
                "latestSummary": "Portable package created.",
                "ghostSummary": {
                    "title": "Package the portable build",
                    "subtitle": "Verify",
                    "body": "Stormhelm has enough durable state to resume honestly.",
                },
                "commandDeck": {
                    "groups": [
                        {
                            "title": "Next Bearings",
                            "entries": [
                                {"title": "Verify", "status": "ready", "detail": "Confirm the portable output."}
                            ],
                        },
                        {
                            "title": "In Flight",
                            "entries": [
                                {"title": "No active execution", "status": "steady", "detail": "No task step is currently running."}
                            ],
                        },
                        {
                            "title": "Attention",
                            "entries": [
                                {"title": "No open blockers", "status": "steady", "detail": "Task continuity is clear."}
                            ],
                        },
                    ]
                },
            }
        }
    )

    assert bridge.context_cards[0]["title"] == "Package the portable build"
    assert "resume honestly" in bridge.context_cards[0]["body"].lower()

    bridge.setMode("deck")
    bridge.activateModule("chartroom")
    bridge.activateWorkspaceSection("tasks")

    assert bridge.workspaceCanvas["taskGroups"][0]["title"] == "Next Bearings"
    assert bridge.workspaceCanvas["taskGroups"][0]["entries"][0]["title"] == "Verify"


def test_ui_bridge_systems_uses_machine_runtime_state_slice(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "environment": temp_config.environment,
                "runtime_mode": "source",
                "max_workers": temp_config.concurrency.max_workers,
                "system_state": {
                    "machine": {
                        "machine_name": "STORMHELM-RIG",
                        "system": "Windows",
                        "release": "11",
                        "timezone": "EDT",
                        "local_time": "2026-04-19T15:04:00-04:00",
                    },
                    "power": {"available": True, "battery_percent": 73, "ac_line_status": "online", "seconds_remaining": 7200},
                    "resources": {
                        "cpu": {
                            "name": "AMD Ryzen",
                            "cores": 8,
                            "logical_processors": 16,
                            "package_temperature_c": 72.0,
                            "effective_clock_mhz": 4380,
                            "utilization_percent": 42.0,
                        },
                        "memory": {"total_bytes": 34359738368, "used_bytes": 21474836480, "free_bytes": 12884901888},
                        "gpu": [
                            {
                                "name": "NVIDIA RTX",
                                "driver_version": "555.10",
                                "temperature_c": 66.0,
                                "utilization_percent": 58.0,
                                "power_w": 140.5,
                            }
                        ],
                    },
                    "hardware": {
                        "capabilities": {
                            "helper_installed": True,
                            "helper_reachable": True,
                            "cpu_deep_telemetry_available": True,
                            "gpu_deep_telemetry_available": True,
                            "thermal_sensor_availability": True,
                            "power_current_available": True,
                        },
                        "freshness": {"sampling_tier": "active", "sample_age_seconds": 4.0},
                    },
                    "storage": {"drives": [{"drive": "C:\\", "total_bytes": 1000, "free_bytes": 400, "used_bytes": 600}]},
                    "network": {
                        "hostname": "stormhelm",
                        "interfaces": [{"interface_alias": "Wi-Fi", "profile": "Home", "status": "Up", "ipv4": ["192.168.1.14"]}],
                        "assessment": {
                            "kind": "local_link_issue",
                            "headline": "Local Wi-Fi instability likely",
                            "summary": "Recent gateway jitter and packet-loss bursts suggest the problem starts on the local link.",
                            "confidence": "moderate",
                            "attribution": "local_link",
                            "evidence_sufficiency": "recent",
                        },
                        "quality": {
                            "latency_ms": 48,
                            "gateway_latency_ms": 29,
                            "external_latency_ms": 48,
                            "jitter_ms": 21,
                            "packet_loss_pct": 3.2,
                            "signal_strength_dbm": -62,
                        },
                        "monitoring": {
                            "history_ready": True,
                            "diagnostic_burst_active": False,
                            "last_sample_age_seconds": 8,
                        },
                        "trend_points": [
                            {"latency_ms": 24, "packet_loss_pct": 0.0, "jitter_ms": 3},
                            {"latency_ms": 29, "packet_loss_pct": 0.0, "jitter_ms": 4},
                            {"latency_ms": 55, "packet_loss_pct": 3.2, "jitter_ms": 21},
                        ],
                        "events": [
                            {"kind": "packet_loss_burst", "title": "Packet-loss burst", "detail": "External loss reached 3.2%.", "seconds_ago": 34},
                            {"kind": "gateway_latency_spike", "title": "Gateway latency spike", "detail": "Gateway latency climbed sharply.", "seconds_ago": 62},
                        ],
                        "providers": {
                            "cloudflare_quality": {
                                "state": "partial",
                                "label": "Cloudflare quality",
                                "detail": "Waiting for richer quality samples.",
                                "comparison_summary": "Cloudflare latency is about 7 ms higher than Stormhelm's external probes.",
                                "sample_count": 4,
                                "successful_samples": 3,
                                "comparison_ready": True,
                                "sampled_at": 1713643200.0,
                                "last_sample_age_seconds": 42,
                            }
                        },
                    },
                    "location": {"resolved": True, "source": "approximate_device", "label": "Queens, New York", "approximate": True},
                },
                "provider_state": {"enabled": True, "configured": True, "planner_model": "gpt-5.4-mini", "reasoning_model": "gpt-5.4"},
                "tool_state": {"enabled_count": 9, "enabled_tools": ["machine_status", "power_status", "storage_status", "network_status"]},
            },
            "settings": {
                "safety": {"allowed_read_dirs": [str(temp_config.project_root)]},
            },
        }
    )

    bridge.activateModule("systems")

    assert bridge.workspaceCanvas["viewKind"] == "facts"
    assert bridge.workspaceCanvas["factGroups"][0]["title"] == "Machine"
    assert any(row["label"] == "Battery" and row["value"] == "73%" for row in bridge.workspaceCanvas["factGroups"][1]["rows"])
    assert any(row["label"] == "Location" and "queens" in row["value"].lower() for row in bridge.workspaceCanvas["factGroups"][0]["rows"])
    assert any(row["label"] == "Telemetry" and row["value"] == "Helper ready" for row in bridge.workspaceCanvas["factGroups"][2]["rows"])
    assert any(row["label"] == "CPU" and "72 c" in row["detail"].lower() for row in bridge.workspaceCanvas["factGroups"][1]["rows"])
    assert any(row["label"] == "GPU" and "66 c" in row["detail"].lower() for row in bridge.workspaceCanvas["factGroups"][1]["rows"])
    assert bridge.workspaceCanvas["networkDisplay"]["hero"]["status"] == "Local Wi-Fi instability likely"
    assert bridge.workspaceCanvas["networkDisplay"]["metrics"][0]["label"] == "Latency"


def test_ui_bridge_helm_surfaces_screen_awareness_policy_and_trace_state(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "screen_awareness": {
                    "enabled": True,
                    "phase": "phase12",
                    "policy_state": {
                        "action_policy_mode": "confirm_before_act",
                        "restricted_domain_guarded": True,
                        "summary": "Phase 12 runs with confirm before act posture; restricted domains stay guarded and debug traces are on.",
                    },
                    "hardening": {
                        "enabled": True,
                        "recent_trace_count": 1,
                        "latest_trace": {
                            "trace_id": "screen-test-trace",
                            "total_duration_ms": 18.4,
                            "slowest_stage": "verification",
                            "audit_passed": True,
                        },
                    },
                }
            },
            "settings": {
                "safety": {"allowed_read_dirs": [str(temp_config.project_root)]},
                "screen_awareness": {
                    "enabled": True,
                    "phase": "phase12",
                    "action_policy_mode": "confirm_before_act",
                },
            },
        }
    )

    bridge.setMode("deck")
    bridge.activateModule("helm")

    entries = {entry["primary"]: entry for entry in bridge.active_deck_module["entries"]}

    assert entries["Screen Bearings"]["secondary"] == "Phase 12 active"
    assert entries["Action Policy"]["secondary"] == "Confirm Before Act"
    assert "latest screen trace took 18.4 ms" in entries["Traceability"]["detail"].lower()
    assert any(
        entry["primary"] == "Screen Bearings"
        for column in bridge.workspaceCanvas["columns"]
        for entry in column["entries"]
    )
    assert any(
        entry["primary"] == "Action Policy"
        for column in bridge.workspaceCanvas["columns"]
        for entry in column["entries"]
    )
    assert any(
        entry["primary"] == "Traceability"
        for column in bridge.workspaceCanvas["columns"]
        for entry in column["entries"]
    )


def test_ui_bridge_systems_surfaces_operational_interpretation_before_raw_facts(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "system_state": {
                    "power": {"available": True, "battery_percent": 62, "ac_line_status": "offline"},
                    "resources": {
                        "cpu": {"name": "AMD Ryzen", "utilization_percent": 34.0},
                        "memory": {
                            "total_bytes": 32 * 1024**3,
                            "used_bytes": 29 * 1024**3,
                            "free_bytes": 3 * 1024**3,
                        },
                        "gpu": [{"name": "NVIDIA RTX"}],
                    },
                    "storage": {
                        "drives": [
                            {
                                "drive": "C:\\",
                                "total_bytes": 512 * 1024**3,
                                "used_bytes": 410 * 1024**3,
                                "free_bytes": 102 * 1024**3,
                            }
                        ]
                    },
                },
                "systems_interpretation": {
                    "headline": "Memory pressure elevated",
                    "summary": "RAM usage is high enough that it may explain sluggishness.",
                    "domains": [
                        {
                            "key": "resources",
                            "label": "Machine Load",
                            "headline": "Memory pressure elevated",
                            "summary": "RAM usage is high enough that it may explain sluggishness.",
                            "severity": "warning",
                        },
                        {
                            "key": "power",
                            "label": "Battery",
                            "headline": "Battery on discharge",
                            "summary": "Battery is currently discharging with no strong charging anomaly.",
                            "severity": "steady",
                        },
                    ],
                },
            }
        }
    )

    bridge.activateModule("systems")

    assert bridge.workspaceCanvas["factGroups"][0]["title"] == "Operational State"
    assert bridge.workspaceCanvas["factGroups"][0]["rows"][0]["value"] == "Memory pressure elevated"
    assert "sluggishness" in bridge.workspaceCanvas["factGroups"][0]["rows"][0]["detail"].lower()


def test_ui_bridge_systems_surfaces_event_stream_runtime_state(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "event_stream": {
                    "capacity": 256,
                    "buffered": 12,
                    "published_total": 48,
                    "expired_total": 3,
                    "latest_cursor": 48,
                    "earliest_cursor": 37,
                    "replay_requests": 5,
                    "replay_gap_total": 1,
                    "connections_current": 1,
                    "family_totals": {"job": 14, "network": 6},
                    "visibility_totals": {"watch_surface": 12, "systems_surface": 10},
                }
            }
        }
    )
    bridge.apply_stream_state({"source": "client", "phase": "reconnecting"})

    bridge.activateModule("systems")

    groups = {group["title"]: group for group in bridge.workspaceCanvas["factGroups"]}
    assert "Event Spine" in groups
    rows = {row["label"]: row for row in groups["Event Spine"]["rows"]}
    assert rows["Buffered"]["value"] == "12 / 256"
    assert rows["Replay"]["detail"] == "5 replays, 1 retention gaps"
    assert rows["Connections"]["value"] == "1 live"
    assert rows["UI Stream"]["value"] == "Reconnecting"
    assert rows["UI Stream"]["detail"] == "reconcile requested"
    assert rows["UI Timing"]["value"] == "1 summaries"


def test_ui_bridge_watch_uses_job_posture_slice(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "environment": temp_config.environment,
                "runtime_mode": "source",
                "max_workers": temp_config.concurrency.max_workers,
                "watch_state": {"active_jobs": 1, "queued_jobs": 1, "recent_failures": 1, "completed_recently": 2},
            },
            "jobs": [
                {
                    "job_id": "job-active",
                    "tool_name": "machine_status",
                    "status": "running",
                    "created_at": "2026-04-19T12:00:00Z",
                    "started_at": "2026-04-19T12:00:01Z",
                },
                {
                    "job_id": "job-fail",
                    "tool_name": "open_url_external",
                    "status": "failed",
                    "created_at": "2026-04-19T11:59:00Z",
                    "finished_at": "2026-04-19T11:59:02Z",
                    "error": "connection lost",
                },
            ],
        }
    )

    bridge.activateModule("watch")

    assert bridge.workspaceCanvas["viewKind"] == "watch"
    assert bridge.workspaceCanvas["stats"][0]["label"] == "Active Jobs"
    assert bridge.workspaceCanvas["lanes"][0]["title"] == "In Flight"
    assert bridge.activeDeckModule["entries"][0]["primary"] == "Machine Status"
    assert "running now" in bridge.workspaceCanvas["lanes"][0]["entries"][0]["detail"].lower()
    assert "failed after" in bridge.workspaceCanvas["lanes"][2]["entries"][0]["detail"].lower()


def test_ui_bridge_watch_uses_operational_fallback_when_idle(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "watch_state": {
                    "active_jobs": 0,
                    "queued_jobs": 0,
                    "recent_failures": 0,
                    "completed_recently": 3,
                    "worker_capacity": 8,
                },
            },
        }
    )

    bridge.activateModule("watch")

    assert bridge.workspaceCanvas["lanes"][0]["entries"][0]["title"] == "No active jobs"
    assert bridge.activeDeckModule["entries"][0]["primary"] == "Worker deck clear"
    assert "workers ready" in bridge.activeDeckModule["entries"][0]["secondary"].lower()


def test_ui_bridge_watch_shows_workflow_step_progress_when_present(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "watch_state": {"active_jobs": 1, "queued_jobs": 0, "recent_failures": 0, "completed_recently": 0},
            },
            "jobs": [
                {
                    "job_id": "job-workflow",
                    "tool_name": "workflow_execute",
                    "status": "running",
                    "created_at": "2026-04-20T12:00:00Z",
                    "started_at": "2026-04-20T12:00:01Z",
                    "result": {
                        "summary": "Running step 2 of 3.",
                        "data": {
                            "workflow": {
                                "kind": "writing_setup",
                                "current_step_index": 1,
                                "steps": [
                                    {"title": "Restore context", "status": "completed"},
                                    {"title": "Open notes", "status": "running"},
                                    {"title": "Focus writing surface", "status": "pending"},
                                ],
                            }
                        },
                    },
                }
            ],
        }
    )

    bridge.activateModule("watch")

    assert "step 2 of 3" in bridge.workspaceCanvas["lanes"][0]["entries"][0]["detail"].lower()


def test_ui_bridge_watch_shows_item_progress_for_long_running_file_operations(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "watch_state": {"active_jobs": 1, "queued_jobs": 0, "recent_failures": 0, "completed_recently": 0},
            },
            "jobs": [
                {
                    "job_id": "job-file-op",
                    "tool_name": "maintenance_action",
                    "status": "running",
                    "created_at": "2026-04-20T12:00:00Z",
                    "started_at": "2026-04-20T12:00:01Z",
                    "result": {
                        "summary": "Archiving older screenshots.",
                        "data": {
                            "workflow": {
                                "kind": "maintenance",
                                "current_step_index": 0,
                                "steps": [
                                    {"title": "Archive older screenshots", "status": "running"},
                                ],
                                "item_progress": {
                                    "processed": 12,
                                    "total": 45,
                                    "changed": 9,
                                    "skipped": 4,
                                },
                            }
                        },
                    },
                }
            ],
        }
    )

    bridge.activateModule("watch")

    detail = bridge.workspaceCanvas["lanes"][0]["entries"][0]["detail"].lower()
    assert "12 of 45 items" in detail
    assert "4 skipped" in detail


def test_ui_bridge_anchor_notch_covers_text_lane_below_anchor(temp_config) -> None:
    bridge = UiBridge(temp_config)

    assert bridge._panel_overlaps_anchor_notch({"gridX": 4, "gridY": 2, "colSpan": 2, "rowSpan": 1}) is True


def test_ui_bridge_signals_use_payload_detail_and_recent_meta(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "events": [
                {
                    "event_id": 11,
                    "level": "WARNING",
                    "source": "network",
                    "message": "Packet-loss burst",
                    "created_at": "2026-04-19T12:04:00Z",
                    "payload": {
                        "detail": "External probes lost 1 of 2 recent samples.",
                        "severity": "warning",
                    },
                }
            ],
            "jobs": [
                {
                    "job_id": "job-complete",
                    "tool_name": "open_url_external",
                    "status": "completed",
                    "created_at": "2026-04-19T12:00:00Z",
                    "finished_at": "2026-04-19T12:00:03Z",
                    "result": {"summary": "Opened the requested page externally."},
                }
            ],
        }
    )

    bridge.activateModule("signals")

    assert bridge.workspaceCanvas["timeline"][0]["detail"] == "External probes lost 1 of 2 recent samples."
    assert " | " in bridge.activeDeckModule["entries"][0]["secondary"]
    assert bridge.activeDeckModule["sections"][0]["entries"][0]["detail"] == "External probes lost 1 of 2 recent samples."


def test_ui_bridge_close_requests_hide_when_tray_behavior_is_enabled(temp_config) -> None:
    bridge = UiBridge(temp_config)

    assert bridge.handleCloseRequest() is True

    bridge.setHideToTrayOnClose(False)

    assert bridge.handleCloseRequest() is False


def test_ui_bridge_exposes_ghost_instrumentation_and_active_context(temp_config) -> None:
    bridge = UiBridge(temp_config)

    corners = {item["corner"]: item for item in bridge.ghostCornerReadouts}

    assert set(corners) == {"top_left", "top_right", "bottom_left", "bottom_right"}
    assert corners["top_left"]["label"] == "Stormhelm"
    assert "Deck" in corners["bottom_right"]["primary"]

    bridge.activateModule("signals")

    assert any(item["key"] == "live" and item["active"] for item in bridge.workspaceRailItems)
    assert any(item["key"] == "signals" and item["active"] for item in bridge.commandRailItems)
    assert bridge.activeDeckModule["key"] == "signals"


def test_ui_bridge_uses_warning_state_for_connection_errors(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.set_connection_error("offline")

    assert bridge.connection_state == "disrupted"
    assert bridge.assistant_state_value == "warning"


def test_ui_bridge_ghost_capture_tracks_draft_and_submission(temp_config) -> None:
    bridge = UiBridge(temp_config)
    sent_messages: list[str] = []
    bridge.sendMessageRequested.connect(sent_messages.append)

    bridge.beginGhostCapture()
    bridge.appendGhostDraft("Plot safe harbor")

    assert bridge.ghostCaptureActive is True
    assert bridge.ghostDraftText == "Plot safe harbor"
    assert bridge.ghostInputHint == "Enter sends · Esc clears"

    bridge.submitGhostDraft()

    assert sent_messages == ["Plot safe harbor"]
    assert bridge.ghostCaptureActive is False
    assert bridge.ghostDraftText == ""
    assert bridge.assistant_state_value == "thinking"


def test_ui_bridge_workspace_sections_and_canvas_follow_active_destination(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.activateModule("helm")

    assert bridge.workspaceSections[0]["key"] == "overview"
    assert any(section["key"] == "hotkeys" for section in bridge.workspaceSections)
    assert bridge.workspaceCanvas["key"] == "helm"
    assert bridge.workspaceCanvas["title"] == "Helm"
    assert any(chip["label"] == "Ghost Shortcut" for chip in bridge.workspaceCanvas["chips"])

    bridge.activateWorkspaceSection("safety")

    assert bridge.workspaceCanvas["sectionKey"] == "safety"


def test_ui_bridge_workspace_focus_action_moves_surface_without_opening_item(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action({"type": "workspace_focus", "module": "systems", "section": "overview"})

    assert bridge.mode_value == "deck"
    assert bridge.active_module_key == "systems"
    assert bridge.workspaceCanvas["sectionKey"] == "overview"
    assert bridge.workspaceCanvas["viewKind"] == "facts"


def test_ui_bridge_workspace_open_actions_create_opened_items(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action(
        {
            "type": "workspace_open",
            "module": "browser",
            "section": "open-pages",
            "item": {
                "itemId": "page-1",
                "kind": "browser",
                "viewer": "browser",
                "title": "OpenAI Docs",
                "url": "https://platform.openai.com/docs",
            },
        }
    )

    assert bridge.mode_value == "deck"
    assert bridge.active_module_key == "browser"
    assert bridge.activeOpenedItem["itemId"] == "page-1"
    assert bridge.workspaceCanvas["activeItem"]["viewer"] == "browser"
    assert bridge.workspaceCanvas["openedItems"][0]["title"] == "OpenAI Docs"


def test_ui_bridge_workspace_open_actions_preserve_surface_section_in_context(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action(
        {
            "type": "workspace_open",
            "module": "browser",
            "section": "open-pages",
            "item": {
                "itemId": "page-1",
                "kind": "browser",
                "viewer": "browser",
                "title": "OpenAI Docs",
                "url": "https://platform.openai.com/docs",
            },
        }
    )

    context = bridge.workspace_context_payload()

    assert context["opened_items"][0]["section"] == "open-pages"
    assert context["active_item"]["section"] == "open-pages"


def test_ui_bridge_workspace_restore_replaces_opened_items_and_tracks_focus(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action(
        {
            "type": "workspace_restore",
            "module": "files",
            "section": "opened-items",
            "workspace": {
                "workspaceId": "ws-stormhelm",
                "name": "Stormhelm Internals",
                "topic": "stormhelm internals",
                "summary": "Continue the advanced internals buildout.",
            },
            "items": [
                {
                    "itemId": "item-a",
                    "kind": "text",
                    "viewer": "text",
                    "title": "README.md",
                    "path": "C:/Stormhelm/README.md",
                    "content": "# Stormhelm",
                },
                {
                    "itemId": "item-b",
                    "kind": "browser",
                    "viewer": "browser",
                    "title": "OpenAI Docs",
                    "url": "https://platform.openai.com/docs",
                },
            ],
            "active_item_id": "item-b",
        }
    )

    assert bridge.mode_value == "deck"
    assert bridge.active_module_key == "files"
    assert bridge.workspaceCanvas["title"] == "Stormhelm Internals"
    assert bridge.activeOpenedItem["itemId"] == "item-b"
    assert len(bridge.workspaceCanvas["openedItems"]) == 2


def test_ui_bridge_uses_response_tiers_for_status_and_ghost_bearing(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_chat_result(
        {
            "assistant_message": {
                "message_id": "assistant-1",
                "role": "assistant",
                "content": "Connected on Wi-Fi. Local address 192.168.1.20.",
                "created_at": "2026-04-19T11:50:05Z",
                "metadata": {
                    "bearing_title": "Network",
                    "micro_response": "Connected on Wi-Fi.",
                    "full_response": "Connected on Wi-Fi. Local address 192.168.1.20.",
                },
            }
        }
    )

    corners = {item["corner"]: item for item in bridge.ghostCornerReadouts}

    assert bridge.statusLine == "Connected on Wi-Fi."
    assert bridge.messages[-1]["content"] == "Connected on Wi-Fi. Local address 192.168.1.20."
    assert bridge.ghostMessages[-1]["content"] == "Connected on Wi-Fi."
    assert corners["bottom_left"]["primary"] == "Network"
    assert corners["bottom_left"]["secondary"] == "Connected on Wi-Fi."


def test_ui_bridge_preserves_next_suggestion_metadata_for_transcript_surfaces(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_chat_result(
        {
            "assistant_message": {
                "message_id": "assistant-1",
                "role": "assistant",
                "content": "Chrome was terminated directly.",
                "created_at": "2026-04-20T18:15:05Z",
                "metadata": {
                    "bearing_title": "Chrome force-quit",
                    "micro_response": "Force-quit Chrome.",
                    "full_response": "Chrome was terminated directly.",
                    "next_suggestion": {
                        "title": "Relaunch Chrome",
                        "command": "relaunch chrome",
                    },
                },
            }
        }
    )

    assert bridge.messages[-1]["nextSuggestion"]["title"] == "Relaunch Chrome"
    assert bridge.messages[-1]["nextSuggestion"]["command"] == "relaunch chrome"


def test_ui_bridge_keeps_pending_chat_visible_until_assistant_reply_arrives(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-0",
                    "role": "assistant",
                    "content": "Standing by.",
                    "created_at": "2026-04-20T12:00:00Z",
                }
            ]
        }
    )

    bridge.sendMessage("Check the network.")

    assert bridge.assistantState == "thinking"
    assert bridge.statusLine == "Plotting a response."
    assert bridge.messages[-1]["role"] == "user"
    assert bridge.messages[-1]["content"] == "Check the network."

    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-0",
                    "role": "assistant",
                    "content": "Standing by.",
                    "created_at": "2026-04-20T12:00:00Z",
                }
            ]
        }
    )

    assert bridge.assistantState == "thinking"
    assert bridge.statusLine == "Plotting a response."
    assert bridge.messages[-1]["role"] == "user"
    assert bridge.messages[-1]["content"] == "Check the network."

    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-0",
                    "role": "assistant",
                    "content": "Standing by.",
                    "created_at": "2026-04-20T12:00:00Z",
                },
                {
                    "message_id": "user-1",
                    "role": "user",
                    "content": "Check the network.",
                    "created_at": "2026-04-20T12:00:05Z",
                },
                {
                    "message_id": "assistant-1",
                    "role": "assistant",
                    "content": "Recent packet-loss bursts point to local Wi-Fi instability.",
                    "created_at": "2026-04-20T12:00:07Z",
                    "metadata": {
                        "bearing_title": "Wi-Fi instability",
                        "micro_response": "Recent packet-loss bursts point to local Wi-Fi instability.",
                        "full_response": "Recent packet-loss bursts point to local Wi-Fi instability.",
                    },
                },
            ]
        }
    )

    assert bridge.assistantState == "idle"
    assert bridge.statusLine == "Recent packet-loss bursts point to local Wi-Fi instability."
    assert bridge.messages[-2]["messageId"] == "user-1"
    assert bridge.messages[-1]["messageId"] == "assistant-1"


def test_ui_bridge_chat_result_reconciles_pending_user_echo(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.sendMessage("Open diagnostics.")

    assert bridge.messages[-1]["role"] == "user"
    assert bridge.messages[-1]["content"] == "Open diagnostics."

    bridge.apply_chat_result(
        {
            "user_message": {
                "message_id": "user-1",
                "role": "user",
                "content": "Open diagnostics.",
                "created_at": "2026-04-20T12:10:00Z",
            },
            "assistant_message": {
                "message_id": "assistant-1",
                "role": "assistant",
                "content": "Opened diagnostics.",
                "created_at": "2026-04-20T12:10:02Z",
                "metadata": {
                    "bearing_title": "Diagnostics opened",
                    "micro_response": "Opened diagnostics.",
                    "full_response": "Opened diagnostics.",
                },
            },
        }
    )

    assert [message["messageId"] for message in bridge.messages] == ["user-1", "assistant-1"]
    assert bridge.statusLine == "Opened diagnostics."


def test_ui_bridge_signals_prefer_interpreted_outcomes_over_raw_levels(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "events": [
                {
                    "event_id": 7,
                    "level": "INFO",
                    "source": "core",
                    "message": "Stormhelm core started.",
                    "created_at": "2026-04-18T12:00:00Z",
                },
                {
                    "event_id": 8,
                    "level": "WARNING",
                    "source": "network",
                    "message": "Wi-Fi link flapped.",
                    "created_at": "2026-04-18T12:02:00Z",
                },
            ],
            "jobs": [
                {
                    "job_id": "job-1",
                    "tool_name": "open_url_external",
                    "status": "failed",
                    "created_at": "2026-04-18T12:03:00Z",
                    "finished_at": "2026-04-18T12:03:02Z",
                    "error": "connection lost",
                }
            ],
        }
    )

    bridge.activateModule("signals")

    details = [str(entry["detail"]).lower() for entry in bridge.workspaceCanvas["timeline"]]

    assert bridge.workspaceCanvas["viewKind"] == "signals"
    assert all(detail not in {"info", "warning", "error"} for detail in details)
    assert any("failed after" in detail for detail in details)


def test_ui_bridge_signals_prefer_structured_signal_state_when_available(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "signal_state": {
                    "signals": [
                        {
                            "title": "Wi-Fi instability detected",
                            "detail": "Gateway and external probes degraded together, which points to the local link.",
                            "severity": "warning",
                            "category": "network",
                            "source": "systems",
                            "meta": "34s ago",
                        }
                    ]
                }
            },
            "events": [
                {
                    "event_id": 9,
                    "level": "WARNING",
                    "source": "network",
                    "message": "Packet-loss burst",
                    "created_at": "2026-04-18T12:02:00Z",
                }
            ],
        }
    )

    bridge.activateModule("signals")

    assert bridge.workspaceCanvas["timeline"][0]["title"] == "Wi-Fi instability detected"
    assert "local link" in bridge.workspaceCanvas["timeline"][0]["detail"].lower()


def test_ui_bridge_browser_and_files_surfaces_describe_live_deck_capabilities(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.activateModule("browser")
    browser_body = bridge.workspaceCanvas["body"].lower()
    assert "future" not in browser_body
    assert "references" in browser_body
    assert "browser hand-off" in browser_body

    bridge.activateModule("files")
    files_body = bridge.workspaceCanvas["body"].lower()
    assert "scaffold" not in files_body
    assert "working set" in files_body
    assert "native apps" in files_body


def test_ui_bridge_workspace_local_sections_are_materially_distinct(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "user-1",
                    "role": "user",
                    "content": "Continue the packaging workspace.",
                    "created_at": "2026-04-19T11:50:00Z",
                },
                {
                    "message_id": "assistant-1",
                    "role": "assistant",
                    "content": "Stormhelm restored the packaging bearings and opened the active references.",
                    "created_at": "2026-04-19T11:50:05Z",
                },
            ],
            "events": [
                {
                    "event_id": 1,
                    "level": "INFO",
                    "source": "job_manager",
                    "message": "Job completed cleanly.",
                    "created_at": "2026-04-19T11:50:06Z",
                }
            ],
            "jobs": [
                {
                    "job_id": "job-1",
                    "tool_name": "workspace_restore",
                    "status": "completed",
                    "created_at": "2026-04-19T11:50:01Z",
                    "finished_at": "2026-04-19T11:50:04Z",
                    "result": {"summary": "Restored packaging workspace."},
                }
            ],
            "notes": [
                {
                    "note_id": "note-1",
                    "title": "Packaging next step",
                    "content": "Verify portable build after the restore.",
                    "created_at": "2026-04-19T11:49:30Z",
                }
            ],
        }
    )
    bridge.apply_action(
        {
            "type": "workspace_restore",
            "module": "chartroom",
            "section": "active-thread",
            "workspace": {
                "workspaceId": "ws-packaging",
                "name": "Packaging Workspace",
                "topic": "packaging",
                "summary": "Continue packaging verification and release prep.",
            },
            "items": [
                {
                    "itemId": "item-doc",
                    "kind": "browser",
                    "viewer": "browser",
                    "title": "PyInstaller Docs",
                    "url": "https://pyinstaller.org/",
                    "summary": "Primary packaging reference.",
                }
            ],
            "active_item_id": "item-doc",
        }
    )

    assert bridge.workspaceCanvas["viewKind"] == "thread"

    bridge.activateWorkspaceSection("references")
    assert bridge.workspaceCanvas["viewKind"] == "collection"
    assert bridge.workspaceCanvas["items"][0]["title"] == "PyInstaller Docs"

    bridge.activateWorkspaceSection("findings")
    assert bridge.workspaceCanvas["viewKind"] == "findings"
    assert bridge.workspaceCanvas["highlights"][0]["title"] != ""

    bridge.activateWorkspaceSection("session")
    assert bridge.workspaceCanvas["viewKind"] == "session"
    assert bridge.workspaceCanvas["panels"][0]["title"] == "Current Bearing"

    bridge.activateWorkspaceSection("tasks")
    assert bridge.workspaceCanvas["viewKind"] == "tasks"
    assert bridge.workspaceCanvas["taskGroups"][0]["title"] == "Next Bearings"


def test_ui_bridge_workspace_surface_content_overrides_generic_section_fallbacks(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action(
        {
            "type": "workspace_restore",
            "module": "chartroom",
            "section": "session",
            "workspace": {
                "workspaceId": "ws-triage",
                "name": "Wi-Fi Triage",
                "topic": "network",
                "summary": "Continue diagnosing intermittent Wi-Fi instability.",
                "surfaceContent": {
                    "references": {
                        "presentationKind": "collection",
                        "items": [
                            {
                                "title": "Adapter Driver Notes",
                                "subtitle": "Research",
                                "detail": "https://example.test/driver-notes",
                                "badge": "Support",
                                "role": "Referenced in the last troubleshooting session.",
                            }
                        ],
                    },
                    "findings": {
                        "presentationKind": "highlights",
                        "items": [
                            {
                                "title": "Gateway and external latency degraded together",
                                "summary": "The slowdown appears to begin on the local link.",
                                "source": "Systems",
                            }
                        ],
                    },
                    "session": {
                        "presentationKind": "panels",
                        "items": [
                            {
                                "title": "Current Bearing",
                                "summary": "Wi-Fi Triage",
                                "detail": "Investigate intermittent Wi-Fi instability.",
                                "entries": [{"label": "Topic", "value": "network"}],
                            }
                        ],
                    },
                    "tasks": {
                        "presentationKind": "task-groups",
                        "items": [
                            {
                                "title": "Next Bearings",
                                "entries": [
                                    {
                                        "title": "Run a fresh gateway ping sample.",
                                        "status": "priority",
                                        "detail": "Confirm whether the local link is still unstable.",
                                    }
                                ],
                            }
                        ],
                    },
                    "logbook": {
                        "presentationKind": "collection",
                        "items": [
                            {
                                "title": "Driver rollback note",
                                "subtitle": "Logbook",
                                "detail": "The issue started after the most recent adapter update.",
                                "badge": "Retained",
                                "role": "Saved where-we-left-off note.",
                            }
                        ],
                    },
                    "files": {
                        "presentationKind": "collection",
                        "items": [
                            {
                                "title": "wifi-diagnostics.md",
                                "subtitle": "Files",
                                "detail": "C:/Stormhelm/wifi-diagnostics.md",
                                "badge": "Held",
                                "role": "Used in the last troubleshooting pass.",
                            }
                        ],
                    },
                },
            },
            "items": [
                {
                    "itemId": "item-a",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "wifi-diagnostics.md",
                    "path": "C:/Stormhelm/wifi-diagnostics.md",
                    "summary": "Active troubleshooting file.",
                }
            ],
            "active_item_id": "item-a",
        }
    )

    bridge.activateWorkspaceSection("references")
    assert bridge.workspaceCanvas["items"][0]["title"] == "Adapter Driver Notes"

    bridge.activateWorkspaceSection("findings")
    assert bridge.workspaceCanvas["highlights"][0]["title"] == "Gateway and external latency degraded together"

    bridge.activateWorkspaceSection("session")
    assert bridge.workspaceCanvas["panels"][0]["title"] == "Current Bearing"

    bridge.activateWorkspaceSection("tasks")
    assert bridge.workspaceCanvas["taskGroups"][0]["entries"][0]["title"] == "Run a fresh gateway ping sample."

    bridge.activateModule("logbook")
    assert bridge.workspaceCanvas["items"][0]["title"] == "Driver rollback note"

    bridge.activateModule("files")
    assert bridge.workspaceCanvas["items"][0]["title"] == "wifi-diagnostics.md"


def test_ui_bridge_uses_workspace_likely_next_and_pending_steps_in_tasks(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action(
        {
            "type": "workspace_restore",
            "module": "chartroom",
            "section": "session",
            "workspace": {
                "workspaceId": "ws-controls",
                "name": "Controls Project",
                "topic": "controls",
                "summary": "Reconnect the controls mapping layer.",
                "likelyNext": "Reconnect the device mapping layer.",
                "pendingNextSteps": [
                    "Reconnect the device mapping layer.",
                    "Verify Ghost follow-up routing.",
                ],
            },
            "items": [
                {
                    "itemId": "item-a",
                    "kind": "text",
                    "viewer": "text",
                    "title": "controls-map.md",
                    "path": "C:/Stormhelm/controls-map.md",
                }
            ],
            "active_item_id": "item-a",
        }
    )

    bridge.activateWorkspaceSection("tasks")

    assert bridge.workspaceCanvas["viewKind"] == "tasks"
    assert bridge.workspaceCanvas["taskGroups"][0]["entries"][0]["title"] == "Reconnect the device mapping layer."
    assert "Ghost follow-up routing" in bridge.workspaceCanvas["taskGroups"][0]["entries"][1]["detail"]


def test_ui_bridge_ghost_hide_and_show_share_reveal_path(temp_config) -> None:
    app = _ensure_app()
    bridge = UiBridge(temp_config)
    window = QtGui.QWindow()
    bridge.attachWindow(window)

    bridge.showWindow()
    app.processEvents()

    assert bridge.ghostRevealTarget == 1.0
    assert window.isVisible() is True

    bridge.hideWindow()

    assert bridge.ghostRevealTarget == 0.0
    assert window.isVisible() is True

    QtTest.QTest.qWait(360)
    app.processEvents()

    assert window.isVisible() is False

    bridge.showWindow()
    app.processEvents()

    assert bridge.ghostRevealTarget == 1.0
    assert window.isVisible() is True

    window.close()


def test_ui_bridge_exposes_ghost_adaptive_style_and_position_state(temp_config) -> None:
    bridge = UiBridge(temp_config)

    assert bridge.ghostAdaptiveStyle["tone"] == 0.0
    assert bridge.ghostPlacement["anchorKey"] == "center"
    assert bridge.ghostAdaptiveDiagnostics["backgroundState"] == "unknown"

    bridge.updateGhostAdaptiveState(
        {
            "tone": 0.24,
            "surfaceOpacity": 0.84,
            "edgeOpacity": 0.32,
            "lineOpacity": 0.11,
            "textContrast": 0.2,
            "secondaryTextContrast": 0.14,
            "glowBoost": 0.16,
            "anchorGlowBoost": 0.28,
            "anchorStrokeBoost": 0.36,
            "anchorFillBoost": 0.19,
            "anchorBackdropOpacity": 0.18,
            "shadowOpacity": 0.2,
            "backdropOpacity": 0.14,
            "backgroundState": "bright",
        },
        {
            "anchorKey": "left",
            "state": "repositioning",
            "offsetX": -96.0,
            "offsetY": -18.0,
            "currentScore": 0.33,
            "bestScore": 0.62,
        },
        {
            "supported": True,
            "backgroundState": "bright",
            "brightness": 0.86,
            "motion": 0.18,
            "edgeDensity": 0.34,
        },
    )

    assert bridge.ghostAdaptiveStyle["backgroundState"] == "bright"
    assert bridge.ghostAdaptiveStyle["surfaceOpacity"] == 0.84
    assert bridge.ghostAdaptiveStyle["anchorStrokeBoost"] == 0.36
    assert bridge.ghostAdaptiveStyle["anchorFillBoost"] == 0.19
    assert bridge.ghostPlacement["anchorKey"] == "left"
    assert bridge.ghostPlacement["offsetX"] == -96.0
    assert bridge.ghostAdaptiveDiagnostics["supported"] is True
    assert bridge.ghostAdaptiveDiagnostics["brightness"] == 0.86


def test_ui_bridge_builds_spatial_deck_panels_with_context_priority(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action(
        {
            "type": "workspace_restore",
            "module": "files",
            "section": "opened-items",
            "workspace": {
                "workspaceId": "ws-research",
                "name": "Research Workspace",
                "topic": "research",
                "summary": "Hold the active file set and supporting references together.",
            },
            "items": [
                {
                    "itemId": "file-a",
                    "kind": "text",
                    "viewer": "text",
                    "title": "notes.md",
                    "path": "C:/Projects/notes.md",
                    "summary": "Active working notes.",
                },
                {
                    "itemId": "page-a",
                    "kind": "browser",
                    "viewer": "browser",
                    "title": "OpenAI Docs",
                    "url": "https://platform.openai.com/docs",
                    "summary": "Supporting reference surface.",
                },
            ],
            "active_item_id": "page-a",
        }
    )

    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}

    assert bridge.mode_value == "deck"
    assert {"command-spine", "workspace-main", "preview-surface"}.issubset(panels)
    assert panels["workspace-main"]["contentKind"] == "workspace-section"
    assert panels["preview-surface"]["contentKind"] == "preview"
    assert panels["command-spine"]["colSpan"] < panels["workspace-main"]["colSpan"]
    assert panels["workspace-main"]["title"] == "Research Workspace"


def test_ui_bridge_surfaces_trust_prompt_and_systems_bearings(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "environment": temp_config.environment,
                "runtime_mode": "source",
                "max_workers": temp_config.concurrency.max_workers,
                "system_state": {},
                "trust": {
                    "enabled": True,
                    "pending_request_count": 1,
                    "active_grant_count": 1,
                    "pending_requests": [
                        {
                            "approval_request_id": "trust-1",
                            "subject": "firefox",
                            "state": "pending_operator_confirmation",
                        }
                    ],
                    "active_grants": [
                        {
                            "grant_id": "grant-1",
                            "subject": "Baby",
                            "scope": "session",
                            "state": "approved_for_session",
                        }
                    ],
                    "recent_audit": [
                        {
                            "audit_id": "audit-1",
                            "summary": "Granted discord relay dispatch for this session.",
                            "approval_state": "approved_for_session",
                        }
                    ],
                },
            },
            "active_request_state": {
                "trust": {
                    "decision": "confirmation_required",
                    "approval_state": "pending_operator_confirmation",
                    "suggested_scope": "task",
                    "operator_message": "Approval is required before Stormhelm can install Firefox.",
                }
            },
            "settings": {
                "safety": {"allowed_read_dirs": [str(temp_config.project_root)]},
            },
        }
    )

    assert any(card["title"] == "Approval Needed" for card in bridge.context_cards)

    bridge.activateModule("systems")

    trust_column = next(column for column in bridge.workspaceCanvas["columns"] if column["title"] == "Trust Bearings")
    assert trust_column["entries"][0]["primary"] == "Pending Approval"
    assert trust_column["entries"][0]["secondary"] == "1"
    assert trust_column["entries"][1]["primary"] == "Active Grants"
    assert trust_column["entries"][1]["secondary"] == "1"


def test_ui_bridge_persists_deck_layout_per_workspace(temp_config) -> None:
    restore_action = {
        "type": "workspace_restore",
        "module": "chartroom",
        "section": "active-thread",
        "workspace": {
            "workspaceId": "ws-packaging",
            "name": "Packaging Workspace",
            "topic": "packaging",
            "summary": "Continue packaging verification.",
        },
        "items": [
            {
                "itemId": "item-a",
                "kind": "text",
                "viewer": "text",
                "title": "build-notes.md",
                "path": "C:/Projects/build-notes.md",
            }
        ],
        "active_item_id": "item-a",
    }

    bridge = UiBridge(temp_config)
    bridge.apply_action(restore_action)
    bridge.updateDeckPanelGrid("command-spine", 1, 1, 3, 5)
    bridge.setDeckPanelPinned("command-spine", True)
    bridge.setDeckPanelCollapsed("signals-module", True)

    reloaded = UiBridge(temp_config)
    reloaded.apply_action(restore_action)
    panels = {panel["panelId"]: panel for panel in reloaded.deckPanels}

    assert panels["command-spine"]["gridX"] == 1
    assert panels["command-spine"]["gridY"] == 1
    assert panels["command-spine"]["colSpan"] == 3
    assert panels["command-spine"]["rowSpan"] == 5
    assert panels["command-spine"]["pinned"] is True
    assert panels["signals-module"]["collapsed"] is True


def test_ui_bridge_hides_and_restores_panels_from_hidden_rail(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.setMode("deck")

    bridge.setDeckPanelHidden("signals-module", True)

    visible_ids = {panel["panelId"] for panel in bridge.deckPanels}
    hidden_ids = {panel["panelId"] for panel in bridge.hiddenDeckPanels}

    assert "signals-module" not in visible_ids
    assert "signals-module" in hidden_ids

    bridge.restoreDeckPanel("signals-module")

    visible_ids = {panel["panelId"] for panel in bridge.deckPanels}
    hidden_ids = {panel["panelId"] for panel in bridge.hiddenDeckPanels}

    assert "signals-module" in visible_ids
    assert "signals-module" not in hidden_ids


def test_ui_bridge_saves_and_restores_explicit_deck_layout_snapshot(temp_config) -> None:
    restore_action = {
        "type": "workspace_restore",
        "module": "chartroom",
        "section": "active-thread",
        "workspace": {
            "workspaceId": "ws-packaging",
            "name": "Packaging Workspace",
            "topic": "packaging",
            "summary": "Continue packaging verification.",
        },
        "items": [
            {
                "itemId": "item-a",
                "kind": "text",
                "viewer": "text",
                "title": "build-notes.md",
                "path": "C:/Projects/build-notes.md",
            }
        ],
        "active_item_id": "item-a",
    }

    bridge = UiBridge(temp_config)
    bridge.apply_action(restore_action)
    bridge.updateDeckPanelGrid("command-spine", 1, 1, 3, 5)
    bridge.setDeckPanelPinned("command-spine", True)

    bridge.saveDeckLayout()

    bridge.updateDeckPanelGrid("command-spine", 6, 0, 2, 4)
    bridge.setDeckPanelPinned("command-spine", False)

    bridge.restoreSavedDeckLayout()

    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}

    assert panels["command-spine"]["gridX"] == 1
    assert panels["command-spine"]["gridY"] == 1
    assert panels["command-spine"]["colSpan"] == 3
    assert panels["command-spine"]["rowSpan"] == 5
    assert panels["command-spine"]["pinned"] is True


def test_ui_bridge_exposes_named_layout_presets_and_panel_catalog(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.activateModule("systems")

    presets = {entry["key"]: entry for entry in bridge.deckLayoutPresets}
    assert {"command-focus", "workspace-focus", "systems-focus", "research-focus"} <= set(presets)
    assert bridge.activeDeckLayoutPreset == "systems-focus"

    catalog = {entry["panelId"]: entry for entry in bridge.deckPanelCatalog}
    assert catalog["workspace-main"]["hidden"] is False
    assert catalog["signals-module"]["title"] == "Signals"

    bridge.setDeckPanelHidden("signals-module", True)

    refreshed = {entry["panelId"]: entry for entry in bridge.deckPanelCatalog}
    assert refreshed["signals-module"]["hidden"] is True


def test_ui_bridge_can_switch_named_layout_presets(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.activateModule("chartroom")

    bridge.setDeckLayoutPreset("research-focus")

    assert bridge.activeDeckLayoutPreset == "research-focus"
    assert bridge._ensure_layout_scope_state()["preset"] == "research-focus"


def test_ui_bridge_resizing_center_panel_reflows_adjacent_docked_panels(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.activateModule("chartroom")

    before = {panel["panelId"]: panel for panel in bridge.deckPanels}
    assert before["signals-module"]["gridX"] == 9
    assert before["watch-module"]["gridX"] == 9

    bridge.updateDeckPanelGrid("workspace-main", 3, 1, 7, 5)

    after = {panel["panelId"]: panel for panel in bridge.deckPanels}
    assert after["workspace-main"]["colSpan"] == 7
    assert after["signals-module"]["gridX"] == 10
    assert after["signals-module"]["colSpan"] == 2
    assert after["watch-module"]["gridX"] == 10
    assert after["watch-module"]["colSpan"] == 2


def test_ui_bridge_helm_surfaces_ghost_adaptive_posture(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.updateGhostAdaptiveState(
        {"backgroundState": "bright", "textContrast": 0.18},
        {"anchorKey": "right", "state": "repositioning", "offsetX": 88.0, "offsetY": -22.0},
        {"supported": True, "backgroundState": "bright", "readabilityRisk": 0.62},
    )

    bridge.activateModule("helm")

    chips = {chip["label"]: chip["value"] for chip in bridge.workspaceCanvas["chips"]}
    assert chips["Ghost Contrast"] == "Bright"
    assert chips["Ghost Anchor"] == "Right"
    assert "repositioning" in bridge.workspaceCanvas["summary"].lower()


def test_ui_bridge_default_chartroom_layout_preserves_anchor_clearance_notch(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.activateModule("chartroom")

    def overlaps_anchor_notch(panel: dict[str, object]) -> bool:
        left = int(panel["gridX"])
        top = int(panel["gridY"])
        right = left + int(panel["colSpan"])
        bottom = top + int(panel["rowSpan"])
        notch_left, notch_top, notch_right, notch_bottom = 4, 0, 8, 2
        return max(left, notch_left) < min(right, notch_right) and max(top, notch_top) < min(bottom, notch_bottom)

    assert not any(overlaps_anchor_notch(panel) for panel in bridge.deckPanels)


def test_ui_bridge_builds_route_aware_relay_surface_with_backend_grounded_actions(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-1",
                    "role": "assistant",
                    "content": "Relay preview is ready for Baby once you approve it.",
                    "created_at": "2026-04-23T11:20:00Z",
                    "metadata": {
                        "bearing_title": "Relay Preview",
                        "micro_response": "Relay preview ready for Baby.",
                        "route_state": {
                            "normalized_summary": {"normalized_text": "send this to Baby"},
                            "decomposition": {
                                "action_intent": "dispatch",
                                "subject": "Baby",
                                "deictic_references": ["this"],
                                "continuity_cues": ["preview_live"],
                                "approval_hints": ["preview_before_send"],
                                "verification_hints": ["delivery_confirmation"],
                            },
                            "winner": {
                                "route_family": "discord_relay",
                                "query_shape": "discord_relay_request",
                                "confidence": 0.99,
                                "posture": "clear_winner",
                                "status": "preview_ready",
                                "score": 0.99,
                                "dominant_evidence": ["relay phrasing matched a trusted-send request"],
                                "unresolved_targets": [],
                                "clarification_needed": False,
                                "provider_fallback_reason": None,
                            },
                            "deictic_binding": {
                                "resolved": True,
                                "selected_source": "selection",
                                "selected_target": {
                                    "source": "selection",
                                    "target_type": "text",
                                    "label": "Selected launch notes",
                                    "freshness": "current",
                                },
                                "candidates": [
                                    {
                                        "source": "selection",
                                        "target_type": "text",
                                        "label": "Selected launch notes",
                                        "freshness": "current",
                                    }
                                ],
                                "binding_posture": "resolved",
                                "source_summary": "The current selection is bound to the live relay preview.",
                            },
                        },
                    },
                }
            ],
            "active_request_state": {
                "family": "discord_relay",
                "subject": "Baby",
                "request_type": "discord_relay_dispatch",
                "query_shape": "discord_relay_request",
                "route": {
                    "tool_name": "",
                    "response_mode": "action_result",
                    "route_mode": "local_client_automation",
                },
                "parameters": {
                    "destination_alias": "Baby",
                    "payload_hint": "selected_text",
                    "note_text": "",
                    "request_stage": "preview",
                    "pending_preview": {
                        "preview_id": "relay-preview-1",
                        "route_mode": "local_client_automation",
                        "destination": {"alias": "Baby", "label": "Baby"},
                        "payload": {
                            "kind": "selected_text",
                            "summary": "Selected launch notes",
                            "preview_text": "Selected launch notes",
                        },
                    },
                },
                "trust": {
                    "decision": "confirmation_required",
                    "approval_state": "pending_operator_confirmation",
                    "operator_message": "Approval is required before Stormhelm sends this to Baby. Choose once or session.",
                    "request_id": "trust-1",
                    "suggested_scope": "once",
                    "available_scopes": ["once", "session"],
                },
            },
            "recent_context_resolutions": [
                {
                    "kind": "discord_relay",
                    "summary": "Selected text bound to the relay preview.",
                    "selected_source": "selection",
                    "selected_target": {"label": "Selected launch notes", "freshness": "current"},
                }
            ],
        }
    )

    primary = bridge.ghostPrimaryCard
    assert primary["title"] == "Relay Preview"
    assert primary["resultState"] == "preview_ready"
    assert primary["routeLabel"] == "Discord Relay"
    provenance = {entry["label"]: entry["value"] for entry in primary["provenance"]}
    assert provenance["Binding"] == "Selection"
    assert provenance["Payload"] == "Selected Text"
    assert provenance["Trust"] == "Pending Operator Confirmation"

    actions = {entry["label"]: entry for entry in bridge.ghostActionStrip}
    assert actions["Approve Once"]["sendText"] == "approve once"
    assert actions["Approve Session"]["sendText"] == "approve for session"
    assert actions["Deny"]["sendText"] == "deny"
    assert actions["Inspect Route"]["localAction"] == "open_route_inspector"

    composer = bridge.requestComposer
    chips = {entry["label"]: entry["value"] for entry in composer["chips"]}
    assert chips["Route"] == "Discord Relay"
    assert chips["Request Stage"] == "Preview"
    assert chips["Binding"] == "Selection"
    assert chips["Trust"] == "Pending Operator Confirmation"
    assert composer["placeholder"] == "Continue the live request or redirect it with a grounded follow-up."
    quick_actions = {entry["label"]: entry["sendText"] for entry in composer["quickActions"]}
    assert quick_actions["Approve Once"] == "approve once"


def test_ui_bridge_surfaces_clarification_choices_in_ghost_and_request_composer(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-2",
                    "role": "assistant",
                    "content": 'This looks like a relay request, but I still need to know whether "this" means the page, the file, or the selected text.',
                    "created_at": "2026-04-23T11:24:00Z",
                    "metadata": {
                        "bearing_title": "Relay Clarification",
                        "micro_response": "Relay payload still needs binding.",
                        "route_state": {
                            "normalized_summary": {"normalized_text": "send this to Baby"},
                            "decomposition": {
                                "action_intent": "dispatch",
                                "subject": "Baby",
                                "deictic_references": ["this"],
                            },
                            "winner": {
                                "route_family": "discord_relay",
                                "query_shape": "discord_relay_request",
                                "confidence": 0.82,
                                "posture": "conditional_winner",
                                "status": "clarify_payload",
                                "score": 0.82,
                                "dominant_evidence": ["relay phrasing matched a trusted-send request"],
                                "unresolved_targets": ["payload"],
                                "clarification_needed": True,
                                "clarification_reason": "ambiguous_relay_payload",
                            },
                            "deictic_binding": {
                                "resolved": False,
                                "selected_source": None,
                                "selected_target": None,
                                "candidates": [
                                    {"source": "browser", "target_type": "page", "label": "Stormhelm docs", "freshness": "current"},
                                    {"source": "workspace", "target_type": "file", "label": "notes.md", "freshness": "current"},
                                    {"source": "selection", "target_type": "text", "label": "Selected launch notes", "freshness": "current"},
                                ],
                                "binding_posture": "ambiguous",
                                "unresolved_reason": "multiple_live_binding_candidates",
                                "source_summary": "Multiple live sources still match the relay payload.",
                            },
                        },
                    },
                }
            ],
            "active_request_state": {
                "family": "discord_relay",
                "subject": "Baby",
                "request_type": "discord_relay_dispatch",
                "query_shape": "discord_relay_request",
                "route": {"tool_name": "", "response_mode": "action_result", "route_mode": "local_client_automation"},
                "parameters": {
                    "destination_alias": "Baby",
                    "request_stage": "clarify_payload",
                    "ambiguity_choices": ["page", "file", "text"],
                },
            },
        }
    )

    primary = bridge.ghostPrimaryCard
    assert primary["title"] == "Relay Clarification"
    assert primary["resultState"] == "unresolved"
    assert primary["routeLabel"] == "Discord Relay"

    actions = {entry["label"]: entry for entry in bridge.ghostActionStrip}
    assert actions["Page"]["sendText"] == "page"
    assert actions["File"]["sendText"] == "file"
    assert actions["Text"]["sendText"] == "text"

    composer = bridge.requestComposer
    assert [entry["label"] for entry in composer["clarificationChoices"]] == ["Page", "File", "Text"]
    assert [entry["sendText"] for entry in composer["clarificationChoices"]] == ["page", "file", "text"]
    assert composer["placeholder"] == "Clarify the live request or ask Stormhelm to rebind it."


def test_ui_bridge_builds_route_inspector_with_support_system_summaries(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-3",
                    "role": "assistant",
                    "content": "Firefox is prepared through winget and is waiting on operator approval.",
                    "created_at": "2026-04-23T11:28:00Z",
                    "metadata": {
                        "bearing_title": "Software Approval",
                        "micro_response": "Firefox is prepared and waiting for approval.",
                        "route_state": {
                            "normalized_summary": {"normalized_text": "install firefox"},
                            "decomposition": {
                                "action_intent": "install",
                                "subject": "Firefox",
                                "approval_hints": ["approval_required"],
                                "verification_hints": ["software_verification"],
                            },
                            "winner": {
                                "route_family": "software_control",
                                "query_shape": "software_control_request",
                                "confidence": 0.98,
                                "posture": "clear_winner",
                                "status": "ready_after_approval",
                                "score": 0.98,
                                "dominant_evidence": ["native software route selected"],
                                "unresolved_targets": [],
                                "clarification_needed": False,
                            },
                            "deictic_binding": {
                                "resolved": True,
                                "selected_source": "active_preview",
                                "selected_target": {
                                    "source": "active_preview",
                                    "target_type": "software_target",
                                    "label": "Firefox",
                                    "freshness": "current",
                                },
                                "candidates": [
                                    {
                                        "source": "active_preview",
                                        "target_type": "software_target",
                                        "label": "Firefox",
                                        "freshness": "current",
                                    }
                                ],
                                "binding_posture": "resolved",
                                "source_summary": "The prepared software target is still live.",
                            },
                        },
                    },
                }
            ],
            "status": {
                "watch_state": {"active_jobs": 1, "queued_jobs": 2, "recent_failures": 0},
                "memory": {"families": {"session": 2, "workspace": 1}},
                "lifecycle": {"bootstrap": {"lifecycle_hold_reason": "Restart review is still waiting on operator confirmation."}},
            },
            "active_task": {
                "taskId": "task-77",
                "title": "Package Firefox for the portable deck",
                "state": "paused",
                "whereLeftOff": "Prepared the software plan and held at approval.",
            },
            "active_request_state": {
                "family": "software_control",
                "subject": "firefox",
                "request_type": "software_control_response",
                "query_shape": "software_control_request",
                "parameters": {
                    "operation_type": "install",
                    "target_name": "firefox",
                    "request_stage": "awaiting_confirmation",
                    "selected_source_route": "winget",
                    "task_id": "task-77",
                },
                "trust": {
                    "decision": "confirmation_required",
                    "approval_state": "pending_operator_confirmation",
                    "operator_message": "Approval is required before Stormhelm can install Firefox. Choose once, task, or session.",
                    "request_id": "trust-77",
                    "suggested_scope": "task",
                    "available_scopes": ["once", "task", "session"],
                },
            },
        }
    )

    inspector = bridge.routeInspector
    assert inspector["title"] == "Software Approval"
    assert inspector["resultState"] == "awaiting_approval"
    trace = {entry["label"]: entry["value"] for entry in inspector["trace"]}
    assert trace["Route"] == "Software Control"
    assert trace["Request Stage"] == "Awaiting Confirmation"
    assert trace["Selected Route"] == "winget"

    support = {entry["label"]: entry["value"] for entry in inspector["supportSystems"]}
    assert support["Task"] == "Package Firefox for the portable deck"
    assert support["Trust"] == "Pending Operator Confirmation"
    assert support["Memory"] == "3 family records"
    assert support["Lifecycle"] == "Restart review is still waiting on operator confirmation."
    assert support["Watch"] == "1 active / 2 queued"

    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    assert panels["route-inspector"]["contentKind"] == "route-inspector"
    assert panels["route-inspector"]["title"] == "Route Inspector"


def test_ui_bridge_surfaces_stale_relay_preview_with_degraded_actions_and_native_stations(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-stale-relay",
                    "role": "assistant",
                    "content": "The relay preview is no longer live because the original selection changed.",
                    "created_at": "2026-04-23T12:10:00Z",
                    "metadata": {
                        "bearing_title": "Relay Preview Stale",
                        "micro_response": "The relay preview needs a fresh binding before it can continue.",
                        "route_state": {
                            "decomposition": {
                                "action_intent": "dispatch",
                                "subject": "Baby",
                            },
                            "winner": {
                                "route_family": "discord_relay",
                                "query_shape": "discord_relay_request",
                                "posture": "conditional_winner",
                                "status": "preview_ready",
                                "clarification_needed": False,
                            },
                            "deictic_binding": {
                                "resolved": False,
                                "selected_source": "selection",
                                "selected_target": {
                                    "source": "selection",
                                    "target_type": "text",
                                    "label": "Original launch notes",
                                    "freshness": "stale",
                                },
                                "binding_posture": "invalidated",
                                "unresolved_reason": "selection_replaced_since_preview",
                                "source_summary": "The selection changed after the preview was prepared, so the original payload binding is no longer live.",
                            },
                            "continuation": {
                                "posture": "invalidated",
                                "reason": "The preview continuity lost to the fresher current selection.",
                            },
                        },
                    },
                }
            ],
            "recent_context_resolutions": [
                {
                    "kind": "discord_relay",
                    "summary": "The original relay payload came from the old selection and is now stale.",
                    "selected_source": "selection",
                    "selected_target": {"label": "Original launch notes", "freshness": "stale"},
                }
            ],
            "active_task": {
                "taskId": "task-relay-stale",
                "title": "Share launch notes with Baby",
                "state": "superseded",
                "whereLeftOff": "The original relay preview lost freshness after the selection changed.",
                "continuity": {
                    "posture": "superseded",
                    "freshness": "stale",
                    "active_step": "Rebind payload",
                    "stale_reason": "A fresher selection replaced the payload used by the old preview.",
                    "next_step": "Choose the new payload source before sending.",
                    "resumable": True,
                },
            },
            "active_request_state": {
                "family": "discord_relay",
                "subject": "Baby",
                "request_type": "discord_relay_dispatch",
                "query_shape": "discord_relay_request",
                "route": {
                    "tool_name": "",
                    "response_mode": "action_result",
                    "route_mode": "local_client_automation",
                },
                "parameters": {
                    "destination_alias": "Baby",
                    "payload_hint": "selected_text",
                    "request_stage": "preview",
                    "pending_preview": {
                        "preview_id": "relay-preview-stale",
                        "route_mode": "local_client_automation",
                        "freshness": "stale",
                        "invalidated_reason": "The selection changed after the preview was prepared.",
                        "destination": {"alias": "Baby", "label": "Baby"},
                        "payload": {
                            "kind": "selected_text",
                            "summary": "Original launch notes",
                            "preview_text": "Original launch notes",
                        },
                    },
                },
                "trust": {
                    "decision": "confirmation_required",
                    "approval_state": "expired",
                    "operator_message": "The approval request expired after the preview lost freshness.",
                    "request_id": "trust-expired-1",
                    "available_scopes": ["once", "session"],
                },
            },
        }
    )

    primary = bridge.ghostPrimaryCard
    assert primary["title"] == "Relay Preview Stale"
    assert primary["resultState"] == "stale"
    assert primary["statusLabel"] == "Stale"

    actions = {entry["label"]: entry for entry in bridge.ghostActionStrip}
    assert "Approve Once" not in actions
    assert "Approve Session" not in actions
    assert "Deny" not in actions
    assert actions["Inspect Route"]["localAction"] == "open_route_inspector"

    composer = bridge.requestComposer
    chips = {entry["label"]: entry["value"] for entry in composer["chips"]}
    assert chips["Status"] == "Stale"
    assert chips["Trust"] == "Expired"
    assert chips["Continuity"] == "Superseded"
    assert composer["placeholder"] == "Refresh the stale request, rebind the target, or start a fresh command."

    invalidations = {entry["label"]: entry["reason"] for entry in bridge.routeInspector["invalidations"]}
    assert "selection changed" in invalidations["Preview"].lower()
    assert "expired" in invalidations["Approval"].lower()
    assert "no longer live" in invalidations["Binding"].lower()
    assert "fresher selection" in invalidations["Continuity"].lower()

    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    assert panels["relay-station"]["contentKind"] == "command-station"
    assert panels["trust-station"]["contentKind"] == "command-station"
    assert panels["continuity-station"]["contentKind"] == "command-station"

    trust_station = panels["trust-station"]["stationData"]
    assert trust_station["resultState"] == "stale"
    assert not any(action.get("category") == "approve" for action in trust_station["actions"])

    continuity_station = panels["continuity-station"]["stationData"]
    continuity_entries = {
        entry["primary"]: entry
        for section in continuity_station["sections"]
        for entry in section["entries"]
    }
    assert continuity_entries["Posture"]["secondary"] == "Superseded"
    assert "rebind payload" in continuity_entries["Active Step"]["secondary"].lower()


def test_ui_bridge_deepens_software_recovery_and_runtime_stations(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-recovery-1",
                    "role": "assistant",
                    "content": "Firefox needs a recovery pass before Stormhelm can verify the install.",
                    "created_at": "2026-04-23T12:18:00Z",
                    "metadata": {
                        "bearing_title": "Software Recovery",
                        "micro_response": "Firefox is in a recovery-ready posture.",
                        "next_suggestion": {
                            "title": "Retry Recovery",
                            "command": "retry the firefox recovery",
                        },
                        "route_state": {
                            "decomposition": {
                                "action_intent": "install",
                                "subject": "Firefox",
                            },
                            "winner": {
                                "route_family": "software_control",
                                "query_shape": "software_control_request",
                                "posture": "conditional_winner",
                                "status": "recovery_ready",
                                "clarification_needed": False,
                            },
                            "deictic_binding": {
                                "resolved": True,
                                "selected_source": "active_preview",
                                "selected_target": {
                                    "source": "active_preview",
                                    "target_type": "software_target",
                                    "label": "Firefox",
                                    "freshness": "current",
                                },
                                "binding_posture": "resolved",
                                "source_summary": "The recovery target is still bound to the live Firefox install plan.",
                            },
                        },
                    },
                }
            ],
            "status": {
                "watch_state": {
                    "active_jobs": 1,
                    "queued_jobs": 1,
                    "recent_failures": 2,
                    "health": "degraded",
                    "current_tool": "winget",
                },
                "lifecycle": {
                    "bootstrap": {
                        "state": "ready",
                        "lifecycle_hold_reason": "",
                    }
                },
            },
            "active_task": {
                "taskId": "task-firefox-recovery",
                "title": "Repair Firefox install",
                "state": "paused",
                "whereLeftOff": "The install attempted, but verification could not confirm Firefox yet.",
                "continuity": {
                    "posture": "resumable",
                    "freshness": "current",
                    "active_step": "Recover package state",
                    "blocker_state": "No active blocker",
                    "next_step": "Retry the recovery flow.",
                    "resumable": True,
                },
            },
            "active_request_state": {
                "family": "software_control",
                "subject": "firefox",
                "request_type": "software_control_response",
                "query_shape": "software_control_request",
                "parameters": {
                    "operation_type": "install",
                    "target_name": "firefox",
                    "request_stage": "recovery_ready",
                    "selected_source_route": "winget",
                    "repair_kind": "install_recovery",
                    "workflow_kind": "software_recovery",
                    "recovery_summary": "The first install pass did not verify cleanly.",
                    "task_id": "task-firefox-recovery",
                },
                "trust": {
                    "decision": "allowed",
                    "approval_state": "approved_for_task",
                    "request_id": "trust-firefox-recovery",
                    "task_id": "task-firefox-recovery",
                },
            },
        }
    )

    primary = bridge.ghostPrimaryCard
    assert primary["resultState"] == "recovery_in_progress"
    assert primary["routeLabel"] == "Software Recovery"

    actions = {entry["label"]: entry for entry in bridge.ghostActionStrip}
    assert actions["Retry Recovery"]["sendText"] == "retry the firefox recovery"

    composer = bridge.requestComposer
    chips = {entry["label"]: entry["value"] for entry in composer["chips"]}
    assert chips["Route"] == "Software Recovery"
    assert chips["Continuity"] == "Resumable"
    quick_actions = {entry["label"]: entry["sendText"] for entry in composer["quickActions"]}
    assert quick_actions["Retry Recovery"] == "retry the firefox recovery"

    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    assert panels["software-recovery-station"]["contentKind"] == "command-station"
    assert panels["runtime-station"]["contentKind"] == "command-station"
    assert panels["continuity-station"]["contentKind"] == "command-station"

    recovery_station = panels["software-recovery-station"]["stationData"]
    recovery_entries = {
        entry["primary"]: entry
        for section in recovery_station["sections"]
        for entry in section["entries"]
    }
    assert recovery_entries["Operation"]["secondary"] == "Install Firefox"
    assert recovery_entries["Recovery Route"]["secondary"] == "Winget"
    assert any(action.get("sendText") == "retry the firefox recovery" for action in recovery_station["actions"])

    runtime_station = panels["runtime-station"]["stationData"]
    runtime_entries = {
        entry["primary"]: entry
        for section in runtime_station["sections"]
        for entry in section["entries"]
    }
    assert runtime_entries["Watch Health"]["secondary"] == "Degraded"
    assert runtime_entries["Queue"]["secondary"] == "1 active / 1 queued"

    continuity_station = panels["continuity-station"]["stationData"]
    continuity_entries = {
        entry["primary"]: entry
        for section in continuity_station["sections"]
        for entry in section["entries"]
    }
    assert continuity_entries["Posture"]["secondary"] == "Resumable"
    assert continuity_entries["Next Move"]["detail"] == "Retry the recovery flow."


def test_ui_bridge_expands_screen_awareness_and_memory_command_surfaces(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-screen-1",
                    "role": "assistant",
                    "content": "OBS is on screen and ready for a guided follow-up.",
                    "created_at": "2026-04-23T12:24:00Z",
                    "metadata": {
                        "bearing_title": "Screen Guidance",
                        "micro_response": "OBS is visible and Stormhelm can stay grounded to the current screen state.",
                        "route_state": {
                            "decomposition": {
                                "action_intent": "guide",
                                "subject": "OBS",
                            },
                            "winner": {
                                "route_family": "screen_awareness",
                                "query_shape": "screen_guided_request",
                                "posture": "clear_winner",
                                "status": "attempted",
                                "clarification_needed": False,
                            },
                            "deictic_binding": {
                                "resolved": True,
                                "selected_source": "browser",
                                "selected_target": {
                                    "source": "browser",
                                    "target_type": "window",
                                    "label": "OBS Studio",
                                    "freshness": "current",
                                },
                                "binding_posture": "resolved",
                                "source_summary": "The live OBS window is still the current grounding target.",
                            },
                        },
                    },
                }
            ],
            "recent_context_resolutions": [
                {
                    "kind": "screen_awareness",
                    "summary": "Recent traces still point at OBS Studio settings.",
                    "selected_source": "browser",
                    "selected_target": {"label": "OBS Studio", "freshness": "current"},
                }
            ],
            "status": {
                "memory": {
                    "families": {"session": 2, "workspace": 1},
                    "active_contributors": [
                        {"family": "session", "summary": "Recent traces still point at OBS Studio settings."}
                    ],
                },
                "screen_awareness": {
                    "enabled": True,
                    "phase": "phase12",
                    "policy_state": {
                        "action_policy_mode": "confirm_before_act",
                        "summary": "Phase 12 keeps confirm-before-act posture while OBS remains on screen.",
                    },
                    "hardening": {
                        "recent_trace_count": 1,
                        "latest_trace": {
                            "trace_id": "trace-obs-1",
                            "total_duration_ms": 18.4,
                            "slowest_stage": "verification",
                            "audit_passed": True,
                        },
                    },
                },
            },
            "active_request_state": {
                "family": "screen_awareness",
                "subject": "OBS",
                "request_type": "screen_guided_request",
                "query_shape": "screen_guided_request",
                "parameters": {
                    "request_stage": "prepare_plan",
                    "selected_source_route": "screen_context",
                    "result_state": "attempted",
                },
            },
        }
    )

    primary = bridge.ghostPrimaryCard
    assert primary["resultState"] == "attempted"
    assert primary["routeLabel"] == "Visual Context"

    composer = bridge.requestComposer
    chips = {entry["label"]: entry["value"] for entry in composer["chips"]}
    assert chips["Route"] == "Visual Context"
    assert chips["Request Stage"] == "Prepare Plan"

    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    assert panels["screen-awareness-station"]["contentKind"] == "command-station"
    assert panels["memory-station"]["contentKind"] == "command-station"

    screen_station = panels["screen-awareness-station"]["stationData"]
    screen_entries = {
        entry["primary"]: entry
        for section in screen_station["sections"]
        for entry in section["entries"]
    }
    assert screen_entries["Policy"]["secondary"] == "Confirm Before Act"
    assert screen_entries["Trace"]["secondary"] == "18.4 ms"

    memory_station = panels["memory-station"]["stationData"]
    memory_entries = {
        entry["primary"]: entry
        for section in memory_station["sections"]
        for entry in section["entries"]
    }
    assert memory_entries["Role"]["secondary"] == "Support Only"
    assert "obs studio settings" in memory_entries["Recent Support"]["detail"].lower()
