from __future__ import annotations

from stormhelm.config.loader import load_config


def test_vad_config_defaults_to_disabled_foundation(temp_project_root) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.voice.vad.enabled is False
    assert config.voice.vad.provider == "mock"
    assert config.voice.vad.silence_ms == 900
    assert config.voice.vad.speech_start_threshold == 0.5
    assert config.voice.vad.speech_stop_threshold == 0.35
    assert config.voice.vad.min_speech_ms == 250
    assert config.voice.vad.max_utterance_ms == 30000
    assert config.voice.vad.pre_roll_ms == 250
    assert config.voice.vad.post_roll_ms == 250
    assert config.voice.vad.allow_dev_vad is False
    assert config.voice.vad.auto_finalize_capture is True
    assert config.voice.capture.enabled is False
    assert config.voice.wake.enabled is False
    assert config.voice.realtime_enabled is False


def test_vad_config_loads_environment_overrides_separately(temp_project_root) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_VOICE_VAD_ENABLED": "true",
            "STORMHELM_VOICE_VAD_PROVIDER": "mock",
            "STORMHELM_VOICE_VAD_SILENCE_MS": "1100",
            "STORMHELM_VOICE_VAD_SPEECH_START_THRESHOLD": "0.62",
            "STORMHELM_VOICE_VAD_SPEECH_STOP_THRESHOLD": "0.24",
            "STORMHELM_VOICE_VAD_MIN_SPEECH_MS": "300",
            "STORMHELM_VOICE_VAD_MAX_UTTERANCE_MS": "12000",
            "STORMHELM_VOICE_VAD_PRE_ROLL_MS": "180",
            "STORMHELM_VOICE_VAD_POST_ROLL_MS": "420",
            "STORMHELM_VOICE_VAD_ALLOW_DEV_VAD": "true",
            "STORMHELM_VOICE_VAD_AUTO_FINALIZE_CAPTURE": "false",
            "STORMHELM_VOICE_WAKE_ENABLED": "false",
            "STORMHELM_VOICE_REALTIME_ENABLED": "false",
        },
    )

    assert config.voice.vad.enabled is True
    assert config.voice.vad.provider == "mock"
    assert config.voice.vad.silence_ms == 1100
    assert config.voice.vad.speech_start_threshold == 0.62
    assert config.voice.vad.speech_stop_threshold == 0.24
    assert config.voice.vad.min_speech_ms == 300
    assert config.voice.vad.max_utterance_ms == 12000
    assert config.voice.vad.pre_roll_ms == 180
    assert config.voice.vad.post_roll_ms == 420
    assert config.voice.vad.allow_dev_vad is True
    assert config.voice.vad.auto_finalize_capture is False
    assert config.voice.wake.enabled is False
    assert config.voice.realtime_enabled is False


def test_vad_config_sanitizes_invalid_numeric_values(temp_project_root) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_VOICE_VAD_SILENCE_MS": "-1",
            "STORMHELM_VOICE_VAD_SPEECH_START_THRESHOLD": "2.4",
            "STORMHELM_VOICE_VAD_SPEECH_STOP_THRESHOLD": "-9",
            "STORMHELM_VOICE_VAD_MIN_SPEECH_MS": "-50",
            "STORMHELM_VOICE_VAD_MAX_UTTERANCE_MS": "-10",
            "STORMHELM_VOICE_VAD_PRE_ROLL_MS": "-1",
            "STORMHELM_VOICE_VAD_POST_ROLL_MS": "-2",
        },
    )

    assert config.voice.vad.silence_ms == 0
    assert config.voice.vad.speech_start_threshold == 1.0
    assert config.voice.vad.speech_stop_threshold == 0.0
    assert config.voice.vad.min_speech_ms == 0
    assert config.voice.vad.max_utterance_ms == 1
    assert config.voice.vad.pre_roll_ms == 0
    assert config.voice.vad.post_roll_ms == 0
