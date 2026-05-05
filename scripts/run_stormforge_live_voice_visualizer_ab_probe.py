from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / ".artifacts" / "ui_voice_live_iso_2"
REPORT_JSON = ARTIFACT_DIR / "live_voice_visualizer_ab_report.json"
REPORT_MD = ARTIFACT_DIR / "live_voice_visualizer_ab_report.md"
OBSERVATIONS_CSV = ARTIFACT_DIR / "live_voice_visualizer_ab_observations.csv"
DEFAULT_SPOKEN_PROMPT = "Testing one, two, three. Anchor sync check."
NOT_AVAILABLE = "not_available"
OPENAI_NOT_CONFIGURED_TEXT = "openai integration is not configured"
QUIET_LOGGERS = (
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "httpx",
    "urllib3",
    "requests",
)


CASES: list[dict[str, Any]] = [
    {
        "case": "A",
        "name": "fog_off_visualizer_off",
        "fog_enabled": False,
        "visualizer_mode": "off",
        "expected": "If this stutters, the problem is not anchor reactive animation or fog.",
    },
    {
        "case": "B",
        "name": "fog_off_constant_test_wave",
        "fog_enabled": False,
        "visualizer_mode": "constant_test_wave",
        "expected": "If this is smooth, Anchor local animation can be smooth during real voice playback.",
    },
    {
        "case": "C",
        "name": "fog_off_procedural",
        "fog_enabled": False,
        "visualizer_mode": "procedural",
        "expected": "If constant wave is smooth but this stutters, suspect procedural speaking path or speaking-state churn.",
    },
    {
        "case": "D",
        "name": "fog_off_envelope_timeline",
        "fog_enabled": False,
        "visualizer_mode": "envelope_timeline",
        "expected": "If procedural is smooth but this stutters, suspect envelope timeline sampling or payload churn.",
    },
    {
        "case": "E",
        "name": "fog_on_procedural",
        "fog_enabled": True,
        "visualizer_mode": "procedural",
        "expected": "Compares fog plus real voice load against procedural speaking.",
    },
    {
        "case": "F",
        "name": "fog_on_envelope_timeline",
        "fog_enabled": True,
        "visualizer_mode": "envelope_timeline",
        "expected": "Full intended Stormforge speaking path.",
    },
    {
        "case": "G",
        "name": "fog_on_default_mode",
        "fog_enabled": True,
        "visualizer_mode": "",
        "expected": "If forced modes are smooth but default stutters, suspect source selection or config mismatch.",
        "optional": True,
    },
]


STATUS_FIELDS: tuple[str, ...] = (
    "playback_backend",
    "playback_mode",
    "tts_live_format",
    "tts_artifact_format",
    "stream_tts_outputs",
    "last_spoken_text_preview",
    "last_speech_request_id",
    "last_synthesis_state",
    "last_synthesis_error",
    "last_openai_tts_call_attempted",
    "last_openai_tts_call_blocked_reason",
    "audio_generated",
    "last_voice_speak_decision",
    "voice_output",
    "last_spoken_result",
    "active_playback_status",
    "last_playback_status",
    "playback_stable",
    "playback_id",
    "active_playback_id",
    "active_playback_stream_id",
    "voice_anchor_state",
    "voice_current_phase",
    "speaking_visual_active",
    "user_heard_claimed",
    "playback_envelope_supported",
    "playback_envelope_available",
    "playback_envelope_usable",
    "playback_envelope_source",
    "playback_envelope_usable_reason",
    "playback_envelope_sample_rate_hz",
    "playback_envelope_sample_count",
    "playback_envelope_sample_age_ms",
    "playback_envelope_window_mode",
    "playback_envelope_query_time_ms",
    "playback_envelope_latest_time_ms",
    "playback_envelope_alignment_delta_ms",
    "playback_envelope_alignment_tolerance_ms",
    "playback_envelope_alignment_status",
    "playback_envelope_energy",
    "latest_voice_energy",
    "latest_voice_energy_time_ms",
    "anchor_uses_playback_envelope",
    "procedural_fallback_active",
    "speaking_visual_sync_mode",
    "envelope_interpolation_active",
    "envelope_timeline_available",
    "envelopeTimelineAvailable",
    "envelope_timeline_sample_count",
    "envelopeTimelineReadyAtPlaybackStart",
    "envelope_timeline_ready_at_playback_start",
    "visualizerSourceStrategy",
    "visualizer_source_strategy",
    "visualizerSourceLocked",
    "visualizer_source_locked",
    "visualizerSourceSwitchCount",
    "visualizer_source_switch_count",
    "visualizerSourcePlaybackId",
    "visualizer_source_playback_id",
    "requested_anchor_visualizer_mode",
    "requestedAnchorVisualizerMode",
    "effective_anchor_visualizer_mode",
    "effectiveAnchorVisualizerMode",
    "forced_visualizer_mode_honored",
    "forcedVisualizerModeHonored",
    "forced_visualizer_mode_unavailable_reason",
    "forcedVisualizerModeUnavailableReason",
    "visualizer_strategy_selected_by",
    "visualizerStrategySelectedBy",
    "qmlSpeakingEnergySource",
    "speakingEnergySourceLatched",
    "qmlFinalSpeakingEnergy",
    "finalSpeakingEnergy",
    "visualizer_updates_received",
    "visualizer_updates_coalesced",
    "visualizer_updates_dropped",
    "bridge_receive_rate_hz",
    "max_bridge_frame_gap_ms",
    "last_bridge_frame_gap_ms",
    "bridge_collection_rebuilds_during_speech",
    "collection_rebuilds_during_visualizer_updates",
    "qml_anchor_updates_during_speech",
    "raw_audio_present",
    "raw_audio_logged",
)


SUBJECTIVE_CHOICES = {
    "smooth",
    "stutter",
    "freeze",
    "no_animation",
    "wrong_source",
    "not_tested",
}


def case_env(case: dict[str, Any]) -> dict[str, str]:
    env = {
        "STORMHELM_UI_VARIANT": "stormforge",
        "STORMHELM_STORMFORGE_FOG": "1" if bool(case["fog_enabled"]) else "0",
    }
    mode = str(case.get("visualizer_mode") or "").strip()
    if mode:
        env["STORMHELM_ANCHOR_VISUALIZER_MODE"] = mode
    return env


EXPECTED_STRATEGY_BY_MODE = {
    "off": "off",
    "constant_test_wave": "constant_test_wave",
    "procedural": "procedural_speaking",
    "envelope_timeline": "playback_envelope_timeline",
}


def expected_strategy_for_mode(mode: str | None) -> str:
    normalized = str(mode or "").strip().lower().replace("-", "_").replace(" ", "_")
    return EXPECTED_STRATEGY_BY_MODE.get(normalized, "")


def source_expectation_check(
    requested_env: dict[str, str],
    summary: dict[str, Any],
) -> dict[str, Any]:
    requested_mode = requested_env.get("STORMHELM_ANCHOR_VISUALIZER_MODE", "")
    expected_strategy = expected_strategy_for_mode(requested_mode)
    chosen_strategy = str(summary.get("chosen_visualizer_strategy") or "")
    unavailable_reason = str(
        summary.get("forced_visualizer_mode_unavailable_reason") or ""
    )
    mismatch = bool(
        expected_strategy
        and chosen_strategy not in {"", NOT_AVAILABLE}
        and chosen_strategy != expected_strategy
    )
    reason = ""
    if mismatch:
        reason = (
            f"requested {requested_mode} expected {expected_strategy} "
            f"but live status reported {chosen_strategy}"
        )
    elif expected_strategy and unavailable_reason:
        reason = unavailable_reason
    return {
        "expected_visualizer_strategy": expected_strategy or NOT_AVAILABLE,
        "source_mismatch_detected": mismatch,
        "source_mismatch_reason": reason,
    }


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _iter_key_values(payload: Any, key: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(payload, dict):
        for item_key, item_value in payload.items():
            if item_key == key:
                values.append(item_value)
            values.extend(_iter_key_values(item_value, key))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_iter_key_values(item, key))
    return values


def _first_value(payload: dict[str, Any], key: str) -> Any:
    for value in _iter_key_values(payload, key):
        if value is not None:
            return value
    return None


def _dig(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if number != number else number


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _json_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _sample_text(samples: list[dict[str, Any]], *keys: str) -> tuple[str, str]:
    for row in reversed(samples):
        for key in keys:
            value = row.get(key)
            if value in {None, ""}:
                continue
            parsed = _json_scalar(value)
            if isinstance(parsed, dict):
                for nested_key in (
                    "spoken_text",
                    "text",
                    "message",
                    "content",
                    "micro_response",
                    "spoken_response",
                ):
                    text = _compact_text(parsed.get(nested_key))
                    if text:
                        return text, key
                continue
            text = _compact_text(value)
            if text:
                return text, key
    return "", ""


def _trigger_assistant_text(trigger_response: dict[str, Any] | None) -> str:
    payload = trigger_response if isinstance(trigger_response, dict) else {}
    for key in ("spoken_response", "micro_response", "content", "message", "full_response"):
        text = _compact_text(_first_value(payload, key))
        if text:
            return text
    assistant = payload.get("assistant_message") if isinstance(payload, dict) else {}
    if isinstance(assistant, dict):
        text = _compact_text(assistant.get("content"))
        if text:
            return text
    return ""


def _sample_error_text(samples: list[dict[str, Any]]) -> str:
    for row in reversed(samples):
        for key in ("last_synthesis_error_message", "tts_error_message"):
            text = _compact_text(row.get(key))
            if text:
                return text
        parsed = _json_scalar(row.get("last_synthesis_error"))
        if isinstance(parsed, dict):
            text = _compact_text(parsed.get("message") or parsed.get("error"))
            if text:
                return text
    return ""


def _openai_configured(settings: dict[str, Any], samples: list[dict[str, Any]]) -> bool | str:
    openai_enabled = _dig(settings, "openai", "enabled")
    if openai_enabled is None:
        openai_enabled = _first_value(settings, "openai_enabled")
    blocked_reason = _sample_text(samples, "last_openai_tts_call_blocked_reason")[0]
    if blocked_reason in {"openai_key_missing", "openai_disabled"}:
        return False
    if openai_enabled is not None:
        return _as_bool(openai_enabled)
    return NOT_AVAILABLE


def spoken_stimulus_diagnostics(
    *,
    requested_prompt: str,
    trigger_response: dict[str, Any] | None,
    samples: list[dict[str, Any]],
    settings: dict[str, Any],
    use_local_voice_test_fixture: bool = False,
) -> dict[str, Any]:
    assistant_response_text = _trigger_assistant_text(trigger_response)
    status_spoken_text, status_source = _sample_text(
        samples,
        "last_spoken_text_preview",
        "spoken_text_actual",
        "assistant_response_text",
        "last_voice_speak_decision",
        "last_spoken_result",
    )
    spoken_actual = status_spoken_text or assistant_response_text
    lower_actual = spoken_actual.lower()
    requested = _compact_text(requested_prompt)
    openai_configured = _openai_configured(settings, samples)
    blocked_reason = _sample_text(samples, "last_openai_tts_call_blocked_reason")[0]
    tts_status = _sample_text(samples, "last_synthesis_state", "tts_generation_status")[0]
    tts_error = _sample_error_text(samples)
    tts_provider = _sample_text(samples, "tts_provider_name", "provider")[0]
    fallback_reason = ""
    voice_output_path = "normal_tts" if spoken_actual else "unavailable"
    valid = bool(spoken_actual)
    if use_local_voice_test_fixture:
        voice_output_path = "unavailable"
        valid = False
        fallback_reason = "local_voice_test_fixture_unavailable_no_safe_endpoint"
    elif OPENAI_NOT_CONFIGURED_TEXT in lower_actual:
        voice_output_path = "fallback_error"
        valid = False
        fallback_reason = "openai_integration_not_configured"
    elif requested and spoken_actual and requested.lower() not in lower_actual:
        valid = False
        fallback_reason = "spoken_text_did_not_match_requested_prompt"
    return {
        "requested_prompt_text": requested,
        "assistant_response_text": assistant_response_text or NOT_AVAILABLE,
        "spoken_text_requested": requested,
        "spoken_text_actual": spoken_actual or NOT_AVAILABLE,
        "spoken_text_source": status_source or ("assistant_response" if assistant_response_text else NOT_AVAILABLE),
        "valid_spoken_stimulus": bool(valid),
        "tts_request_created": any(
            row.get("last_speech_request_id") not in {None, ""}
            or row.get("last_synthesis_state") not in {None, ""}
            for row in samples
        ),
        "tts_provider_configured": False
        if openai_configured is False or blocked_reason in {"openai_key_missing", "openai_disabled"}
        else bool(openai_configured is True),
        "tts_provider_name": tts_provider or NOT_AVAILABLE,
        "tts_generation_status": tts_status or NOT_AVAILABLE,
        "tts_error_message": tts_error or NOT_AVAILABLE,
        "spoken_fallback_reason": fallback_reason or NOT_AVAILABLE,
        "openai_configured": openai_configured,
        "voice_output_path": voice_output_path,
        "local_voice_test_fixture_requested": bool(use_local_voice_test_fixture),
        "local_voice_test_fixture_available": False if use_local_voice_test_fixture else NOT_AVAILABLE,
        "local_voice_test_fixture_status": (
            "unavailable_no_safe_http_playback_fixture"
            if use_local_voice_test_fixture
            else NOT_AVAILABLE
        ),
    }


def configure_probe_logging(*, verbose_polling: bool) -> None:
    level = logging.INFO if verbose_polling else logging.WARNING
    for logger_name in QUIET_LOGGERS:
        logging.getLogger(logger_name).setLevel(level)


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in {None, ""}:
            return str(value)
    return ""


def _first_bool(row: dict[str, Any], *keys: str) -> bool:
    return any(_as_bool(row.get(key)) for key in keys)


def _first_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if row.get(key) is not None:
            return _as_float(row.get(key))
    return None


def _mode_is_bad(mode: str) -> bool:
    return str(mode or "").strip().lower() in {"stutter", "freeze"}


def _mode_is_smooth(mode: str) -> bool:
    return str(mode or "").strip().lower() == "smooth"


def classify_root_cause(case_results: list[dict[str, Any]]) -> str:
    result_by_case = {
        str(item.get("case") or "").upper(): str(item.get("subjective_result") or "").lower()
        for item in case_results
    }
    if not result_by_case:
        return "insufficient_live_audible_ab_results"
    if _mode_is_bad(result_by_case.get("A", "")):
        return "case_a_stutter_real_voice_bridge_or_ghost_runtime_pressure"
    if _mode_is_smooth(result_by_case.get("A", "")) and _mode_is_bad(result_by_case.get("B", "")):
        return "case_b_stutter_anchor_canvas_or_speaking_state_churn"
    if (
        _mode_is_smooth(result_by_case.get("B", ""))
        and _mode_is_bad(result_by_case.get("C", ""))
    ):
        return "case_c_stutter_procedural_speaking_path"
    if (
        _mode_is_smooth(result_by_case.get("C", ""))
        and _mode_is_bad(result_by_case.get("D", ""))
    ):
        return "case_d_stutter_envelope_timeline_sampling_or_payload_churn"
    if all(_mode_is_smooth(result_by_case.get(case_id, "")) for case_id in ("B", "C", "D")) and (
        _mode_is_bad(result_by_case.get("E", ""))
        or _mode_is_bad(result_by_case.get("F", ""))
    ):
        return "fog_render_load_combined_with_real_voice"
    if all(_mode_is_smooth(result_by_case.get(case_id, "")) for case_id in ("B", "C", "D", "E", "F")):
        if _mode_is_bad(result_by_case.get("G", "")):
            return "default_source_selection_or_env_config_mismatch"
        if "G" in result_by_case and _mode_is_smooth(result_by_case.get("G", "")):
            return "all_forced_and_default_live_cases_smooth_no_stutter_reproduced"
        return "forced_live_ab_cases_smooth_run_default_mode_next"
    if any(value == "not_tested" for value in result_by_case.values()):
        return "insufficient_live_audible_ab_results"
    return "live_ab_results_inconclusive_review_case_notes"


def _most_common_text(values: list[str]) -> str:
    clean = [value for value in values if value and value != NOT_AVAILABLE]
    if not clean:
        return NOT_AVAILABLE
    return Counter(clean).most_common(1)[0][0]


def _switch_count(values: list[str]) -> int:
    previous = ""
    switches = 0
    for value in values:
        if not value or value == NOT_AVAILABLE:
            continue
        if previous and value != previous:
            switches += 1
        previous = value
    return switches


def _rate_from_counter(samples: list[dict[str, Any]], key: str, duration: float) -> float | str:
    values = [_as_int(row.get(key), -1) for row in samples if row.get(key) is not None]
    values = [value for value in values if value >= 0]
    if len(values) < 2 or duration <= 0:
        return NOT_AVAILABLE
    delta = max(0, values[-1] - values[0])
    return round(delta / duration, 3)


def _sample_status(status: dict[str, Any], *, started: float) -> dict[str, Any]:
    now = time.perf_counter()
    row: dict[str, Any] = {
        "sample_t": now,
        "t_ms": round((now - started) * 1000.0, 3),
    }
    for field in STATUS_FIELDS:
        row[field] = _safe_scalar(_first_value(status, field))
    row["speaking_or_playing"] = bool(
        _as_bool(row.get("speaking_visual_active"))
        or str(row.get("active_playback_status") or "").lower()
        in {"playing", "started", "stable"}
        or str(row.get("voice_anchor_state") or "").lower() == "speaking"
    )
    row["source_label"] = _first_text(
        row,
        "qmlSpeakingEnergySource",
        "speakingEnergySourceLatched",
        "visualizerSourceStrategy",
        "visualizer_source_strategy",
    )
    row["chosen_strategy"] = _first_text(
        row,
        "visualizerSourceStrategy",
        "visualizer_source_strategy",
    )
    row["effective_voice_energy"] = max(
        _as_float(row.get("qmlFinalSpeakingEnergy")),
        _as_float(row.get("finalSpeakingEnergy")),
        _as_float(row.get("latest_voice_energy")),
        _as_float(row.get("playback_envelope_energy")),
    )
    return row


def summarize_case_samples(
    samples: list[dict[str, Any]],
    *,
    started_at: float,
    ended_at: float,
) -> dict[str, Any]:
    duration = max(0.001, ended_at - started_at)
    active = [
        row
        for row in samples
        if _as_bool(row.get("speaking_visual_active"))
        or _as_bool(row.get("speaking_or_playing"))
        or str(row.get("active_playback_status") or "").lower()
        in {"playing", "started", "stable"}
    ]
    considered = active or samples
    energies = [
        number
        for number in (
            _first_number(
                row,
                "qmlFinalSpeakingEnergy",
                "finalSpeakingEnergy",
                "latest_voice_energy",
                "playback_envelope_energy",
                "effective_voice_energy",
            )
            for row in considered
        )
        if number is not None
    ]
    energy_min: float | str = round(min(energies), 6) if energies else NOT_AVAILABLE
    energy_max: float | str = round(max(energies), 6) if energies else NOT_AVAILABLE
    energy_range: float | str = (
        round(float(energy_max) - float(energy_min), 6)
        if isinstance(energy_min, (int, float)) and isinstance(energy_max, (int, float))
        else NOT_AVAILABLE
    )
    source_values = [
        _first_text(row, "source_label", "qmlSpeakingEnergySource", "speakingEnergySourceLatched")
        for row in considered
    ]
    strategy_values = [
        _first_text(row, "chosen_strategy", "visualizerSourceStrategy", "visualizer_source_strategy")
        for row in considered
    ]
    explicit_switch = max(
        (
            _as_int(row.get("visualizerSourceSwitchCount"), _as_int(row.get("visualizer_source_switch_count"), 0))
            for row in considered
        ),
        default=0,
    )
    return {
        "sample_count": len(samples),
        "active_sample_count": len(active),
        "finalSpeakingEnergy_min": energy_min,
        "finalSpeakingEnergy_max": energy_max,
        "finalSpeakingEnergy_range": energy_range,
        "qmlSpeakingEnergySource": _most_common_text(source_values),
        "chosen_visualizer_strategy": _most_common_text(strategy_values),
        "visualizer_source_switch_count": max(explicit_switch, _switch_count(source_values)),
        "requested_anchor_visualizer_mode": _most_common_text(
            [
                _first_text(
                    row,
                    "requested_anchor_visualizer_mode",
                    "requestedAnchorVisualizerMode",
                )
                for row in considered
            ]
        ),
        "effective_anchor_visualizer_mode": _most_common_text(
            [
                _first_text(
                    row,
                    "effective_anchor_visualizer_mode",
                    "effectiveAnchorVisualizerMode",
                )
                for row in considered
            ]
        ),
        "forced_visualizer_mode_honored": any(
            _first_bool(
                row,
                "forced_visualizer_mode_honored",
                "forcedVisualizerModeHonored",
            )
            for row in considered
        ),
        "forced_visualizer_mode_unavailable_reason": _most_common_text(
            [
                _first_text(
                    row,
                    "forced_visualizer_mode_unavailable_reason",
                    "forcedVisualizerModeUnavailableReason",
                )
                for row in considered
            ]
        ),
        "visualizer_strategy_selected_by": _most_common_text(
            [
                _first_text(
                    row,
                    "visualizer_strategy_selected_by",
                    "visualizerStrategySelectedBy",
                )
                for row in considered
            ]
        ),
        "envelope_timeline_ready_at_playback_start": any(
            _first_bool(
                row,
                "envelopeTimelineReadyAtPlaybackStart",
                "envelope_timeline_ready_at_playback_start",
            )
            for row in considered
        ),
        "playback_envelope_available": any(
            _as_bool(row.get("playback_envelope_available")) for row in considered
        ),
        "playback_envelope_usable": any(
            _as_bool(row.get("playback_envelope_usable")) for row in considered
        ),
        "playback_envelope_source": _most_common_text(
            [str(row.get("playback_envelope_source") or "") for row in considered]
        ),
        "playback_envelope_sample_count": max(
            (_as_int(row.get("playback_envelope_sample_count"), 0) for row in considered),
            default=0,
        ),
        "playback_envelope_latest_age_ms": next(
            (
                row.get("playback_envelope_sample_age_ms")
                for row in reversed(considered)
                if row.get("playback_envelope_sample_age_ms") is not None
            ),
            NOT_AVAILABLE,
        ),
        "playback_envelope_alignment_delta_ms": next(
            (
                row.get("playback_envelope_alignment_delta_ms")
                for row in reversed(considered)
                if row.get("playback_envelope_alignment_delta_ms") is not None
            ),
            NOT_AVAILABLE,
        ),
        "playback_envelope_alignment_tolerance_ms": next(
            (
                row.get("playback_envelope_alignment_tolerance_ms")
                for row in reversed(considered)
                if row.get("playback_envelope_alignment_tolerance_ms") is not None
            ),
            NOT_AVAILABLE,
        ),
        "playback_envelope_alignment_status": _most_common_text(
            [
                str(row.get("playback_envelope_alignment_status") or "")
                for row in considered
            ]
        ),
        "voice_payload_updates_per_second": _rate_from_counter(
            considered, "visualizer_updates_received", duration
        ),
        "voice_surface_updates_per_second": _rate_from_counter(
            considered, "visualizer_updates_received", duration
        ),
        "bridge_surface_rebuilds_per_second": _rate_from_counter(
            considered, "bridge_collection_rebuilds_during_speech", duration
        ),
        "visual_voice_state_apply_rate": _rate_from_counter(
            considered, "qml_anchor_updates_during_speech", duration
        ),
        "anchor_paint_count_per_second": NOT_AVAILABLE,
        "anchor_request_paint_count_per_second": NOT_AVAILABLE,
        "shared_animation_clock_fps": NOT_AVAILABLE,
        "frameSwapped_fps": NOT_AVAILABLE,
        "max_frame_gap_ms": NOT_AVAILABLE,
        "long_frames_over_33ms": NOT_AVAILABLE,
        "long_frames_over_50ms": NOT_AVAILABLE,
        "raw_audio_present": any(_as_bool(row.get("raw_audio_present")) for row in considered),
        "raw_audio_logged": any(_as_bool(row.get("raw_audio_logged")) for row in considered),
        "last_sample": considered[-1] if considered else None,
    }


def _settings_case_verification(
    settings: dict[str, Any],
    requested_env: dict[str, str],
) -> dict[str, Any]:
    visual_variant = _dig(settings, "ui", "visual_variant")
    fog_enabled = _dig(settings, "ui", "stormforge_fog", "enabled")
    visualizer_mode = _dig(
        settings,
        "ui",
        "stormforge_voice_diagnostics",
        "anchor_visualizer_mode",
    )
    if visual_variant is None:
        visual_variant = _first_value(settings, "visual_variant")
    if fog_enabled is None:
        fog_enabled = _first_value(settings, "enabled")
    if visualizer_mode is None:
        visualizer_mode = _first_value(settings, "anchor_visualizer_mode")
    return {
        "requested": dict(requested_env),
        "settings_visual_variant": visual_variant,
        "settings_fog_enabled": fog_enabled,
        "settings_anchor_visualizer_mode": visualizer_mode,
        "ui_variant_matches": str(visual_variant or "").lower()
        == "stormforge",
        "fog_matches": _as_bool(fog_enabled)
        == (requested_env.get("STORMHELM_STORMFORGE_FOG") == "1"),
        "visualizer_mode_matches": (
            "STORMHELM_ANCHOR_VISUALIZER_MODE" not in requested_env
            or str(visualizer_mode or "").lower()
            == requested_env["STORMHELM_ANCHOR_VISUALIZER_MODE"]
        ),
    }


def _powershell_json(command: str, *, timeout: float = 20.0) -> Any:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        return {"error": completed.stderr.strip() or completed.stdout.strip()}
    output = completed.stdout.strip()
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"raw": output}


def stormhelm_processes() -> list[dict[str, Any]]:
    command = r"""
$items = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'stormhelm\.entrypoints\.(core|ui)' } |
  ForEach-Object {
    [pscustomobject]@{
      pid = $_.ProcessId
      parent_pid = $_.ParentProcessId
      name = $_.Name
      role = if ($_.CommandLine -match 'stormhelm\.entrypoints\.core') { 'core' } else { 'ui' }
      command_line = $_.CommandLine
    }
  }
@($items) | ConvertTo-Json -Depth 5
"""
    payload = _powershell_json(command)
    if isinstance(payload, dict):
        if "pid" in payload:
            return [payload]
        return [{"error": payload.get("error") or payload.get("raw") or str(payload)}]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _safe_filename(value: str) -> str:
    safe = []
    for character in str(value or ""):
        if character.isalnum() or character in {"_", "-"}:
            safe.append(character)
        else:
            safe.append("_")
    return "".join(safe).strip("_") or "case"


def child_log_plan(
    *,
    case: dict[str, Any],
    output_dir: Path | str,
    verbose_polling: bool,
) -> dict[str, Any]:
    if verbose_polling:
        return {"redirected": False, "reason": "verbose_polling_enabled"}
    base_name = f"case_{_safe_filename(str(case.get('case') or ''))}_{_safe_filename(str(case.get('name') or ''))}"
    log_dir = Path(output_dir) / "process_logs"
    return {
        "redirected": True,
        "core_log_path": str(log_dir / f"{base_name}_core.log"),
        "ui_log_path": str(log_dir / f"{base_name}_ui.log"),
    }


def _open_child_log(plan: dict[str, Any], role: str):
    if not plan.get("redirected"):
        return None
    path_value = plan.get(f"{role}_log_path")
    if not path_value:
        return None
    path = Path(str(path_value))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a", encoding="utf-8")


def stop_stormhelm_processes() -> dict[str, Any]:
    before = stormhelm_processes()
    command = r"""
$allProcesses = @(Get-CimInstance Win32_Process)
$roots = @($allProcesses | Where-Object { $_.CommandLine -match 'stormhelm\.entrypoints\.(core|ui)' })
$ids = @{}
function Add-Tree([int]$ProcessId) {
  if ($ids.ContainsKey([string]$ProcessId)) { return }
  $ids[[string]$ProcessId] = $true
  foreach ($child in @($allProcesses | Where-Object { $_.ParentProcessId -eq $ProcessId })) {
    Add-Tree -ProcessId ([int]$child.ProcessId)
  }
}
foreach ($root in $roots) { Add-Tree -ProcessId ([int]$root.ProcessId) }
$stopped = @()
foreach ($id in @($ids.Keys | Sort-Object {[int]$_} -Descending)) {
  try {
    Stop-Process -Id ([int]$id) -Force -ErrorAction Stop
    $stopped += [int]$id
  } catch {}
}
[pscustomobject]@{ stopped_pids = $stopped } | ConvertTo-Json -Depth 4
"""
    stopped = _powershell_json(command, timeout=30.0)
    time.sleep(1.0)
    after = stormhelm_processes()
    return {"before": before, "stopped": stopped, "after": after}


def start_stormhelm_processes(
    case_environment: dict[str, str],
    *,
    log_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(case_environment)
    if "STORMHELM_ANCHOR_VISUALIZER_MODE" not in case_environment:
        env.pop("STORMHELM_ANCHOR_VISUALIZER_MODE", None)
    env["PYTHONPATH"] = str(ROOT / "src")
    log_plan = dict(log_plan or {"redirected": False, "reason": "not_configured"})
    core_log = _open_child_log(log_plan, "core")
    core = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "run_core.ps1"),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=core_log if core_log is not None else None,
        stderr=subprocess.STDOUT if core_log is not None else None,
    )
    if core_log is not None:
        core_log.close()
    time.sleep(1.5)
    ui_log = _open_child_log(log_plan, "ui")
    ui = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "run_ui.ps1"),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=ui_log if ui_log is not None else None,
        stderr=subprocess.STDOUT if ui_log is not None else None,
    )
    if ui_log is not None:
        ui_log.close()
    return {
        "core_launcher_pid": core.pid,
        "ui_launcher_pid": ui.pid,
        "child_output": log_plan,
        "processes_after_launch": stormhelm_processes(),
    }


def wait_for_health(base_url: str, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_seconds
    last_error = ""
    while time.perf_counter() < deadline:
        try:
            health = _http_json("GET", f"{base_url}/health", timeout=3.0)
            if health.get("status") == "ok":
                return health
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            last_error = str(error)
        time.sleep(0.5)
    return {"status": "unavailable", "error": last_error or "health_timeout"}


def safe_clear_cache() -> dict[str, Any]:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return {"cleared": False, "reason": "LOCALAPPDATA_not_set"}
    root = Path(local_app_data).resolve() / "Stormhelm"
    candidates = [
        root / "cache",
        root / "Stormhelm" / "cache",
    ]
    cleared: list[str] = []
    missing: list[str] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if root.resolve() not in resolved.parents and resolved != root.resolve():
            continue
        if not resolved.exists():
            missing.append(str(resolved))
            continue
        for child in resolved.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
        cleared.append(str(resolved))
    return {"cleared": bool(cleared), "paths": cleared, "missing": missing}


def _prompt_choice(prompt: str, choices: set[str], default: str) -> str:
    while True:
        value = input(f"{prompt} [{default}]: ").strip().lower()
        if not value:
            return default
        if value in choices:
            return value
        print(f"Please enter one of: {', '.join(sorted(choices))}")


def _prompt_bool(prompt: str, default: bool = False) -> bool:
    default_text = "y" if default else "n"
    value = input(f"{prompt} [y/n, default {default_text}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true"}


def _operator_observation(non_interactive: bool) -> dict[str, Any]:
    if non_interactive:
        return {
            "subjective_result": "not_tested",
            "real_audible_playback_occurred": False,
            "audio_itself_skipped": NOT_AVAILABLE,
            "anchor_skipped": NOT_AVAILABLE,
            "fog_skipped": NOT_AVAILABLE,
            "anchor_visible_motion": NOT_AVAILABLE,
            "motion_character": NOT_AVAILABLE,
            "source_label_changed_during_speech": NOT_AVAILABLE,
            "operator_notes": "non_interactive_run_no_subjective_scoring",
        }
    result = _prompt_choice(
        "Subjective result (smooth/stutter/freeze/no_animation/wrong_source/not_tested)",
        SUBJECTIVE_CHOICES,
        "not_tested",
    )
    return {
        "subjective_result": result,
        "real_audible_playback_occurred": _prompt_bool("Did real audible Stormhelm speech play?", default=True),
        "audio_itself_skipped": _prompt_bool("Did the audio itself skip?", default=False),
        "anchor_skipped": _prompt_bool("Did the anchor skip/freeze?", default=False),
        "fog_skipped": _prompt_bool("Did fog skip?", default=False),
        "anchor_visible_motion": _prompt_bool("Did the anchor have visible speaking motion?", default=True),
        "motion_character": _prompt_choice(
            "Motion character (audio_reactive/procedural/static/none/unsure)",
            {"audio_reactive", "procedural", "static", "none", "unsure"},
            "unsure",
        ),
        "source_label_changed_during_speech": _prompt_bool("Did the source/status label change during speech?", default=False),
        "operator_notes": input("Notes (optional): ").strip(),
    }


def polling_terminal_summary(samples: list[dict[str, Any]]) -> str:
    errors = sum(1 for row in samples if row.get("status_error"))
    return f"Captured {len(samples)} status samples, {errors} request errors."


def trigger_spoken_response(
    *,
    base_url: str,
    session_id: str,
    spoken_prompt: str,
    timeout: float,
) -> dict[str, Any]:
    chat_prompt = f"Please say exactly: {spoken_prompt}"
    return _http_json(
        "POST",
        f"{base_url}/chat/send",
        payload={
            "message": chat_prompt,
            "session_id": session_id,
            "surface_mode": "ghost",
            "active_module": "ghost",
        },
        timeout=timeout,
    )


def run_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    base_url = str(args.base_url).rstrip("/")
    requested_env = case_env(case)
    session_id = f"live-voice-iso2-{case['case'].lower()}-{uuid4().hex[:8]}"
    process_state: dict[str, Any] = {"management": "skipped"}
    cache_state = {"cleared": False, "reason": "not_requested"}

    print(f"\n=== Case {case['case']} - {case['name']} ===")
    print(json.dumps(requested_env, indent=2))

    if args.clear_cache:
        cache_state = safe_clear_cache()

    log_plan = child_log_plan(
        case=case,
        output_dir=Path(args.output_dir),
        verbose_polling=bool(args.verbose_polling),
    )
    if not args.skip_process_management:
        process_state = {
            "stop": stop_stormhelm_processes(),
            "start": start_stormhelm_processes(requested_env, log_plan=log_plan),
        }
        if log_plan.get("redirected"):
            print(
                "Core/UI process output redirected to "
                f"{log_plan.get('core_log_path')} and {log_plan.get('ui_log_path')}."
            )
    elif args.print_manual_commands:
        print_manual_case_commands(case)
    elif not args.verbose_polling:
        print(
            "Process management skipped; any already-attached Core/UI access logs "
            "cannot be redirected by this probe."
        )

    health = wait_for_health(base_url, timeout_seconds=float(args.startup_wait_seconds))
    try:
        settings = _http_json("GET", f"{base_url}/settings", timeout=args.timeout)
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        settings = {"error": str(error)}
    env_verification = _settings_case_verification(settings, requested_env)

    if not args.non_interactive:
        input("Press Enter when the Stormforge UI is visible and ready for this case...")

    trigger_response: dict[str, Any] | None = None
    trigger_error = ""
    started = time.perf_counter()
    if args.no_trigger:
        print("Trigger disabled. Start one real spoken Stormhelm response now.")
        if not args.non_interactive:
            input("Press Enter immediately after triggering the spoken response...")
    else:
        print(f"Triggering spoken prompt through /chat/send: {args.spoken_prompt!r}")
        try:
            trigger_response = trigger_spoken_response(
                base_url=base_url,
                session_id=session_id,
                spoken_prompt=args.spoken_prompt,
                timeout=args.timeout,
            )
        except Exception as error:  # noqa: BLE001 - diagnostics must preserve failure text
            trigger_error = str(error)
            print(f"WARNING: spoken prompt trigger failed: {trigger_error}", file=sys.stderr)

    samples: list[dict[str, Any]] = []
    deadline = time.perf_counter() + max(1.0, float(args.poll_seconds))
    interval = max(0.05, float(args.poll_interval_seconds))
    if args.verbose_polling:
        print(
            f"Polling /status verbosely for {float(args.poll_seconds):.1f} seconds "
            f"every {interval:.2f} seconds..."
        )
    else:
        print(f"Polling status quietly for {float(args.poll_seconds):.1f} seconds...")
    while time.perf_counter() < deadline:
        try:
            status = _http_json("GET", f"{base_url}/status", timeout=args.timeout)
            sample = _sample_status(status, started=started)
            samples.append(sample)
            if args.verbose_polling:
                print(
                    "status sample "
                    f"t={sample.get('t_ms')}ms "
                    f"playback={sample.get('active_playback_status')} "
                    f"speaking={sample.get('speaking_visual_active')} "
                    f"source={sample.get('source_label') or NOT_AVAILABLE}"
                )
        except Exception as error:  # noqa: BLE001 - keep probe alive for report
            sample = {
                "sample_t": time.perf_counter(),
                "t_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "status_error": str(error),
            }
            samples.append(sample)
            if args.verbose_polling:
                print(f"status sample error at {sample['t_ms']}ms: {error}", file=sys.stderr)
        time.sleep(interval)
    ended = time.perf_counter()
    print(polling_terminal_summary(samples))

    summary = summarize_case_samples(samples, started_at=started, ended_at=ended)
    source_check = source_expectation_check(requested_env, summary)
    observation = _operator_observation(bool(args.non_interactive))
    if observation["real_audible_playback_occurred"] is False and any(
        _as_bool(row.get("user_heard_claimed")) for row in samples
    ):
        observation["backend_user_heard_claimed"] = True

    result = {
        "case": case["case"],
        "name": case["name"],
        "expected_interpretation": case["expected"],
        "env": requested_env,
        "session_id": session_id,
        "health": health,
        "settings_verification": env_verification,
        "process_state": process_state,
        "cache_state": cache_state,
        "child_output": log_plan,
        "triggered_chat": trigger_response is not None,
        "trigger_error": trigger_error,
        "trigger_response_received": bool(trigger_response),
        "real_audible_playback_occurred": observation["real_audible_playback_occurred"],
        "audible_confirmation_source": "operator" if not args.non_interactive else "not_confirmed",
        "fogActive": bool(case["fog_enabled"]),
        "fog_disabled_reason": "STORMHELM_STORMFORGE_FOG=0"
        if not bool(case["fog_enabled"])
        else "",
        **summary,
        **source_check,
        **observation,
        "diagnostic_limitations": [
            "QML-only frameSwapped, anchor paint, and shared animation clock metrics are not exposed through the live HTTP status path; they remain not_available unless added to a future UI telemetry return channel."
        ],
    }
    return result


def build_report(
    *,
    cases: list[dict[str, Any]],
    process_state: dict[str, Any],
    cache_state: dict[str, Any],
    spoken_prompt: str,
) -> dict[str, Any]:
    required = {"A", "B", "C", "D", "E", "F"}
    audible_required = {
        str(case.get("case") or "").upper()
        for case in cases
        if case.get("real_audible_playback_occurred") is True
    }
    return {
        "probe_version": "UI-VOICE-LIVE-ISO.2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live_audible_voice_playback_exercised": required.issubset(audible_required),
        "visible_qml_probe_was_final_proof": False,
        "spoken_prompt": spoken_prompt,
        "process_state": process_state,
        "cache_state": cache_state,
        "cases": cases,
        "root_cause_classification": classify_root_cause(cases),
        "privacy": {
            "raw_audio_exposed": False,
            "raw_audio_logged": any(_as_bool(case.get("raw_audio_logged")) for case in cases),
            "raw_audio_present_in_payload": any(_as_bool(case.get("raw_audio_present")) for case in cases),
        },
        "decision_rules": [
            "Case A stutter means suspect real voice path, bridge churn, surface rebuilds, or Ghost runtime pressure.",
            "Case A smooth and B stutter means suspect Anchor Canvas/render path or speaking-state churn.",
            "Case B smooth and C stutter means suspect procedural speaking path.",
            "Case C smooth and D stutter means suspect envelope timeline sampling or payload churn.",
            "B/C/D smooth with E/F stutter means suspect fog/render load combined with real voice.",
            "B/C/D/E/F smooth with default stutter means suspect default source selection or env/config mismatch.",
        ],
    }


def _markdown_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value if value not in {None, ""} else NOT_AVAILABLE)


def write_artifacts(report: dict[str, Any], output_dir: Path | str = ARTIFACT_DIR) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / REPORT_JSON.name).write_text(
        json.dumps(report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    rows = report.get("cases") if isinstance(report.get("cases"), list) else []
    fieldnames = [
        "case",
        "name",
        "STORMHELM_STORMFORGE_FOG",
        "STORMHELM_ANCHOR_VISUALIZER_MODE",
        "real_audible_playback_occurred",
        "subjective_result",
        "audio_itself_skipped",
        "anchor_skipped",
        "fog_skipped",
        "anchor_visible_motion",
        "motion_character",
        "source_label_changed_during_speech",
        "qmlSpeakingEnergySource",
        "chosen_visualizer_strategy",
        "expected_visualizer_strategy",
        "source_mismatch_detected",
        "source_mismatch_reason",
        "forced_visualizer_mode_honored",
        "forced_visualizer_mode_unavailable_reason",
        "visualizer_strategy_selected_by",
        "playback_envelope_alignment_delta_ms",
        "playback_envelope_alignment_tolerance_ms",
        "playback_envelope_alignment_status",
        "finalSpeakingEnergy_min",
        "finalSpeakingEnergy_max",
        "finalSpeakingEnergy_range",
        "visualizer_source_switch_count",
        "envelope_timeline_ready_at_playback_start",
        "playback_envelope_available",
        "playback_envelope_usable",
        "voice_payload_updates_per_second",
        "voice_surface_updates_per_second",
        "bridge_surface_rebuilds_per_second",
        "visual_voice_state_apply_rate",
        "anchor_paint_count_per_second",
        "anchor_request_paint_count_per_second",
        "shared_animation_clock_fps",
        "frameSwapped_fps",
        "max_frame_gap_ms",
        "long_frames_over_33ms",
        "long_frames_over_50ms",
        "fogActive",
        "fog_disabled_reason",
        "operator_notes",
    ]
    with (output / OBSERVATIONS_CSV.name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            env = row.get("env") if isinstance(row.get("env"), dict) else {}
            flat["STORMHELM_STORMFORGE_FOG"] = env.get("STORMHELM_STORMFORGE_FOG", "")
            flat["STORMHELM_ANCHOR_VISUALIZER_MODE"] = env.get(
                "STORMHELM_ANCHOR_VISUALIZER_MODE", "default"
            )
            writer.writerow(flat)

    lines = [
        "# UI-VOICE-LIVE-ISO.2 Live Voice Visualizer A/B Report",
        "",
        f"- Generated: `{report.get('generated_at')}`",
        f"- Spoken prompt: `{report.get('spoken_prompt')}`",
        f"- Real audible A-F exercised: `{report.get('live_audible_voice_playback_exercised')}`",
        f"- Root-cause classification: `{report.get('root_cause_classification')}`",
        f"- Raw audio exposed/logged: `false`",
        "",
        "| Case | Fog | Mode | Audible | Subjective | Audio Skip | Anchor Skip | Fog Skip | Source | Strategy | Expected | Mismatch | Align | Energy Range | Switches | Voice Updates/s | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        env = row.get("env") if isinstance(row.get("env"), dict) else {}
        lines.append(
            "| {case} | {fog} | `{mode}` | {audible} | {subjective} | {audio_skip} | {anchor_skip} | {fog_skip} | `{source}` | `{strategy}` | `{expected}` | {mismatch} | `{align}` | {energy} | {switches} | {updates} | {notes} |".format(
                case=row.get("case", ""),
                fog="on" if env.get("STORMHELM_STORMFORGE_FOG") == "1" else "off",
                mode=env.get("STORMHELM_ANCHOR_VISUALIZER_MODE", "default"),
                audible=_markdown_value(row.get("real_audible_playback_occurred")),
                subjective=_markdown_value(row.get("subjective_result")),
                audio_skip=_markdown_value(row.get("audio_itself_skipped")),
                anchor_skip=_markdown_value(row.get("anchor_skipped")),
                fog_skip=_markdown_value(row.get("fog_skipped")),
                source=_markdown_value(row.get("qmlSpeakingEnergySource")),
                strategy=_markdown_value(row.get("chosen_visualizer_strategy")),
                expected=_markdown_value(row.get("expected_visualizer_strategy")),
                mismatch=_markdown_value(row.get("source_mismatch_detected")),
                align=_markdown_value(row.get("playback_envelope_alignment_status")),
                energy=_markdown_value(row.get("finalSpeakingEnergy_range")),
                switches=_markdown_value(row.get("visualizer_source_switch_count")),
                updates=_markdown_value(row.get("voice_payload_updates_per_second")),
                notes=str(row.get("operator_notes") or "").replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Process And Cache",
            "",
            "```json",
            json.dumps(
                {
                    "process_state": report.get("process_state"),
                    "cache_state": report.get("cache_state"),
                },
                indent=2,
                default=str,
            ),
            "```",
            "",
            "## Limitations",
            "",
            "- The harness exercises real `/chat/send` spoken output when run interactively without `--no-trigger`.",
            "- Operator scoring is required for visual smooth/stutter/freeze judgments.",
            "- Live HTTP status does not currently expose actual QQuickWindow frameSwapped or QML anchor paint cadence from the production UI process, so those fields are recorded as `not_available` rather than inferred.",
        ]
    )
    (output / REPORT_MD.name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_manual_case_commands(case: dict[str, Any]) -> None:
    env = case_env(case)
    print("Manual launch overrides:")
    print("$env:STORMHELM_UI_VARIANT='stormforge'")
    print(f"$env:STORMHELM_STORMFORGE_FOG='{env['STORMHELM_STORMFORGE_FOG']}'")
    if "STORMHELM_ANCHOR_VISUALIZER_MODE" in env:
        print(
            "$env:STORMHELM_ANCHOR_VISUALIZER_MODE="
            f"'{env['STORMHELM_ANCHOR_VISUALIZER_MODE']}'"
        )
    else:
        print("Remove-Item Env:STORMHELM_ANCHOR_VISUALIZER_MODE -ErrorAction SilentlyContinue")
    print(".\\scripts\\run_core.ps1")
    print(".\\scripts\\run_ui.ps1")


def selected_cases(value: str, *, include_default: bool) -> list[dict[str, Any]]:
    wanted = [item.strip().upper() for item in str(value or "").split(",") if item.strip()]
    if not wanted:
        wanted = ["A", "B", "C", "D", "E", "F"]
    if include_default and "G" not in wanted:
        wanted.append("G")
    known = {case["case"]: case for case in CASES}
    missing = [case_id for case_id in wanted if case_id not in known]
    if missing:
        raise SystemExit(f"Unknown case id(s): {', '.join(missing)}")
    return [known[case_id] for case_id in wanted]


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    process_state_before = {
        "before_probe": stormhelm_processes(),
        "process_management": "dry_run_no_process_mutation"
        if args.dry_run
        else "skipped"
        if args.skip_process_management
        else "managed_per_case",
    }
    cache_state = {"cleared": False, "reason": "not_requested"}
    if args.dry_run:
        cases = [
            {
                "case": case["case"],
                "name": case["name"],
                "env": case_env(case),
                "real_audible_playback_occurred": False,
                "subjective_result": "not_tested",
                "expected_interpretation": case["expected"],
            }
            for case in selected_cases(args.cases, include_default=args.include_default)
        ]
        report = build_report(
            cases=cases,
            process_state=process_state_before,
            cache_state=cache_state,
            spoken_prompt=args.spoken_prompt,
        )
        write_artifacts(report, Path(args.output_dir))
        return report

    case_results: list[dict[str, Any]] = []
    for case in selected_cases(args.cases, include_default=args.include_default):
        result = run_case(case, args)
        case_results.append(result)
        report = build_report(
            cases=case_results,
            process_state=process_state_before | {"latest": stormhelm_processes()},
            cache_state=result.get("cache_state", cache_state),
            spoken_prompt=args.spoken_prompt,
        )
        write_artifacts(report, Path(args.output_dir))

    if not args.leave_running and not args.skip_process_management:
        process_state_before["final_stop"] = stop_stormhelm_processes()

    report = build_report(
        cases=case_results,
        process_state=process_state_before | {"after_probe": stormhelm_processes()},
        cache_state=case_results[-1].get("cache_state", cache_state) if case_results else cache_state,
        spoken_prompt=args.spoken_prompt,
    )
    write_artifacts(report, Path(args.output_dir))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run guided real-audible Stormforge voice visualizer A/B validation."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--cases", default="A,B,C,D,E,F")
    parser.add_argument("--include-default", action="store_true")
    parser.add_argument("--spoken-prompt", default=DEFAULT_SPOKEN_PROMPT)
    parser.add_argument("--poll-seconds", type=float, default=16.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.12)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--startup-wait-seconds", type=float, default=25.0)
    parser.add_argument("--output-dir", default=str(ARTIFACT_DIR))
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-trigger", action="store_true")
    parser.add_argument("--skip-process-management", action="store_true")
    parser.add_argument("--print-manual-commands", action="store_true")
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--leave-running", action="store_true")
    parser.add_argument(
        "--verbose-polling",
        "--verbose-http",
        dest="verbose_polling",
        action="store_true",
        help="Show per-poll status details and leave child Core/UI output attached to the terminal.",
    )
    parser.add_argument(
        "--print-report-json",
        action="store_true",
        help="Print the full structured report JSON to the terminal after writing artifacts.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_probe_logging(verbose_polling=bool(args.verbose_polling))

    report = run_probe(args)
    if args.print_report_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"\nReport written to: {Path(args.output_dir) / REPORT_MD.name}")
        print(f"Observations CSV: {Path(args.output_dir) / OBSERVATIONS_CSV.name}")
        print(f"Root-cause classification: {report.get('root_cause_classification')}")
    if not report.get("live_audible_voice_playback_exercised"):
        print(
            "\nLive audible A-F validation is not complete until each required case is run "
            "with operator-confirmed audible speech and subjective scoring.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
