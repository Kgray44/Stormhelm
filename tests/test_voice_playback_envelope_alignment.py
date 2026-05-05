from __future__ import annotations

from types import SimpleNamespace

from stormhelm.core.voice.service import VoiceService


def _service() -> VoiceService:
    service = object.__new__(VoiceService)
    service.config = SimpleNamespace(visual_sync=SimpleNamespace())
    service._voice_visualizer_source_locks = {}
    return service


def _samples(start_ms: int = 0, count: int = 8, energy: float = 0.16) -> list[dict]:
    return [
        {
            "sample_time_ms": start_ms + index * 16,
            "energy": energy,
            "smoothed_energy": energy,
            "source": "pcm_playback",
            "valid": True,
        }
        for index in range(count)
    ]


def test_playback_envelope_alignment_holds_fresh_tail_within_tolerance() -> None:
    service = _service()

    aligned, delta_ms, status, tolerance_ms = service._playback_envelope_timebase_alignment(
        _samples(start_ms=80, count=8),
        query_time_ms=250,
        window_mode="playback_time",
    )

    assert aligned is True
    assert delta_ms == 58
    assert status == "ahead_clamped"
    assert tolerance_ms == 260


def test_playback_envelope_alignment_rejects_far_ahead_query() -> None:
    service = _service()

    aligned, delta_ms, status, tolerance_ms = service._playback_envelope_timebase_alignment(
        _samples(start_ms=80, count=8),
        query_time_ms=900,
        window_mode="playback_time",
    )

    assert aligned is False
    assert delta_ms == 708
    assert status == "ahead"
    assert tolerance_ms == 260


def test_snapshot_uses_computed_alignment_over_stale_explicit_false() -> None:
    service = _service()
    payload = {
        "playback_id": "alignment-gate",
        "envelope_supported": True,
        "envelope_available": True,
        "envelope_source": "playback_pcm",
        "envelope_sample_rate_hz": 60,
        "latest_voice_energy": 0.16,
        "latest_voice_energy_time_ms": 192,
        "playback_envelope_window_mode": "playback_time",
        "playback_envelope_query_time_ms": 250,
        "playback_envelope_sample_age_ms": 0,
        "playback_envelope_timebase_aligned": False,
        "envelope_samples_recent": _samples(start_ms=80, count=8),
        "envelope_timeline_available": True,
        "raw_audio_present": False,
    }

    snapshot = service._playback_envelope_snapshot_fields(payload)

    assert snapshot["playback_envelope_timebase_aligned"] is True
    assert snapshot["playback_envelope_usable"] is True
    assert snapshot["playback_envelope_alignment_status"] == "ahead_clamped"
    assert snapshot["playback_envelope_alignment_delta_ms"] == 58
    assert snapshot["visualizerSourceStrategy"] == "playback_envelope_timeline"


def test_snapshot_treats_timeline_only_payload_with_query_as_playback_time() -> None:
    service = _service()
    timeline = [
        {"t_ms": 0, "energy": 0.12},
        {"t_ms": 16, "energy": 0.18},
        {"t_ms": 32, "energy": 0.26},
        {"t_ms": 48, "energy": 0.20},
        {"t_ms": 64, "energy": 0.31},
    ]
    payload = {
        "playback_id": "timeline-only-query",
        "envelope_supported": True,
        "envelope_available": True,
        "envelope_source": "playback_pcm",
        "envelope_sample_rate_hz": 60,
        "latest_voice_energy": 0.0,
        "latest_voice_energy_time_ms": 64,
        "playback_envelope_window_mode": "latest",
        "playback_envelope_query_time_ms": 64,
        "playback_envelope_sample_age_ms": 0,
        "envelope_samples_recent": [],
        "envelope_timeline_samples": timeline,
        "envelope_timeline_available": True,
        "raw_audio_present": False,
    }

    snapshot = service._playback_envelope_snapshot_fields(payload)

    assert snapshot["playback_envelope_window_mode"] == "playback_time"
    assert snapshot["playback_envelope_alignment_status"] == "aligned"
    assert snapshot["playback_envelope_usable"] is True
    assert snapshot["playback_envelope_sample_count"] == len(timeline)
    assert snapshot["playback_envelope_energy"] > 0.0
    assert snapshot["visualizerSourceStrategy"] == "playback_envelope_timeline"


def test_forced_anchor_visualizer_mode_overrides_auto_source_lock(monkeypatch) -> None:
    service = _service()
    monkeypatch.setenv("STORMHELM_ANCHOR_VISUALIZER_MODE", "constant_test_wave")

    fields = service._visualizer_source_strategy_fields(
        playback_id="forced-mode",
        envelope_ready=False,
    )

    assert fields["requested_anchor_visualizer_mode"] == "constant_test_wave"
    assert fields["visualizerSourceStrategy"] == "constant_test_wave"
    assert fields["forced_visualizer_mode_honored"] is True
    assert fields["visualizer_strategy_selected_by"] == "config"


def test_forced_envelope_timeline_reports_unavailable_instead_of_procedural(
    monkeypatch,
) -> None:
    service = _service()
    monkeypatch.setenv("STORMHELM_ANCHOR_VISUALIZER_MODE", "envelope_timeline")

    fields = service._visualizer_source_strategy_fields(
        playback_id="forced-envelope",
        envelope_ready=False,
        envelope_unavailable_reason="playback_envelope_unaligned",
    )

    assert fields["visualizerSourceStrategy"] == "playback_envelope_timeline"
    assert fields["forced_visualizer_mode_honored"] is True
    assert fields["forced_visualizer_mode_unavailable_reason"] == (
        "playback_envelope_unaligned"
    )
    assert fields["visualizer_strategy_selected_by"] == "config"
