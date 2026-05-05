from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from run_voice_live_envelope_activation_probe import _as_bool
from run_voice_live_envelope_activation_probe import _as_float
from run_voice_live_envelope_activation_probe import _first_value
from run_voice_live_envelope_activation_probe import _http_json
from run_voice_live_envelope_activation_probe import _safe_scalar
from run_voice_live_envelope_activation_probe import _settings_summary


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "reports" / "voice_playback_envelope"
REPORT_PATH = OUTPUT_DIR / "live_envelope_source_latch_report.json"
TIMELINE_PATH = OUTPUT_DIR / "speaking_energy_timeline.csv"


FIELDS = (
    "active_playback_status",
    "playback_id",
    "active_playback_id",
    "active_playback_stream_id",
    "voice_anchor_state",
    "voice_current_phase",
    "speaking_visual_active",
    "playback_envelope_supported",
    "playback_envelope_available",
    "playback_envelope_usable",
    "playback_envelope_usable_reason",
    "playback_envelope_source",
    "playback_envelope_timebase_aligned",
    "playback_envelope_alignment_error_ms",
    "playback_envelope_sample_count",
    "playback_envelope_sample_age_ms",
    "playback_envelope_window_mode",
    "playback_envelope_query_time_ms",
    "playback_envelope_latest_time_ms",
    "latest_voice_energy_time_ms",
    "playback_envelope_energy",
    "latest_voice_energy",
    "anchor_uses_playback_envelope",
    "procedural_fallback_active",
    "speaking_visual_sync_mode",
    "envelope_interpolation_active",
    "envelope_fallback_reason",
    "raw_audio_present",
    "raw_audio_logged",
)


def _sample_status(status: dict[str, Any], *, started: float) -> dict[str, Any]:
    row: dict[str, Any] = {"t_ms": round((time.perf_counter() - started) * 1000.0, 3)}
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


def _switch_count(values: list[str]) -> int:
    previous = ""
    switches = 0
    for value in values:
        if not value:
            continue
        if previous and value != previous:
            switches += 1
        previous = value
    return switches


def _first_time(rows: list[dict[str, Any]], predicate) -> float | None:
    for row in rows:
        if predicate(row):
            return _as_float(row.get("t_ms"))
    return None


def _summarize(
    *,
    base_url: str,
    session_id: str,
    settings: dict[str, Any],
    samples: list[dict[str, Any]],
    trigger_response: dict[str, Any] | None,
) -> dict[str, Any]:
    active = [row for row in samples if row.get("speaking_or_playing")]
    active_sources = [
        str(row.get("usable_visual_energy_source") or "")
        for row in active
        if row.get("usable_visual_energy_source") not in {None, ""}
    ]
    sync_modes = [
        str(row.get("speaking_visual_sync_mode") or "")
        for row in active
        if row.get("speaking_visual_sync_mode") not in {None, ""}
    ]
    bad_envelope_dominance = [
        row
        for row in active
        if _as_bool(row.get("anchor_uses_playback_envelope"))
        and not _as_bool(row.get("playback_envelope_timebase_aligned"))
    ]
    active_without_source = [
        row
        for row in active
        if row.get("usable_visual_energy_source") not in {"playback_envelope", "procedural_fallback"}
    ]
    unaligned_available = [
        row
        for row in active
        if _as_bool(row.get("playback_envelope_available"))
        and not _as_bool(row.get("playback_envelope_usable"))
        and str(row.get("playback_envelope_usable_reason") or "") == "playback_envelope_unaligned"
    ]
    first_active_t = _as_float(active[0].get("t_ms")) if active else None
    first_visual_t = _first_time(
        active,
        lambda row: row.get("usable_visual_energy_source")
        in {"playback_envelope", "procedural_fallback"},
    )
    early_visual_delay_ms = (
        None if first_active_t is None or first_visual_t is None else max(0, first_visual_t - first_active_t)
    )
    passed = bool(
        active
        and not active_without_source
        and not bad_envelope_dominance
        and _switch_count(active_sources) <= 2
        and (early_visual_delay_ms is None or early_visual_delay_ms <= 350)
    )
    return {
        "probe": "Voice-L0.4 live envelope source latch",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "session_id": session_id,
        "settings": _settings_summary(settings),
        "triggered_chat": trigger_response is not None,
        "trigger_response_received": bool(trigger_response),
        "sample_count": len(samples),
        "active_sample_count": len(active),
        "source_switch_count": _switch_count(active_sources),
        "sync_mode_switch_count": _switch_count(sync_modes),
        "visual_sources_seen": sorted(set(active_sources)),
        "sync_modes_seen": sorted(set(sync_modes)),
        "first_active_t_ms": first_active_t,
        "first_visual_source_t_ms": first_visual_t,
        "early_visual_delay_ms": early_visual_delay_ms,
        "first_envelope_usable_t_ms": _first_time(
            active, lambda row: _as_bool(row.get("playback_envelope_usable"))
        ),
        "first_unaligned_available_t_ms": _first_time(
            active, lambda row: row in unaligned_available
        ),
        "unaligned_available_sample_count": len(unaligned_available),
        "bad_envelope_dominance_count": len(bad_envelope_dominance),
        "active_without_source_count": len(active_without_source),
        "max_effective_voice_energy": round(
            max((_as_float(row.get("effective_voice_energy")) for row in samples), default=0.0),
            6,
        ),
        "first_active_sample": active[0] if active else None,
        "first_unaligned_available_sample": unaligned_available[0]
        if unaligned_available
        else None,
        "first_envelope_usable_sample": next(
            (row for row in active if _as_bool(row.get("playback_envelope_usable"))),
            None,
        ),
        "last_sample": samples[-1] if samples else None,
        "privacy": {
            "raw_audio_exposed": False,
            "raw_audio_logged": any(_as_bool(row.get("raw_audio_logged")) for row in samples),
            "raw_audio_present_in_payload": any(_as_bool(row.get("raw_audio_present")) for row in samples),
        },
        "source_latch_passed": passed,
        "source_latch_failure_reason": ""
        if passed
        else "no_active_playback_samples"
        if not active
        else "active_without_visual_source"
        if active_without_source
        else "unaligned_pcm_envelope_dominated_visuals"
        if bad_envelope_dominance
        else "source_flapped_too_often",
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    base_url = str(args.base_url).rstrip("/")
    session_id = args.session_id or f"voice-l04-live-{uuid4().hex[:8]}"
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
        description="Probe live Stormhelm voice envelope source latching and playback-time alignment."
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
    timeline_path = output_dir / TIMELINE_PATH.name
    samples = report.pop("samples", [])
    report["artifacts"] = {
        "report": str(report_path),
        "timeline": str(timeline_path),
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with timeline_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "t_ms",
                *FIELDS,
                "effective_voice_energy",
                "speaking_or_playing",
                "usable_visual_energy_source",
            ),
        )
        writer.writeheader()
        writer.writerows(samples)

    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"artifact={report_path}")
    print(f"timeline={timeline_path}")
    return 0 if report.get("source_latch_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
