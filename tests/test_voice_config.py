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
    assert config.voice.playback.streaming_min_preroll_ms == 350
    assert config.voice.playback.streaming_min_preroll_chunks == 2
    assert config.voice.playback.streaming_min_preroll_bytes == 0
    assert config.voice.playback.streaming_max_preroll_wait_ms == 1200
    assert config.voice.playback.playback_stable_after_ms == 180
    assert config.voice.playback.max_audio_bytes == 10_000_000
    assert config.voice.playback.max_duration_ms == 120_000
    assert config.voice.playback.delete_transient_after_playback is True
    assert config.voice.visual_sync.enabled is True
    assert config.voice.visual_sync.envelope_visual_offset_ms == 0
    assert config.voice.visual_sync.estimated_output_latency_ms == 120
    assert config.voice.visual_sync.debug_show_sync is False
    assert config.voice.visual_meter.enabled is True
    assert config.voice.visual_meter.sample_rate_hz == 60
    assert config.voice.visual_meter.startup_preroll_ms == 350
    assert config.voice.visual_meter.attack_ms == 60
    assert config.voice.visual_meter.release_ms == 160
    assert config.voice.visual_meter.noise_floor == 0.015
    assert config.voice.visual_meter.gain == 2.0
    assert config.voice.visual_meter.max_startup_wait_ms == 800
    assert config.voice.visual_meter.visual_offset_ms == 0
    assert config.voice.capture.enabled is False
    assert config.voice.capture.provider == "local"
    assert config.voice.capture.mode == "push_to_talk"
    assert config.voice.capture.device == "default"
    assert config.voice.capture.sample_rate == 16000
    assert config.voice.capture.channels == 1
    assert config.voice.capture.format == "wav"
    assert config.voice.capture.max_duration_ms == 30_000
    assert config.voice.capture.max_audio_bytes == 10_000_000
    assert config.voice.capture.auto_stop_on_max_duration is True
    assert config.voice.capture.persist_captured_audio is False
    assert config.voice.capture.delete_transient_after_turn is True
    assert config.voice.capture.allow_dev_capture is False
    assert config.voice.openai.stt_model == "gpt-4o-mini-transcribe"
    assert config.voice.openai.transcription_language is None
    assert config.voice.openai.transcription_prompt is None
    assert config.voice.openai.timeout_seconds == 60
    assert config.voice.openai.max_audio_seconds == 30
    assert config.voice.openai.max_audio_bytes == 25 * 1024 * 1024
    assert config.voice.openai.tts_model == "gpt-4o-mini-tts"
    assert config.voice.openai.tts_voice == "onyx"
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
            "STORMHELM_VOICE_PLAYBACK_STREAMING_MIN_PREROLL_MS": "420",
            "STORMHELM_VOICE_PLAYBACK_STREAMING_MIN_PREROLL_CHUNKS": "3",
            "STORMHELM_VOICE_PLAYBACK_STREAMING_MIN_PREROLL_BYTES": "2048",
            "STORMHELM_VOICE_PLAYBACK_STREAMING_MAX_PREROLL_WAIT_MS": "900",
            "STORMHELM_VOICE_PLAYBACK_STABLE_AFTER_MS": "240",
            "STORMHELM_VOICE_PLAYBACK_MAX_AUDIO_BYTES": "456789",
            "STORMHELM_VOICE_PLAYBACK_MAX_DURATION_MS": "6543",
            "STORMHELM_VOICE_PLAYBACK_DELETE_TRANSIENT_AFTER_PLAYBACK": "false",
            "STORMHELM_VOICE_VISUAL_SYNC_ENABLED": "false",
            "STORMHELM_VOICE_VISUAL_OFFSET_MS": "-80",
            "STORMHELM_VOICE_VISUAL_ESTIMATED_OUTPUT_LATENCY_MS": "140",
            "STORMHELM_VOICE_VISUAL_SYNC_DEBUG": "true",
            "STORMHELM_VOICE_VISUAL_METER_ENABLED": "false",
            "STORMHELM_VOICE_VISUAL_METER_SAMPLE_RATE_HZ": "30",
            "STORMHELM_VOICE_VISUAL_METER_STARTUP_PREROLL_MS": "420",
            "STORMHELM_VOICE_VISUAL_METER_ATTACK_MS": "45",
            "STORMHELM_VOICE_VISUAL_METER_RELEASE_MS": "210",
            "STORMHELM_VOICE_VISUAL_METER_NOISE_FLOOR": "0.02",
            "STORMHELM_VOICE_VISUAL_METER_GAIN": "2.4",
            "STORMHELM_VOICE_VISUAL_METER_MAX_STARTUP_WAIT_MS": "700",
            "STORMHELM_VOICE_VISUAL_METER_OFFSET_MS": "-120",
            "STORMHELM_VOICE_CAPTURE_ENABLED": "true",
            "STORMHELM_VOICE_CAPTURE_PROVIDER": "mock",
            "STORMHELM_VOICE_CAPTURE_MODE": "push_to_talk",
            "STORMHELM_VOICE_CAPTURE_DEVICE": "desk-mic",
            "STORMHELM_VOICE_CAPTURE_SAMPLE_RATE": "24000",
            "STORMHELM_VOICE_CAPTURE_CHANNELS": "2",
            "STORMHELM_VOICE_CAPTURE_FORMAT": "webm",
            "STORMHELM_VOICE_CAPTURE_MAX_DURATION_MS": "12345",
            "STORMHELM_VOICE_CAPTURE_MAX_AUDIO_BYTES": "987654",
            "STORMHELM_VOICE_CAPTURE_AUTO_STOP_ON_MAX_DURATION": "false",
            "STORMHELM_VOICE_CAPTURE_PERSIST_CAPTURED_AUDIO": "true",
            "STORMHELM_VOICE_CAPTURE_DELETE_TRANSIENT_AFTER_TURN": "false",
            "STORMHELM_VOICE_CAPTURE_ALLOW_DEV_CAPTURE": "true",
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
    assert config.voice.playback.streaming_min_preroll_ms == 420
    assert config.voice.playback.streaming_min_preroll_chunks == 3
    assert config.voice.playback.streaming_min_preroll_bytes == 2048
    assert config.voice.playback.streaming_max_preroll_wait_ms == 900
    assert config.voice.playback.playback_stable_after_ms == 240
    assert config.voice.playback.max_audio_bytes == 456789
    assert config.voice.playback.max_duration_ms == 6543
    assert config.voice.playback.delete_transient_after_playback is False
    assert config.voice.visual_sync.enabled is False
    assert config.voice.visual_sync.envelope_visual_offset_ms == -80
    assert config.voice.visual_sync.estimated_output_latency_ms == 140
    assert config.voice.visual_sync.debug_show_sync is True
    assert config.voice.visual_meter.enabled is False
    assert config.voice.visual_meter.sample_rate_hz == 30
    assert config.voice.visual_meter.startup_preroll_ms == 420
    assert config.voice.visual_meter.attack_ms == 45
    assert config.voice.visual_meter.release_ms == 210
    assert config.voice.visual_meter.noise_floor == 0.02
    assert config.voice.visual_meter.gain == 2.4
    assert config.voice.visual_meter.max_startup_wait_ms == 700
    assert config.voice.visual_meter.visual_offset_ms == -120
    assert config.voice.capture.enabled is True
    assert config.voice.capture.provider == "mock"
    assert config.voice.capture.mode == "push_to_talk"
    assert config.voice.capture.device == "desk-mic"
    assert config.voice.capture.sample_rate == 24000
    assert config.voice.capture.channels == 2
    assert config.voice.capture.format == "webm"
    assert config.voice.capture.max_duration_ms == 12345
    assert config.voice.capture.max_audio_bytes == 987654
    assert config.voice.capture.auto_stop_on_max_duration is False
    assert config.voice.capture.persist_captured_audio is True
    assert config.voice.capture.delete_transient_after_turn is False
    assert config.voice.capture.allow_dev_capture is True
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


def test_load_config_clamps_voice_visual_sync_values(temp_project_root) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_VOICE_VISUAL_OFFSET_MS": "-900",
            "STORMHELM_VOICE_VISUAL_ESTIMATED_OUTPUT_LATENCY_MS": "900",
        },
    )

    assert config.voice.visual_sync.envelope_visual_offset_ms == -500
    assert config.voice.visual_sync.estimated_output_latency_ms == 500


def test_load_config_clamps_voice_visual_meter_offset(temp_project_root) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_VOICE_VISUAL_METER_OFFSET_MS": "900"},
    )

    assert config.voice.visual_meter.visual_offset_ms == 300


def test_load_config_reads_local_env_voice_runtime_gates_without_leaking_key(
    temp_project_root,
) -> None:
    secret = "present-test-value"
    (temp_project_root / ".env").write_text(
        "\n".join(
            [
                f"OPENAI_API_KEY={secret}",
                "STORMHELM_OPENAI_ENABLED=1",
                "STORMHELM_VOICE_ENABLED=1",
                "STORMHELM_VOICE_MODE=output_only",
                "STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED=1",
                "STORMHELM_VOICE_DEBUG_MOCK_PROVIDER=false",
                "STORMHELM_VOICE_OPENAI_STREAM_TTS_OUTPUTS=true",
                "STORMHELM_VOICE_OPENAI_TTS_LIVE_FORMAT=pcm",
                "STORMHELM_VOICE_PLAYBACK_ENABLED=true",
                "STORMHELM_VOICE_PLAYBACK_PROVIDER=local",
                "STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK=true",
                "STORMHELM_VOICE_PLAYBACK_STREAMING_ENABLED=true",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(project_root=temp_project_root, env={})
    serialized = str(config.to_dict())

    assert config.openai.api_key == secret
    assert config.openai.enabled is True
    assert config.voice.enabled is True
    assert config.voice.mode == "output_only"
    assert config.voice.spoken_responses_enabled is True
    assert config.voice.debug_mock_provider is False
    assert config.voice.openai.stream_tts_outputs is True
    assert config.voice.openai.tts_live_format == "pcm"
    assert config.voice.playback.enabled is True
    assert config.voice.playback.provider == "local"
    assert config.voice.playback.allow_dev_playback is True
    assert config.voice.playback.streaming_enabled is True
    assert secret not in serialized


def test_l6_voice_input_aliases_match_windows_manual_conversation_env(
    temp_project_root,
) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_VOICE_ENABLED": "1",
            "STORMHELM_VOICE_INPUT_ENABLED": "1",
            "STORMHELM_VOICE_MICROPHONE_ENABLED": "1",
            "STORMHELM_VOICE_PUSH_TO_TALK_ENABLED": "1",
            "STORMHELM_VOICE_INPUT_PROVIDER": "openai",
            "STORMHELM_VOICE_STT_PROVIDER": "openai",
            "STORMHELM_VOICE_STT_MODEL": "gpt-4o-mini-transcribe",
            "STORMHELM_VOICE_INPUT_LANGUAGE": "en",
            "STORMHELM_VOICE_ENDPOINT_SILENCE_MS": "700",
            "STORMHELM_VOICE_MAX_UTTERANCE_SECONDS": "20",
        },
    )

    assert config.voice.enabled is True
    assert config.voice.capture.enabled is True
    assert config.voice.manual_input_enabled is True
    assert config.voice.provider == "openai"
    assert config.voice.openai.stt_model == "gpt-4o-mini-transcribe"
    assert config.voice.openai.transcription_language == "en"
    assert config.voice.vad.silence_ms == 700
    assert config.voice.capture.max_duration_ms == 20000
    assert config.voice.vad.max_utterance_ms == 20000
