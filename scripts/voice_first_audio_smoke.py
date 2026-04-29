from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.voice.models import VoiceLivePlaybackRequest
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem


def _openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key="test-key",
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


def _voice_config() -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="manual",
        manual_input_enabled=True,
        spoken_responses_enabled=True,
        debug_mock_provider=True,
        openai=VoiceOpenAIConfig(
            stream_tts_outputs=True,
            tts_live_format="pcm",
            tts_artifact_format="mp3",
            max_tts_chars=600,
        ),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            device="mock-device",
            allow_dev_playback=True,
            streaming_enabled=True,
            max_audio_bytes=256,
        ),
    )


def _service(
    *,
    audio: bytes = b"mock stream bytes for first audio smoke",
    chunk_size: int = 8,
    fail_before: bool = False,
    fail_after_chunks: int | None = None,
) -> Any:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(
        tts_audio_bytes=audio,
        tts_stream_chunk_size=chunk_size,
        tts_stream_error_code="mock_stream_failed" if fail_before else None,
        tts_stream_fail_after_chunks=fail_after_chunks,
    )
    service.playback_provider = MockPlaybackProvider(complete_immediately=False)
    return service


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)

    def percentile(q: float) -> float:
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
        return round(float(ordered[index]), 3)

    return {
        "count": len(ordered),
        "p50": percentile(0.5),
        "p90": percentile(0.9),
        "p95": percentile(0.95),
        "max": percentile(1.0),
    }


def _row_from_output(
    *,
    scenario_id: str,
    mode: str,
    text: str,
    output: Any,
    interrupted: bool = False,
) -> dict[str, Any]:
    tts = output.tts_result
    playback = output.playback_result
    latency = output.latency
    return {
        "scenario_id": scenario_id,
        "mode": mode,
        "provider": tts.provider if tts is not None else "mock",
        "playback_backend": playback.provider if playback is not None else "mock",
        "streaming_transport_kind": output.streaming_transport_kind,
        "live_format": latency.live_format,
        "artifact_format": latency.artifact_format,
        "text_length": len(text),
        "tts_start_to_first_chunk_ms": latency.tts_start_to_first_chunk_ms,
        "first_chunk_to_playback_start_ms": latency.first_chunk_to_playback_start_ms,
        "core_result_to_first_audio_ms": latency.core_result_to_first_audio_ms,
        "request_to_first_audio_ms": latency.request_to_first_audio_ms,
        "stream_complete_ms": latency.stream_complete_ms,
        "playback_complete_ms": latency.playback_complete_ms,
        "first_chunk_before_complete": output.first_chunk_before_complete,
        "fallback_used": output.fallback_used,
        "partial_playback": output.partial_playback,
        "interrupted": interrupted,
        "ok": output.ok,
        "status": output.status,
        "error_code": output.error_code,
        "user_heard_claimed": False,
    }


async def _run_stream_scenario(
    scenario_id: str,
    text: str,
    *,
    fail_before: bool = False,
    fail_after_chunks: int | None = None,
) -> dict[str, Any]:
    service = _service(
        audio=(text.encode("utf-8") or b"voice"),
        fail_before=fail_before,
        fail_after_chunks=fail_after_chunks,
    )
    started = int(time.perf_counter() * 1000)
    output = await service.stream_core_approved_spoken_text(
        text,
        speak_allowed=True,
        session_id="voice-smoke",
        turn_id=f"turn-{scenario_id}",
        source="core_spoken_summary",
        metadata={"voice_stream_used_by_normal_path": True},
        request_started_ms=started,
        core_result_completed_ms=started,
    )
    return _row_from_output(
        scenario_id=scenario_id,
        mode="mock-stream",
        text=text,
        output=output,
    )


async def _run_interruption_scenario() -> dict[str, Any]:
    service = _service(audio=b"interruptible output")
    session = service.playback_provider.start_stream(
        VoiceLivePlaybackRequest(
            speech_request_id="voice-smoke-interrupt",
            provider="mock",
            device="mock-device",
            audio_format="pcm",
            session_id="voice-smoke",
            turn_id="turn-interruption",
            allowed_to_play=True,
        )
    )
    service.playback_provider.feed_stream_chunk(session.playback_stream_id, b"chunk")
    stopped = await service.stop_speaking(
        session_id="voice-smoke",
        playback_id=session.playback_stream_id,
        reason="smoke_interruption",
    )
    return {
        "scenario_id": "interruption",
        "mode": "mock-stream",
        "provider": "mock",
        "playback_backend": "mock",
        "streaming_transport_kind": "mock_stream",
        "live_format": "pcm",
        "artifact_format": "mp3",
        "text_length": 0,
        "tts_start_to_first_chunk_ms": None,
        "first_chunk_to_playback_start_ms": None,
        "core_result_to_first_audio_ms": None,
        "request_to_first_audio_ms": None,
        "stream_complete_ms": None,
        "playback_complete_ms": None,
        "first_chunk_before_complete": True,
        "fallback_used": False,
        "partial_playback": bool(
            stopped.playback_result and stopped.playback_result.partial_playback
        ),
        "interrupted": True,
        "ok": stopped.ok,
        "status": stopped.status,
        "error_code": stopped.error_code,
        "user_heard_claimed": False,
    }


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first_audio = [
        float(row["request_to_first_audio_ms"])
        for row in rows
        if row.get("request_to_first_audio_ms") is not None
    ]
    transport_counts = Counter(
        str(row.get("streaming_transport_kind") or "unknown") for row in rows
    )
    return {
        "mode": "mock-stream",
        "scenario_count": len(rows),
        "first_audio_ms": _summary(first_audio),
        "streaming_transport_kind_counts": dict(sorted(transport_counts.items())),
        "fallback_count": sum(1 for row in rows if row.get("fallback_used")),
        "partial_playback_count": sum(1 for row in rows if row.get("partial_playback")),
        "interruption_count": sum(1 for row in rows if row.get("interrupted")),
        "unsupported_live_format_count": sum(
            1 for row in rows if row.get("error_code") == "unsupported_live_format"
        ),
        "user_heard_claimed": False,
    }


def _render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Voice First-Audio Smoke",
        "",
        f"- mode: {summary['mode']}",
        f"- scenarios: {summary['scenario_count']}",
        f"- first_audio_ms: {summary['first_audio_ms']}",
        f"- streaming_transport_kind_counts: {summary['streaming_transport_kind_counts']}",
        f"- fallback_count: {summary['fallback_count']}",
        f"- partial_playback_count: {summary['partial_playback_count']}",
        f"- interruption_count: {summary['interruption_count']}",
        f"- user_heard_claimed: {summary['user_heard_claimed']}",
        "",
        "| Scenario | Status | Transport | First audio ms | Fallback | Partial | Interrupted |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {scenario_id} | {status} | {streaming_transport_kind} | {first_audio} | {fallback} | {partial} | {interrupted} |".format(
                scenario_id=row["scenario_id"],
                status=row["status"],
                streaming_transport_kind=row["streaming_transport_kind"],
                first_audio=row.get("request_to_first_audio_ms"),
                fallback=row["fallback_used"],
                partial=row["partial_playback"],
                interrupted=row["interrupted"],
            )
        )
    return "\n".join(lines) + "\n"


def run_mock_stream_smoke(output_dir: str | Path) -> dict[str, Any]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    rows = [
        asyncio.run(_run_stream_scenario("short", "Bearing acquired.")),
        asyncio.run(
            _run_stream_scenario(
                "medium",
                "I found the route and I am checking it now.",
            )
        ),
        asyncio.run(
            _run_stream_scenario(
                "longer",
                "Stormhelm has the approved response and is measuring the first audio chunk before playback completes.",
            )
        ),
        asyncio.run(
            _run_stream_scenario(
                "failure_before_first_chunk",
                "Fallback should stay explicit.",
                fail_before=True,
            )
        ),
        asyncio.run(
            _run_stream_scenario(
                "failure_after_partial",
                "Partial playback must stay partial.",
                fail_after_chunks=1,
            )
        ),
        asyncio.run(_run_interruption_scenario()),
    ]
    summary = _build_summary(rows)
    (target / "voice_first_audio_smoke_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (target / "voice_first_audio_smoke_events.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    (target / "voice_first_audio_smoke_report.md").write_text(
        _render_report(summary, rows),
        encoding="utf-8",
    )
    return {"summary": summary, "rows": rows, "output_dir": str(target)}


def _write_skipped(output_dir: Path, *, mode: str, reason: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "scenario_count": 0,
        "status": "skipped",
        "reason": reason,
        "user_heard_claimed": False,
    }
    (output_dir / "voice_first_audio_smoke_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "voice_first_audio_smoke_events.jsonl").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "voice_first_audio_smoke_report.md").write_text(
        "# Voice First-Audio Smoke\n\n"
        f"- mode: {mode}\n"
        "- status: skipped\n"
        f"- reason: {reason}\n"
        "- user_heard_claimed: False\n",
        encoding="utf-8",
    )
    return {"summary": payload, "rows": [], "output_dir": str(output_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stormhelm voice first-audio smoke.")
    parser.add_argument("--mode", default="mock-stream", choices=("mock-stream", "local-playback", "openai-stream"))
    parser.add_argument("--output-dir", default=".artifacts/voice_first_audio_smoke")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    if args.mode == "mock-stream":
        result = run_mock_stream_smoke(output_dir)
    elif args.mode == "openai-stream":
        if os.getenv("STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE") != "1":
            result = _write_skipped(
                output_dir,
                mode=args.mode,
                reason="live OpenAI smoke requires STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE=1",
            )
        else:
            result = _write_skipped(
                output_dir,
                mode=args.mode,
                reason="live OpenAI smoke runner is deferred to L6 device/network validation",
            )
    else:
        if os.getenv("STORMHELM_RUN_LIVE_VOICE_SMOKE") != "1":
            result = _write_skipped(
                output_dir,
                mode=args.mode,
                reason="local playback smoke requires STORMHELM_RUN_LIVE_VOICE_SMOKE=1",
            )
        else:
            result = _write_skipped(
                output_dir,
                mode=args.mode,
                reason="real device playback benchmark is deferred to L6 hardware validation",
            )
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
