from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANCHOR_CORE = PROJECT_ROOT / "assets" / "qml" / "variants" / "stormforge" / "StormforgeAnchorCore.qml"
ANCHOR_HOST = PROJECT_ROOT / "assets" / "qml" / "variants" / "stormforge" / "StormforgeAnchorHost.qml"
GHOST_SHELL = PROJECT_ROOT / "assets" / "qml" / "variants" / "stormforge" / "StormforgeGhostShell.qml"


def test_anchor_core_exposes_ar14_speaking_dynamics_diagnostics() -> None:
    source = ANCHOR_CORE.read_text(encoding="utf-8")

    assert 'speakingEnergyAttackVersion: "AR14"' in source
    assert "startupLimiterActive" in source
    assert "earlySpeechOvershootDetected" in source
    assert "lateSpeechCompressionDetected" in source
    assert "speakingDynamicsPhase" in source
    assert "speakingDynamicsConfidence" in source


def test_anchor_core_limits_startup_without_delaying_speaking_entry() -> None:
    source = ANCHOR_CORE.read_text(encoding="utf-8")

    assert "speakingDynamicsStartupRampMs" in source
    assert "speakingDynamicsStartupCap" in source
    assert "meterEnergyTarget * root.speakingDynamicsStartupRamp" in source
    assert "root.voiceVisualFirstTrueAtMs" in source
    assert "anchorSpeakingStartDelayMs" in source


def test_anchor_core_keeps_late_speech_expressive_without_faking_silence() -> None:
    source = ANCHOR_CORE.read_text(encoding="utf-8")

    assert "speakingDynamicsExpressiveFloor" in source
    assert "backendSpeakingNow && root.voiceVisualTargetFresh" in source
    assert "Math.max(gainedEnergy, root.speakingDynamicsExpressiveFloor)" in source
    assert "!backendSpeakingNow && root.finalSpeakingEnergy < 0.003" in source


def test_anchor_host_and_ghost_shell_forward_ar14_dynamics_diagnostics() -> None:
    host = ANCHOR_HOST.read_text(encoding="utf-8")
    ghost = GHOST_SHELL.read_text(encoding="utf-8")

    for key in (
        "speakingEnergyAttackVersion",
        "startupLimiterActive",
        "lateSpeechCompressionDetected",
        "speakingDynamicsPhase",
    ):
        assert key in host
        assert key in ghost
