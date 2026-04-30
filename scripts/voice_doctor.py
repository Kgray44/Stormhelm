from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.core.voice.service import build_voice_subsystem


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _enabled(value: Any) -> str:
    return "enabled" if _truthy(value) else "disabled"


def _present(value: Any) -> str:
    return "present" if str(value or "").strip() else "missing"


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
        if key:
            parsed[key] = value.strip().strip('"').strip("'")
    return parsed


def _env_values(
    *, project_root: Path, base_env: Mapping[str, str] | None = None
) -> dict[str, str]:
    values = _parse_env_file(project_root / ".env")
    values.update(dict(base_env or os.environ))
    return {str(key): str(value) for key, value in values.items()}


def _env_tracked_by_git(project_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", ".env"],
            cwd=str(project_root),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    return bool(result.stdout.strip())


def _load_app_config(
    project_root: Path, env_values: Mapping[str, str]
) -> tuple[AppConfig | None, str]:
    if not (project_root / "config" / "default.toml").exists():
        return None, "config_default_missing"
    try:
        return load_config(project_root=project_root, env=env_values), "loaded"
    except Exception:
        return None, "config_load_failed"


def _playback_status(config: AppConfig | None, env_values: Mapping[str, str]) -> dict[str, Any]:
    if config is not None:
        service = build_voice_subsystem(config.voice, config.openai)
        status = service.status_snapshot()
        playback = dict(status.get("playback") or {})
        return {
            "provider": playback.get("provider") or config.voice.playback.provider,
            "available": bool(playback.get("available")),
            "speaker_backend": playback.get("speaker_backend"),
            "speaker_backend_available": bool(
                playback.get("speaker_backend_available")
                or (
                    playback.get("provider") == "local"
                    and playback.get("available") is True
                )
            ),
            "unavailable_reason": playback.get("unavailable_reason"),
        }
    provider = str(env_values.get("STORMHELM_VOICE_PLAYBACK_PROVIDER") or "local")
    enabled = _truthy(env_values.get("STORMHELM_VOICE_PLAYBACK_ENABLED"))
    return {
        "provider": provider,
        "available": bool(enabled and provider.lower() == "local" and sys.platform.startswith("win")),
        "speaker_backend": "winmm_waveout" if provider.lower() == "local" else None,
        "speaker_backend_available": bool(
            enabled and provider.lower() == "local" and sys.platform.startswith("win")
        ),
        "unavailable_reason": None
        if enabled and provider.lower() == "local" and sys.platform.startswith("win")
        else "speaker_backend_not_loaded",
    }


def _voice_status(config: AppConfig | None) -> dict[str, Any]:
    if config is None:
        return {}
    service = build_voice_subsystem(config.voice, config.openai)
    return service.status_snapshot()


def build_voice_doctor_report(
    *,
    project_root: str | Path | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    env_path = root / ".env"
    values = _env_values(project_root=root, base_env=base_env)
    app_config, config_status = _load_app_config(root, values)
    playback = _playback_status(app_config, values)
    voice_status = _voice_status(app_config)
    capture = dict(voice_status.get("capture") or {})
    voice_input = dict(voice_status.get("voice_input") or {})
    platform_name = "Windows" if sys.platform.startswith("win") else platform.system()

    return {
        "env_loaded": env_path.exists(),
        "env_tracked_by_git": _env_tracked_by_git(root),
        "config_load_status": config_status,
        "platform": platform_name,
        "OPENAI_API_KEY": _present(values.get("OPENAI_API_KEY")),
        "STORMHELM_OPENAI_ENABLED": _enabled(values.get("STORMHELM_OPENAI_ENABLED")),
        "STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE": _enabled(
            values.get("STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE")
        ),
        "STORMHELM_VOICE_ENABLED": _enabled(values.get("STORMHELM_VOICE_ENABLED")),
        "STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED": _enabled(
            values.get("STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED")
        ),
        "STORMHELM_VOICE_INPUT_ENABLED": _enabled(
            values.get("STORMHELM_VOICE_INPUT_ENABLED")
            or values.get("STORMHELM_VOICE_CAPTURE_ENABLED")
        ),
        "STORMHELM_VOICE_MICROPHONE_ENABLED": _enabled(
            values.get("STORMHELM_VOICE_MICROPHONE_ENABLED")
            or values.get("STORMHELM_VOICE_CAPTURE_ENABLED")
        ),
        "STORMHELM_VOICE_PUSH_TO_TALK_ENABLED": _enabled(
            values.get("STORMHELM_VOICE_PUSH_TO_TALK_ENABLED")
            or values.get("STORMHELM_VOICE_MANUAL_INPUT_ENABLED")
            or "1"
        ),
        "STORMHELM_VOICE_STT_PROVIDER": str(
            values.get("STORMHELM_VOICE_STT_PROVIDER")
            or values.get("STORMHELM_VOICE_PROVIDER")
            or "openai"
        ),
        "STORMHELM_VOICE_STT_MODEL": str(
            values.get("STORMHELM_VOICE_STT_MODEL")
            or values.get("STORMHELM_VOICE_OPENAI_STT_MODEL")
            or (
                app_config.voice.openai.stt_model
                if app_config is not None
                else "gpt-4o-mini-transcribe"
            )
        ),
        "STORMHELM_VOICE_OPENAI_STREAM_TTS_OUTPUTS": _enabled(
            values.get("STORMHELM_VOICE_OPENAI_STREAM_TTS_OUTPUTS")
        ),
        "STORMHELM_VOICE_OPENAI_TTS_LIVE_FORMAT": str(
            values.get("STORMHELM_VOICE_OPENAI_TTS_LIVE_FORMAT") or "pcm"
        ),
        "STORMHELM_VOICE_PLAYBACK_ENABLED": _enabled(
            values.get("STORMHELM_VOICE_PLAYBACK_ENABLED")
        ),
        "STORMHELM_VOICE_PLAYBACK_PROVIDER": str(
            playback.get("provider")
            or values.get("STORMHELM_VOICE_PLAYBACK_PROVIDER")
            or "local"
        ),
        "STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK": _enabled(
            values.get("STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK")
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_ENABLED": _enabled(
            values.get("STORMHELM_VOICE_PLAYBACK_STREAMING_ENABLED")
        ),
        "speaker_backend": playback.get("speaker_backend"),
        "speaker_backend_available": bool(playback.get("speaker_backend_available")),
        "speaker_unavailable_reason": playback.get("unavailable_reason"),
        "microphone_available": bool(
            voice_input.get("microphone_available") or capture.get("available")
        ),
        "selected_input_device": capture.get("device")
        or values.get("STORMHELM_VOICE_CAPTURE_DEVICE")
        or "default",
        "capture_provider": capture.get("provider")
        or values.get("STORMHELM_VOICE_CAPTURE_PROVIDER")
        or "local",
        "capture_unavailable_reason": capture.get("unavailable_reason"),
        "wake_enabled": bool(
            app_config.voice.wake.enabled if app_config is not None else _truthy(values.get("STORMHELM_VOICE_WAKE_ENABLED"))
        ),
        "current_voice_state": voice_input.get("current_voice_state"),
        "live_smoke_gate": _enabled(values.get("STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE")),
        "ordinary_runtime_requires_live_smoke_gate": False,
        "raw_secret_logged": False,
        "raw_audio_logged": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Stormhelm voice runtime gates.")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Stormhelm project root. Defaults to the repository root.",
    )
    args = parser.parse_args(argv)
    report = build_voice_doctor_report(project_root=args.project_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
