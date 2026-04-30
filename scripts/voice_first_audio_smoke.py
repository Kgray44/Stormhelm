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
from stormhelm.core.voice.providers import NullStreamingPlaybackProvider
from stormhelm.core.voice.service import build_voice_subsystem


SPEAKER_SINK_KINDS = {"speaker", "local", "local_speaker", "windows_speaker"}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        parsed[key] = value.strip().strip('"').strip("'")
    return parsed


def load_smoke_env(
    *,
    base_env: Any | None = None,
    env_file: str | Path | None = None,
) -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    env_path = Path(env_file) if env_file is not None else root / ".env"
    merged = dict(_parse_env_file(env_path))
    merged.update(dict(base_env or os.environ))
    return {str(key): str(value) for key, value in merged.items()}


def smoke_env_status(env: Any | None = None) -> dict[str, Any]:
    values = dict(env or {})
    return {
        "OPENAI_API_KEY": "present"
        if str(values.get("OPENAI_API_KEY") or "").strip()
        else "missing",
        "STORMHELM_OPENAI_ENABLED": "enabled"
        if _truthy(values.get("STORMHELM_OPENAI_ENABLED"))
        else "disabled",
        "STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE": "enabled"
        if _truthy(values.get("STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE"))
        else "disabled",
        "raw_secret_logged": False,
    }


def _openai_config(
    *,
    api_key: str = "test-key",
    base_url: str = "https://api.openai.com/v1",
) -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key=api_key,
        base_url=base_url,
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
    sink_kind: str = "mock",
    debug_mock_provider: bool = True,
) -> VoiceConfig:
    normalized_sink = str(sink_kind or "mock").strip().lower()
    if normalized_sink == "null_stream":
        playback_provider = "null_stream"
        playback_device = "null-stream"
    elif normalized_sink in SPEAKER_SINK_KINDS:
        playback_provider = "local"
        playback_device = "default"
    else:
        playback_provider = "mock"
        playback_device = "mock-device"
    return VoiceConfig(
        enabled=True,
        mode="manual",
        manual_input_enabled=True,
        spoken_responses_enabled=True,
        debug_mock_provider=debug_mock_provider,
        openai=VoiceOpenAIConfig(
            stream_tts_outputs=True,
            tts_live_format="pcm",
            tts_artifact_format="mp3",
            max_tts_chars=600,
        ),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider=playback_provider,
            device=playback_device,
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
    sink_kind: str = "mock",
) -> Any:
    service = build_voice_subsystem(
        _voice_config(sink_kind=sink_kind),
        _openai_config(),
    )
    service.provider = MockVoiceProvider(
        tts_audio_bytes=audio,
        tts_stream_chunk_size=chunk_size,
        tts_stream_error_code="mock_stream_failed" if fail_before else None,
        tts_stream_fail_after_chunks=fail_after_chunks,
    )
    service.playback_provider = (
        NullStreamingPlaybackProvider()
        if sink_kind == "null_stream"
        else MockPlaybackProvider(complete_immediately=False)
    )
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
    sink_kind = (
        latency.sink_kind
        or (playback.metadata.get("sink_kind") if playback is not None else "")
        or (playback.provider if playback is not None else "mock")
    )
    return {
        "scenario_id": scenario_id,
        "mode": mode,
        "provider": tts.provider if tts is not None else "mock",
        "playback_backend": playback.provider if playback is not None else "mock",
        "sink_kind": sink_kind,
        "streaming_transport_kind": output.streaming_transport_kind,
        "live_format": latency.live_format,
        "artifact_format": latency.artifact_format,
        "text_length": len(text),
        "tts_start_to_first_chunk_ms": latency.tts_start_to_first_chunk_ms,
        "first_chunk_to_playback_start_ms": latency.first_chunk_to_playback_start_ms,
        "first_chunk_to_sink_accept_ms": latency.first_chunk_to_sink_accept_ms,
        "core_result_to_first_audio_ms": latency.core_result_to_first_audio_ms,
        "core_result_to_first_output_start_ms": (
            latency.core_result_to_first_output_start_ms
        ),
        "request_to_first_audio_ms": latency.request_to_first_audio_ms,
        "first_output_start_ms": latency.first_output_start_ms,
        "null_sink_first_accept_ms": latency.null_sink_first_accept_ms,
        "live_openai_voice_smoke_run": latency.live_openai_voice_smoke_run,
        "live_openai_first_chunk_ms": latency.live_openai_first_chunk_ms,
        "realtime_deferred_to_l6": True,
        "realtime_session_creation_attempted": False,
        "stream_complete_ms": latency.stream_complete_ms,
        "playback_complete_ms": latency.playback_complete_ms,
        "first_chunk_before_complete": output.first_chunk_before_complete,
        "fallback_used": output.fallback_used,
        "partial_playback": output.partial_playback,
        "interrupted": interrupted,
        "ok": output.ok,
        "status": output.status,
        "error_code": output.error_code,
        "raw_audio_logged": False,
        "user_heard_claimed": bool(
            latency.user_heard_claimed
            or (playback is not None and playback.user_heard_claimed)
        ),
    }


async def _run_stream_scenario(
    scenario_id: str,
    text: str,
    *,
    fail_before: bool = False,
    fail_after_chunks: int | None = None,
    sink_kind: str = "mock",
    mode: str = "mock-stream",
) -> dict[str, Any]:
    service = _service(
        audio=(text.encode("utf-8") or b"voice"),
        fail_before=fail_before,
        fail_after_chunks=fail_after_chunks,
        sink_kind=sink_kind,
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
        mode=mode,
        text=text,
        output=output,
    )


async def _run_interruption_scenario() -> dict[str, Any]:
    service = _service(audio=b"interruptible output", sink_kind="null_stream")
    session = service.playback_provider.start_stream(
        VoiceLivePlaybackRequest(
            speech_request_id="voice-smoke-interrupt",
            provider="null_stream",
            device="null-stream",
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
        "playback_backend": "null_stream",
        "sink_kind": "null_stream",
        "streaming_transport_kind": "mock_stream",
        "live_format": "pcm",
        "artifact_format": "mp3",
        "text_length": 0,
        "tts_start_to_first_chunk_ms": None,
        "first_chunk_to_playback_start_ms": None,
        "first_chunk_to_sink_accept_ms": None,
        "core_result_to_first_audio_ms": None,
        "core_result_to_first_output_start_ms": None,
        "request_to_first_audio_ms": None,
        "first_output_start_ms": None,
        "null_sink_first_accept_ms": None,
        "live_openai_voice_smoke_run": False,
        "live_openai_first_chunk_ms": None,
        "realtime_deferred_to_l6": True,
        "realtime_session_creation_attempted": False,
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
        "raw_audio_logged": False,
        "user_heard_claimed": False,
    }


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first_audio = [
        float(row["request_to_first_audio_ms"])
        for row in rows
        if row.get("request_to_first_audio_ms") is not None
    ]
    first_output = [
        float(row["first_output_start_ms"])
        for row in rows
        if row.get("first_output_start_ms") is not None
    ]
    null_sink_accept = [
        float(row["null_sink_first_accept_ms"])
        for row in rows
        if row.get("null_sink_first_accept_ms") is not None
    ]
    live_openai_first_chunk = [
        float(row["live_openai_first_chunk_ms"])
        for row in rows
        if row.get("live_openai_first_chunk_ms") is not None
    ]
    transport_counts = Counter(
        str(row.get("streaming_transport_kind") or "unknown") for row in rows
    )
    sink_counts = Counter(str(row.get("sink_kind") or "unknown") for row in rows)
    return {
        "mode": "mock-stream",
        "scenario_count": len(rows),
        "first_audio_ms": _summary(first_audio),
        "first_output_start_ms": _summary(first_output),
        "null_sink_first_accept_ms": _summary(null_sink_accept),
        "live_openai_first_chunk_ms": _summary(live_openai_first_chunk),
        "streaming_transport_kind_counts": dict(sorted(transport_counts.items())),
        "sink_kind_counts": dict(sorted(sink_counts.items())),
        "fallback_count": sum(1 for row in rows if row.get("fallback_used")),
        "partial_playback_count": sum(1 for row in rows if row.get("partial_playback")),
        "interruption_count": sum(1 for row in rows if row.get("interrupted")),
        "unsupported_live_format_count": sum(
            1 for row in rows if row.get("error_code") == "unsupported_live_format"
        ),
        "live_openai_voice_smoke_run_count": sum(
            1 for row in rows if row.get("live_openai_voice_smoke_run")
        ),
        "realtime_deferred_to_l6": True,
        "realtime_session_creation_attempted": False,
        "raw_audio_logged": False,
        "user_heard_claimed": any(row.get("user_heard_claimed") for row in rows),
    }


def _render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Voice First-Audio Smoke",
        "",
        f"- mode: {summary['mode']}",
        f"- scenarios: {summary['scenario_count']}",
        f"- first_audio_ms: {summary['first_audio_ms']}",
        f"- first_output_start_ms: {summary['first_output_start_ms']}",
        f"- null_sink_first_accept_ms: {summary['null_sink_first_accept_ms']}",
        f"- streaming_transport_kind_counts: {summary['streaming_transport_kind_counts']}",
        f"- sink_kind_counts: {summary['sink_kind_counts']}",
        f"- fallback_count: {summary['fallback_count']}",
        f"- partial_playback_count: {summary['partial_playback_count']}",
        f"- interruption_count: {summary['interruption_count']}",
        f"- user_heard_claimed: {summary['user_heard_claimed']}",
        "",
        "| Scenario | Status | Transport | Sink | First output ms | First audio ms | Fallback | Partial | Interrupted |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {scenario_id} | {status} | {streaming_transport_kind} | {sink_kind} | {first_output} | {first_audio} | {fallback} | {partial} | {interrupted} |".format(
                scenario_id=row["scenario_id"],
                status=row["status"],
                streaming_transport_kind=row["streaming_transport_kind"],
                sink_kind=row.get("sink_kind"),
                first_output=row.get("first_output_start_ms"),
                first_audio=row.get("request_to_first_audio_ms"),
                fallback=row["fallback_used"],
                partial=row["partial_playback"],
                interrupted=row["interrupted"],
            )
        )
    return "\n".join(lines) + "\n"


def run_mock_stream_smoke(
    output_dir: str | Path,
    *,
    sink_kind: str = "mock",
) -> dict[str, Any]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    rows = [
        asyncio.run(
            _run_stream_scenario(
                "short",
                "Bearing acquired.",
                sink_kind=sink_kind,
            )
        ),
        asyncio.run(
            _run_stream_scenario(
                "medium",
                "I found the route and I am checking it now.",
                sink_kind=sink_kind,
            )
        ),
        asyncio.run(
            _run_stream_scenario(
                "longer",
                "Stormhelm has the approved response and is measuring the first audio chunk before playback completes.",
                sink_kind=sink_kind,
            )
        ),
        asyncio.run(
            _run_stream_scenario(
                "failure_before_first_chunk",
                "Fallback should stay explicit.",
                fail_before=True,
                sink_kind=sink_kind,
            )
        ),
        asyncio.run(
            _run_stream_scenario(
                "failure_after_partial",
                "Partial playback must stay partial.",
                fail_after_chunks=1,
                sink_kind=sink_kind,
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


async def _run_live_openai_stream_scenario(
    text: str,
    *,
    api_key: str,
    base_url: str,
    sink_kind: str,
) -> dict[str, Any]:
    service = build_voice_subsystem(
        _voice_config(sink_kind=sink_kind, debug_mock_provider=False),
        _openai_config(api_key=api_key, base_url=base_url),
    )
    if sink_kind == "null_stream":
        service.playback_provider = NullStreamingPlaybackProvider()
    started = int(time.perf_counter() * 1000)
    output = await service.stream_core_approved_spoken_text(
        text,
        speak_allowed=True,
        session_id="voice-live-smoke",
        turn_id="turn-openai-stream",
        source="core_spoken_summary",
        metadata={
            "voice_stream_used_by_normal_path": True,
            "live_openai_voice_smoke_run": True,
        },
        request_started_ms=started,
        core_result_completed_ms=started,
    )
    row = _row_from_output(
        scenario_id="live_openai_stream",
        mode="openai-stream",
        text=text,
        output=output,
    )
    row["live_openai_voice_smoke_run"] = True
    row["live_openai_first_chunk_ms"] = row.get("tts_start_to_first_chunk_ms")
    return row


def run_live_openai_stream_smoke(
    output_dir: str | Path,
    *,
    env: Any | None = None,
    sink_kind: str = "null_stream",
    text: str = "Stormhelm has approved this voice smoke response.",
) -> dict[str, Any]:
    target = Path(output_dir)
    env = dict(env) if env is not None else load_smoke_env()
    env_status = smoke_env_status(env)
    if not _truthy(env.get("STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE")):
        return _write_skipped(
            target,
            mode="openai-stream",
            reason="live OpenAI smoke requires STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE=1",
            env_status=env_status,
        )
    if not _truthy(env.get("STORMHELM_OPENAI_ENABLED")):
        return _write_skipped(
            target,
            mode="openai-stream",
            reason="live OpenAI smoke requires STORMHELM_OPENAI_ENABLED=1",
            env_status=env_status,
        )
    api_key = str(env.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return _write_skipped(
            target,
            mode="openai-stream",
            reason="live OpenAI smoke requires OPENAI_API_KEY",
            env_status=env_status,
        )
    base_url = str(env.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").strip()
    target.mkdir(parents=True, exist_ok=True)
    rows = [
        asyncio.run(
            _run_live_openai_stream_scenario(
                text,
                api_key=api_key,
                base_url=base_url,
                sink_kind=sink_kind,
            )
        )
    ]
    summary = _build_summary(rows)
    summary["mode"] = "openai-stream"
    summary["env_gates"] = env_status
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


def _write_skipped(
    output_dir: Path,
    *,
    mode: str,
    reason: str,
    env_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "scenario_count": 0,
        "status": "skipped",
        "reason": reason,
        "realtime_deferred_to_l6": True,
        "realtime_session_creation_attempted": False,
        "raw_audio_logged": False,
        "user_heard_claimed": False,
    }
    if env_status is not None:
        payload["env_gates"] = env_status
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
        "- realtime_deferred_to_l6: True\n"
        "- user_heard_claimed: False\n",
        encoding="utf-8",
    )
    return {"summary": payload, "rows": [], "output_dir": str(output_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stormhelm voice first-audio smoke.")
    parser.add_argument("--mode", default="mock-stream", choices=("mock-stream", "local-playback", "openai-stream"))
    parser.add_argument("--output-dir", default=".artifacts/voice_first_audio_smoke")
    parser.add_argument(
        "--sink-kind",
        default="null_stream",
        choices=("mock", "null_stream", "speaker", "local", "local_speaker", "windows_speaker"),
    )
    parser.add_argument("--print-env-gates", action="store_true")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    smoke_env = load_smoke_env()
    if args.print_env_gates:
        print(json.dumps(smoke_env_status(smoke_env), indent=2, sort_keys=True))
        return 0
    if args.mode == "mock-stream":
        result = run_mock_stream_smoke(output_dir, sink_kind=args.sink_kind)
    elif args.mode == "openai-stream":
        result = run_live_openai_stream_smoke(
            output_dir,
            sink_kind=args.sink_kind,
            env=smoke_env,
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
