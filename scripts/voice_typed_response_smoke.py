from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.voice_doctor import build_voice_doctor_report


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8")
    return json.loads(data) if data else {}


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _safe_voice_summary(status: dict[str, Any]) -> dict[str, Any]:
    voice = status.get("voice") if isinstance(status.get("voice"), dict) else {}
    tts = voice.get("tts") if isinstance(voice.get("tts"), dict) else {}
    playback = (
        voice.get("playback") if isinstance(voice.get("playback"), dict) else {}
    )
    decision = (
        voice.get("last_voice_speak_decision")
        if isinstance(voice.get("last_voice_speak_decision"), dict)
        else {}
    )
    live_result = (
        playback.get("last_live_playback_result")
        if isinstance(playback.get("last_live_playback_result"), dict)
        else {}
    )
    first_audio = (
        tts.get("first_audio_latency")
        if isinstance(tts.get("first_audio_latency"), dict)
        else {}
    )
    return {
        "voice_enabled": bool(voice.get("enabled")),
        "spoken_responses_enabled": bool(voice.get("spoken_responses_enabled")),
        "typed_response_speech_enabled": bool(
            voice.get("typed_response_speech_enabled")
        ),
        "provider": _nested(voice, "provider", "name"),
        "playback_provider": playback.get("provider"),
        "speaker_backend": playback.get("speaker_backend"),
        "speaker_backend_available": playback.get("speaker_backend_available"),
        "currently_speaking": playback.get("currently_speaking"),
        "last_voice_speak_decision": decision or None,
        "tts_streaming_status": tts.get("streaming_tts_status"),
        "streaming_transport_kind": tts.get("streaming_transport_kind"),
        "sink_kind": tts.get("sink_kind") or playback.get("sink_kind"),
        "first_openai_chunk_ms": first_audio.get("tts_start_to_first_chunk_ms"),
        "first_speaker_playback_start_ms": first_audio.get(
            "core_result_to_first_audio_ms"
        ),
        "first_output_start_ms": first_audio.get("first_output_start_ms"),
        "first_chunk_before_complete": first_audio.get("first_chunk_before_complete"),
        "stream_complete_ms": first_audio.get("stream_complete_ms"),
        "fallback_used": first_audio.get("fallback_used"),
        "partial_playback": first_audio.get("partial_playback")
        or live_result.get("partial_playback"),
        "user_heard_claimed": bool(
            first_audio.get("user_heard_claimed")
            or live_result.get("user_heard_claimed")
            or playback.get("user_heard_claimed")
        ),
        "raw_audio_logged": bool(tts.get("raw_audio_logged")) is True,
        "raw_audio_present": bool(live_result.get("raw_audio_present")) is True,
    }


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    base_url = str(args.base_url).rstrip("/")
    session_id = args.session_id or f"typed-voice-smoke-{uuid4().hex[:8]}"
    started = time.perf_counter()
    doctor = build_voice_doctor_report(project_root=Path.cwd())
    initial_status = _http_json("GET", f"{base_url}/status", timeout=args.timeout)
    response = _http_json(
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
    assistant = (
        response.get("assistant_message")
        if isinstance(response.get("assistant_message"), dict)
        else {}
    )
    metadata = (
        assistant.get("metadata") if isinstance(assistant.get("metadata"), dict) else {}
    )
    voice_output = (
        metadata.get("voice_output")
        if isinstance(metadata.get("voice_output"), dict)
        else {}
    )
    decision = (
        voice_output.get("decision")
        if isinstance(voice_output.get("decision"), dict)
        else {}
    )
    final_status = initial_status
    final_voice = _safe_voice_summary(initial_status)
    deadline = time.perf_counter() + max(1.0, float(args.wait_seconds))
    while time.perf_counter() < deadline:
        time.sleep(0.35)
        final_status = _http_json("GET", f"{base_url}/status", timeout=args.timeout)
        final_voice = _safe_voice_summary(final_status)
        status_decision = final_voice.get("last_voice_speak_decision")
        status_session = (
            status_decision.get("session_id")
            if isinstance(status_decision, dict)
            else None
        )
        if status_session != session_id:
            continue
        if status_decision and status_decision.get("skipped_reason"):
            break
        if final_voice.get("tts_streaming_status") in {"completed", "failed"}:
            break
        if final_voice.get("user_heard_claimed") and not final_voice.get(
            "currently_speaking"
        ):
            break

    voice_summary = _safe_voice_summary(final_status)
    status_decision = voice_summary.get("last_voice_speak_decision")
    if isinstance(status_decision, dict) and status_decision.get("session_id") == session_id:
        decision = status_decision

    report = {
        "smoke": "voice_typed_response",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "session_id": session_id,
        "prompt_chars": len(args.prompt),
        "sink_kind_requested": args.sink_kind,
        "text_response_received": bool(str(assistant.get("content") or "").strip()),
        "text_response_chars": len(str(assistant.get("content") or "")),
        "approved_spoken_text_present": bool(
            decision.get("approved_spoken_text_present")
        ),
        "voice_service_called": bool(decision.get("voice_service_called")),
        "skipped_reason": decision.get("skipped_reason"),
        "disabled_reasons": decision.get("disabled_reasons") or [],
        "voice_output_metadata": {
            "scheduled": bool(voice_output.get("scheduled")),
            "streaming_requested": bool(voice_output.get("streaming_requested")),
            "output_mode": voice_output.get("output_mode"),
            "user_heard_claimed": bool(voice_output.get("user_heard_claimed")),
        },
        "voice": voice_summary,
        "env_gates": {
            "env_loaded": doctor.get("env_loaded"),
            "OPENAI_API_KEY": doctor.get("OPENAI_API_KEY"),
            "STORMHELM_OPENAI_ENABLED": doctor.get("STORMHELM_OPENAI_ENABLED"),
            "STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE": doctor.get(
                "STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE"
            ),
            "STORMHELM_VOICE_ENABLED": doctor.get("STORMHELM_VOICE_ENABLED"),
            "STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED": doctor.get(
                "STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED"
            ),
            "raw_secret_logged": False,
        },
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "raw_audio_logged": False,
        "raw_secret_logged": False,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise the normal typed /chat/send path and report spoken-output truth."
    )
    parser.add_argument("--prompt", default="what time is it")
    parser.add_argument("--speak", action="store_true", help="Document intent; speech is config-gated by Core.")
    parser.add_argument("--sink-kind", default="speaker", choices=["speaker", "local", "null_stream", "mock"])
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--wait-seconds", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output-dir", default=".artifacts/voice_typed_response_smoke")
    args = parser.parse_args()

    try:
        report = run_smoke(args)
    except urllib.error.URLError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2, default=str))
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "voice_typed_response_smoke.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"artifact={report_path}")
    return 0 if report.get("text_response_received") else 1


if __name__ == "__main__":
    raise SystemExit(main())
