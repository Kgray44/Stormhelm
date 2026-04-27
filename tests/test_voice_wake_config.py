from __future__ import annotations

from stormhelm.config.loader import load_config


def test_wake_config_defaults_to_disabled_foundation(temp_project_root) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.voice.wake.enabled is False
    assert config.voice.wake.provider == "mock"
    assert config.voice.wake.wake_phrase == "Stormhelm"
    assert config.voice.wake.device == "default"
    assert config.voice.wake.sample_rate == 16000
    assert config.voice.wake.backend == "unavailable"
    assert config.voice.wake.model_path is None
    assert config.voice.wake.sensitivity == 0.5
    assert config.voice.wake.confidence_threshold == 0.75
    assert config.voice.wake.cooldown_ms == 2500
    assert config.voice.wake.max_wake_session_ms == 15000
    assert config.voice.wake.false_positive_window_ms == 3000
    assert config.voice.wake.allow_dev_wake is False
    assert config.voice.capture.enabled is False
    assert config.voice.spoken_responses_enabled is False
    assert config.voice.playback.enabled is False
    assert config.voice.realtime_enabled is False


def test_wake_config_loads_environment_overrides_separately(temp_project_root) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_VOICE_WAKE_ENABLED": "true",
            "STORMHELM_VOICE_WAKE_PROVIDER": "mock",
            "STORMHELM_VOICE_WAKE_PHRASE": "Helm",
            "STORMHELM_VOICE_WAKE_DEVICE": "test-mic",
            "STORMHELM_VOICE_WAKE_SAMPLE_RATE": "22050",
            "STORMHELM_VOICE_WAKE_BACKEND": "fake-local",
            "STORMHELM_VOICE_WAKE_MODEL_PATH": "models/wake.bin",
            "STORMHELM_VOICE_WAKE_SENSITIVITY": "0.61",
            "STORMHELM_VOICE_WAKE_CONFIDENCE_THRESHOLD": "0.88",
            "STORMHELM_VOICE_WAKE_COOLDOWN_MS": "4321",
            "STORMHELM_VOICE_WAKE_MAX_WAKE_SESSION_MS": "22222",
            "STORMHELM_VOICE_WAKE_FALSE_POSITIVE_WINDOW_MS": "1111",
            "STORMHELM_VOICE_WAKE_ALLOW_DEV_WAKE": "true",
            "STORMHELM_VOICE_CAPTURE_ENABLED": "false",
            "STORMHELM_VOICE_REALTIME_ENABLED": "false",
        },
    )

    assert config.voice.wake.enabled is True
    assert config.voice.wake.provider == "mock"
    assert config.voice.wake.wake_phrase == "Helm"
    assert config.voice.wake.device == "test-mic"
    assert config.voice.wake.sample_rate == 22050
    assert config.voice.wake.backend == "fake-local"
    assert config.voice.wake.model_path == "models/wake.bin"
    assert config.voice.wake.sensitivity == 0.61
    assert config.voice.wake.confidence_threshold == 0.88
    assert config.voice.wake.cooldown_ms == 4321
    assert config.voice.wake.max_wake_session_ms == 22222
    assert config.voice.wake.false_positive_window_ms == 1111
    assert config.voice.wake.allow_dev_wake is True
    assert config.voice.capture.enabled is False
    assert config.voice.realtime_enabled is False


def test_wake_config_sanitizes_invalid_numeric_values(temp_project_root) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_VOICE_WAKE_CONFIDENCE_THRESHOLD": "2.5",
            "STORMHELM_VOICE_WAKE_SAMPLE_RATE": "-1",
            "STORMHELM_VOICE_WAKE_SENSITIVITY": "9",
            "STORMHELM_VOICE_WAKE_COOLDOWN_MS": "-25",
            "STORMHELM_VOICE_WAKE_MAX_WAKE_SESSION_MS": "-1",
            "STORMHELM_VOICE_WAKE_FALSE_POSITIVE_WINDOW_MS": "-5",
        },
    )

    assert config.voice.wake.confidence_threshold == 1.0
    assert config.voice.wake.sample_rate == 1
    assert config.voice.wake.sensitivity == 1.0
    assert config.voice.wake.cooldown_ms == 0
    assert config.voice.wake.max_wake_session_ms == 1
    assert config.voice.wake.false_positive_window_ms == 0
