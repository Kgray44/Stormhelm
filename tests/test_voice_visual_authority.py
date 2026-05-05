from __future__ import annotations

import json

from stormhelm.ui.voice_visual_authority import VoiceVisualPlaybackAuthority


def test_hot_path_active_cannot_be_cleared_by_broad_snapshot_without_playback_id() -> None:
    authority = VoiceVisualPlaybackAuthority()

    active = authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.62,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "playing",
            "voice_visual_sequence": 10,
        },
        now_ms=1_000,
    )
    stale = authority.apply_snapshot_update(
        {
            "voice_visual_active": False,
            "voice_visual_energy": 0.0,
            "voice_visual_source": "pcm_stream_meter",
            "active_playback_status": "playing",
            "voice_visual_sequence": 9,
        },
        now_ms=1_030,
    )

    assert active["authoritativeVoiceVisualActive"] is True
    assert stale["authoritativeVoiceVisualActive"] is True
    assert stale["voice_visual_active"] is True
    assert stale["voice_visual_energy"] == 0.62
    assert stale["activePlaybackId"] == "playback-a"
    assert stale["staleBroadSnapshotIgnored"] is True
    assert stale["staleBroadSnapshotIgnoredCount"] == 1
    assert stale["lastIgnoredUpdateSource"] == "broad_snapshot"


def test_broad_snapshot_with_old_sequence_is_ignored_for_active_playback() -> None:
    authority = VoiceVisualPlaybackAuthority()
    authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.48,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "playing",
            "voice_visual_sequence": 20,
        },
        now_ms=1_000,
    )

    state = authority.apply_snapshot_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.02,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "playing",
            "voice_visual_sequence": 19,
        },
        now_ms=1_050,
    )

    assert state["authoritativeVoiceVisualEnergy"] == 0.48
    assert state["voice_visual_energy"] == 0.48
    assert state["staleBroadSnapshotIgnored"] is True
    assert state["staleBroadSnapshotIgnoredCount"] == 1


def test_terminal_event_for_matching_playback_releases_speaking() -> None:
    authority = VoiceVisualPlaybackAuthority(release_tail_ms=700)
    authority.apply_playback_event(
        "voice.playback_started",
        {"playback_id": "playback-a"},
        now_ms=1_000,
    )
    authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.7,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
        },
        now_ms=1_020,
    )

    state = authority.apply_playback_event(
        "voice.playback_completed",
        {"playback_id": "playback-a"},
        now_ms=1_600,
    )

    assert state["authoritativeVoiceVisualActive"] is False
    assert state["speaking_visual_active"] is False
    assert state["activePlaybackId"] is None
    assert state["authoritativePlaybackId"] == "playback-a"
    assert state["activePlaybackStatus"] == "completed"
    assert state["releaseTailMs"] == 700
    assert state["releaseDeadlineMs"] == 2_300
    assert state["terminalEventAcceptedCount"] == 1
    assert state["speakingExitedReason"] == "terminal_completed"


def test_terminal_event_for_wrong_playback_id_is_ignored() -> None:
    authority = VoiceVisualPlaybackAuthority()
    authority.apply_playback_event(
        "voice.playback_started",
        {"playback_id": "playback-a"},
        now_ms=1_000,
    )

    state = authority.apply_playback_event(
        "voice.playback_completed",
        {"playback_id": "old-playback"},
        now_ms=1_200,
    )

    assert state["authoritativeVoiceVisualActive"] is True
    assert state["speaking_visual_active"] is True
    assert state["activePlaybackId"] == "playback-a"
    assert state["playbackIdMismatchIgnoredCount"] == 1
    assert state["lastIgnoredUpdateSource"] == "terminal_event"


def test_repeated_speech_switches_playback_id_cleanly() -> None:
    authority = VoiceVisualPlaybackAuthority()
    first = authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.4,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "playing",
        },
        now_ms=1_000,
    )
    second = authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.55,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-b",
            "active_playback_status": "playing",
        },
        now_ms=2_000,
    )

    assert first["activePlaybackId"] == "playback-a"
    assert second["activePlaybackId"] == "playback-b"
    assert second["authoritativePlaybackId"] == "playback-b"
    assert second["voice_visual_playback_id"] == "playback-b"
    assert second["playbackIdSwitchCount"] == 1
    assert second["authoritativeVoiceVisualEnergy"] == 0.55


def test_old_terminal_event_after_playback_switch_does_not_suppress_new_playback() -> None:
    authority = VoiceVisualPlaybackAuthority()
    authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.4,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "playing",
        },
        now_ms=1_000,
    )
    authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.55,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-b",
            "active_playback_status": "playing",
        },
        now_ms=1_500,
    )

    state = authority.apply_playback_event(
        "voice.playback_completed",
        {"playback_id": "playback-a"},
        now_ms=1_560,
    )

    assert state["activePlaybackId"] == "playback-b"
    assert state["authoritativePlaybackId"] == "playback-b"
    assert state["authoritativeVoiceVisualActive"] is True
    assert state["authoritativeVoiceVisualEnergy"] == 0.55
    assert state["playbackIdMismatchIgnoredCount"] == 1
    assert state["lastIgnoredUpdateSource"] == "terminal_event"


def test_authority_snapshot_contains_ar9_playback_boundary_diagnostics() -> None:
    authority = VoiceVisualPlaybackAuthority()
    state = authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.52,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "playing",
        },
        now_ms=1_000,
    )

    assert state["currentAnchorPlaybackId"] == "playback-a"
    assert state["anchorAcceptedPlaybackId"] == "playback-a"
    assert state["anchorSpeakingEntryPlaybackId"] == "playback-a"
    assert state["anchorSpeakingEntryReason"] == "playback_active_hot_path"
    assert state["finalSpeakingEnergyPlaybackId"] == "playback-a"
    assert state["blobDrivePlaybackId"] == "playback-a"


def test_false_speaking_is_not_created_without_active_playback() -> None:
    authority = VoiceVisualPlaybackAuthority()

    state = authority.apply_snapshot_update(
        {
            "speaking_visual_active": True,
            "voice_visual_active": False,
            "voice_visual_energy": 0.0,
            "active_playback_status": "idle",
        },
        now_ms=1_000,
    )

    assert state["authoritativeVoiceVisualActive"] is False
    assert state["speaking_visual_active"] is False
    assert state["falseSpeakingWithoutAudioDetected"] is False


def test_hot_false_during_active_playback_decays_energy_without_forcing_idle() -> None:
    authority = VoiceVisualPlaybackAuthority()
    authority.apply_playback_event(
        "voice.playback_started",
        {"playback_id": "playback-a"},
        now_ms=1_000,
    )

    state = authority.apply_hot_path_update(
        {
            "voice_visual_active": False,
            "voice_visual_energy": 0.0,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "playing",
        },
        now_ms=1_040,
    )

    assert state["authoritativeVoiceVisualActive"] is True
    assert state["speaking_visual_active"] is True
    assert state["authoritativeVoiceVisualEnergy"] == 0.0
    assert state["speakingEnteredReason"] in {
        "playback_started",
        "playback_active_hot_path",
    }
    assert state["voiceVisualActiveFlapCount"] == 0


def test_hot_path_terminal_status_releases_instead_of_reentering_from_prior_playing() -> None:
    authority = VoiceVisualPlaybackAuthority()
    authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.68,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "playing",
            "voice_visual_sequence": 30,
        },
        now_ms=1_000,
    )

    state = authority.apply_hot_path_update(
        {
            "voice_visual_active": False,
            "voice_visual_energy": 0.0,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "completed",
            "voice_visual_sequence": 31,
        },
        now_ms=1_500,
    )

    assert state["authoritativePlaybackStatus"] == "completed"
    assert state["authoritativeVoiceVisualActive"] is False
    assert state["speaking_visual_active"] is False
    assert state["activePlaybackId"] is None
    assert state["terminalEventAcceptedCount"] == 1
    assert state["speakingExitedReason"] == "hot_path_terminal_completed"


def test_authoritative_payload_is_scalar_only() -> None:
    authority = VoiceVisualPlaybackAuthority()

    state = authority.apply_hot_path_update(
        {
            "voice_visual_active": True,
            "voice_visual_energy": 0.3,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "playback-a",
            "active_playback_status": "playing",
            "pcm_bytes": b"forbidden",
            "raw_samples": [1, 2, 3],
            "raw_audio_present": True,
        },
        now_ms=1_000,
    )

    serialized = json.dumps(state, sort_keys=True)
    assert state["raw_audio_present"] is False
    assert "pcm_bytes" not in serialized
    assert "raw_samples" not in serialized
    assert "forbidden" not in serialized
