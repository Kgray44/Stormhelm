from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "reports" / "voice_playback_envelope"
REPORT_PATH = OUTPUT_DIR / "live_envelope_activation_report.json"
SAMPLES_PATH = OUTPUT_DIR / "live_envelope_activation_samples.csv"


FIELDS = (
    "playback_backend",
    "playback_mode",
    "tts_live_format",
    "tts_artifact_format",
    "stream_tts_outputs",
    "active_playback_status",
    "playback_stable",
    "playback_id",
    "active_playback_stream_id",
    "voice_anchor_state",
    "voice_current_phase",
    "speaking_visual_active",
    "playback_envelope_supported",
    "playback_envelope_available",
    "playback_envelope_usable",
    "playback_envelope_source",
    "playback_envelope_disabled_reason",
    "playback_envelope_fallback_reason",
    "playback_envelope_sample_rate_hz",
    "playback_envelope_sample_count",
    "playback_envelope_sample_age_ms",
    "playback_envelope_window_mode",
    "playback_envelope_query_time_ms",
    "playback_envelope_energy",
    "latest_voice_energy",
    "latest_voice_energy_time_ms",
    "anchor_uses_playback_envelope",
    "procedural_fallback_active",
    "speaking_visual_sync_mode",
    "envelope_interpolation_active",
    "raw_audio_present",
    "raw_audio_logged",
)


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _iter_key_values(payload: Any, key: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(payload, dict):
        for item_key, item_value in payload.items():
            if item_key == key:
                values.append(item_value)
            values.extend(_iter_key_values(item_value, key))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_iter_key_values(item, key))
    return values


def _first_value(payload: dict[str, Any], key: str) -> Any:
    values = _iter_key_values(payload, key)
    for value in values:
        if value is not None:
            return value
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _as_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return number


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _settings_summary(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "voice_enabled": _first_value(settings, "voice_enabled"),
        "spoken_responses_enabled": _first_value(settings, "spoken_responses_enabled"),
        "playback_provider": _first_value(settings, "playback_provider"),
        "speaker_backend": _first_value(settings, "speaker_backend"),
        "playback_backend": _first_value(settings, "playback_backend"),
        "stream_tts_outputs": _first_value(settings, "stream_tts_outputs"),
        "tts_live_format": _first_value(settings, "tts_live_format"),
        "tts_artifact_format": _first_value(settings, "tts_artifact_format"),
    }


def _sample_status(status: dict[str, Any], *, started: float) -> dict[str, Any]:
    row: dict[str, Any] = {
        "t_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }
    for field in FIELDS:
        row[field] = _safe_scalar(_first_value(status, field))
    row["effective_voice_energy"] = max(
        _as_float(row.get("playback_envelope_energy")),
        _as_float(row.get("latest_voice_energy")),
    )
    row["speaking_or_playing"] = bool(
        _as_bool(row.get("speaking_visual_active"))
        or str(row.get("active_playback_status") or "").lower() in {"playing", "started"}
        or str(row.get("voice_anchor_state") or "").lower() == "speaking"
    )
    row["usable_visual_energy_source"] = (
        "playback_envelope"
        if _as_bool(row.get("anchor_uses_playback_envelope"))
        else "procedural_fallback"
        if _as_bool(row.get("procedural_fallback_active"))
        else "none"
    )
    return row


def _summarize(
    *,
    base_url: str,
    session_id: str,
    settings: dict[str, Any],
    samples: list[dict[str, Any]],
    trigger_response: dict[str, Any] | None,
) -> dict[str, Any]:
    active = [row for row in samples if row.get("speaking_or_playing")]
    active_with_source = [
        row
        for row in active
        if row.get("usable_visual_energy_source") in {"playback_envelope", "procedural_fallback"}
    ]
    envelope_rows = [row for row in samples if _as_bool(row.get("playback_envelope_available"))]
    usable_rows = [row for row in samples if _as_bool(row.get("playback_envelope_usable"))]
    fallback_rows = [row for row in samples if _as_bool(row.get("procedural_fallback_active"))]
    energies = [_as_float(row.get("effective_voice_energy")) for row in samples]
    sources = sorted(
        {
            str(row.get("usable_visual_energy_source"))
            for row in samples
            if row.get("usable_visual_energy_source")
        }
    )
    playback_modes = sorted(
        {
            str(row.get("playback_mode") or "")
            for row in samples
            if row.get("playback_mode") not in {None, ""}
        }
    )
    envelope_sources = sorted(
        {
            str(row.get("playback_envelope_source") or "")
            for row in samples
            if row.get("playback_envelope_source") not in {None, ""}
        }
    )
    return {
        "probe": "Voice-L0.2.1 live envelope activation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "session_id": session_id,
        "settings": _settings_summary(settings),
        "triggered_chat": trigger_response is not None,
        "trigger_response_received": bool(trigger_response),
        "sample_count": len(samples),
        "active_sample_count": len(active),
        "active_samples_with_visual_source": len(active_with_source),
        "envelope_available_sample_count": len(envelope_rows),
        "envelope_usable_sample_count": len(usable_rows),
        "procedural_fallback_sample_count": len(fallback_rows),
        "max_effective_voice_energy": round(max(energies) if energies else 0.0, 6),
        "first_active_sample": active[0] if active else None,
        "peak_energy_sample": max(samples, key=lambda row: _as_float(row.get("effective_voice_energy"))) if samples else None,
        "last_sample": samples[-1] if samples else None,
        "visual_energy_sources_seen": sources,
        "playback_modes_seen": playback_modes,
        "envelope_sources_seen": envelope_sources,
        "activation_passed": bool(active and active_with_source),
        "activation_failure_reason": ""
        if active and active_with_source
        else "no_active_playback_samples"
        if not active
        else "active_playback_without_envelope_or_fallback_source",
        "privacy": {
            "raw_audio_exposed": False,
            "raw_audio_logged": any(_as_bool(row.get("raw_audio_logged")) for row in samples),
            "raw_audio_present_in_payload": any(_as_bool(row.get("raw_audio_present")) for row in samples),
        },
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    base_url = str(args.base_url).rstrip("/")
    session_id = args.session_id or f"voice-l021-live-{uuid4().hex[:8]}"
    settings = _http_json("GET", f"{base_url}/settings", timeout=args.timeout)
    trigger_response = None
    started = time.perf_counter()

    if not args.no_trigger:
        trigger_response = _http_json(
            "POST",
            f"{base_url}/chat/send",
            payload={
                "message": args.prompt,
                "session_id": session_id,
                "surface_mode": "ghost",
                "active_module": "ghost",
            },
            timeout=args.timeout,
        )

    samples: list[dict[str, Any]] = []
    deadline = time.perf_counter() + max(1.0, float(args.poll_seconds))
    interval = max(0.05, float(args.poll_interval_seconds))
    while time.perf_counter() < deadline:
        status = _http_json("GET", f"{base_url}/status", timeout=args.timeout)
        samples.append(_sample_status(status, started=started))
        time.sleep(interval)

    return _summarize(
        base_url=base_url,
        session_id=session_id,
        settings=settings,
        samples=samples,
        trigger_response=trigger_response,
    ) | {"samples": samples}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe live Stormhelm voice playback envelope/fallback activation during audible speech."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--prompt", default="what time is it")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--poll-seconds", type=float, default=18.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.12)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--no-trigger", action="store_true")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    try:
        report = run_probe(args)
    except (urllib.error.URLError, TimeoutError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2, default=str))
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / REPORT_PATH.name
    samples_path = output_dir / SAMPLES_PATH.name
    samples = report.pop("samples", [])
    report["artifacts"] = {
        "report": str(report_path),
        "samples": str(samples_path),
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with samples_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("t_ms", *FIELDS, "effective_voice_energy", "speaking_or_playing", "usable_visual_energy_source"))
        writer.writeheader()
        writer.writerows(samples)

    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"artifact={report_path}")
    print(f"samples={samples_path}")
    return 0 if report.get("activation_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
