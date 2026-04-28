from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from stormhelm.config.loader import load_config
from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.config.models import VoicePostWakeConfig
from stormhelm.config.models import VoiceRealtimeConfig
from stormhelm.config.models import VoiceVADConfig
from stormhelm.config.models import VoiceWakeConfig
from stormhelm.core.voice.service import build_voice_subsystem


SMOKE_TEXT = "Bearing acquired. Voice output test complete."


def _mock_openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-5.4-nano",
        planner_model="gpt-5.4-nano",
        reasoning_model="gpt-5.4",
        timeout_seconds=60,
        max_tool_rounds=4,
        max_output_tokens=1024,
        planner_max_output_tokens=512,
        reasoning_max_output_tokens=1024,
        instructions="voice smoke test",
    )


def _mock_voice_config() -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="output_only",
        spoken_responses_enabled=True,
        manual_input_enabled=True,
        debug_mock_provider=True,
        openai=VoiceOpenAIConfig(
            tts_voice="onyx",
            persist_tts_outputs=False,
            max_audio_bytes=1024,
            max_audio_seconds=10,
        ),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            allow_dev_playback=True,
        ),
        capture=VoiceCaptureConfig(enabled=False),
        wake=VoiceWakeConfig(enabled=False),
        post_wake=VoicePostWakeConfig(enabled=False),
        vad=VoiceVADConfig(enabled=False),
        realtime=VoiceRealtimeConfig(enabled=False),
    )


async def _run_smoke(*, live: bool, text: str) -> dict[str, Any]:
    if live:
        app_config = load_config()
        service = build_voice_subsystem(app_config.voice, app_config.openai)
    else:
        service = build_voice_subsystem(_mock_voice_config(), _mock_openai_config())

    readiness = service.runtime_mode_readiness_report().to_dict()
    synthesis = await service.synthesize_speech_text(
        text,
        source="output_only_smoke",
        persona_mode="test",
        session_id="voice-smoke",
        metadata={"live_provider": live},
    )
    playback = await service.play_speech_output(
        synthesis,
        session_id="voice-smoke",
        metadata={"live_provider": live},
    )
    status = service.status_snapshot()
    status_text = str(status).lower()
    return {
        "live": live,
        "skipped": False,
        "runtime_mode": readiness,
        "synthesis": {
            "ok": synthesis.ok,
            "status": synthesis.status,
            "provider": synthesis.provider,
            "model": synthesis.model,
            "voice": synthesis.voice,
            "format": synthesis.format,
            "audio_bytes_produced": bool(
                synthesis.audio_output and synthesis.audio_output.size_bytes > 0
            ),
            "size_bytes": synthesis.audio_output.size_bytes
            if synthesis.audio_output is not None
            else 0,
            "error_code": synthesis.error_code,
        },
        "playback": {
            "ok": playback.ok,
            "status": playback.status,
            "provider": playback.provider,
            "device": playback.device,
            "played_locally": playback.played_locally,
            "user_heard_claimed": playback.user_heard_claimed,
            "error_code": playback.error_code,
            "error_message": playback.error_message,
        },
        "privacy": {
            "raw_audio_in_status": "'audio_bytes':" in status_text
            or '"audio_bytes":' in status_text
            or "'raw_audio_bytes':" in status_text
            or '"raw_audio_bytes":' in status_text
            or "'generated_audio_bytes':" in status_text
            or '"generated_audio_bytes":' in status_text,
            "capture_started": bool(status["capture"].get("active_capture_id")),
            "wake_active": bool(status["wake"].get("monitoring_active")),
            "vad_active": bool(status["vad"].get("active")),
            "realtime_active": bool(status["realtime"].get("session_active")),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Stormhelm output-only voice smoke checks."
    )
    parser.add_argument("--live", action="store_true", help="Use live configured providers.")
    parser.add_argument("--text", default=SMOKE_TEXT)
    args = parser.parse_args()

    live_requested = bool(args.live)
    live_allowed = os.environ.get("STORMHELM_RUN_LIVE_VOICE_SMOKE") == "1"
    if live_requested and not live_allowed:
        print(
            json.dumps(
                {
                    "live": True,
                    "skipped": True,
                    "reason": "Set STORMHELM_RUN_LIVE_VOICE_SMOKE=1 to run live voice smoke.",
                },
                indent=2,
            )
        )
        return 0

    result = asyncio.run(_run_smoke(live=live_requested, text=str(args.text or "")))
    print(json.dumps(result, indent=2))
    return 0 if result["synthesis"]["ok"] and result["playback"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
