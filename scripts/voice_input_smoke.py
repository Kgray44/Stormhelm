from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.core.voice.models import VoiceCaptureResult
from stormhelm.core.voice.service import build_voice_subsystem


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip():
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env(project_root: Path, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    values = _parse_env_file(project_root / ".env")
    values.update(dict(base_env or os.environ))
    return {str(key): str(value) for key, value in values.items()}


def _prepare_live_voice_config(config: AppConfig) -> AppConfig:
    config.voice.enabled = True
    config.voice.mode = "manual"
    config.voice.provider = "openai"
    config.voice.debug_mock_provider = False
    config.voice.capture.enabled = True
    config.voice.capture.provider = "local"
    config.voice.capture.allow_dev_capture = True
    config.voice.vad.enabled = True
    return config


async def _run_openai_stt_smoke(config: AppConfig) -> dict[str, Any]:
    if not config.openai.enabled or not config.openai.api_key:
        return {
            "skipped": True,
            "skipped_reason": "openai_disabled_or_missing_key",
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        }

    service = build_voice_subsystem(config.voice, config.openai)
    t0 = time.perf_counter()
    session_or_result = await service.start_push_to_talk_capture(
        session_id="voice-input-smoke",
        metadata={
            "surface": "script",
            "manual_listen_session": True,
            "endpointing_enabled": True,
            "endpoint_silence_ms": config.voice.vad.silence_ms,
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        },
    )
    mic_start_ms = int((time.perf_counter() - t0) * 1000)
    if isinstance(session_or_result, VoiceCaptureResult):
        return {
            "skipped": True,
            "skipped_reason": session_or_result.error_code or session_or_result.status,
            "capture": session_or_result.to_dict(),
            "mic_start_ms": mic_start_ms,
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        }

    endpoint = await service._wait_for_capture_endpoint(session_or_result.capture_id)
    endpoint_ms = int((time.perf_counter() - t0) * 1000)
    capture = await service.stop_push_to_talk_capture(
        session_or_result.capture_id,
        reason=str(endpoint.get("reason") or "manual_stop_required"),
    )
    if not capture.ok or capture.audio_input is None:
        return {
            "skipped": True,
            "skipped_reason": capture.error_code or capture.status,
            "capture": capture.to_dict(),
            "mic_start_ms": mic_start_ms,
            "speech_detected_ms": endpoint.get("speech_detected_ms"),
            "endpoint_ms": endpoint_ms,
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        }

    transcription_start_ms = int((time.perf_counter() - t0) * 1000)
    transcription = await service._transcribe_audio(capture.audio_input)
    transcription_complete_ms = int((time.perf_counter() - t0) * 1000)
    cleanup = getattr(service.capture_provider, "cleanup_capture_audio", None)
    if callable(cleanup):
        cleanup(capture.audio_input)
    return {
        "skipped": False,
        "transcript": transcription.transcript,
        "transcript_present": bool(transcription.transcript),
        "transcription": transcription.to_dict(),
        "timings": {
            "mic_start_ms": mic_start_ms,
            "speech_detected_ms": endpoint.get("speech_detected_ms"),
            "endpoint_ms": endpoint_ms,
            "transcription_start_ms": transcription_start_ms,
            "transcription_complete_ms": transcription_complete_ms,
        },
        "capture": {
            "status": capture.status,
            "duration_ms": capture.duration_ms,
            "size_bytes": capture.size_bytes,
            "endpoint_reason": endpoint.get("reason"),
        },
        "raw_audio_logged": False,
        "raw_secret_logged": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stormhelm microphone/STT smoke.")
    parser.add_argument("--mode", default="openai-stt", choices=["openai-stt"])
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--output-dir", default=".artifacts/voice_input_smoke")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
    )
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.listen:
        result = {
            "skipped": True,
            "skipped_reason": "pass --listen to open the microphone",
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        }
    else:
        config = _prepare_live_voice_config(load_config(project_root=root, env=_env(root)))
        result = asyncio.run(_run_openai_stt_smoke(config))

    (output_dir / "voice_input_smoke_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("skipped") or result.get("transcript_present") else 1


if __name__ == "__main__":
    raise SystemExit(main())
