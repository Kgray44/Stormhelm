from __future__ import annotations

import argparse
import asyncio
import json
import math
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.providers import NullStreamingPlaybackProvider
from stormhelm.core.voice.service import build_voice_subsystem


def _openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key="probe-no-network",
        base_url="https://api.openai.com/v1",
        model="gpt-5.4-nano",
        planner_model="gpt-5.4-nano",
        reasoning_model="gpt-5.4",
        timeout_seconds=60,
        max_tool_rounds=4,
        max_output_tokens=1200,
        planner_max_output_tokens=900,
        reasoning_max_output_tokens=1400,
        instructions="",
    )


def _voice_config(
    *,
    streaming_enabled: bool,
    sink_kind: str,
    min_preroll_ms: int,
    min_preroll_chunks: int,
    min_preroll_bytes: int,
    max_preroll_wait_ms: int,
    stable_after_ms: int,
) -> VoiceConfig:
    playback_provider = "null_stream" if sink_kind == "null_stream" else "mock"
    return VoiceConfig(
        enabled=True,
        mode="manual",
        manual_input_enabled=True,
        spoken_responses_enabled=True,
        debug_mock_provider=True,
        openai=VoiceOpenAIConfig(
            stream_tts_outputs=streaming_enabled,
            streaming_fallback_to_buffered=True,
            tts_live_format="pcm",
            tts_artifact_format="mp3",
            max_tts_chars=600,
        ),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider=playback_provider,
            device="startup-probe",
            volume=0.5,
            allow_dev_playback=True,
            streaming_enabled=streaming_enabled,
            streaming_min_preroll_ms=min_preroll_ms,
            streaming_min_preroll_chunks=min_preroll_chunks,
            streaming_min_preroll_bytes=min_preroll_bytes,
            streaming_max_preroll_wait_ms=max_preroll_wait_ms,
            playback_stable_after_ms=stable_after_ms,
            max_audio_bytes=2_000_000,
            max_duration_ms=30_000,
        ),
    )


def _synthetic_pcm(*, seconds: float = 1.2, sample_rate: int = 24_000) -> bytes:
    frames = int(max(0.1, seconds) * sample_rate)
    samples = bytearray()
    for index in range(frames):
        amplitude = int(9000 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate))
        samples.extend(struct.pack("<h", amplitude))
    return bytes(samples)


def _service(
    *,
    streaming_enabled: bool,
    sink_kind: str,
    audio: bytes,
    chunk_size: int,
    min_preroll_ms: int,
    min_preroll_chunks: int,
    min_preroll_bytes: int,
    max_preroll_wait_ms: int,
    stable_after_ms: int,
) -> Any:
    service = build_voice_subsystem(
        _voice_config(
            streaming_enabled=streaming_enabled,
            sink_kind=sink_kind,
            min_preroll_ms=min_preroll_ms,
            min_preroll_chunks=min_preroll_chunks,
            min_preroll_bytes=min_preroll_bytes,
            max_preroll_wait_ms=max_preroll_wait_ms,
            stable_after_ms=stable_after_ms,
        ),
        _openai_config(),
    )
    service.provider = MockVoiceProvider(
        tts_audio_bytes=audio,
        tts_stream_chunk_size=max(1, chunk_size),
    )
    service.playback_provider = (
        NullStreamingPlaybackProvider(complete_immediately=False)
        if sink_kind == "null_stream"
        else MockPlaybackProvider(complete_immediately=not streaming_enabled)
    )
    return service


async def _run_streaming(args: argparse.Namespace, audio: bytes) -> dict[str, Any]:
    service = _service(
        streaming_enabled=True,
        sink_kind=args.sink_kind,
        audio=audio,
        chunk_size=args.chunk_size,
        min_preroll_ms=args.min_preroll_ms,
        min_preroll_chunks=args.min_preroll_chunks,
        min_preroll_bytes=args.min_preroll_bytes,
        max_preroll_wait_ms=args.max_preroll_wait_ms,
        stable_after_ms=args.stable_after_ms,
    )
    result = await service.stream_core_approved_spoken_text(
        args.text,
        speak_allowed=True,
        session_id="voice-startup-probe",
        turn_id="voice-startup-probe-streaming",
        source="voice_playback_startup_probe",
        core_result_completed_ms=20,
        request_started_ms=0,
    )
    playback_metadata = (
        dict(result.playback_result.metadata) if result.playback_result is not None else {}
    )
    return {
        "mode": "streaming",
        "ok": result.ok,
        "status": result.status,
        "first_audio_available": result.first_audio_available,
        "first_chunk_before_complete": result.first_chunk_before_complete,
        "latency": result.latency.to_dict(),
        "playback_result": result.playback_result.to_dict()
        if result.playback_result is not None
        else None,
        "playback_startup_trace": playback_metadata.get("playback_startup_trace"),
        "voice_status_playback": service.status_snapshot()["playback"],
        "raw_audio_present": False,
    }


async def _run_buffered(args: argparse.Namespace, audio: bytes) -> dict[str, Any]:
    service = _service(
        streaming_enabled=False,
        sink_kind=args.sink_kind,
        audio=audio,
        chunk_size=args.chunk_size,
        min_preroll_ms=args.min_preroll_ms,
        min_preroll_chunks=args.min_preroll_chunks,
        min_preroll_bytes=args.min_preroll_bytes,
        max_preroll_wait_ms=args.max_preroll_wait_ms,
        stable_after_ms=args.stable_after_ms,
    )
    result = await service.stream_core_approved_spoken_text(
        args.text,
        speak_allowed=True,
        session_id="voice-startup-probe",
        turn_id="voice-startup-probe-buffered",
        source="voice_playback_startup_probe",
        core_result_completed_ms=20,
        request_started_ms=0,
    )
    return {
        "mode": "buffered_fallback",
        "ok": result.ok,
        "status": result.status,
        "first_audio_available": result.first_audio_available,
        "latency": result.latency.to_dict(),
        "buffered_synthesis_result": result.buffered_synthesis_result.to_dict()
        if result.buffered_synthesis_result is not None
        else None,
        "voice_status_playback": service.status_snapshot()["playback"],
        "raw_audio_present": False,
    }


def _write_report(report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "voice_playback_startup_probe.json"
    md_path = output_dir / "voice_playback_startup_probe.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    streaming = report["streaming"]
    trace = streaming.get("playback_startup_trace") or {}
    buffered = report["buffered"]
    md_path.write_text(
        "\n".join(
            [
                "# Voice Playback Startup Probe",
                "",
                f"- generated_at: {report['generated_at']}",
                f"- sink_kind: {report['sink_kind']}",
                f"- streaming_status: {streaming['status']}",
                f"- buffered_status: {buffered['status']}",
                f"- preroll_ms: {trace.get('preroll_ms')}",
                f"- chunk_count_before_start: {trace.get('chunk_count_before_start')}",
                f"- bytes_buffered_before_start: {trace.get('bytes_buffered_before_start')}",
                f"- playback_startup_stable: {trace.get('playback_startup_stable')}",
                f"- chunk_gap_max_ms_startup: {trace.get('chunk_gap_max_ms_startup')}",
                f"- speaking_visual_flap_count_startup: {trace.get('speaking_visual_flap_count_startup')}",
                f"- warnings: {', '.join(trace.get('warnings') or []) or 'none'}",
                "",
                "Raw audio is not written to this report.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {"json": str(json_path), "markdown": str(md_path)}


async def _main_async(args: argparse.Namespace) -> dict[str, Any]:
    audio = _synthetic_pcm(seconds=args.audio_seconds)
    streaming = await _run_streaming(args, audio)
    buffered = await _run_buffered(args, audio)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "text": args.text,
        "sink_kind": args.sink_kind,
        "audio_seconds": args.audio_seconds,
        "chunk_size": args.chunk_size,
        "streaming": streaming,
        "buffered": buffered,
        "raw_audio_present": False,
    }
    report["artifacts"] = _write_report(report, Path(args.output_dir))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a local voice playback startup probe with streaming vs buffered comparison."
    )
    parser.add_argument(
        "--text",
        default="Stormhelm playback startup probe. This short phrase checks first audio stability.",
    )
    parser.add_argument("--sink-kind", choices=["mock", "null_stream"], default="mock")
    parser.add_argument("--audio-seconds", type=float, default=1.2)
    parser.add_argument("--chunk-size", type=int, default=4096)
    parser.add_argument("--min-preroll-ms", type=int, default=350)
    parser.add_argument("--min-preroll-chunks", type=int, default=2)
    parser.add_argument("--min-preroll-bytes", type=int, default=0)
    parser.add_argument("--max-preroll-wait-ms", type=int, default=1200)
    parser.add_argument("--stable-after-ms", type=int, default=180)
    parser.add_argument(
        "--output-dir",
        default=str(
            Path(".artifacts")
            / "voice_playback_startup_probe"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ),
    )
    args = parser.parse_args()
    report = asyncio.run(_main_async(args))
    trace = report["streaming"].get("playback_startup_trace") or {}
    print(
        json.dumps(
            {
                "streaming_status": report["streaming"]["status"],
                "buffered_status": report["buffered"]["status"],
                "playback_startup_stable": trace.get("playback_startup_stable"),
                "chunk_count_before_start": trace.get("chunk_count_before_start"),
                "bytes_buffered_before_start": trace.get("bytes_buffered_before_start"),
                "chunk_gap_max_ms_startup": trace.get("chunk_gap_max_ms_startup"),
                "artifacts": report["artifacts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
