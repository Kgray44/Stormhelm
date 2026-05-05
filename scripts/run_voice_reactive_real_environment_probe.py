from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "voice_ar5_real_environment"
RAW_FORBIDDEN = (
    "pcm_bytes",
    "raw_samples",
    "audio_bytes",
    "raw_audio_bytes",
    "sample_values",
    "base64",
)
AR6_STATUS_AUTHORITY_KEYS = (
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
)

sys.path.insert(0, str(SRC_DIR))

from stormhelm.core.voice.reactive_real_environment_probe import (  # noqa: E402
    audio_visual_sync_diagnosis,
    real_environment_report_markdown,
    real_environment_timeline_csv_text,
    sanitize_scalar_payload,
    speaking_lifetime_report,
    summarize_real_environment_chain,
)


def _python_executable() -> str:
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv_python if venv_python.exists() else Path(sys.executable))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_ms(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp() * 1000.0


def _request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + urlencode(query)
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method.upper())
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    if not data:
        return {}
    return json.loads(data.decode("utf-8"))


def _wait_for_health(base_url: str, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            return _request_json(base_url, "GET", "/health", timeout=2.0)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = str(error)
            time.sleep(0.35)
    raise RuntimeError(f"Core health did not become ready: {last_error}")


def _stop_existing_processes() -> list[dict[str, Any]]:
    command = r"""
$matches = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'stormhelm\.entrypoints\.(core|ui)' }
foreach ($proc in $matches) {
  [PSCustomObject]@{ pid = $proc.ProcessId; command_line = $proc.CommandLine } |
    ConvertTo-Json -Compress
  Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}
"""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=20,
    )
    stopped: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            stopped.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    time.sleep(0.75)
    return stopped


def _process_snapshot(pids: list[int]) -> list[dict[str, Any]]:
    if not pids:
        return []
    id_list = ",".join(str(int(pid)) for pid in pids if pid)
    command = rf"""
$ids = @({id_list})
Get-CimInstance Win32_Process |
  Where-Object {{ $ids -contains $_.ProcessId -or $ids -contains $_.ParentProcessId }} |
  Select-Object ProcessId, ParentProcessId, Name, CommandLine |
  ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    text = completed.stdout.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    return [sanitize_scalar_payload(row) for row in parsed if isinstance(row, dict)]


def _start_process(
    module: str,
    *,
    env: dict[str, str],
    log_path: Path,
) -> subprocess.Popen[bytes]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    return subprocess.Popen(
        [_python_executable(), "-m", module],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP")
        else 0,
    )


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return payload


def _event_metadata(event: dict[str, Any]) -> dict[str, Any]:
    payload = _event_payload(event)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return metadata


def _voice_from_visualizer_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = _event_metadata(event)
    voice = metadata.get("voice") if isinstance(metadata.get("voice"), dict) else {}
    return sanitize_scalar_payload(voice)


def _voice_status_field(voice: dict[str, Any], key: str) -> Any:
    if key in voice:
        return voice.get(key)
    voice_anchor = voice.get("voice_anchor")
    if isinstance(voice_anchor, dict) and key in voice_anchor:
        return voice_anchor.get(key)
    playback = voice.get("playback")
    if isinstance(playback, dict) and key in playback:
        return playback.get(key)
    return None


def _status_row_from_voice_status(
    status: dict[str, Any],
    *,
    observed_at_ms: float | None = None,
) -> dict[str, Any]:
    voice = status.get("voice") if isinstance(status.get("voice"), dict) else {}
    observed = round(float(observed_at_ms), 3) if observed_at_ms is not None else round(time.time() * 1000.0, 3)
    legacy_active = _voice_status_field(voice, "voice_visual_active")
    legacy_energy = _voice_status_field(voice, "voice_visual_energy")
    row: dict[str, Any] = {
        "status_wall_time_ms": observed,
        "legacy_voice_visual_energy": legacy_energy,
        "legacy_voice_visual_active": legacy_active,
        "legacy_voice_visual_source": _voice_status_field(voice, "voice_visual_source"),
        "voice_visual_energy": legacy_energy,
        "voice_visual_active": legacy_active,
        "voice_visual_source": _voice_status_field(voice, "voice_visual_source"),
        "active_playback_status": _voice_status_field(voice, "active_playback_status"),
        "active_playback_id": _voice_status_field(voice, "active_playback_id"),
        "speaking_visual_active": _voice_status_field(voice, "speaking_visual_active"),
        "status_voice_visual_authority": "legacy_status",
        "raw_audio_present": False,
    }
    for key in AR6_STATUS_AUTHORITY_KEYS:
        value = _voice_status_field(voice, key)
        if value is not None:
            row[key] = value
    if str(row.get("authoritativeVoiceStateVersion") or "").strip().upper() == "AR6":
        row["voice_visual_active"] = bool(row.get("authoritativeVoiceVisualActive", False))
        row["voice_visual_energy"] = row.get("authoritativeVoiceVisualEnergy", 0.0)
        row["voice_visual_source"] = row.get("authoritativeStateSource") or row.get("voice_visual_source")
        row["active_playback_status"] = row.get("activePlaybackStatus") or row.get("authoritativePlaybackStatus") or row.get("active_playback_status")
        row["active_playback_id"] = row.get("activePlaybackId") or row.get("authoritativePlaybackId") or row.get("active_playback_id")
        row["status_voice_visual_authority"] = "ar6_authoritative_status"
    return sanitize_scalar_payload(row)


def _row_authority_time_ms(row: dict[str, Any]) -> float | None:
    for key in (
        "qml_receive_time_ms",
        "bridge_receive_wall_time_ms",
        "status_wall_time_ms",
        "payload_wall_time_ms",
    ):
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return None


def _latest_authority_at(
    authority_rows: list[dict[str, Any]],
    timestamp_ms: float | None,
) -> dict[str, Any]:
    if not authority_rows:
        return {}
    if timestamp_ms is None:
        return authority_rows[-1]
    latest: dict[str, Any] = {}
    for row in authority_rows:
        row_time = _row_authority_time_ms(row)
        if row_time is None:
            continue
        if row_time > timestamp_ms + 500.0:
            break
        if row_time <= timestamp_ms + 500.0:
            latest = row
    return latest or authority_rows[-1]


def _enrich_status_rows_with_authority(
    status_rows: list[dict[str, Any]],
    qml_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    authority_rows = [
        sanitize_scalar_payload(row)
        for row in qml_rows
        if str(row.get("authoritativeVoiceStateVersion") or "").strip().upper() == "AR6"
    ]
    authority_rows.sort(key=lambda row: _row_authority_time_ms(row) or 0.0)
    enriched: list[dict[str, Any]] = []
    for status_row in status_rows:
        row = sanitize_scalar_payload(status_row)
        row.setdefault("legacy_voice_visual_active", row.get("voice_visual_active"))
        row.setdefault("legacy_voice_visual_energy", row.get("voice_visual_energy"))
        row.setdefault("legacy_voice_visual_source", row.get("voice_visual_source"))
        authority = _latest_authority_at(
            authority_rows,
            _row_authority_time_ms(row),
        )
        if authority:
            for key in AR6_STATUS_AUTHORITY_KEYS:
                if key in authority and authority.get(key) is not None:
                    row[key] = authority.get(key)
            row["voice_visual_active"] = bool(
                authority.get("authoritativeVoiceVisualActive", False)
            )
            row["voice_visual_energy"] = authority.get(
                "authoritativeVoiceVisualEnergy",
                0.0,
            )
            row["voice_visual_source"] = (
                authority.get("authoritativeStateSource")
                or row.get("legacy_voice_visual_source")
                or row.get("voice_visual_source")
            )
            row["active_playback_status"] = (
                authority.get("activePlaybackStatus")
                or authority.get("authoritativePlaybackStatus")
                or row.get("active_playback_status")
            )
            row["active_playback_id"] = (
                authority.get("activePlaybackId")
                or authority.get("authoritativePlaybackId")
                or row.get("active_playback_id")
            )
            row["status_voice_visual_authority"] = "ar6_authoritative_overlay"
        else:
            row.setdefault("status_voice_visual_authority", "legacy_status")
        row["raw_audio_present"] = False
        enriched.append(sanitize_scalar_payload(row))
    return enriched


def _collect_events(
    base_url: str,
    *,
    session_id: str,
    timeout_seconds: float,
    qml_diag_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    cursor = 0
    deadline = time.time() + timeout_seconds
    completion_seen_at: float | None = None
    while time.time() < deadline:
        try:
            replay = _request_json(
                base_url,
                "GET",
                "/events",
                timeout=3.0,
                query={"session_id": session_id, "cursor": cursor, "limit": 300},
            )
            batch = replay.get("events") if isinstance(replay.get("events"), list) else []
            for event in batch:
                if isinstance(event, dict) and int(event.get("cursor") or 0) > cursor:
                    events.append(sanitize_scalar_payload(event))
                    cursor = max(cursor, int(event.get("cursor") or cursor))
        except Exception:
            pass
        try:
            status = _request_json(base_url, "GET", "/status", timeout=3.0)
            status_rows.append(_status_row_from_voice_status(status))
        except Exception:
            pass
        event_types = {str(event.get("event_type") or "") for event in events[-20:]}
        if (
            "voice.playback_completed" in event_types
            or "voice.playback_stream_completed" in event_types
        ):
            if completion_seen_at is None:
                completion_seen_at = time.time()
            elif time.time() - completion_seen_at >= 3.0:
                break
        if qml_diag_path.exists() and completion_seen_at is not None:
            try:
                qml_lines = qml_diag_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                qml_lines = []
            if len(qml_lines) > 4 and time.time() - completion_seen_at >= 2.0:
                break
        time.sleep(0.15)
    return events, status_rows


def _read_qml_rows(qml_diag_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not qml_diag_path.exists():
        return rows
    for line in qml_diag_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(sanitize_scalar_payload(payload))
    return rows


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "active", "speaking"}
    return bool(value)


def _first_ms(
    rows: list[dict[str, Any]],
    key: str,
    *,
    truth_key: str | None = None,
    after_ms: float | None = None,
) -> float | None:
    for row in rows:
        if truth_key is not None and not _as_bool(row.get(truth_key)):
            continue
        value = row.get(key)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric <= 0.0:
            continue
        if after_ms is not None and numeric <= float(after_ms):
            continue
        return numeric
    return None


def _row_time_ms(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return None


def _first_event_ms(events: list[dict[str, Any]], event_types: set[str]) -> float | None:
    for event in events:
        if str(event.get("event_type") or "") in event_types:
            return _parse_iso_ms(event.get("timestamp") or event.get("created_at"))
    return None


def _event_ms(event: dict[str, Any]) -> float | None:
    return _parse_iso_ms(event.get("timestamp") or event.get("created_at"))


def _event_playback_id(event: dict[str, Any]) -> str:
    payload = _event_payload(event)
    metadata = _event_metadata(event)
    for source in (payload, metadata):
        value = source.get("playback_id") or source.get("voice_visual_playback_id")
        if value:
            return str(value)
    return ""


def _row_playback_id(row: dict[str, Any]) -> str:
    for key in (
        "playback_id",
        "voice_visual_playback_id",
        "qmlReceivedPlaybackId",
        "bridge_playback_id",
        "authoritativePlaybackId",
        "activePlaybackId",
        "currentAnchorPlaybackId",
        "anchorAcceptedPlaybackId",
        "anchorSpeakingEntryPlaybackId",
        "qsgRendererPlaybackId",
        "qsgRendererReceivedEnergyForPlaybackId",
        "qsgRendererPaintedPlaybackId",
        "finalSpeakingEnergyPlaybackId",
        "blobDrivePlaybackId",
    ):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def _playback_event_times(
    events: list[dict[str, Any]],
    event_types: set[str],
) -> dict[str, float]:
    times: dict[str, float] = {}
    for event in events:
        if str(event.get("event_type") or "") not in event_types:
            continue
        playback_id = _event_playback_id(event)
        timestamp = _event_ms(event)
        if not playback_id or timestamp is None:
            continue
        times.setdefault(playback_id, timestamp)
    return times


def _build_timelines(
    events: list[dict[str, Any]],
    qml_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pcm_rows: list[dict[str, Any]] = []
    payload_rows: list[dict[str, Any]] = []
    playback_start_by_id = _playback_event_times(
        events,
        {"voice.playback_started", "voice.tts_first_chunk_received"},
    )
    playback_start_wall_ms = _first_event_ms(
        events,
        {"voice.playback_started", "voice.tts_first_chunk_received"},
    )
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type == "voice.pcm_submitted_to_playback":
            diagnostics = _event_metadata(event).get("voice_ar1_pcm_submit")
            if isinstance(diagnostics, dict):
                row = sanitize_scalar_payload(diagnostics)
                playback_id = _row_playback_id(row) or _event_playback_id(event)
                if playback_id and not row.get("playback_id"):
                    row["playback_id"] = playback_id
                sample_time_ms = _row_float(row, "pcm_sample_time_ms")
                playback_start_for_row = (
                    playback_start_by_id.get(playback_id)
                    if playback_id
                    else playback_start_wall_ms
                )
                if playback_start_for_row is None:
                    playback_start_for_row = playback_start_wall_ms
                if playback_start_for_row is not None and sample_time_ms is not None:
                    row["pcm_audible_wall_time_ms"] = round(
                        playback_start_for_row + sample_time_ms,
                        3,
                    )
                pcm_rows.append(row)
        elif event_type == "voice.visualizer_update":
            voice = _voice_from_visualizer_event(event)
            if voice:
                payload_rows.append(voice)
    def stage_samples(
        rows: list[dict[str, Any]],
        *time_keys: str,
    ) -> list[tuple[float, dict[str, Any]]]:
        samples: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            timestamp = _row_time_ms(row, *time_keys)
            if timestamp is not None:
                samples.append((timestamp, row))
        return sorted(samples, key=lambda item: item[0])

    def latest_at(
        samples: list[tuple[float, dict[str, Any]]],
        timestamp: float,
    ) -> dict[str, Any]:
        latest: dict[str, Any] = {}
        for sample_time, row in samples:
            if sample_time > timestamp:
                break
            latest = row
        return latest

    pcm_samples = stage_samples(
        pcm_rows,
        "pcm_audible_wall_time_ms",
        "pcm_submit_wall_time_ms",
    )
    payload_samples = stage_samples(payload_rows, "payload_wall_time_ms", "meter_wall_time_ms")
    qml_samples = stage_samples(qml_rows, "qml_receive_time_ms", "bridge_receive_wall_time_ms")
    sample_times = sorted(
        {
            round(timestamp, 3)
            for timestamp, _row in pcm_samples + payload_samples + qml_samples
            if timestamp > 0.0
        }
    )
    first_time = sample_times[0] if sample_times else time.time() * 1000.0
    timeline: list[dict[str, Any]] = []
    for abs_time in sample_times:
        pcm = latest_at(pcm_samples, abs_time)
        payload = latest_at(payload_samples, abs_time)
        qml = latest_at(qml_samples, abs_time)
        rel_time = float(abs_time) - float(first_time)
        row = sanitize_scalar_payload(
            {
                "time_ms": round(rel_time, 3),
                "pcm_energy": pcm.get("voice_visual_energy", ""),
                "meter_energy": payload.get("voice_visual_energy", ""),
                "payload_energy": payload.get("voice_visual_energy", ""),
                "bridge_energy": qml.get("bridge_voice_visual_energy", ""),
                "qml_received_energy": qml.get("qmlReceivedVoiceVisualEnergy", ""),
                "finalSpeakingEnergy": qml.get("finalSpeakingEnergy", ""),
                "blobScaleDrive": qml.get("blobScaleDrive", ""),
                "blobDeformationDrive": qml.get("blobDeformationDrive", ""),
                "blobRadiusScale": qml.get("blobRadiusScale", ""),
                "radianceDrive": qml.get("radianceDrive", ""),
                "ringDrive": qml.get("ringDrive", ""),
                "visualAmplitudeCompressionRatio": qml.get(
                    "visualAmplitudeCompressionRatio", ""
                ),
                "visualAmplitudeLatencyMs": qml.get("visualAmplitudeLatencyMs", ""),
                "anchor_paint_time": qml.get("anchorLastPaintTimeMs", ""),
                "dynamic_core_paint_time": qml.get("dynamicCoreLastPaintTimeMs", ""),
                "static_frame_paint_time": qml.get("staticFrameLastPaintTimeMs", ""),
                "voice_visual_active": qml.get(
                    "authoritativeVoiceVisualActive",
                    payload.get("voice_visual_active", ""),
                ),
                "hot_voice_visual_active": payload.get("voice_visual_active", ""),
                "authoritativeVoiceStateVersion": qml.get(
                    "authoritativeVoiceStateVersion", ""
                ),
                "authoritativeVoiceVisualActive": qml.get(
                    "authoritativeVoiceVisualActive", ""
                ),
                "authoritativeVoiceVisualEnergy": qml.get(
                    "authoritativeVoiceVisualEnergy", ""
                ),
                "authoritativePlaybackId": qml.get("authoritativePlaybackId", ""),
                "authoritativePlaybackStatus": qml.get(
                    "authoritativePlaybackStatus", ""
                ),
                "activePlaybackId": qml.get("activePlaybackId", ""),
                "activePlaybackStatus": qml.get("activePlaybackStatus", ""),
                "authoritativeStateSequence": qml.get(
                    "authoritativeStateSequence", ""
                ),
                "authoritativeStateSource": qml.get("authoritativeStateSource", ""),
                "lastAcceptedUpdateSource": qml.get("lastAcceptedUpdateSource", ""),
                "lastIgnoredUpdateSource": qml.get("lastIgnoredUpdateSource", ""),
                "staleBroadSnapshotIgnored": qml.get("staleBroadSnapshotIgnored", ""),
                "staleBroadSnapshotIgnoredCount": qml.get(
                    "staleBroadSnapshotIgnoredCount", ""
                ),
                "hotPathAcceptedCount": qml.get("hotPathAcceptedCount", ""),
                "terminalEventAcceptedCount": qml.get(
                    "terminalEventAcceptedCount", ""
                ),
                "playbackIdSwitchCount": qml.get("playbackIdSwitchCount", ""),
                "playbackIdMismatchIgnoredCount": qml.get(
                    "playbackIdMismatchIgnoredCount", ""
                ),
                "currentAnchorPlaybackId": qml.get("currentAnchorPlaybackId", ""),
                "lastAnchorPlaybackId": qml.get("lastAnchorPlaybackId", ""),
                "anchorPlaybackIdSwitchCount": qml.get("anchorPlaybackIdSwitchCount", ""),
                "anchorAcceptedPlaybackId": qml.get("anchorAcceptedPlaybackId", ""),
                "anchorIgnoredPlaybackId": qml.get("anchorIgnoredPlaybackId", ""),
                "anchorSpeakingEntryPlaybackId": qml.get("anchorSpeakingEntryPlaybackId", ""),
                "anchorSpeakingExitPlaybackId": qml.get("anchorSpeakingExitPlaybackId", ""),
                "anchorSpeakingEntryReason": qml.get("anchorSpeakingEntryReason", ""),
                "anchorSpeakingExitReason": qml.get("anchorSpeakingExitReason", ""),
                "qsgRendererPlaybackId": qml.get("qsgRendererPlaybackId", ""),
                "qsgRendererReceivedEnergyForPlaybackId": qml.get("qsgRendererReceivedEnergyForPlaybackId", ""),
                "qsgRendererPaintedPlaybackId": qml.get("qsgRendererPaintedPlaybackId", ""),
                "finalSpeakingEnergyPlaybackId": qml.get("finalSpeakingEnergyPlaybackId", ""),
                "blobDrivePlaybackId": qml.get("blobDrivePlaybackId", ""),
                "voiceVisualActiveFlapCount": qml.get(
                    "voiceVisualActiveFlapCount", ""
                ),
                "speaking_visual_active": qml.get("speaking_visual_active", ""),
                "anchor_visual_state": qml.get("anchorCurrentVisualState", ""),
                "playback_status": qml.get(
                    "authoritativePlaybackStatus",
                    qml.get("playback_status", ""),
                ),
                "fog_active": qml.get("fog_active", ""),
                "frame_gap_ms": qml.get("anchorFrameDeltaMs", ""),
                "pcm_submit_wall_time_ms": pcm.get("pcm_submit_wall_time_ms"),
                "pcm_audible_wall_time_ms": pcm.get("pcm_audible_wall_time_ms"),
                "pcm_sample_time_ms": pcm.get("pcm_sample_time_ms"),
                "meter_wall_time_ms": payload.get("meter_wall_time_ms"),
                "payload_wall_time_ms": payload.get("payload_wall_time_ms"),
                "bridge_receive_time_ms": qml.get("bridge_receive_wall_time_ms"),
                "qml_receive_time_ms": qml.get("qml_receive_time_ms"),
                "finalSpeakingEnergyUpdatedAtMs": qml.get(
                    "finalSpeakingEnergyUpdatedAtMs"
                ),
                "raw_audio_present": False,
            }
        )
        timeline.append(row)
    stage_rows = {
        "pcm_rows": pcm_rows,
        "payload_rows": payload_rows,
        "qml_rows": qml_rows,
    }
    return timeline, stage_rows


def _ordered_playback_ids(
    events: list[dict[str, Any]],
    qml_rows: list[dict[str, Any]],
    payload_rows: list[dict[str, Any]],
) -> list[str]:
    ids: list[str] = []
    for event in events:
        playback_id = _event_playback_id(event)
        if playback_id and playback_id not in ids:
            ids.append(playback_id)
    for rows in (payload_rows, qml_rows):
        for row in rows:
            playback_id = _row_playback_id(row)
            if playback_id and playback_id not in ids:
                ids.append(playback_id)
    return ids


def _row_in_playback_window(
    row: dict[str, Any],
    *,
    playback_id: str,
    timestamp_ms: float | None,
    start_ms: float | None,
    stop_ms: float | None,
    allow_unkeyed: bool = False,
) -> bool:
    row_playback_id = _row_playback_id(row)
    if row_playback_id:
        if row_playback_id != playback_id:
            return False
    elif not allow_unkeyed:
        return False
    if timestamp_ms is None:
        return False
    if start_ms is not None and timestamp_ms < start_ms - 100.0:
        return False
    if stop_ms is not None and timestamp_ms > stop_ms + 100.0:
        return False
    return True


def _first_row_ms_for_playback(
    rows: list[dict[str, Any]],
    playback_id: str,
    *time_keys: str,
    truth_key: str | None = None,
    start_ms: float | None = None,
    stop_ms: float | None = None,
    allow_unkeyed: bool = False,
) -> float | None:
    for row in rows:
        timestamp = _row_time_ms(row, *time_keys)
        if not _row_in_playback_window(
            row,
            playback_id=playback_id,
            timestamp_ms=timestamp,
            start_ms=start_ms,
            stop_ms=stop_ms,
            allow_unkeyed=allow_unkeyed,
        ):
            continue
        if truth_key is not None and not _as_bool(row.get(truth_key)):
            continue
        return timestamp
    return None


def _first_inactive_row_ms_for_playback(
    rows: list[dict[str, Any]],
    playback_id: str,
    *time_keys: str,
    truth_key: str,
    after_ms: float | None,
    stop_ms: float | None = None,
    allow_unkeyed: bool = False,
) -> float | None:
    for row in rows:
        timestamp = _row_time_ms(row, *time_keys)
        if timestamp is None or (after_ms is not None and timestamp < after_ms):
            continue
        if not _row_in_playback_window(
            row,
            playback_id=playback_id,
            timestamp_ms=timestamp,
            start_ms=after_ms,
            stop_ms=stop_ms,
            allow_unkeyed=allow_unkeyed,
        ):
            continue
        if not _as_bool(row.get(truth_key)):
            return timestamp
    return None


def _per_playback_speaking_lifetimes(
    events: list[dict[str, Any]],
    qml_rows: list[dict[str, Any]],
    payload_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    playback_ids = _ordered_playback_ids(events, qml_rows, payload_rows)
    if not playback_ids:
        return []
    starts = _playback_event_times(
        events,
        {"voice.playback_started", "voice.tts_first_chunk_received"},
    )
    ends = _playback_event_times(
        events,
        {"voice.playback_completed", "voice.playback_stream_completed"},
    )
    ordered_starts = [
        (playback_id, starts.get(playback_id))
        for playback_id in playback_ids
        if starts.get(playback_id) is not None
    ]
    ordered_starts.sort(key=lambda item: float(item[1] or 0.0))
    next_start_by_id: dict[str, float] = {}
    for index, (playback_id, start_ms) in enumerate(ordered_starts[:-1]):
        next_start = ordered_starts[index + 1][1]
        if start_ms is not None and next_start is not None:
            next_start_by_id[playback_id] = float(next_start)

    lifetimes: list[dict[str, Any]] = []
    for playback_id in playback_ids:
        playback_start = starts.get(playback_id)
        next_start = next_start_by_id.get(playback_id)
        playback_end = ends.get(playback_id)
        window_stop = next_start if next_start is not None else None
        voice_true = _first_row_ms_for_playback(
            payload_rows,
            playback_id,
            "payload_wall_time_ms",
            "meter_wall_time_ms",
            truth_key="voice_visual_active",
            start_ms=playback_start,
            stop_ms=window_stop,
        )
        if playback_start is None:
            playback_start = voice_true or _first_row_ms_for_playback(
                qml_rows,
                playback_id,
                "qml_receive_time_ms",
                truth_key="authoritativeVoiceVisualActive",
                stop_ms=window_stop,
            )
        voice_false = _first_inactive_row_ms_for_playback(
            payload_rows,
            playback_id,
            "payload_wall_time_ms",
            "meter_wall_time_ms",
            truth_key="voice_visual_active",
            after_ms=playback_end or voice_true,
            stop_ms=window_stop,
        )
        release_reference_values = [
            value for value in (playback_end, voice_false) if value is not None
        ]
        release_reference = max(release_reference_values) if release_reference_values else None
        qml_true = _first_row_ms_for_playback(
            qml_rows,
            playback_id,
            "qml_receive_time_ms",
            truth_key="speaking_visual_active",
            start_ms=playback_start,
            stop_ms=window_stop,
        )
        anchor_true = _first_row_ms_for_playback(
            qml_rows,
            playback_id,
            "qml_receive_time_ms",
            truth_key="anchorSpeakingVisualActive",
            start_ms=playback_start,
            stop_ms=window_stop,
        )
        if anchor_true is None:
            anchor_true = qml_true
        inactive_stop = window_stop
        release_truncated = False
        if (
            release_reference is not None
            and next_start is not None
            and next_start - release_reference < 1000.0
        ):
            inactive_stop = next_start
            release_truncated = True
        qml_false = _first_inactive_row_ms_for_playback(
            qml_rows,
            playback_id,
            "qml_receive_time_ms",
            truth_key="speaking_visual_active",
            after_ms=release_reference or qml_true,
            stop_ms=inactive_stop,
            allow_unkeyed=True,
        )
        anchor_false = _first_inactive_row_ms_for_playback(
            qml_rows,
            playback_id,
            "qml_receive_time_ms",
            truth_key="anchorSpeakingVisualActive",
            after_ms=release_reference or anchor_true,
            stop_ms=inactive_stop,
            allow_unkeyed=True,
        )
        lifetime = speaking_lifetime_report(
            playback_start_ms=playback_start,
            playback_end_ms=playback_end,
            voice_visual_active_true_ms=voice_true,
            voice_visual_active_false_ms=voice_false,
            qml_speaking_true_ms=qml_true,
            qml_speaking_false_ms=qml_false,
            anchor_speaking_true_ms=anchor_true,
            anchor_speaking_false_ms=anchor_false,
        )
        lifetime["playback_id"] = playback_id
        lifetime["next_playback_start_time_ms"] = (
            round(next_start, 3) if next_start is not None else None
        )
        lifetime["release_observation_truncated_by_next_playback"] = release_truncated
        lifetime["raw_audio_present"] = False
        lifetimes.append(sanitize_scalar_payload(lifetime))
    return lifetimes


def _aggregate_playback_lifetimes(
    base_report: dict[str, Any],
    lifetimes: list[dict[str, Any]],
) -> dict[str, Any]:
    if not lifetimes:
        return base_report
    aggregate = dict(base_report)
    aggregate["playback_lifetimes"] = lifetimes
    aggregate["speaking_lifetime_method"] = "per_playback_authoritative"
    aggregate["playback_lifetime_count"] = len(lifetimes)
    max_fields = (
        "speaking_visual_start_delay_ms",
        "anchor_speaking_start_delay_ms",
        "speaking_visual_end_delay_ms",
        "anchor_speaking_stuck_after_audio_ms",
        "anchor_release_tail_ms",
    )
    for field in max_fields:
        values = []
        for lifetime in lifetimes:
            if field in {
                "speaking_visual_end_delay_ms",
                "anchor_speaking_stuck_after_audio_ms",
                "anchor_release_tail_ms",
            } and lifetime.get("release_observation_truncated_by_next_playback"):
                continue
            try:
                value = float(lifetime.get(field))
            except (TypeError, ValueError):
                continue
            values.append(value)
        if values:
            aggregate[field] = round(max(values), 3)
    aggregate["raw_audio_present"] = False
    return aggregate


def _ordered_boundary_playback_ids(
    events: list[dict[str, Any]],
    pcm_rows: list[dict[str, Any]],
    payload_rows: list[dict[str, Any]],
    qml_rows: list[dict[str, Any]],
) -> list[str]:
    ids: list[str] = []
    for event in events:
        playback_id = _event_playback_id(event)
        if playback_id and playback_id not in ids:
            ids.append(playback_id)
    for rows in (pcm_rows, payload_rows, qml_rows):
        for row in rows:
            playback_id = _row_playback_id(row)
            if playback_id and playback_id not in ids:
                ids.append(playback_id)
    return ids


def _event_ids_for_playback(
    events: list[dict[str, Any]],
    playback_id: str,
) -> dict[str, str]:
    result = {
        "playback_request_id": "",
        "speech_request_id": "",
        "session_id": "",
    }
    for event in events:
        if _event_playback_id(event) != playback_id:
            continue
        payload = _event_payload(event)
        metadata = _event_metadata(event)
        for key in result:
            value = payload.get(key) or metadata.get(key) or event.get(key)
            if value and not result[key]:
                result[key] = str(value)
    return result


def _row_with_energy_time_for_playback(
    rows: list[dict[str, Any]],
    playback_id: str,
    *,
    energy_keys: tuple[str, ...],
    time_keys: tuple[str, ...],
    threshold: float = 0.035,
    start_ms: float | None = None,
    stop_ms: float | None = None,
) -> float | None:
    for row in rows:
        timestamp = _row_time_ms(row, *time_keys)
        if not _row_in_playback_window(
            row,
            playback_id=playback_id,
            timestamp_ms=timestamp,
            start_ms=start_ms,
            stop_ms=stop_ms,
        ):
            continue
        if max((_row_float(row, key) or 0.0) for key in energy_keys) > threshold:
            return timestamp
    return None


def _first_qml_time_for_playback(
    qml_rows: list[dict[str, Any]],
    playback_id: str,
    *,
    truth_keys: tuple[str, ...] = (),
    energy_keys: tuple[str, ...] = (),
    threshold: float = 0.035,
    start_ms: float | None = None,
    stop_ms: float | None = None,
) -> float | None:
    for row in qml_rows:
        timestamp = _row_time_ms(row, "qml_receive_time_ms")
        if not _row_in_playback_window(
            row,
            playback_id=playback_id,
            timestamp_ms=timestamp,
            start_ms=start_ms,
            stop_ms=stop_ms,
        ):
            continue
        if truth_keys and any(_as_bool(row.get(key)) for key in truth_keys):
            return timestamp
        if energy_keys and max((_row_float(row, key) or 0.0) for key in energy_keys) > threshold:
            return timestamp
        if not truth_keys and not energy_keys:
            return timestamp
    return None


def _delay_ms(right: float | None, left: float | None) -> float | None:
    if right is None or left is None:
        return None
    return round(float(right) - float(left), 3)


def _boundary_classification(segment: dict[str, Any]) -> str:
    reference = segment.get("first_pcm_hot_path_energy_time_ms") or segment.get(
        "audible_playback_start_time_ms"
    )
    if reference is None:
        return "missing_pcm_energy"
    payload_delay = _delay_ms(segment.get("first_payload_active_time_ms"), reference)
    if payload_delay is None or payload_delay > 250.0:
        return "payload_handoff_delayed"
    qml_delay = _delay_ms(
        segment.get("first_qml_authoritative_active_time_ms"),
        segment.get("first_payload_active_time_ms"),
    )
    if qml_delay is None or qml_delay > 250.0:
        return "qml_handoff_delayed"
    anchor_delay = _delay_ms(
        segment.get("first_anchor_speaking_active_time_ms"),
        segment.get("first_qml_authoritative_active_time_ms"),
    )
    if anchor_delay is None or anchor_delay > 250.0:
        return "anchor_entry_delayed"
    final_delay = _delay_ms(
        segment.get("first_finalSpeakingEnergy_time_ms"),
        segment.get("first_qml_authoritative_active_time_ms"),
    )
    if final_delay is None or final_delay > 250.0:
        return "final_energy_delayed"
    blob_delay = _delay_ms(
        segment.get("first_blobScaleDrive_time_ms"),
        segment.get("first_finalSpeakingEnergy_time_ms"),
    )
    if blob_delay is None or blob_delay > 250.0:
        return "blob_drive_delayed"
    return "playback_boundary_pass"


def _playback_boundary_segments(
    events: list[dict[str, Any]],
    pcm_rows: list[dict[str, Any]],
    payload_rows: list[dict[str, Any]],
    qml_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    playback_ids = _ordered_boundary_playback_ids(events, pcm_rows, payload_rows, qml_rows)
    if not playback_ids:
        return []
    starts = _playback_event_times(
        events,
        {"voice.playback_started", "voice.tts_first_chunk_received"},
    )
    ends = _playback_event_times(
        events,
        {"voice.playback_completed", "voice.playback_stream_completed"},
    )
    start_candidates: list[tuple[str, float]] = []
    for playback_id in playback_ids:
        first_pcm = _first_row_ms_for_playback(
            pcm_rows,
            playback_id,
            "pcm_audible_wall_time_ms",
            "pcm_submit_wall_time_ms",
            start_ms=None,
            stop_ms=None,
        )
        start = starts.get(playback_id) or first_pcm
        if start is not None:
            start_candidates.append((playback_id, start))
    start_candidates.sort(key=lambda item: item[1])
    next_start_by_id: dict[str, float] = {}
    for index, (playback_id, _start) in enumerate(start_candidates[:-1]):
        next_start_by_id[playback_id] = start_candidates[index + 1][1]

    segments: list[dict[str, Any]] = []
    for playback_id in playback_ids:
        ids = _event_ids_for_playback(events, playback_id)
        next_start = next_start_by_id.get(playback_id)
        window_stop = next_start
        playback_start = starts.get(playback_id)
        pcm_first = _first_row_ms_for_playback(
            pcm_rows,
            playback_id,
            "pcm_audible_wall_time_ms",
            "pcm_submit_wall_time_ms",
            start_ms=playback_start,
            stop_ms=window_stop,
        )
        pcm_hot = _row_with_energy_time_for_playback(
            pcm_rows,
            playback_id,
            energy_keys=("voice_visual_energy", "rms", "peak"),
            time_keys=("pcm_audible_wall_time_ms", "pcm_submit_wall_time_ms"),
            start_ms=playback_start,
            stop_ms=window_stop,
        )
        payload_active = _first_row_ms_for_playback(
            payload_rows,
            playback_id,
            "payload_wall_time_ms",
            "meter_wall_time_ms",
            truth_key="voice_visual_active",
            start_ms=pcm_first or playback_start,
            stop_ms=window_stop,
        )
        bridge_active = _first_qml_time_for_playback(
            qml_rows,
            playback_id,
            truth_keys=("bridge_voice_visual_active", "authoritativeVoiceVisualActive"),
            start_ms=payload_active or pcm_first or playback_start,
            stop_ms=window_stop,
        )
        qml_active = _first_qml_time_for_playback(
            qml_rows,
            playback_id,
            truth_keys=("authoritativeVoiceVisualActive", "qmlReceivedVoiceVisualActive"),
            start_ms=payload_active or pcm_first or playback_start,
            stop_ms=window_stop,
        )
        anchor_active = _first_qml_time_for_playback(
            qml_rows,
            playback_id,
            truth_keys=("anchorSpeakingVisualActive", "speaking_visual_active"),
            start_ms=qml_active or payload_active or pcm_first or playback_start,
            stop_ms=window_stop,
        )
        final_energy = _first_qml_time_for_playback(
            qml_rows,
            playback_id,
            energy_keys=("finalSpeakingEnergy",),
            start_ms=qml_active or payload_active or pcm_first or playback_start,
            stop_ms=window_stop,
        )
        blob_drive = _first_qml_time_for_playback(
            qml_rows,
            playback_id,
            energy_keys=("blobScaleDrive",),
            start_ms=final_energy or qml_active or payload_active or pcm_first or playback_start,
            stop_ms=window_stop,
        )
        paint_time = None
        for row in qml_rows:
            timestamp = _row_time_ms(row, "qml_receive_time_ms")
            if not _row_in_playback_window(
                row,
                playback_id=playback_id,
                timestamp_ms=timestamp,
                start_ms=anchor_active or qml_active or payload_active or pcm_first,
                stop_ms=window_stop,
            ):
                continue
            paint_time = _row_time_ms(row, "anchorLastPaintTimeMs", "dynamicCoreLastPaintTimeMs")
            if paint_time is not None:
                break
        playback_complete = ends.get(playback_id)
        if playback_complete is None:
            playback_complete = _first_inactive_row_ms_for_playback(
                payload_rows,
                playback_id,
                "payload_wall_time_ms",
                "meter_wall_time_ms",
                truth_key="voice_visual_active",
                after_ms=payload_active,
                stop_ms=window_stop,
            )
        anchor_release = _first_inactive_row_ms_for_playback(
            qml_rows,
            playback_id,
            "qml_receive_time_ms",
            truth_key="anchorSpeakingVisualActive",
            after_ms=playback_complete or anchor_active,
            stop_ms=window_stop,
            allow_unkeyed=True,
        )
        reference = pcm_hot or pcm_first or playback_start
        segment = {
            "playback_id": playback_id,
            **ids,
            "audible_playback_start_time_ms": pcm_first or playback_start,
            "first_pcm_hot_path_energy_time_ms": pcm_hot,
            "first_bridge_authoritative_active_time_ms": bridge_active,
            "first_payload_active_time_ms": payload_active,
            "first_qml_authoritative_active_time_ms": qml_active,
            "first_anchor_speaking_active_time_ms": anchor_active,
            "first_finalSpeakingEnergy_time_ms": final_energy,
            "first_blobScaleDrive_time_ms": blob_drive,
            "first_paint_after_speaking_time_ms": paint_time,
            "playback_completed_time_ms": playback_complete,
            "anchor_release_time_ms": anchor_release,
            "next_playback_start_time_ms": next_start,
            "payload_delay_from_pcm_ms": _delay_ms(payload_active, reference),
            "qml_delay_from_payload_ms": _delay_ms(qml_active, payload_active),
            "anchor_delay_from_qml_ms": _delay_ms(anchor_active, qml_active),
            "anchor_start_delay_from_pcm_ms": _delay_ms(anchor_active, reference),
            "final_energy_delay_from_qml_ms": _delay_ms(final_energy, qml_active),
            "blob_drive_delay_from_final_ms": _delay_ms(blob_drive, final_energy),
            "paint_delay_from_anchor_ms": _delay_ms(paint_time, anchor_active),
            "release_tail_ms": _delay_ms(anchor_release, playback_complete),
            "raw_audio_present": False,
        }
        segment["boundary_classification"] = _boundary_classification(segment)
        segments.append(sanitize_scalar_payload(segment))
    return segments


def _speaking_lifetime(events: list[dict[str, Any]], qml_rows: list[dict[str, Any]], payload_rows: list[dict[str, Any]]) -> dict[str, Any]:
    playback_start = _first_event_ms(
        events,
        {"voice.playback_started", "voice.tts_first_chunk_received"},
    )
    playback_end = _first_event_ms(
        events,
        {"voice.playback_completed", "voice.playback_stream_completed"},
    )
    voice_true = _first_ms(payload_rows, "payload_wall_time_ms", truth_key="voice_visual_active")
    if voice_true is None:
        voice_true = _first_ms(payload_rows, "meter_wall_time_ms", truth_key="voice_visual_active")
    voice_false = None
    voice_false_candidates: list[float] = []
    for row in payload_rows:
        timestamp = _row_time_ms(row, "payload_wall_time_ms", "meter_wall_time_ms")
        if timestamp is None or voice_true is None or timestamp <= voice_true:
            continue
        if not _as_bool(row.get("voice_visual_active")):
            voice_false_candidates.append(timestamp)
    if voice_false_candidates:
        if playback_end is not None:
            voice_false = next(
                (
                    timestamp
                    for timestamp in voice_false_candidates
                    if timestamp >= playback_end - 25.0
                ),
                voice_false_candidates[-1],
            )
        else:
            voice_false = voice_false_candidates[0]
    qml_true = _first_ms(qml_rows, "qml_receive_time_ms", truth_key="speaking_visual_active")
    qml_false = None
    anchor_true = _first_ms(qml_rows, "anchorSpeakingEnteredAtMs")
    anchor_false = None
    qml_last_active = None
    anchor_last_active = None
    release_reference_values = [
        value for value in (playback_end, voice_false) if value is not None
    ]
    release_reference = max(release_reference_values) if release_reference_values else None
    for row in qml_rows:
        qml_timestamp = _row_time_ms(row, "qml_receive_time_ms")
        if qml_timestamp is not None and _as_bool(row.get("speaking_visual_active")):
            qml_last_active = qml_timestamp
        if qml_timestamp is not None and _as_bool(row.get("anchorSpeakingVisualActive")):
            anchor_last_active = qml_timestamp
        after_release_reference = (
            release_reference is None
            or (qml_timestamp is not None and qml_timestamp >= release_reference)
        )
        if (
            qml_false is None
            and qml_true is not None
            and qml_timestamp is not None
            and qml_timestamp > qml_true
            and after_release_reference
            and not _as_bool(row.get("speaking_visual_active"))
        ):
            qml_false = qml_timestamp
        anchor_candidate = _row_time_ms(row, "anchorSpeakingExitedAtMs")
        if (
            anchor_false is None
            and anchor_true is not None
            and anchor_candidate is not None
            and anchor_candidate > float(anchor_true)
            and (release_reference is None or anchor_candidate >= release_reference)
        ):
            anchor_false = anchor_candidate
        if (
            anchor_false is None
            and anchor_true is not None
            and qml_timestamp is not None
            and qml_timestamp > float(anchor_true)
            and after_release_reference
            and not _as_bool(row.get("anchorSpeakingVisualActive"))
        ):
            anchor_false = qml_timestamp
    report = speaking_lifetime_report(
        playback_start_ms=playback_start,
        playback_end_ms=playback_end,
        voice_visual_active_true_ms=voice_true,
        voice_visual_active_false_ms=voice_false,
        qml_speaking_true_ms=qml_true,
        qml_speaking_false_ms=qml_false,
        anchor_speaking_true_ms=anchor_true,
        anchor_speaking_false_ms=anchor_false,
    )
    if playback_end is not None:
        if qml_false is None and qml_last_active is not None and qml_last_active > playback_end:
            report["qml_speaking_still_active_last_observed_ms"] = round(qml_last_active, 3)
            report["qml_speaking_still_active_after_audio_ms"] = round(
                qml_last_active - playback_end,
                3,
            )
        if (
            anchor_false is None
            and anchor_last_active is not None
            and anchor_last_active > playback_end
        ):
            lower_bound = round(anchor_last_active - playback_end, 3)
            report["anchor_speaking_still_active_last_observed_ms"] = round(
                anchor_last_active,
                3,
            )
            report["anchor_speaking_still_active_after_audio_ms"] = lower_bound
            if report.get("anchor_speaking_stuck_after_audio_ms") is None:
                report["anchor_speaking_stuck_after_audio_ms"] = lower_bound
    report["raw_audio_present"] = False
    return _aggregate_playback_lifetimes(
        report,
        _per_playback_speaking_lifetimes(events, qml_rows, payload_rows),
    )


def _row_float(row: dict[str, Any], key: str) -> float | None:
    try:
        value = float(row.get(key))
    except (TypeError, ValueError):
        return None
    if value <= 0.0:
        return None
    return value


def _row_number(row: dict[str, Any], key: str) -> float | None:
    try:
        value = float(row.get(key))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _counter_fps(
    rows: list[dict[str, Any]],
    counter_key: str,
    *,
    time_key: str = "qml_receive_time_ms",
) -> float | None:
    samples = sorted(
        (time_value, count_value)
        for row in rows
        for time_value in [_row_number(row, time_key)]
        for count_value in [_row_number(row, counter_key)]
        if time_value is not None and count_value is not None
    )
    if len(samples) < 2:
        return None
    first_time, first_count = samples[0]
    last_time, last_count = samples[-1]
    elapsed_ms = max(0.0, last_time - first_time)
    if elapsed_ms <= 0.0 or last_count < first_count:
        return None
    return round((last_count - first_count) * 1000.0 / elapsed_ms, 3)


def _render_metrics(qml_rows: list[dict[str, Any]]) -> dict[str, Any]:
    renderer_values = [
        str(row.get("effectiveAnchorRenderer") or "").strip()
        for row in qml_rows
        if str(row.get("effectiveAnchorRenderer") or "").strip()
    ]
    frame_gaps = [
        value
        for row in qml_rows
        for value in [_row_float(row, "anchorFrameDeltaMs")]
        if value is not None
    ]
    rolling_max_gaps = [
        value
        for row in qml_rows
        for value in [_row_float(row, "maxFrameGapMs")]
        if value is not None
    ]
    speaking_rows = [
        row
        for row in qml_rows
        if _as_bool(row.get("speaking_visual_active"))
        or _as_bool(row.get("anchorSpeakingVisualActive"))
    ]
    qml_receive_times = [
        value
        for row in qml_rows
        for value in [_row_float(row, "qml_receive_time_ms")]
        if value is not None
    ]
    speaking_qml_receive_times = [
        value
        for row in speaking_rows
        for value in [_row_float(row, "qml_receive_time_ms")]
        if value is not None
    ]
    qml_receive_gaps = [
        qml_receive_times[index] - qml_receive_times[index - 1]
        for index in range(1, len(qml_receive_times))
    ]
    speaking_qml_receive_gaps = [
        speaking_qml_receive_times[index] - speaking_qml_receive_times[index - 1]
        for index in range(1, len(speaking_qml_receive_times))
    ]
    qml_diagnostic_max_gaps = [
        value
        for row in qml_rows
        for value in [_row_float(row, "qml_diagnostic_max_gap_ms")]
        if value is not None
    ]
    shared_animation_fps_during_speaking = [
        value
        for row in speaking_rows
        for value in [_row_float(row, "sharedAnimationClockFpsDuringSpeaking")]
        if value is not None
    ]
    speaking_frame_gaps = [
        value
        for row in speaking_rows
        for value in [_row_float(row, "anchorFrameDeltaMs")]
        if value is not None
    ]
    anchor_paint_fps_all = _counter_fps(qml_rows, "anchorPaintCount")
    anchor_paint_fps_speaking = _counter_fps(speaking_rows, "anchorPaintCount")
    anchor_request_paint_fps_all = _counter_fps(qml_rows, "anchorRequestPaintCount")
    anchor_request_paint_fps_speaking = _counter_fps(
        speaking_rows, "anchorRequestPaintCount"
    )
    anchor_local_speaking_frame_fps = _counter_fps(
        speaking_rows, "anchorLocalSpeakingFrameTickCount"
    )
    dynamic_core_paint_fps_all = _counter_fps(qml_rows, "dynamicCorePaintCount")
    dynamic_core_paint_fps_speaking = _counter_fps(
        speaking_rows, "dynamicCorePaintCount"
    )
    dynamic_core_request_fps_all = _counter_fps(
        qml_rows, "dynamicCoreRequestPaintCount"
    )
    dynamic_core_request_fps_speaking = _counter_fps(
        speaking_rows, "dynamicCoreRequestPaintCount"
    )
    static_frame_paint_fps_all = _counter_fps(qml_rows, "staticFramePaintCount")
    static_frame_paint_fps_speaking = _counter_fps(
        speaking_rows, "staticFramePaintCount"
    )
    fog_tick_fps_during_speaking = [
        value
        for row in speaking_rows
        for value in [_row_float(row, "fogTickFps")]
        if value is not None
    ]
    max_all = max(frame_gaps or rolling_max_gaps or qml_receive_gaps or [0.0])
    max_speaking = max(speaking_frame_gaps) if speaking_frame_gaps else None
    max_qml_gap = max(qml_receive_gaps) if qml_receive_gaps else None
    max_qml_gap_speaking = (
        max(speaking_qml_receive_gaps) if speaking_qml_receive_gaps else None
    )
    max_diagnostic_gap = max(qml_diagnostic_max_gaps) if qml_diagnostic_max_gaps else None
    classification_gap = (
        max_speaking
        if max_speaking is not None
        else max_qml_gap_speaking
        if max_qml_gap_speaking is not None
        else max_qml_gap
        if max_qml_gap is not None
        else max_all
    )
    shared_fps_min = (
        min(shared_animation_fps_during_speaking)
        if shared_animation_fps_during_speaking
        else None
    )
    cadence_gap_stable = classification_gap is not None and classification_gap <= 100.0
    effective_anchor_paint_fps = (
        anchor_paint_fps_speaking
        if anchor_paint_fps_speaking is not None
        else anchor_paint_fps_all
    )
    request_paint_storm = (
        anchor_request_paint_fps_speaking is not None
        and anchor_request_paint_fps_speaking > 70.0
    )
    cadence_fps_stable = (
        effective_anchor_paint_fps is not None
        and effective_anchor_paint_fps >= 30.0
        and not request_paint_storm
    )
    shared_clock_under_target = (
        shared_fps_min is not None and shared_fps_min < 30.0
    )
    local_anchor_clock_compensated = (
        shared_clock_under_target
        and cadence_gap_stable
        and cadence_fps_stable
        and dynamic_core_paint_fps_speaking is not None
        and dynamic_core_paint_fps_speaking >= 30.0
        and anchor_local_speaking_frame_fps is not None
        and anchor_local_speaking_frame_fps >= 30.0
    )
    return {
        "effectiveAnchorRenderer": renderer_values[-1] if renderer_values else "",
        "maxFrameGapMs": round(classification_gap, 3),
        "maxFrameGapMsAll": round(max_all, 3),
        "maxFrameGapMsDuringSpeaking": (
            round(max_speaking, 3) if max_speaking is not None else None
        ),
        "qmlDiagnosticMaxGapMs": (
            round(max_diagnostic_gap, 3) if max_diagnostic_gap is not None else None
        ),
        "qmlReceiveMaxGapMs": round(max_qml_gap, 3) if max_qml_gap is not None else None,
        "qmlReceiveMaxGapMsDuringSpeaking": (
            round(max_qml_gap_speaking, 3)
            if max_qml_gap_speaking is not None
            else None
        ),
        "longFramesOver33Ms": sum(1 for value in frame_gaps if value > 33.0),
        "longFramesOver50Ms": sum(1 for value in frame_gaps if value > 50.0),
        "longFramesOver100Ms": sum(1 for value in frame_gaps if value > 100.0),
        "longFramesOver33MsDuringSpeaking": sum(
            1 for value in speaking_frame_gaps if value > 33.0
        ),
        "longFramesOver50MsDuringSpeaking": sum(
            1 for value in speaking_frame_gaps if value > 50.0
        ),
        "longFramesOver100MsDuringSpeaking": sum(
            1 for value in speaking_frame_gaps if value > 100.0
        ),
        "renderCadenceDuringSpeakingStable": cadence_gap_stable and cadence_fps_stable,
        "sharedClockUnderTargetButAnchorLocalClockCompensated": local_anchor_clock_compensated,
        "sharedAnimationClockFpsDuringSpeakingMin": (
            round(shared_fps_min, 3)
            if shared_fps_min is not None
            else None
        ),
        "sharedAnimationClockFpsDuringSpeakingMean": _mean_or_none(
            shared_animation_fps_during_speaking
        ),
        "sharedAnimationClockFpsDuringSpeakingMax": (
            round(max(shared_animation_fps_during_speaking), 3)
            if shared_animation_fps_during_speaking
            else None
        ),
        "frameSwappedFps": 0,
        "frameSwappedAvailable": False,
        "frameSwappedUnavailableReason": "production_window_frameSwapped_not_exposed_to_probe",
        "anchorPaintFps": effective_anchor_paint_fps,
        "anchorPaintFpsAll": anchor_paint_fps_all,
        "anchorPaintFpsDuringSpeaking": anchor_paint_fps_speaking,
        "anchorRequestPaintFps": anchor_request_paint_fps_all,
        "anchorRequestPaintFpsDuringSpeaking": anchor_request_paint_fps_speaking,
        "dynamicCorePaintFps": dynamic_core_paint_fps_all,
        "dynamicCorePaintFpsDuringSpeaking": dynamic_core_paint_fps_speaking,
        "dynamicCoreRequestPaintFps": dynamic_core_request_fps_all,
        "dynamicCoreRequestPaintFpsDuringSpeaking": dynamic_core_request_fps_speaking,
        "staticFramePaintFps": static_frame_paint_fps_all,
        "staticFramePaintFpsDuringSpeaking": static_frame_paint_fps_speaking,
        "anchorLocalSpeakingFrameFps": anchor_local_speaking_frame_fps,
        "requestPaintStormDetected": request_paint_storm,
        "fogTickFpsDuringSpeakingMin": (
            round(min(fog_tick_fps_during_speaking), 3)
            if fog_tick_fps_during_speaking
            else None
        ),
        "fogTickFpsDuringSpeakingMean": _mean_or_none(fog_tick_fps_during_speaking),
        "fogTickFpsDuringSpeakingMax": (
            round(max(fog_tick_fps_during_speaking), 3)
            if fog_tick_fps_during_speaking
            else None
        ),
        "anchorPaintCount": max(
            [
                int(value)
                for row in qml_rows
                for value in [_row_float(row, "anchorPaintCount")]
                if value is not None
            ]
            or [0]
        ),
        "anchorRequestPaintCount": max(
            [
                int(value)
                for row in qml_rows
                for value in [_row_float(row, "anchorRequestPaintCount")]
                if value is not None
            ]
            or [0]
        ),
        "dynamicCorePaintCount": max(
            [
                int(value)
                for row in qml_rows
                for value in [_row_float(row, "dynamicCorePaintCount")]
                if value is not None
            ]
            or [0]
        ),
        "dynamicCoreRequestPaintCount": max(
            [
                int(value)
                for row in qml_rows
                for value in [_row_float(row, "dynamicCoreRequestPaintCount")]
                if value is not None
            ]
            or [0]
        ),
        "staticFramePaintCount": max(
            [
                int(value)
                for row in qml_rows
                for value in [_row_float(row, "staticFramePaintCount")]
                if value is not None
            ]
            or [0]
        ),
        "qmlRowsDuringSpeaking": len(speaking_rows),
        "raw_audio_present": False,
    }


def _mean_or_none(values: list[float]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 3)


def _field_values(
    rows: list[dict[str, Any]],
    key: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _row_float(row, key)
        if value is None:
            continue
        if minimum is not None and value < minimum:
            continue
        if maximum is not None and value > maximum:
            continue
        values.append(value)
    return values


def _nearest_previous_deltas(
    source_times: list[float],
    target_times: list[float],
    *,
    max_window_ms: float = 5000.0,
) -> list[float]:
    source = sorted(source_times)
    deltas: list[float] = []
    cursor = 0
    latest: float | None = None
    for target in sorted(target_times):
        while cursor < len(source) and source[cursor] <= target:
            latest = source[cursor]
            cursor += 1
        if latest is None:
            continue
        delta = target - latest
        if 0.0 <= delta <= max_window_ms:
            deltas.append(delta)
    return deltas


def _nearest_forward_deltas(
    source_times: list[float],
    target_times: list[float],
    *,
    max_window_ms: float = 5000.0,
) -> list[float]:
    target = sorted(target_times)
    deltas: list[float] = []
    cursor = 0
    for source in sorted(source_times):
        while cursor < len(target) and target[cursor] < source:
            cursor += 1
        if cursor >= len(target):
            break
        delta = target[cursor] - source
        if 0.0 <= delta <= max_window_ms:
            deltas.append(delta)
    return deltas


def _stage_latency_metrics(
    stage_rows: dict[str, Any],
    qml_rows: list[dict[str, Any]],
) -> dict[str, float | None]:
    pcm_rows = list(stage_rows.get("pcm_rows", []))
    payload_rows = list(stage_rows.get("payload_rows", []))
    pcm_audible_times = _field_values(pcm_rows, "pcm_audible_wall_time_ms")
    pcm_submit_times = _field_values(pcm_rows, "pcm_submit_wall_time_ms")
    meter_times = _field_values(payload_rows, "meter_wall_time_ms")
    payload_times = _field_values(payload_rows, "payload_wall_time_ms")
    bridge_times = _field_values(qml_rows, "bridge_receive_wall_time_ms")
    qml_times = _field_values(qml_rows, "qml_receive_time_ms")
    final_update_times = _field_values(qml_rows, "finalSpeakingEnergyUpdatedAtMs")
    paint_times = _field_values(qml_rows, "anchorLastPaintTimeMs")
    submit_meter_latency_values = _field_values(
        payload_rows,
        "meter_latency_from_pcm_submit_ms",
        minimum=0.0,
        maximum=5000.0,
    )
    if not submit_meter_latency_values:
        submit_meter_latency_values = _nearest_previous_deltas(
            pcm_submit_times,
            meter_times,
            max_window_ms=250.0,
        )
    meter_latency_values = _nearest_forward_deltas(
        pcm_audible_times,
        meter_times,
        max_window_ms=500.0,
    )
    if not meter_latency_values:
        meter_latency_values = submit_meter_latency_values
    payload_bridge_values = _field_values(
        qml_rows,
        "bridge_latency_from_payload_ms",
        minimum=0.0,
        maximum=10000.0,
    )
    if not payload_bridge_values:
        payload_bridge_values = _nearest_forward_deltas(
            payload_times,
            bridge_times,
            max_window_ms=5000.0,
        )
    bridge_qml_values = [
        max(0.0, qml_time - bridge_time)
        for row in qml_rows
        for bridge_time in [_row_float(row, "bridge_receive_wall_time_ms")]
        for qml_time in [_row_float(row, "qml_receive_time_ms")]
        if bridge_time is not None
        and qml_time is not None
        and abs(qml_time - bridge_time) <= 100.0
    ]
    if not bridge_qml_values:
        bridge_qml_values = _nearest_forward_deltas(
            bridge_times,
            qml_times,
            max_window_ms=100.0,
        )
    qml_final_values = [
        float(row.get("finalSpeakingEnergyUpdatedAtMs"))
        - float(row.get("qml_receive_time_ms"))
        for row in qml_rows
        if _row_float(row, "finalSpeakingEnergyUpdatedAtMs") is not None
        and _row_float(row, "qml_receive_time_ms") is not None
        and 0.0
        <= float(row.get("finalSpeakingEnergyUpdatedAtMs"))
        - float(row.get("qml_receive_time_ms"))
        <= 5000.0
    ]
    final_paint_values = _nearest_forward_deltas(
        final_update_times,
        paint_times,
        max_window_ms=5000.0,
    )
    pcm_paint_values = _nearest_forward_deltas(
        pcm_audible_times or pcm_submit_times,
        paint_times,
        max_window_ms=5000.0,
    )
    return {
        "pcm_to_meter": _mean_or_none(meter_latency_values),
        "pcm_submit_to_meter": _mean_or_none(submit_meter_latency_values),
        "meter_to_payload": _mean_or_none(
            _field_values(
                payload_rows,
                "payload_latency_from_meter_ms",
                minimum=0.0,
                maximum=5000.0,
            )
            or [
                payload_time - meter_time
                for payload_time, meter_time in zip(payload_times, meter_times, strict=False)
                if 0.0 <= payload_time - meter_time <= 5000.0
            ]
        ),
        "payload_to_bridge": _mean_or_none(payload_bridge_values),
        "bridge_to_qml": _mean_or_none(bridge_qml_values),
        "qml_to_finalSpeakingEnergy": _mean_or_none(qml_final_values),
        "finalSpeakingEnergy_to_paint": _mean_or_none(final_paint_values),
        "pcm_to_paint_estimated": _mean_or_none(pcm_paint_values),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _assert_scalar_artifacts(output_dir: Path) -> None:
    serialized = ""
    for path in output_dir.glob("*"):
        if path.is_file() and path.suffix.lower() in {".json", ".md", ".csv", ".jsonl"}:
            serialized += path.read_text(encoding="utf-8", errors="ignore")
    forbidden_present = [token for token in RAW_FORBIDDEN if token in serialized]
    if forbidden_present:
        raise RuntimeError(
            "Raw audio-like fields leaked into artifacts: "
            + ", ".join(sorted(forbidden_present))
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the real Stormhelm Voice-AR1 live chain probe."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stormforge", action="store_true", default=False)
    parser.add_argument("--fog", choices=["on", "off", "auto"], default="auto")
    parser.add_argument(
        "--anchor-renderer",
        choices=[
            "legacy_blob",
            "legacy_blob_reference",
            "legacy_blob_fast_candidate",
            "legacy_blob_qsg_candidate",
            "ar3_split",
        ],
        default="legacy_blob_reference",
        help="Stormforge anchor renderer to exercise in the real production UI.",
    )
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument(
        "--spoken-prompt",
        default="Testing one, two, three. Anchor sync check.",
    )
    parser.add_argument("--audible", action="store_true")
    parser.add_argument("--use-local-pcm-voice-fixture", action="store_true")
    parser.add_argument("--session-id", default="default")
    parser.add_argument("--stop-existing", action="store_true", default=True)
    parser.add_argument("--no-stop-existing", dest="stop_existing", action="store_false")
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    qml_diag_path = output_dir / "production_ui_diagnostics.jsonl"
    base_url = f"http://{args.host}:{args.port}"
    session_id = str(args.session_id or "default")
    stopped_processes: list[dict[str, Any]] = []
    core_proc: subprocess.Popen[bytes] | None = None
    ui_proc: subprocess.Popen[bytes] | None = None
    events: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    spoken_stimulus: dict[str, Any] = {
        "requested_text": args.spoken_prompt,
        "mode": "chat_send",
        "audible_requested": bool(args.audible),
        "raw_audio_present": False,
    }
    process_state: dict[str, Any] = {}

    try:
        if args.stop_existing:
            stopped_processes = _stop_existing_processes()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR)
        env["STORMHELM_CORE_HOST"] = args.host
        env["STORMHELM_CORE_PORT"] = str(args.port)
        env["STORMHELM_VOICE_AR1_LIVE_DIAG"] = "1"
        env["STORMHELM_VOICE_AR1_QML_DIAG"] = "1"
        env["STORMHELM_VOICE_AR1_QML_DIAG_PATH"] = str(qml_diag_path)
        env["QML_DISABLE_DISK_CACHE"] = "1" if args.clear_cache else env.get("QML_DISABLE_DISK_CACHE", "0")
        if args.stormforge:
            env["STORMHELM_UI_VARIANT"] = "stormforge"
        env["STORMHELM_STORMFORGE_ANCHOR_RENDERER"] = args.anchor_renderer
        if args.fog != "auto":
            env["STORMHELM_STORMFORGE_FOG"] = "true" if args.fog == "on" else "false"
        core_proc = _start_process(
            "stormhelm.entrypoints.core",
            env=env,
            log_path=output_dir / "core.log",
        )
        health = _wait_for_health(base_url, timeout_seconds=20.0)
        ui_proc = _start_process(
            "stormhelm.entrypoints.ui",
            env=env,
            log_path=output_dir / "ui.log",
        )
        time.sleep(3.0)
        settings = {}
        try:
            settings = _request_json(base_url, "GET", "/settings", timeout=5.0)
        except Exception:
            settings = {}
        ui_settings = settings.get("ui") if isinstance(settings.get("ui"), dict) else {}
        stormforge_settings = (
            ui_settings.get("stormforge")
            if isinstance(ui_settings.get("stormforge"), dict)
            else {}
        )
        process_state = {
            "started_at": _utc_now(),
            "command": " ".join(sys.argv),
            "stopped_existing_processes": stopped_processes,
            "core": {"pid": core_proc.pid, "module": "stormhelm.entrypoints.core"},
            "ui": {"pid": ui_proc.pid, "module": "stormhelm.entrypoints.ui"},
            "process_tree": _process_snapshot([core_proc.pid, ui_proc.pid]),
            "health": sanitize_scalar_payload(health),
            "settings": sanitize_scalar_payload(
                {
                    "ui": {
                        "visual_variant": ui_settings.get("visual_variant"),
                        "stormforge": {
                            "fog": stormforge_settings.get("fog")
                            if isinstance(stormforge_settings, dict)
                            else {},
                            "voice_diagnostics": stormforge_settings.get(
                                "voice_diagnostics"
                            )
                            if isinstance(stormforge_settings, dict)
                            else {},
                        },
                    },
                    "runtime_mode": settings.get("runtime", {}).get("mode")
                    if isinstance(settings.get("runtime"), dict)
                    else None,
                }
            ),
            "env": {
                "PYTHONPATH": str(SRC_DIR),
                "STORMHELM_CORE_HOST": args.host,
                "STORMHELM_CORE_PORT": str(args.port),
                "STORMHELM_UI_VARIANT": env.get("STORMHELM_UI_VARIANT"),
                "STORMHELM_STORMFORGE_FOG": env.get("STORMHELM_STORMFORGE_FOG"),
                "STORMHELM_STORMFORGE_ANCHOR_RENDERER": env.get("STORMHELM_STORMFORGE_ANCHOR_RENDERER"),
                "STORMHELM_VOICE_AR1_LIVE_DIAG": "1",
                "STORMHELM_VOICE_AR1_QML_DIAG": "1",
                "STORMHELM_VOICE_AR1_QML_DIAG_PATH": str(qml_diag_path),
                "QML_DISABLE_DISK_CACHE": env.get("QML_DISABLE_DISK_CACHE"),
            },
            "clear_cache_requested": bool(args.clear_cache),
            "safe_cache_action": "qml_disk_cache_disabled_for_probe"
            if args.clear_cache
            else "not_requested",
            "raw_audio_present": False,
        }
        _write_json(output_dir / "process_state.json", process_state)

        chat_payload = {
            "message": args.spoken_prompt,
            "session_id": session_id,
            "surface_mode": "ghost",
            "active_module": "chartroom",
            "response_profile": "concise",
        }
        try:
            chat_response = _request_json(
                base_url,
                "POST",
                "/chat/send",
                chat_payload,
                timeout=20.0,
            )
            spoken_stimulus["chat_send_ok"] = True
            spoken_stimulus["chat_response_status"] = chat_response.get("status")
            spoken_stimulus["assistant_response_text"] = chat_response.get(
                "assistant_response"
            ) or chat_response.get("response")
        except Exception as error:
            spoken_stimulus["chat_send_ok"] = False
            spoken_stimulus["chat_send_error"] = str(error)

        events, status_rows = _collect_events(
            base_url,
            session_id=session_id,
            timeout_seconds=min(args.timeout_seconds, 12.0),
            qml_diag_path=qml_diag_path,
        )
        pcm_seen = any(
            str(event.get("event_type") or "") == "voice.pcm_submitted_to_playback"
            for event in events
        )
        if not pcm_seen and args.use_local_pcm_voice_fixture:
            spoken_stimulus["mode"] = "local_pcm_voice_fixture"
            fixture = _request_json(
                base_url,
                "POST",
                "/voice/diagnostics/local-pcm-fixture",
                {
                    "session_id": session_id,
                    "prompt": args.spoken_prompt,
                },
                timeout=max(20.0, args.timeout_seconds),
            )
            spoken_stimulus["local_pcm_fixture"] = sanitize_scalar_payload(fixture)
            more_events, more_status = _collect_events(
                base_url,
                session_id=session_id,
                timeout_seconds=args.timeout_seconds,
                qml_diag_path=qml_diag_path,
            )
            events.extend(more_events)
            status_rows.extend(more_status)

        qml_rows = _read_qml_rows(qml_diag_path)
        status_rows = _enrich_status_rows_with_authority(status_rows, qml_rows)
        timeline_rows, stage_rows = _build_timelines(events, qml_rows)
        lifetime = _speaking_lifetime(
            events,
            qml_rows,
            stage_rows.get("payload_rows", []),
        )
        playback_id = ""
        for row in stage_rows.get("pcm_rows", []):
            playback_id = str(row.get("playback_id") or "")
            if playback_id:
                break
        if not playback_id:
            for row in qml_rows:
                playback_id = str(row.get("qmlReceivedPlaybackId") or "")
                if playback_id:
                    break
        spoken_stimulus_valid = any(
            str(event.get("event_type") or "") == "voice.pcm_submitted_to_playback"
            for event in events
        )
        render_metrics = _render_metrics(qml_rows)
        report = summarize_real_environment_chain(
            playback_id=playback_id,
            spoken_stimulus_valid=spoken_stimulus_valid,
            timeline_rows=timeline_rows,
            process_state=process_state,
            runtime_identity=process_state.get("health", {}).get("runtime_identity", {}),
            spoken_stimulus=spoken_stimulus,
            speaking_lifetime=lifetime,
            paint_count=render_metrics["anchorPaintCount"],
            render_metrics=render_metrics,
        )
        report["events_collected"] = len(events)
        report["status_samples_collected"] = len(status_rows)
        report["qml_rows_collected"] = len(qml_rows)
        report["stage_sample_counts"] = {
            "pcm": len(stage_rows.get("pcm_rows", [])),
            "payload": len(stage_rows.get("payload_rows", [])),
            "qml": len(qml_rows),
        }
        report["latency_ms"] = sanitize_scalar_payload(
            _stage_latency_metrics(stage_rows, qml_rows)
        )
        if isinstance(report.get("audio_visual_alignment"), dict):
            report["audio_visual_alignment"].update(
                audio_visual_sync_diagnosis(
                    report["audio_visual_alignment"],
                    report.get("latency_ms", {}),
                )
            )
            report["audio_visual_alignment"] = sanitize_scalar_payload(
                report["audio_visual_alignment"]
            )
        report["latency_notes"] = {
            "method": "timestamp_aligned_stage_diagnostics",
            "bridge_to_qml": "estimated from production QML diagnostic callback timestamps; frameSwapped is not exposed",
            "frameSwapped_latency": "not_available_in_current_production_ui_probe",
            "raw_audio_present": False,
        }
        report["spoken_stimulus"] = sanitize_scalar_payload(spoken_stimulus)

        _write_json(output_dir / "real_environment_voice_chain_report.json", report)
        (output_dir / "real_environment_voice_chain_report.md").write_text(
            real_environment_report_markdown(report),
            encoding="utf-8",
        )
        (output_dir / "real_environment_voice_chain_timeline.csv").write_text(
            real_environment_timeline_csv_text(timeline_rows),
            encoding="utf-8",
        )
        _write_json(output_dir / "pcm_submit_timeline.json", stage_rows.get("pcm_rows", []))
        _write_json(output_dir / "voice_payload_timeline.json", stage_rows.get("payload_rows", []))
        _write_json(output_dir / "qml_anchor_timeline.json", qml_rows)
        _write_json(output_dir / "status_timeline.json", status_rows)
        with (output_dir / "energy_timeline.csv").open("w", newline="", encoding="utf-8") as handle:
            if timeline_rows:
                writer = csv.DictWriter(handle, fieldnames=list(timeline_rows[0].keys()))
                writer.writeheader()
                writer.writerows(timeline_rows)
        _assert_scalar_artifacts(output_dir)
        print(json.dumps({"report": str(output_dir / "real_environment_voice_chain_report.json"), "classification": report.get("classification")}, indent=2))
        return 0
    finally:
        if not args.keep_running:
            for proc in (ui_proc, core_proc):
                if proc is not None and proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass


if __name__ == "__main__":
    raise SystemExit(main())
