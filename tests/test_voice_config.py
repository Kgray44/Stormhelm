from __future__ import annotations

from stormhelm.config.loader import load_config


def test_load_config_defaults_voice_to_disabled_foundation(temp_project_root) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.voice.enabled is False
    assert config.voice.provider == "openai"
    assert config.voice.mode == "disabled"
    assert config.voice.wake_word_enabled is False
    assert config.voice.spoken_responses_enabled is False
    assert config.voice.manual_input_enabled is True
    assert config.voice.realtime_enabled is False
    assert config.voice.debug_mock_provider is True
    assert config.voice.playback.enabled is False
    assert config.voice.playback.provider == "local"
    assert config.voice.playback.device == "default"
    assert config.voice.playback.volume == 1.0
    assert config.voice.playback.allow_dev_playback is False
    assert config.voice.playback.max_audio_bytes == 10_000_000
    assert config.voice.playback.max_duration_ms == 120_000
    assert config.voice.playback.delete_transient_after_playback is True
    assert config.voice.openai.stt_model == "gpt-4o-mini-transcribe"
    assert config.voice.openai.transcription_language is None
    assert config.voice.openai.transcription_prompt is None
    assert config.voice.openai.timeout_seconds == 60
    assert config.voice.openai.max_audio_seconds == 30
    assert config.voice.openai.max_audio_bytes == 25 * 1024 * 1024
    assert config.voice.openai.tts_model == "gpt-4o-mini-tts"
    assert config.voice.openai.tts_voice == "cedar"
    assert config.voice.openai.tts_format == "mp3"
    assert config.voice.openai.tts_speed == 1.0
    assert config.voice.openai.max_tts_chars == 600
    assert config.voice.openai.output_audio_dir is None
    assert config.voice.openai.persist_tts_outputs is False
    assert config.voice.openai.realtime_model == "gpt-realtime"
    assert config.voice.openai.vad_mode == "server_vad"


def test_load_config_applies_voice_environment_overrides(temp_project_root) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_VOICE_ENABLED": "true",
            "STORMHELM_VOICE_PROVIDER": "openai",
            "STORMHELM_VOICE_MODE": "manual",
            "STORMHELM_VOICE_WAKE_WORD_ENABLED": "true",
            "STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED": "true",
            "STORMHELM_VOICE_MANUAL_INPUT_ENABLED": "false",
            "STORMHELM_VOICE_REALTIME_ENABLED": "true",
            "STORMHELM_VOICE_DEBUG_MOCK_PROVIDER": "false",
            "STORMHELM_VOICE_PLAYBACK_ENABLED": "true",
            "STORMHELM_VOICE_PLAYBACK_PROVIDER": "mock",
            "STORMHELM_VOICE_PLAYBACK_DEVICE": "test-device",
            "STORMHELM_VOICE_PLAYBACK_VOLUME": "0.42",
            "STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK": "true",
            "STORMHELM_VOICE_PLAYBACK_MAX_AUDIO_BYTES": "456789",
            "STORMHELM_VOICE_PLAYBACK_MAX_DURATION_MS": "6543",
            "STORMHELM_VOICE_PLAYBACK_DELETE_TRANSIENT_AFTER_PLAYBACK": "false",
            "STORMHELM_VOICE_OPENAI_STT_MODEL": "gpt-4o-transcribe",
            "STORMHELM_VOICE_OPENAI_TRANSCRIPTION_LANGUAGE": "en",
            "STORMHELM_VOICE_OPENAI_TRANSCRIPTION_PROMPT": "Stormhelm command terms",
            "STORMHELM_VOICE_OPENAI_TIMEOUT_SECONDS": "12",
            "STORMHELM_VOICE_OPENAI_MAX_AUDIO_SECONDS": "9",
            "STORMHELM_VOICE_OPENAI_MAX_AUDIO_BYTES": "123456",
            "STORMHELM_VOICE_OPENAI_TTS_MODEL": "gpt-4o-audio-preview",
            "STORMHELM_VOICE_OPENAI_TTS_VOICE": "marin",
            "STORMHELM_VOICE_OPENAI_TTS_FORMAT": "wav",
            "STORMHELM_VOICE_OPENAI_TTS_SPEED": "0.95",
            "STORMHELM_VOICE_OPENAI_MAX_TTS_CHARS": "321",
            "STORMHELM_VOICE_OPENAI_OUTPUT_AUDIO_DIR": "var/voice/tts",
            "STORMHELM_VOICE_OPENAI_PERSIST_TTS_OUTPUTS": "true",
            "STORMHELM_VOICE_OPENAI_REALTIME_MODEL": "gpt-realtime-1.5",
            "STORMHELM_VOICE_OPENAI_VAD_MODE": "semantic_vad",
        },
    )

    assert config.voice.enabled is True
    assert config.voice.provider == "openai"
    assert config.voice.mode == "manual"
    assert config.voice.wake_word_enabled is True
    assert config.voice.spoken_responses_enabled is True
    assert config.voice.manual_input_enabled is False
    assert config.voice.realtime_enabled is True
    assert config.voice.debug_mock_provider is False
    assert config.voice.playback.enabled is True
    assert config.voice.playback.provider == "mock"
    assert config.voice.playback.device == "test-device"
    assert config.voice.playback.volume == 0.42
    assert config.voice.playback.allow_dev_playback is True
    assert config.voice.playback.max_audio_bytes == 456789
    assert config.voice.playback.max_duration_ms == 6543
    assert config.voice.playback.delete_transient_after_playback is False
    assert config.voice.openai.stt_model == "gpt-4o-transcribe"
    assert config.voice.openai.transcription_language == "en"
    assert config.voice.openai.transcription_prompt == "Stormhelm command terms"
    assert config.voice.openai.timeout_seconds == 12
    assert config.voice.openai.max_audio_seconds == 9
    assert config.voice.openai.max_audio_bytes == 123456
    assert config.voice.openai.tts_model == "gpt-4o-audio-preview"
    assert config.voice.openai.tts_voice == "marin"
    assert config.voice.openai.tts_format == "wav"
    assert config.voice.openai.tts_speed == 0.95
    assert config.voice.openai.max_tts_chars == 321
    assert config.voice.openai.output_audio_dir == "var/voice/tts"
    assert config.voice.openai.persist_tts_outputs is True
    assert config.voice.openai.realtime_model == "gpt-realtime-1.5"
    assert config.voice.openai.vad_mode == "semantic_vad"
