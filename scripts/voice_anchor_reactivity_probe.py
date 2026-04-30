from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stormhelm.ui.voice_surface import build_voice_ui_state


PROMPT = "Say bearing acquired, then say Stormhelm voice reactivity test in a calm voice."

SAMPLE_FIELDS = (
    "sampled_at",
    "elapsed_ms",
    "voice_anchor_state",
    "speaking_visual_active",
    "voice_motion_intensity",
    "voice_audio_level",
    "voice_audio_level_raw",
    "voice_instant_audio_level",
    "voice_fast_audio_level",
    "voice_smoothed_output_level",
    "voice_visual_drive_level",
    "voice_visual_drive_peak",
    "voice_center_blob_drive",
    "voice_center_blob_scale_drive",
    "voice_center_blob_scale",
    "voice_outer_speaking_motion",
    "voice_visual_gain",
    "voice_audio_reactive_available",
    "voice_audio_reactive_source",
    "streaming_tts_active",
    "live_playback_active",
    "first_audio_started",
    "active_playback_status",
    "audioDriveLevel",
    "voice_visualizer_envelope_frames_generated",
    "voice_visualizer_envelope_frames_published",
    "voice_visualizer_queue_depth",
    "voice_visualizer_frame_worker_active",
    "ui_bridge_update_count",
    "qml_anchor_state",
    "qml_audioDriveLevel",
    "qml_visualDriveLevel",
    "qml_centerBlobDrive",
    "qml_motion_intensity",
)


def _http_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "active"}
    return bool(value)


def _voice_status(status: dict[str, Any]) -> dict[str, Any]:
    status_payload = _dict(status.get("status"))
    if status_payload:
        status = status_payload
    voice = status.get("voice")
    return dict(voice) if isinstance(voice, dict) else dict(status)


def sample_from_status(
    status: dict[str, Any],
    *,
    started_at: float,
    ui_bridge_update_count: int,
) -> dict[str, Any]:
    voice = _voice_status(status)
    playback = _dict(voice.get("playback"))
    visualizer = _dict(voice.get("voice_visualizer"))
    ui_state = build_voice_ui_state({"voice": voice})
    anchor = _dict(ui_state.get("voice_anchor"))
    debug = _dict(ui_state.get("voice_anchor_debug"))
    sample = {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
        "voice_anchor_state": ui_state.get("voice_anchor_state")
        or anchor.get("state"),
        "speaking_visual_active": _bool(ui_state.get("speaking_visual_active")),
        "voice_motion_intensity": _number(ui_state.get("voice_motion_intensity")),
        "voice_audio_level": _number(ui_state.get("voice_audio_level")),
        "voice_audio_level_raw": _number(ui_state.get("voice_audio_level_raw")),
        "voice_instant_audio_level": _number(ui_state.get("voice_instant_audio_level")),
        "voice_fast_audio_level": _number(ui_state.get("voice_fast_audio_level")),
        "voice_smoothed_output_level": _number(
            ui_state.get("voice_smoothed_output_level")
        ),
        "voice_visual_drive_level": _number(ui_state.get("voice_visual_drive_level")),
        "voice_visual_drive_peak": _number(ui_state.get("voice_visual_drive_peak")),
        "voice_center_blob_drive": _number(ui_state.get("voice_center_blob_drive")),
        "voice_center_blob_scale_drive": _number(
            ui_state.get("voice_center_blob_scale_drive")
        ),
        "voice_center_blob_scale": _number(ui_state.get("voice_center_blob_scale"), 1.0),
        "voice_outer_speaking_motion": _number(ui_state.get("voice_outer_speaking_motion")),
        "voice_visual_gain": _number(ui_state.get("voice_visual_gain"), 1.0),
        "voice_audio_reactive_available": _bool(
            ui_state.get("voice_audio_reactive_available")
        ),
        "voice_audio_reactive_source": ui_state.get("voice_audio_reactive_source")
        or debug.get("source")
        or "unavailable",
        "streaming_tts_active": _bool(
            ui_state.get("streaming_tts_active") or voice.get("streaming_tts_active")
        ),
        "live_playback_active": _bool(
            ui_state.get("live_playback_active") or voice.get("live_playback_active")
        ),
        "first_audio_started": _bool(
            ui_state.get("first_audio_started")
            or playback.get("first_audio_started")
            or voice.get("first_audio_started")
        ),
        "active_playback_status": playback.get("active_playback_status")
        or voice.get("active_playback_status"),
        "audioDriveLevel": _number(
            ui_state.get("audioDriveLevel"), ui_state.get("voice_center_blob_drive")
        ),
        "voice_visualizer_envelope_frames_generated": int(
            _number(
                voice.get("voice_visualizer_envelope_frames_generated"),
                visualizer.get("envelope_frames_generated", 0),
            )
        ),
        "voice_visualizer_envelope_frames_published": int(
            _number(
                voice.get("voice_visualizer_envelope_frames_published"),
                visualizer.get("envelope_frames_published", 0),
            )
        ),
        "voice_visualizer_queue_depth": int(
            _number(
                voice.get("voice_visualizer_queue_depth"),
                visualizer.get("queue_depth", 0),
            )
        ),
        "voice_visualizer_frame_worker_active": _bool(
            voice.get("voice_visualizer_frame_worker_active")
            or visualizer.get("active")
        ),
        "ui_bridge_update_count": int(ui_bridge_update_count),
        "qml_anchor_state": None,
        "qml_audioDriveLevel": None,
        "qml_visualDriveLevel": None,
        "qml_centerBlobDrive": None,
        "qml_motion_intensity": None,
    }
    return {key: sample.get(key) for key in SAMPLE_FIELDS}


def _signature(sample: dict[str, Any]) -> tuple[Any, ...]:
    return (
        sample.get("voice_anchor_state"),
        sample.get("speaking_visual_active"),
        sample.get("voice_motion_intensity"),
        sample.get("voice_fast_audio_level"),
        sample.get("voice_smoothed_output_level"),
        sample.get("voice_visual_drive_level"),
        sample.get("voice_center_blob_drive"),
        sample.get("voice_audio_reactive_source"),
        sample.get("active_playback_status"),
    )


def _series(samples: list[dict[str, Any]], key: str) -> list[float]:
    return [_number(sample.get(key)) for sample in samples if sample.get(key) is not None]


def _stats(samples: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = _series(samples, key)
    if not values:
        return {"min": 0.0, "max": 0.0, "average": 0.0}
    return {
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "average": round(mean(values), 4),
    }


def _counter_delta(samples: list[dict[str, Any]], key: str) -> int:
    values = [int(_number(sample.get(key))) for sample in samples if sample.get(key) is not None]
    if not values:
        return 0
    return max(0, max(values) - min(values))


def classify_samples(samples: list[dict[str, Any]]) -> list[str]:
    if not samples:
        return ["backend_envelope_missing"]
    speaking = [sample for sample in samples if sample.get("speaking_visual_active")]
    if not speaking:
        return ["live_path_bypasses_envelope"]
    sources = {str(sample.get("voice_audio_reactive_source") or "unavailable") for sample in speaking}
    real_sources = {
        "playback_output_envelope",
        "streaming_chunk_envelope",
        "precomputed_artifact_envelope",
    }
    classifications: list[str] = []
    if sources <= {"synthetic_fallback_envelope"}:
        classifications.append("synthetic_fallback_only")
    elif not sources & real_sources:
        classifications.append("backend_envelope_missing")
    smoothed = _series(speaking, "voice_smoothed_output_level")
    drive = _series(speaking, "voice_visual_drive_level")
    center_drive = _series(speaking, "voice_center_blob_scale_drive")
    motion = _series(speaking, "voice_motion_intensity")
    if smoothed and max(smoothed) < 0.08:
        classifications.append("backend_envelope_too_small")
    if drive and max(drive) < 0.28:
        classifications.append("backend_envelope_too_small")
    if center_drive and max(center_drive) < 0.2:
        classifications.append("backend_envelope_too_small")
    if center_drive and min(center_drive) > 0.55 and max(center_drive) - min(center_drive) < 0.18:
        classifications.append("animation_design_too_subtle")
    if len(speaking) >= 2:
        duration_ms = _number(speaking[-1].get("elapsed_ms")) - _number(
            speaking[0].get("elapsed_ms")
        )
        update_rate = (len(speaking) - 1) / max(0.001, duration_ms / 1000.0)
        if update_rate < 6.0:
            classifications.append("backend_envelope_updates_too_slow")
    if drive and motion and max(drive) - min(drive) > 0.35 and max(motion) - min(motion) < 0.15:
        classifications.append("animation_design_too_subtle")
    bridge_updates = max(
        int(_number(sample.get("ui_bridge_update_count"))) for sample in samples
    )
    if bridge_updates <= 0 and drive and max(drive) > 0.2:
        classifications.append("bridge_not_forwarding_envelope")
    qml_values = [
        sample
        for sample in samples
        if sample.get("qml_audioDriveLevel") is not None
        or sample.get("qml_visualDriveLevel") is not None
        or sample.get("qml_centerBlobDrive") is not None
    ]
    if qml_values:
        qml_drive = _series(qml_values, "qml_audioDriveLevel")
        expected_drive = center_drive or drive
        if qml_drive and expected_drive and max(expected_drive) - min(expected_drive) > 0.25 and max(qml_drive) - min(qml_drive) < 0.08:
            classifications.append("qml_not_binding_audio_level")
    return sorted(set(classifications))


def build_summary(
    *,
    prompt: str,
    samples: list[dict[str, Any]],
    poll_errors: list[dict[str, str]],
    trigger_result: dict[str, Any] | None,
) -> dict[str, Any]:
    speaking = [sample for sample in samples if sample.get("speaking_visual_active")]
    source_counts = Counter(
        str(sample.get("voice_audio_reactive_source") or "unavailable")
        for sample in speaking or samples
    )
    source = source_counts.most_common(1)[0][0] if source_counts else "unavailable"
    real_sources = {
        "playback_output_envelope",
        "streaming_chunk_envelope",
        "precomputed_artifact_envelope",
    }
    center_drive_values = _series(speaking or samples, "voice_center_blob_scale_drive")
    visual_drive_values = _series(speaking or samples, "voice_visual_drive_level")
    ui_update_count = max(
        [int(_number(sample.get("ui_bridge_update_count"))) for sample in samples]
        or [0]
    )
    generated_frame_count = _counter_delta(
        samples, "voice_visualizer_envelope_frames_generated"
    )
    published_frame_count = _counter_delta(
        samples, "voice_visualizer_envelope_frames_published"
    )
    envelope_frame_count = generated_frame_count or max(ui_update_count, len(speaking))
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "sample_count": len(samples),
        "speaking_sample_count": len(speaking),
        "envelope_frames_produced": envelope_frame_count,
        "envelope_frames_published": published_frame_count
        or max(ui_update_count, len(speaking)),
        "ui_updates_delivered": ui_update_count,
        "backend_envelope_frames_generated_total": max(
            [
                int(_number(sample.get("voice_visualizer_envelope_frames_generated")))
                for sample in samples
                if sample.get("voice_visualizer_envelope_frames_generated") is not None
            ]
            or [0]
        ),
        "backend_envelope_frames_published_total": max(
            [
                int(_number(sample.get("voice_visualizer_envelope_frames_published")))
                for sample in samples
                if sample.get("voice_visualizer_envelope_frames_published") is not None
            ]
            or [0]
        ),
        "source": source,
        "source_counts": dict(source_counts),
        "real_envelope_seen": bool(set(source_counts) & real_sources),
        "synthetic_fallback_used": "synthetic_fallback_envelope" in source_counts,
        "classification": classify_samples(samples),
        "smoothed_level": _stats(speaking or samples, "voice_smoothed_output_level"),
        "instant_audio_level": _stats(speaking or samples, "voice_instant_audio_level"),
        "fast_audio_level": _stats(speaking or samples, "voice_fast_audio_level"),
        "visual_drive": _stats(speaking or samples, "voice_visual_drive_level"),
        "center_blob_drive": _stats(speaking or samples, "voice_center_blob_drive"),
        "center_blob_scale_drive": _stats(
            speaking or samples, "voice_center_blob_scale_drive"
        ),
        "center_blob_scale": _stats(speaking or samples, "voice_center_blob_scale"),
        "outer_speaking_motion": _stats(speaking or samples, "voice_outer_speaking_motion"),
        "motion_intensity": _stats(speaking or samples, "voice_motion_intensity"),
        "center_blob_drive_fell_near_neutral": bool(center_drive_values and min(center_drive_values) <= 0.08),
        "center_blob_drive_rose_for_louder_speech": bool(center_drive_values and max(center_drive_values) >= 0.55),
        "visual_drive_fell_near_neutral": bool(visual_drive_values and min(visual_drive_values) <= 0.08),
        "visual_drive_rose_for_louder_speech": bool(visual_drive_values and max(visual_drive_values) >= 0.55),
        "ui_bridge_update_count": ui_update_count,
        "qml_values_observed": any(
            sample.get("qml_audioDriveLevel") is not None
            or sample.get("qml_visualDriveLevel") is not None
            or sample.get("qml_centerBlobDrive") is not None
            for sample in samples
        ),
        "poll_error_count": len(poll_errors),
        "poll_errors": poll_errors[-5:],
        "trigger_result": trigger_result,
        "raw_audio_logged": False,
        "raw_audio_included": False,
    }


def _summary_markdown(summary: dict[str, Any]) -> str:
    instant = summary["instant_audio_level"]
    fast = summary["fast_audio_level"]
    smoothed = summary["smoothed_level"]
    drive = summary["visual_drive"]
    center = summary["center_blob_drive"]
    center_scale_drive = summary["center_blob_scale_drive"]
    center_scale = summary["center_blob_scale"]
    outer = summary["outer_speaking_motion"]
    motion = summary["motion_intensity"]
    classification = summary.get("classification") or ["none"]
    return "\n".join(
        [
            "# Voice Anchor Reactivity Probe",
            "",
            f"- Samples: {summary['sample_count']} total, {summary['speaking_sample_count']} speaking",
            f"- Envelope frames produced: {summary['envelope_frames_produced']}",
            f"- Envelope frames published: {summary['envelope_frames_published']}",
            f"- UI updates delivered: {summary['ui_updates_delivered']}",
            f"- Source: {summary['source']}",
            f"- Classification: {', '.join(classification)}",
            f"- Instant audio level min/max/avg: {instant['min']} / {instant['max']} / {instant['average']}",
            f"- Fast audio level min/max/avg: {fast['min']} / {fast['max']} / {fast['average']}",
            f"- Smoothed level min/max/avg: {smoothed['min']} / {smoothed['max']} / {smoothed['average']}",
            f"- Visual drive min/max/avg: {drive['min']} / {drive['max']} / {drive['average']}",
            f"- Center blob drive min/max/avg: {center['min']} / {center['max']} / {center['average']}",
            f"- Center blob scale drive min/max/avg: {center_scale_drive['min']} / {center_scale_drive['max']} / {center_scale_drive['average']}",
            f"- Center blob scale min/max/avg: {center_scale['min']} / {center_scale['max']} / {center_scale['average']}",
            f"- Outer speaking motion min/max/avg: {outer['min']} / {outer['max']} / {outer['average']}",
            f"- Motion intensity min/max/avg: {motion['min']} / {motion['max']} / {motion['average']}",
            f"- Center drive fell near neutral: {summary['center_blob_drive_fell_near_neutral']}",
            f"- Center drive rose for louder speech: {summary['center_blob_drive_rose_for_louder_speech']}",
            f"- UI bridge update count: {summary['ui_bridge_update_count']}",
            f"- QML values observed: {summary['qml_values_observed']}",
            f"- Synthetic fallback used: {summary['synthetic_fallback_used']}",
            "- Raw audio logged: False",
            "",
        ]
    )


def write_probe_report(
    *,
    output_dir: str | Path,
    prompt: str,
    samples: list[dict[str, Any]],
    poll_errors: list[dict[str, str]],
    trigger_result: dict[str, Any] | None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    safe_samples = [
        {key: sample.get(key) for key in SAMPLE_FIELDS}
        for sample in samples
    ]
    summary = build_summary(
        prompt=prompt,
        samples=safe_samples,
        poll_errors=poll_errors,
        trigger_result=trigger_result,
    )
    (output_path / "samples.jsonl").write_text(
        "".join(
            json.dumps(sample, sort_keys=True, separators=(",", ":")) + "\n"
            for sample in safe_samples
        ),
        encoding="utf-8",
    )
    (output_path / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_path / "summary.md").write_text(
        _summary_markdown(summary),
        encoding="utf-8",
    )
    return summary


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    status_url = args.status_url
    if not status_url:
        status_url = str(args.base_url).rstrip("/") + "/status"
    start = time.perf_counter()
    samples: list[dict[str, Any]] = []
    poll_errors: list[dict[str, str]] = []
    trigger_process: subprocess.Popen[str] | None = None
    trigger_result: dict[str, Any] | None = None
    if args.trigger_smoke:
        smoke_dir = Path(args.output_dir) / "typed_response_smoke"
        command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "voice_typed_response_smoke.py"),
            "--prompt",
            args.prompt,
            "--speak",
            "--sink-kind",
            args.sink_kind,
            "--base-url",
            str(args.base_url).rstrip("/"),
            "--output-dir",
            str(smoke_dir),
        ]
        trigger_process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    deadline = start + max(0.2, float(args.duration_seconds))
    update_count = 0
    previous_signature: tuple[Any, ...] | None = None
    while time.perf_counter() < deadline or (
        trigger_process is not None and trigger_process.poll() is None
    ):
        try:
            status = _http_json(status_url, timeout=float(args.timeout))
            candidate = sample_from_status(
                status,
                started_at=start,
                ui_bridge_update_count=update_count,
            )
            signature = _signature(candidate)
            if previous_signature is not None and signature != previous_signature:
                update_count += 1
                candidate["ui_bridge_update_count"] = update_count
            previous_signature = signature
            samples.append(candidate)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            poll_errors.append(
                {
                    "type": type(error).__name__,
                    "message": str(error)[:180],
                }
            )
        time.sleep(max(0.02, float(args.interval_ms) / 1000.0))
    if trigger_process is not None:
        output = trigger_process.communicate(timeout=5)[0]
        trigger_result = {
            "return_code": trigger_process.returncode,
            "smoke_output_tail": "\n".join(output.splitlines()[-8:]),
            "raw_audio_logged": False,
        }
    return write_probe_report(
        output_dir=args.output_dir,
        prompt=args.prompt,
        samples=samples,
        poll_errors=poll_errors,
        trigger_result=trigger_result,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe safe normalized voice anchor audio-drive fields during spoken output."
    )
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--status-url", default="")
    parser.add_argument("--output-dir", default=".artifacts/voice_anchor_reactivity_probe")
    parser.add_argument("--duration-seconds", type=float, default=8.0)
    parser.add_argument("--interval-ms", type=float, default=80.0)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--trigger-smoke", action="store_true")
    parser.add_argument("--sink-kind", default="speaker", choices=["speaker", "local", "null_stream", "mock"])
    args = parser.parse_args()

    summary = run_probe(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"artifact={Path(args.output_dir) / 'summary.json'}")
    return 0 if summary.get("sample_count", 0) > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
