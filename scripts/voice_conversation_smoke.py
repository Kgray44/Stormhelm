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
from stormhelm.core.container import build_container


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


def _prepare_live_voice_config(config: AppConfig, *, speak: bool) -> AppConfig:
    config.voice.enabled = True
    config.voice.mode = "manual"
    config.voice.provider = "openai"
    config.voice.debug_mock_provider = False
    config.voice.spoken_responses_enabled = bool(speak)
    config.voice.capture.enabled = True
    config.voice.capture.provider = "local"
    config.voice.capture.allow_dev_capture = True
    config.voice.vad.enabled = True
    if speak:
        config.voice.playback.enabled = True
    return config


async def _run_conversation(config: AppConfig, *, speak: bool) -> dict[str, Any]:
    if not config.openai.enabled or not config.openai.api_key:
        return {
            "skipped": True,
            "skipped_reason": "openai_disabled_or_missing_key",
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        }
    container = build_container(config)
    started = time.perf_counter()
    await container.start()
    try:
        result = await container.voice.listen_and_submit_turn(
            session_id="voice-conversation-smoke",
            mode="ghost",
            play_response=speak,
            metadata={"surface": "script", "smoke": "voice_conversation"},
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        turn_result = result.voice_turn_result
        core_result = turn_result.core_result if turn_result is not None else None
        latency = container.voice.last_first_audio_latency
        spoken = container.voice.last_spoken_result or {}
        status = container.voice.status_snapshot()
        return {
            "skipped": False,
            "final_status": result.final_status,
            "transcript_present": bool(
                turn_result
                and turn_result.turn is not None
                and turn_result.turn.transcript
            ),
            "transcript": turn_result.turn.transcript
            if turn_result is not None and turn_result.turn is not None
            else "",
            "core_response_present": bool(
                core_result
                and (core_result.visual_summary or core_result.spoken_summary)
            ),
            "core_result_state": core_result.result_state if core_result else None,
            "visible_response": core_result.visual_summary if core_result else "",
            "spoken_response_started": bool(
                spoken.get("spoken_response_started")
                or result.playback_result is not None
                or result.streaming_output_result is not None
            ),
            "user_heard_claimed": bool(
                status.get("runtime_truth", {}).get("user_heard_claimed")
            ),
            "skipped_reason": None,
            "timings": {
                "total_ms": elapsed_ms,
                "capture_duration_ms": result.capture_result.duration_ms
                if result.capture_result is not None
                else None,
                "stt_provider_latency_ms": turn_result.transcription_result.provider_latency_ms
                if turn_result is not None
                and turn_result.transcription_result is not None
                else None,
                "core_result_to_first_tts_chunk_ms": latency.tts_start_to_first_chunk_ms
                if latency is not None
                else None,
                "first_tts_chunk_to_speaker_output_ms": latency.first_chunk_to_sink_accept_ms
                if latency is not None
                else None,
                "first_output_start_ms": latency.first_output_start_ms
                if latency is not None
                else None,
                "completion_ms": latency.stream_complete_ms
                if latency is not None
                else None,
            },
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        }
    finally:
        await container.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run an end-to-end Stormhelm microphone to spoken response smoke."
    )
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--speak", action="store_true")
    parser.add_argument("--output-dir", default=".artifacts/voice_conversation_smoke")
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
        config = _prepare_live_voice_config(
            load_config(project_root=root, env=_env(root)),
            speak=bool(args.speak),
        )
        result = asyncio.run(_run_conversation(config, speak=bool(args.speak)))

    (output_dir / "voice_conversation_smoke_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("skipped") or result.get("core_response_present") else 1


if __name__ == "__main__":
    raise SystemExit(main())
