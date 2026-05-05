from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "voice_ar5_live_kraken"

sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from run_voice_reactive_real_environment_probe import (  # noqa: E402
    AR6_STATUS_AUTHORITY_KEYS,
    _build_timelines,
    _collect_events,
    _enrich_status_rows_with_authority,
    _playback_boundary_segments,
    _process_snapshot,
    _read_qml_rows,
    _render_metrics,
    _request_json,
    _speaking_lifetime,
    _start_process,
    _stop_existing_processes,
    _wait_for_health,
)
from stormhelm.core.voice.live_kraken_probe import (  # noqa: E402
    assert_no_raw_audio_payload,
    classify_live_kraken_scenario,
    kraken_markdown,
    qsg_candidate_promotion_gate,
    renderer_comparison_markdown,
    sanitize_kraken_payload,
    summarize_live_kraken,
)
from stormhelm.core.voice.reactive_real_environment_probe import (  # noqa: E402
    audio_visual_sync_diagnosis,
    real_environment_timeline_csv_text,
    sanitize_scalar_payload,
    summarize_real_environment_chain,
)


RAW_TEXT_FORBIDDEN = (
    "pcm_bytes",
    "raw_samples",
    "audio_bytes",
    "raw_audio_bytes",
    "sample_values",
    "base64",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_kraken_payload(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _assert_scalar_artifacts(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".csv", ".md"}:
            continue
        lowered = path.read_text(encoding="utf-8", errors="ignore").lower()
        forbidden = [token for token in RAW_TEXT_FORBIDDEN if token in lowered]
        if forbidden:
            raise RuntimeError(f"raw audio token(s) {forbidden} found in {path}")


def _dedupe_events(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {
        (
            str(row.get("cursor") or ""),
            str(row.get("event_type") or ""),
            str(row.get("created_at") or row.get("timestamp") or ""),
        )
        for row in existing
    }
    for row in incoming:
        key = (
            str(row.get("cursor") or ""),
            str(row.get("event_type") or ""),
            str(row.get("created_at") or row.get("timestamp") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        existing.append(row)
    return existing


def _event_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("cursor") or ""),
        str(row.get("event_type") or ""),
        str(row.get("created_at") or row.get("timestamp") or ""),
    )


def _new_events(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen = {_event_identity(row) for row in existing}
    return [row for row in incoming if _event_identity(row) not in seen]


def _pcm_events_have_valid_stimulus(events: list[dict[str, Any]]) -> bool:
    pcm_rows: list[dict[str, Any]] = []
    for event in events:
        if str(event.get("event_type") or "") != "voice.pcm_submitted_to_playback":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        diagnostics = metadata.get("voice_ar1_pcm_submit")
        if isinstance(diagnostics, dict):
            pcm_rows.append(diagnostics)
    if len(pcm_rows) < 3:
        return False
    max_energy = max(
        float(row.get("voice_visual_energy") or 0.0)
        for row in pcm_rows
    )
    max_peak = max(float(row.get("peak") or 0.0) for row in pcm_rows)
    max_rms = max(float(row.get("rms") or 0.0) for row in pcm_rows)
    return max(max_energy, max_peak, max_rms) > 0.02


def _dedupe_status(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {str(row.get("status_wall_time_ms") or "") for row in existing}
    for row in incoming:
        key = str(row.get("status_wall_time_ms") or "")
        if key in seen:
            continue
        seen.add(key)
        existing.append(row)
    return existing


def _chat_send(base_url: str, *, session_id: str, prompt: str) -> dict[str, Any]:
    return _request_json(
        base_url,
        "POST",
        "/chat/send",
        {
            "message": prompt,
            "session_id": session_id,
            "surface_mode": "ghost",
            "active_module": "chartroom",
            "response_profile": "concise",
        },
        timeout=20.0,
    )


def _fixture_send(base_url: str, *, session_id: str, prompt: str, timeout_seconds: float) -> dict[str, Any]:
    return _request_json(
        base_url,
        "POST",
        "/voice/diagnostics/local-pcm-fixture",
        {"session_id": session_id, "prompt": prompt},
        timeout=max(20.0, timeout_seconds),
    )


def _playback_ids(events: list[dict[str, Any]], qml_rows: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        for source in (metadata, payload):
            value = source.get("playback_id") or source.get("voice_visual_playback_id")
            if value and str(value) not in ids:
                ids.append(str(value))
    for row in qml_rows:
        value = row.get("qmlReceivedPlaybackId") or row.get("bridge_playback_id")
        if value and str(value) not in ids:
            ids.append(str(value))
    return ids


def _bridge_rows(qml_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = [
        "bridge_receive_time_ms",
        "bridge_voice_visual_energy",
        "bridge_voice_visual_active",
        "bridge_playback_id",
        "bridge_update_rate_hz",
        "authoritativeVoiceStateVersion",
        "activePlaybackId",
        "activePlaybackStatus",
        "authoritativePlaybackId",
        "authoritativePlaybackStatus",
        "authoritativeVoiceVisualActive",
        "authoritativeVoiceVisualEnergy",
        "authoritativeStateSequence",
        "authoritativeStateSource",
        "lastAcceptedUpdateSource",
        "lastIgnoredUpdateSource",
        "staleBroadSnapshotIgnored",
        "staleBroadSnapshotIgnoredCount",
        "hotPathAcceptedCount",
        "terminalEventAcceptedCount",
        "playbackIdSwitchCount",
        "playbackIdMismatchIgnoredCount",
        "voiceVisualActiveFlapCount",
        "surface_model_rebuild_count",
        "collection_rebuild_count",
        "dropped_coalesced_update_count",
    ]
    rows = []
    for row in qml_rows:
        bridge = {key: row.get(key) for key in fields if key in row}
        if bridge:
            bridge["raw_audio_present"] = False
            rows.append(sanitize_scalar_payload(bridge))
    return rows


def _latest_authoritative_status(
    qml_rows: list[dict[str, Any]],
    status_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    for row in reversed(qml_rows + status_rows):
        if str(row.get("authoritativeVoiceStateVersion") or "").strip().upper() != "AR6":
            continue
        return sanitize_scalar_payload(
            {key: row.get(key) for key in AR6_STATUS_AUTHORITY_KEYS if key in row}
        )
    return {}


def _scenario_file_name(scenario: str) -> str:
    return {
        "idle_baseline": "idle_baseline_timeline.csv",
        "single_spoken_response": "single_speech_timeline.csv",
        "post_speech_silence": "post_speech_timeline.csv",
        "repeated_speech": "repeated_speech_timeline.csv",
        "no_audio_unavailable": "no_audio_unavailable_timeline.csv",
    }.get(scenario, f"{scenario}_timeline.csv")


def _post_speech_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def row_active(row: dict[str, Any]) -> bool:
        playback_status = str(
            row.get("authoritativePlaybackStatus")
            or row.get("activePlaybackStatus")
            or row.get("playback_status")
            or ""
        ).strip().lower()
        voice_active = str(
            row.get("authoritativeVoiceVisualActive")
            if row.get("authoritativeVoiceVisualActive") not in {None, ""}
            else row.get("voice_visual_active")
        ).strip().lower()
        return playback_status in {"playing", "active", "prerolling", "started"} or voice_active == "true"

    active_indices = [
        index
        for index, row in enumerate(rows)
        if row_active(row)
    ]
    if not active_indices:
        return rows[-60:]
    return rows[max(active_indices) + 1 :]


def _build_report(
    *,
    scenario: str,
    renderer: str,
    scenario_dir: Path,
    process_state: dict[str, Any],
    spoken_stimulus: dict[str, Any],
    events: list[dict[str, Any]],
    status_rows: list[dict[str, Any]],
    qml_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    status_rows = _enrich_status_rows_with_authority(status_rows, qml_rows)
    timeline_rows, stage_rows = _build_timelines(events, qml_rows)
    for row in timeline_rows:
        row["scenario"] = scenario
        row["renderer"] = renderer
    render_metrics = _render_metrics(qml_rows)
    lifetime = _speaking_lifetime(events, qml_rows, stage_rows.get("payload_rows", []))
    playback_boundary_segments = _playback_boundary_segments(
        events,
        stage_rows.get("pcm_rows", []),
        stage_rows.get("payload_rows", []),
        qml_rows,
    )
    playback_ids = _playback_ids(events, qml_rows)
    report = summarize_real_environment_chain(
        playback_id=playback_ids[0] if playback_ids else "",
        spoken_stimulus_valid=_pcm_events_have_valid_stimulus(events),
        timeline_rows=timeline_rows,
        process_state=process_state,
        runtime_identity=process_state.get("health", {}).get("runtime_identity", {}),
        spoken_stimulus=sanitize_scalar_payload(spoken_stimulus),
        speaking_lifetime=lifetime,
        paint_count=render_metrics.get("anchorPaintCount", 0),
        render_metrics=render_metrics,
    )
    report["probe"] = "voice_ar5_live_kraken_scenario"
    report["scenario"] = scenario
    report["renderer"] = renderer
    report["artifact_dir"] = str(scenario_dir)
    report["events_collected"] = len(events)
    report["status_samples_collected"] = len(status_rows)
    report["qml_rows_collected"] = len(qml_rows)
    report["playback_ids"] = playback_ids
    report["playback_boundary_segments"] = playback_boundary_segments
    report.update(_latest_authoritative_status(qml_rows, status_rows))
    report["stale_playback_id_detected"] = len(playback_ids) != len(set(playback_ids))
    if isinstance(report.get("audio_visual_alignment"), dict):
        report["audio_visual_alignment"].update(
            audio_visual_sync_diagnosis(
                report["audio_visual_alignment"],
                report.get("latency_ms", {}),
            )
        )
    kraken_classes = classify_live_kraken_scenario(scenario, timeline_rows, report=report)
    if report["stale_playback_id_detected"]:
        kraken_classes = sorted(set(kraken_classes) | {"stale_playback_id"})
    report["classification"] = kraken_classes
    report["raw_audio_present"] = False
    report = sanitize_kraken_payload(report)

    _write_json(scenario_dir / "scenario_report.json", report)
    _write_csv(scenario_dir / _scenario_file_name(scenario), timeline_rows)
    _write_json(scenario_dir / "pcm_submit_timeline.json", stage_rows.get("pcm_rows", []))
    _write_json(scenario_dir / "voice_payload_timeline.json", stage_rows.get("payload_rows", []))
    _write_json(scenario_dir / "playback_boundary_segments.json", playback_boundary_segments)
    _write_json(scenario_dir / "status_timeline.json", status_rows)
    _write_json(scenario_dir / "qml_anchor_timeline.json", qml_rows)
    _write_json(scenario_dir / "bridge_timeline.json", _bridge_rows(qml_rows))
    return report, timeline_rows, stage_rows


def _run_runtime_scenario(
    *,
    output_dir: Path,
    scenario: str,
    renderer: str,
    host: str,
    port: int,
    stormforge: bool,
    fog: str,
    clear_cache: bool,
    spoken_prompt: str,
    audible: bool,
    use_local_pcm_voice_fixture: bool,
    timeout_seconds: float,
    observe_seconds: float,
    repeat_count: int = 1,
    stop_existing: bool = True,
    playback_enabled: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    scenario_dir = output_dir / scenario / renderer
    if scenario_dir.exists():
        shutil.rmtree(scenario_dir)
    scenario_dir.mkdir(parents=True, exist_ok=True)
    qml_diag_path = scenario_dir / "qml_anchor_diagnostics.jsonl"
    base_url = f"http://{host}:{port}"
    session_id = f"ar5-live-kraken-{scenario}-{renderer}-{int(time.time() * 1000)}"
    stopped_processes: list[dict[str, Any]] = []
    core_proc: subprocess.Popen[bytes] | None = None
    ui_proc: subprocess.Popen[bytes] | None = None
    events: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    process_state: dict[str, Any] = {}
    spoken_stimulus: dict[str, Any] = {
        "scenario": scenario,
        "requested_text": spoken_prompt,
        "mode": "idle_observation" if scenario == "idle_baseline" else "chat_send",
        "audible_requested": bool(audible),
        "use_local_pcm_voice_fixture": bool(use_local_pcm_voice_fixture),
        "raw_audio_present": False,
    }
    try:
        if stop_existing:
            stopped_processes = _stop_existing_processes()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR)
        env["STORMHELM_CORE_HOST"] = host
        env["STORMHELM_CORE_PORT"] = str(port)
        env["STORMHELM_VOICE_AR1_LIVE_DIAG"] = "1"
        env["STORMHELM_VOICE_AR1_QML_DIAG"] = "1"
        env["STORMHELM_VOICE_AR1_QML_DIAG_PATH"] = str(qml_diag_path)
        env["STORMHELM_STORMFORGE_ANCHOR_RENDERER"] = renderer
        if clear_cache:
            env["QML_DISABLE_DISK_CACHE"] = "1"
        if stormforge:
            env["STORMHELM_UI_VARIANT"] = "stormforge"
        if fog != "auto":
            env["STORMHELM_STORMFORGE_FOG"] = "true" if fog == "on" else "false"
        if not playback_enabled:
            env["STORMHELM_VOICE_PLAYBACK_ENABLED"] = "false"

        core_proc = _start_process("stormhelm.entrypoints.core", env=env, log_path=scenario_dir / "core.log")
        health = _wait_for_health(base_url, timeout_seconds=20.0)
        ui_proc = _start_process("stormhelm.entrypoints.ui", env=env, log_path=scenario_dir / "ui.log")
        time.sleep(3.0)
        try:
            settings = _request_json(base_url, "GET", "/settings", timeout=5.0)
        except Exception:
            settings = {}
        process_state = {
            "started_at": _utc_now(),
            "scenario": scenario,
            "renderer": renderer,
            "command": " ".join(sys.argv),
            "stopped_existing_processes": stopped_processes,
            "core": {"pid": core_proc.pid, "module": "stormhelm.entrypoints.core"},
            "ui": {"pid": ui_proc.pid, "module": "stormhelm.entrypoints.ui"},
            "process_tree": _process_snapshot([core_proc.pid, ui_proc.pid]),
            "health": sanitize_scalar_payload(health),
            "settings": sanitize_scalar_payload(settings),
            "env": sanitize_scalar_payload(
                {
                    "PYTHONPATH": str(SRC_DIR),
                    "STORMHELM_CORE_HOST": host,
                    "STORMHELM_CORE_PORT": str(port),
                    "STORMHELM_UI_VARIANT": env.get("STORMHELM_UI_VARIANT"),
                    "STORMHELM_STORMFORGE_FOG": env.get("STORMHELM_STORMFORGE_FOG"),
                    "STORMHELM_STORMFORGE_ANCHOR_RENDERER": renderer,
                    "STORMHELM_VOICE_PLAYBACK_ENABLED": env.get("STORMHELM_VOICE_PLAYBACK_ENABLED"),
                    "STORMHELM_VOICE_AR1_LIVE_DIAG": "1",
                    "STORMHELM_VOICE_AR1_QML_DIAG": "1",
                    "STORMHELM_VOICE_AR1_QML_DIAG_PATH": str(qml_diag_path),
                    "QML_DISABLE_DISK_CACHE": env.get("QML_DISABLE_DISK_CACHE"),
                }
            ),
            "raw_audio_present": False,
        }
        _write_json(scenario_dir / "process_state.json", process_state)

        if scenario == "idle_baseline":
            captured_events, captured_status = _collect_events(
                base_url,
                session_id=session_id,
                timeout_seconds=observe_seconds,
                qml_diag_path=qml_diag_path,
            )
            events = _dedupe_events(events, captured_events)
            status_rows = _dedupe_status(status_rows, captured_status)
        else:
            for index in range(max(1, repeat_count)):
                turn_prompt = spoken_prompt if repeat_count == 1 else f"{spoken_prompt} Run {index + 1}."
                turn_started = time.time() * 1000.0
                pcm_count_before_turn = sum(
                    1
                    for event in events
                    if str(event.get("event_type") or "") == "voice.pcm_submitted_to_playback"
                )
                try:
                    response = _chat_send(base_url, session_id=session_id, prompt=turn_prompt)
                    spoken_stimulus.setdefault("turns", []).append(
                        sanitize_scalar_payload(
                            {
                                "index": index + 1,
                                "chat_send_time_ms": round(turn_started, 3),
                                "chat_send_ok": True,
                                "assistant_response_text": response.get("assistant_response") or response.get("response"),
                                "status": response.get("status"),
                            }
                        )
                    )
                except Exception as error:
                    spoken_stimulus.setdefault("turns", []).append(
                        {
                            "index": index + 1,
                            "chat_send_time_ms": round(turn_started, 3),
                            "chat_send_ok": False,
                            "error": str(error),
                            "raw_audio_present": False,
                        }
                    )
                captured_events, captured_status = _collect_events(
                    base_url,
                    session_id=session_id,
                    timeout_seconds=min(timeout_seconds, 8.0),
                    qml_diag_path=qml_diag_path,
                )
                turn_events = _new_events(events, captured_events)
                events = _dedupe_events(events, captured_events)
                status_rows = _dedupe_status(status_rows, captured_status)
                pcm_count_after_chat = sum(
                    1
                    for event in events
                    if str(event.get("event_type") or "") == "voice.pcm_submitted_to_playback"
                )
                turn_pcm_valid = _pcm_events_have_valid_stimulus(turn_events)
                if not turn_pcm_valid and use_local_pcm_voice_fixture and playback_enabled:
                    spoken_stimulus["mode"] = "local_pcm_voice_fixture"
                    spoken_stimulus.setdefault("invalid_tts_turns", []).append(
                        sanitize_scalar_payload(
                            {
                                "index": index + 1,
                                "pcm_events_seen": pcm_count_after_chat
                                - pcm_count_before_turn,
                                "reason": "tts_pcm_energy_flat_or_missing",
                                "raw_audio_present": False,
                            }
                        )
                    )
                    try:
                        fixture = _fixture_send(
                            base_url,
                            session_id=session_id,
                            prompt=turn_prompt,
                            timeout_seconds=timeout_seconds,
                        )
                        spoken_stimulus.setdefault("fixtures", []).append(sanitize_scalar_payload(fixture))
                    except Exception as error:
                        spoken_stimulus.setdefault("fixtures", []).append(
                            {"error": str(error), "raw_audio_present": False}
                        )
                    captured_events, captured_status = _collect_events(
                        base_url,
                        session_id=session_id,
                        timeout_seconds=timeout_seconds,
                        qml_diag_path=qml_diag_path,
                    )
                    events = _dedupe_events(events, captured_events)
                    status_rows = _dedupe_status(status_rows, captured_status)
                if index < repeat_count - 1:
                    time.sleep(0.4)
            if observe_seconds > 0:
                captured_events, captured_status = _collect_events(
                    base_url,
                    session_id=session_id,
                    timeout_seconds=observe_seconds,
                    qml_diag_path=qml_diag_path,
                )
                events = _dedupe_events(events, captured_events)
                status_rows = _dedupe_status(status_rows, captured_status)

        qml_rows = _read_qml_rows(qml_diag_path)
        report, timeline_rows, stage_rows = _build_report(
            scenario=scenario,
            renderer=renderer,
            scenario_dir=scenario_dir,
            process_state=process_state,
            spoken_stimulus=spoken_stimulus,
            events=events,
            status_rows=status_rows,
            qml_rows=qml_rows,
        )
        if scenario == "single_spoken_response":
            _write_csv(scenario_dir / "post_speech_timeline.csv", _post_speech_rows(timeline_rows))
        assert_no_raw_audio_payload(report)
        return report, timeline_rows, stage_rows
    finally:
        for proc in (ui_proc, core_proc):
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        time.sleep(0.5)


def _renderer_modes(requested: str) -> list[str]:
    if requested.strip():
        return [part.strip() for part in requested.split(",") if part.strip()]
    modes = ["legacy_blob_reference", "legacy_blob_fast_candidate"]
    if (PROJECT_ROOT / "assets" / "qml" / "variants" / "stormforge" / "StormforgeAnchorLegacyBlobQsgCore.qml").exists():
        modes.append("legacy_blob_qsg_candidate")
    return modes


def _resolve_renderer_plan(anchor_renderer: str, requested_renderers: str) -> tuple[str, list[str]]:
    explicit = str(anchor_renderer or "").strip()
    if explicit:
        return explicit, [explicit]
    return "legacy_blob_reference", _renderer_modes(requested_renderers)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run AR5-LIVE-KRAKEN real Stormforge voice/anchor flight recorder."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stormforge", action="store_true")
    parser.add_argument("--fog", choices=["on", "off", "auto"], default="auto")
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--spoken-prompt", default="Testing one, two, three. Anchor sync check.")
    parser.add_argument("--audible", action="store_true")
    parser.add_argument("--use-local-pcm-voice-fixture", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=24.0)
    parser.add_argument("--idle-observe-seconds", type=float, default=10.0)
    parser.add_argument("--post-speech-observe-seconds", type=float, default=8.0)
    parser.add_argument("--renderers", default="")
    parser.add_argument(
        "--anchor-renderer",
        default="",
        help="Run the main live scenarios with one explicit Stormforge anchor renderer.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    main_renderer, renderers = _resolve_renderer_plan(args.anchor_renderer, args.renderers)
    scenario_reports: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    all_pcm_rows: list[dict[str, Any]] = []
    all_payload_rows: list[dict[str, Any]] = []
    all_bridge_rows: list[dict[str, Any]] = []
    all_status_rows: list[dict[str, Any]] = []
    all_qml_lines: list[str] = []
    process_states: list[dict[str, Any]] = []

    scenario_plan = [
        ("idle_baseline", main_renderer, 1, True, args.idle_observe_seconds, True),
        ("single_spoken_response", main_renderer, 1, True, args.post_speech_observe_seconds, True),
        ("repeated_speech", main_renderer, 3, True, args.post_speech_observe_seconds, True),
        ("no_audio_unavailable", main_renderer, 1, False, args.post_speech_observe_seconds, False),
    ]
    for renderer in renderers:
        scenario_plan.append(("renderer_comparison", renderer, 1, True, args.post_speech_observe_seconds, True))

    for scenario, renderer, repeat_count, playback_enabled, observe_seconds, use_fixture in scenario_plan:
        report, timeline_rows, stage_rows = _run_runtime_scenario(
            output_dir=output_dir,
            scenario=scenario,
            renderer=renderer,
            host=args.host,
            port=args.port,
            stormforge=bool(args.stormforge),
            fog=args.fog,
            clear_cache=bool(args.clear_cache),
            spoken_prompt=args.spoken_prompt,
            audible=bool(args.audible),
            use_local_pcm_voice_fixture=bool(args.use_local_pcm_voice_fixture and use_fixture),
            timeout_seconds=float(args.timeout_seconds),
            observe_seconds=float(observe_seconds),
            repeat_count=repeat_count,
            stop_existing=True,
            playback_enabled=playback_enabled,
        )
        scenario_reports.append(report)
        all_rows.extend(timeline_rows)
        all_pcm_rows.extend(sanitize_kraken_payload(stage_rows.get("pcm_rows", [])))
        all_payload_rows.extend(sanitize_kraken_payload(stage_rows.get("payload_rows", [])))
        scenario_dir = output_dir / scenario / renderer
        status_path = scenario_dir / "status_timeline.json"
        qml_path = scenario_dir / "qml_anchor_diagnostics.jsonl"
        process_path = scenario_dir / "process_state.json"
        bridge_path = scenario_dir / "bridge_timeline.json"
        if status_path.exists():
            all_status_rows.extend(json.loads(status_path.read_text(encoding="utf-8")))
        if bridge_path.exists():
            all_bridge_rows.extend(json.loads(bridge_path.read_text(encoding="utf-8")))
        if process_path.exists():
            process_states.append(json.loads(process_path.read_text(encoding="utf-8")))
        if qml_path.exists():
            all_qml_lines.extend(qml_path.read_text(encoding="utf-8").splitlines())

    process_state = {
        "probe": "voice_ar5_live_kraken",
        "started_at": _utc_now(),
        "scenario_processes": process_states,
        "raw_audio_present": False,
    }
    config_env_snapshot = {
        "command": " ".join(sys.argv),
        "renderer_modes": renderers,
        "anchor_renderer": args.anchor_renderer or None,
        "main_renderer": main_renderer,
        "default_renderer_after_pass": "legacy_blob_reference",
        "stormforge": bool(args.stormforge),
        "fog": args.fog,
        "clear_cache": bool(args.clear_cache),
        "audible": bool(args.audible),
        "use_local_pcm_voice_fixture": bool(args.use_local_pcm_voice_fixture),
        "raw_audio_present": False,
    }
    summary = summarize_live_kraken(
        scenario_reports,
        process_state=process_state,
        config_env_snapshot=config_env_snapshot,
    )
    summary["qsg_promotion_gate"] = qsg_candidate_promotion_gate(
        visual_status="pending_review",
        live_report=summary,
        human_approval="",
    )
    summary = sanitize_kraken_payload(summary)
    assert_no_raw_audio_payload(summary)

    _write_json(output_dir / "ar5_live_kraken_report.json", summary)
    (output_dir / "ar5_live_kraken_report.md").write_text(kraken_markdown(summary), encoding="utf-8")
    _write_csv(output_dir / "ar5_live_kraken_timeline.csv", sanitize_kraken_payload(all_rows))
    _write_json(output_dir / "process_state.json", process_state)
    _write_json(output_dir / "config_env_snapshot.json", config_env_snapshot)
    _write_json(output_dir / "voice_payload_timeline.json", all_payload_rows)
    _write_json(output_dir / "bridge_timeline.json", all_bridge_rows)
    _write_json(output_dir / "pcm_submit_timeline.json", all_pcm_rows)
    _write_json(output_dir / "status_timeline.json", all_status_rows)
    (output_dir / "qml_anchor_diagnostics.jsonl").write_text("\n".join(all_qml_lines) + ("\n" if all_qml_lines else ""), encoding="utf-8")
    (output_dir / "renderer_comparison.md").write_text(
        renderer_comparison_markdown(summary.get("renderer_comparison", [])),
        encoding="utf-8",
    )

    for scenario in ("idle_baseline", "single_spoken_response", "repeated_speech", "no_audio_unavailable"):
        scenario_rows = [row for row in all_rows if row.get("scenario") == scenario]
        _write_csv(output_dir / _scenario_file_name(scenario), sanitize_kraken_payload(scenario_rows))
    single_rows = [row for row in all_rows if row.get("scenario") == "single_spoken_response"]
    _write_csv(output_dir / "post_speech_timeline.csv", sanitize_kraken_payload(_post_speech_rows(single_rows)))

    _assert_scalar_artifacts(output_dir)
    print(
        json.dumps(
            {
                "report": str(output_dir / "ar5_live_kraken_report.json"),
                "classification": summary.get("classification"),
                "renderer_modes": renderers,
                "anchor_renderer": args.anchor_renderer or None,
                "qsg_promotion_gate": summary.get("qsg_promotion_gate"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
