from __future__ import annotations

from dataclasses import asdict, dataclass

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig


@dataclass(slots=True, frozen=True)
class VoiceAvailability:
    enabled_requested: bool
    openai_enabled: bool
    provider_configured: bool
    provider_name: str
    available: bool
    unavailable_reason: str | None
    mode: str
    realtime_allowed: bool
    stt_allowed: bool
    tts_allowed: bool
    wake_allowed: bool
    mock_provider_active: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def compute_voice_availability(config: VoiceConfig, openai_config: OpenAIConfig) -> VoiceAvailability:
    provider_name = str(config.provider or "").strip().lower()
    mode = str(config.mode or "").strip().lower() or "disabled"
    enabled_requested = bool(config.enabled) and mode != "disabled"
    openai_enabled = bool(openai_config.enabled)
    mock_provider_active = bool(config.debug_mock_provider)

    def unavailable(reason: str, *, provider_configured: bool = False) -> VoiceAvailability:
        return VoiceAvailability(
            enabled_requested=enabled_requested,
            openai_enabled=openai_enabled,
            provider_configured=provider_configured,
            provider_name=provider_name,
            available=False,
            unavailable_reason=reason,
            mode=mode,
            realtime_allowed=False,
            stt_allowed=False,
            tts_allowed=False,
            wake_allowed=False,
            mock_provider_active=mock_provider_active,
        )

    if not enabled_requested:
        return unavailable("voice_disabled")
    if not provider_name:
        return unavailable("provider_missing")
    if provider_name != "openai":
        return unavailable("unsupported_provider")
    if not openai_enabled:
        return unavailable("openai_disabled")
    if not str(openai_config.api_key or "").strip():
        return unavailable("api_key_missing")
    if not _voice_openai_models_configured(config):
        return unavailable("provider_not_configured")

    return VoiceAvailability(
        enabled_requested=enabled_requested,
        openai_enabled=openai_enabled,
        provider_configured=True,
        provider_name=provider_name,
        available=True,
        unavailable_reason=None,
        mode=mode,
        realtime_allowed=bool(config.realtime_enabled),
        stt_allowed=True,
        tts_allowed=bool(config.spoken_responses_enabled),
        wake_allowed=bool(config.wake_word_enabled),
        mock_provider_active=mock_provider_active,
    )


def _voice_openai_models_configured(config: VoiceConfig) -> bool:
    return all(
        str(value or "").strip()
        for value in (
            config.openai.stt_model,
            config.openai.tts_model,
            config.openai.tts_voice,
            config.openai.realtime_model,
            config.openai.vad_mode,
        )
    )
