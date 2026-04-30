from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stormhelm.core.latency import RouteLatencyPosture, get_route_latency_contract

ARTIFACT_ROOT = PROJECT_ROOT / ".artifacts" / "live-runtime-latency-trace"
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
STATUS_STALL_THRESHOLD_MS = 1_000.0
SNAPSHOT_STALL_THRESHOLD_MS = 1_000.0
BACKEND_SLOW_THRESHOLD_MS = 2_500.0
ROUTE_HANDLER_SLOW_THRESHOLD_MS = 2_000.0
LARGE_RESPONSE_BYTES = 250_000

PROMPTS: list[dict[str, Any]] = [
    {"id": 1, "category": "fast_deterministic", "prompt": "5*4/2"},
    {"id": 2, "category": "fast_deterministic", "prompt": "47k / 2.2u"},
    {"id": 3, "category": "fast_deterministic", "prompt": "what time is it"},
    {"id": 4, "category": "fast_deterministic", "prompt": "calculate 12V * 1.5A"},
    {"id": 5, "category": "weather_location_system", "prompt": "what is the weather"},
    {
        "id": 6,
        "category": "weather_location_system",
        "prompt": "what is the weather in Perkinsville Vermont",
    },
    {"id": 7, "category": "weather_location_system", "prompt": "what is my location"},
    {"id": 8, "category": "weather_location_system", "prompt": "saved locations"},
    {"id": 9, "category": "weather_location_system", "prompt": "network status"},
    {"id": 10, "category": "weather_location_system", "prompt": "battery status"},
    {"id": 24, "category": "weather_location_system", "prompt": "what is my CPU at"},
    {"id": 25, "category": "weather_location_system", "prompt": "CPU usage"},
    {"id": 26, "category": "weather_location_system", "prompt": "memory usage"},
    {"id": 27, "category": "weather_location_system", "prompt": "storage status"},
    {"id": 28, "category": "weather_location_system", "prompt": "machine status"},
    {"id": 11, "category": "voice_text_interaction", "prompt": "say bearing acquired"},
    {"id": 12, "category": "voice_text_interaction", "prompt": "what time is it"},
    {"id": 13, "category": "voice_text_interaction", "prompt": "what time is it"},
    {
        "id": 14,
        "category": "voice_text_interaction",
        "prompt": "Give me a longer spoken response about Stormhelm latency in one calm paragraph.",
    },
    {"id": 15, "category": "ui_snapshot_context", "prompt": "where did we leave off"},
    {"id": 16, "category": "ui_snapshot_context", "prompt": "open github.com"},
    {"id": 17, "category": "ui_snapshot_context", "prompt": "show recent files"},
    {
        "id": 18,
        "category": "ui_snapshot_context",
        "prompt": "restore workspace summary safe dry-run",
    },
    {
        "id": 19,
        "category": "ambiguous_clarification",
        "prompt": "send this to Baby",
        "input_context": {},
    },
    {
        "id": 20,
        "category": "ambiguous_clarification",
        "prompt": "what am I looking at",
    },
    {"id": 21, "category": "ambiguous_clarification", "prompt": "confirm"},
    {
        "id": 22,
        "category": "optional_stretch",
        "prompt": "explain Stormhelm latency briefly",
    },
    {
        "id": 23,
        "category": "optional_stretch",
        "prompt": "weather again immediately after first weather request",
    },
]

RESOURCE_HOT_PATH_PROMPTS: list[dict[str, Any]] = [
    {"id": 101, "category": "system_resource_hot_path", "prompt": "what is my CPU at"},
    {"id": 102, "category": "system_resource_hot_path", "prompt": "CPU usage"},
    {"id": 103, "category": "system_resource_hot_path", "prompt": "memory usage"},
    {"id": 104, "category": "system_resource_hot_path", "prompt": "battery status"},
    {"id": 105, "category": "system_resource_hot_path", "prompt": "network status"},
    {"id": 106, "category": "system_resource_hot_path", "prompt": "storage status"},
    {"id": 107, "category": "system_resource_hot_path", "prompt": "machine status"},
    {"id": 108, "category": "control", "prompt": "5*4/2"},
]

REQUIRED_ROW_FIELDS = (
    "prompt_id",
    "prompt",
    "category",
    "mode",
    "path",
    "started_at",
    "chat_send_wall_ms",
    "response_json_bytes",
    "stage_timings_ms",
    "latency_trace",
    "latency_summary",
    "route_family",
    "voice_output",
    "voice_speak_decision",
    "status_samples",
    "snapshot_samples",
    "event_stream_events",
    "anchor_samples",
    "expected_posture",
    "actual_posture",
    "hot_path_budget_exceeded",
    "blocking_live_probe_detected",
    "cache_hit",
    "cache_miss",
    "async_deferred",
    "payload_size_bytes",
    "status_snapshot_impact",
    "classifications",
)

SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|bearer|token|secret|password|credential|cookie)",
    re.IGNORECASE,
)
RAW_AUDIO_KEY_RE = re.compile(
    r"(raw[_-]?audio|audio[_-]?bytes|pcm[_-]?bytes|wav[_-]?bytes|mp3[_-]?bytes|tts[_-]?audio)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def perf_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def sanitize_for_report(value: Any, *, key: str = "") -> Any:
    if isinstance(value, bool | int | float) or value is None:
        return value
    if SECRET_KEY_RE.search(key):
        return "[REDACTED_SECRET]"
    if RAW_AUDIO_KEY_RE.search(key):
        return "[REDACTED_AUDIO]"
    if isinstance(value, bytes | bytearray | memoryview):
        return f"[REDACTED_BYTES:{len(value)}]"
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_for_report(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [sanitize_for_report(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_report(item, key=key) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE_RE.sub("[REDACTED_SECRET]", value)
    return value


def missing_required_row_fields(row: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_ROW_FIELDS if field not in row]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _lower_key_map(value: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for node_key, node_value in node.items():
                key = str(node_key).strip().lower()
                found.setdefault(key, node_value)
                visit(node_value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(value)
    return found


def _timing(row: dict[str, Any], *names: str) -> float:
    sources = [
        row.get("stage_timings_ms"),
        row.get("latency_trace"),
        row.get("latency_summary"),
    ]
    lowered: dict[str, Any] = {}
    for source in sources:
        lowered.update(_lower_key_map(source))
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return _as_float(value)
    return 0.0


def _timing_raw(row: dict[str, Any], *names: str) -> Any:
    sources = [
        row.get("stage_timings_ms"),
        row.get("latency_trace"),
        row.get("latency_summary"),
        row.get("system_resource_subspans"),
    ]
    lowered: dict[str, Any] = {}
    for source in sources:
        lowered.update(_lower_key_map(source))
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return None


def _timing_bool(row: dict[str, Any], *names: str) -> bool | None:
    value = _timing_raw(row, *names)
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "1", "hit"}:
            return True
        if text in {"false", "no", "0", "miss"}:
            return False
    return None


def _timing_str(row: dict[str, Any], *names: str) -> str:
    value = _timing_raw(row, *names)
    if value is None:
        return ""
    return str(value)


def _normalized_route_family(row: dict[str, Any]) -> str:
    family = str(row.get("route_family") or "").strip().lower()
    aliases = {
        "clock": "time",
        "resource": "resources",
        "system": "machine",
        "system_overview": "machine",
        "recent_files": "task_continuity",
        "file": "file_operation",
        "files": "file_operation",
        "native_unsupported": "unsupported",
    }
    if family:
        return aliases.get(family, family)
    prompt = str(row.get("prompt") or "").strip().lower()
    if any(token in prompt for token in ("cpu", "memory", "ram", "resource usage")):
        return "resources"
    if any(token in prompt for token in ("battery", "power")):
        return "power"
    if any(token in prompt for token in ("network", "internet speed", "wifi", "wi-fi")):
        return "network"
    if any(token in prompt for token in ("storage", "disk", "free space")):
        return "storage"
    if "machine" in prompt or "hardware" in prompt:
        return "machine"
    if "weather" in prompt:
        return "weather"
    if "location" in prompt or "where am i" in prompt:
        return "location"
    if "recent files" in prompt or "where did we leave off" in prompt:
        return "task_continuity"
    if "open " in prompt and "." in prompt:
        return "browser_destination"
    if "looking at" in prompt:
        return "screen_awareness"
    if re.search(r"\d+\s*[\+\-\*/x]\s*\d+", prompt):
        return "calculations"
    if "time" in prompt:
        return "time"
    return "unsupported"


def _trace_cache_hit(row: dict[str, Any]) -> bool | None:
    for key in (
        "system_cache_hit",
        "system_resource_cache_hit",
        "weather_cache_hit",
        "location_cache_hit",
        "workspace_cache_hit",
        "cache_hit",
    ):
        value = _timing_bool(row, key)
        if value is not None:
            return value
    return None


def _trace_async_deferred(row: dict[str, Any]) -> bool:
    return bool(
        _timing_bool(row, "live_probe_deferred") is True
        or _timing_bool(row, "system_probe_deferred") is True
        or _timing_bool(row, "async_initial_response_returned") is True
        or _timing_bool(row, "async_continuation") is True
        or _timing_bool(row, "detail_load_deferred") is True
    )


def _status_snapshot_impact(row: dict[str, Any]) -> dict[str, Any]:
    status_samples = row.get("status_samples") or []
    snapshot_samples = row.get("snapshot_samples") or []
    status_max_ms = max((_as_float(sample.get("wall_ms")) for sample in status_samples), default=0.0)
    snapshot_max_ms = max((_as_float(sample.get("wall_ms")) for sample in snapshot_samples), default=0.0)
    return {
        "status_sample_count": len(status_samples),
        "snapshot_sample_count": len(snapshot_samples),
        "status_max_ms": round(status_max_ms, 3),
        "snapshot_max_ms": round(snapshot_max_ms, 3),
        "status_stall_detected": bool(status_max_ms >= STATUS_STALL_THRESHOLD_MS),
        "snapshot_stall_detected": bool(snapshot_max_ms >= SNAPSHOT_STALL_THRESHOLD_MS),
    }


def enrich_route_posture_fields(row: dict[str, Any]) -> dict[str, Any]:
    family = _normalized_route_family(row)
    contract = get_route_latency_contract(family)
    expected = contract.latency_posture.value
    cache_hit = _trace_cache_hit(row)
    async_deferred = _trace_async_deferred(row)
    chat_ms = _as_float(row.get("chat_send_wall_ms"))
    hot_path_budget_exceeded = bool(chat_ms > float(contract.hot_path_budget_ms))
    live_probe_values = {
        "cpu_probe_ms": _timing(row, "cpu_probe_ms"),
        "resource_probe_ms": _timing(row, "resource_probe_ms", "resource_status_probe_ms"),
        "battery_probe_ms": _timing(row, "battery_probe_ms", "power_probe_ms"),
        "storage_probe_ms": _timing(row, "storage_probe_ms"),
        "network_probe_ms": _timing(row, "network_probe_ms"),
        "hardware_telemetry_probe_ms": _timing(row, "hardware_telemetry_probe_ms"),
        "weather_location_lookup_ms": _timing(row, "weather_location_lookup_ms", "location_lookup_ms"),
        "weather_provider_call_ms": _timing(row, "weather_provider_call_ms", "weather_provider_ms", "provider_call_ms"),
        "location_probe_ms": _timing(row, "location_probe_ms"),
        "workspace_scan_ms": _timing(row, "workspace_scan_ms"),
    }
    live_probe_over_budget = any(
        value > float(contract.live_probe_budget_ms)
        for value in live_probe_values.values()
    )
    blocking_live_probe = (
        live_probe_over_budget
        and hot_path_budget_exceeded
        and not async_deferred
    )
    if expected == RouteLatencyPosture.INSTANT.value:
        actual = RouteLatencyPosture.INSTANT.value
    elif async_deferred:
        actual = RouteLatencyPosture.ASYNC_CONTINUATION.value
    elif expected == RouteLatencyPosture.CACHED_FAST.value and cache_hit is not False:
        actual = RouteLatencyPosture.CACHED_FAST.value
    elif expected == RouteLatencyPosture.BOUNDED_LIVE.value and not blocking_live_probe:
        actual = RouteLatencyPosture.BOUNDED_LIVE.value
    else:
        actual = expected
    payload_size = int(_as_float(row.get("response_json_bytes")))
    return {
        "route_family": family or row.get("route_family") or "",
        "expected_posture": expected,
        "actual_posture": actual,
        "hot_path_budget_ms": contract.hot_path_budget_ms,
        "live_probe_budget_ms": contract.live_probe_budget_ms,
        "hot_path_budget_exceeded": hot_path_budget_exceeded,
        "blocking_live_probe_detected": bool(blocking_live_probe),
        "cache_hit": cache_hit,
        "cache_miss": cache_hit is False,
        "async_deferred": async_deferred,
        "payload_size_bytes": payload_size,
        "status_snapshot_impact": _status_snapshot_impact(row),
    }


def status_stalls(
    samples: Iterable[dict[str, Any]],
    *,
    threshold_ms: float = STATUS_STALL_THRESHOLD_MS,
) -> list[dict[str, Any]]:
    return [
        dict(sample)
        for sample in samples
        if _as_float(sample.get("wall_ms")) >= threshold_ms
    ]


def snapshot_stalls(
    samples: Iterable[dict[str, Any]],
    *,
    threshold_ms: float = SNAPSHOT_STALL_THRESHOLD_MS,
) -> list[dict[str, Any]]:
    return [
        dict(sample)
        for sample in samples
        if _as_float(sample.get("wall_ms")) >= threshold_ms
    ]


def classify_weather_tail(row: dict[str, Any]) -> list[str]:
    prompt = str(row.get("prompt") or "").lower()
    route_family = str(row.get("route_family") or "").lower()
    if "weather" not in prompt and "weather" not in route_family:
        return []

    classes: list[str] = []
    route_handler_ms = _timing(row, "route_handler_ms", "handler_ms")
    job_wait_ms = _timing(
        row,
        "weather_job_wait_ms",
        "job_wait_ms",
        "job_submit_and_wait_ms",
    )
    location_ms = _timing(
        row,
        "weather_location_lookup_ms",
        "location_lookup_ms",
        "location_resolve_ms",
    )
    provider_ms = _timing(
        row,
        "weather_provider_call_ms",
        "weather_provider_ms",
        "provider_call_ms",
        "external_provider_ms",
    )
    timeout_ms = _timing(row, "weather_timeout_ms")
    timeout_seconds = _as_float(
        _lower_key_map(row.get("latency_trace")).get("weather_timeout_seconds")
        or _lower_key_map(row.get("latency_summary")).get("weather_timeout_seconds")
    )
    cache_hit = _lower_key_map(row.get("latency_trace")).get("cache_hit")

    if route_handler_ms >= ROUTE_HANDLER_SLOW_THRESHOLD_MS:
        classes.append("provider_or_tool_wait")
    if job_wait_ms >= 1_000.0:
        classes.append("job_manager_wait")
    if location_ms >= 1_000.0:
        classes.append("weather_location_wait")
    if provider_ms >= 1_000.0:
        classes.append("weather_provider_wait")
    if timeout_ms >= 5_000.0 or timeout_seconds >= 5.0:
        classes.append("provider_timeout_high")
    if cache_hit is False:
        classes.append("cache_miss")
    if not classes and _as_float(row.get("chat_send_wall_ms")) >= BACKEND_SLOW_THRESHOLD_MS:
        classes.append("weather_backend_tail_unknown")
    return classes


def _is_system_resource_row(row: dict[str, Any]) -> bool:
    prompt = str(row.get("prompt") or "").lower()
    route_family = str(row.get("route_family") or "").lower()
    category = str(row.get("category") or "").lower()
    markers = {
        "cpu",
        "memory",
        "ram",
        "resource",
        "resources",
        "battery",
        "power",
        "network",
        "storage",
        "disk",
        "hardware",
        "system",
    }
    return (
        category == "system_resource_hot_path"
        or route_family in {"resources", "resource", "network", "power", "storage", "system"}
        or any(marker in prompt for marker in markers)
        or bool(row.get("system_resource_subspans"))
    )


def _has_explicit_system_resource_trace(row: dict[str, Any]) -> bool:
    if _timing_str(row, "system_freshness_state", "system_resource_freshness_state"):
        return True
    if _timing_bool(row, "live_probe_deferred", "system_probe_deferred") is True:
        return True
    if _timing_bool(row, "system_cache_hit", "system_resource_cache_hit") is not None:
        return True
    return any(
        _timing(row, key) > 0.0
        for key in (
            "cpu_probe_ms",
            "resource_probe_ms",
            "resource_status_probe_ms",
            "hardware_telemetry_probe_ms",
            "network_probe_ms",
            "power_probe_ms",
            "battery_probe_ms",
            "storage_probe_ms",
        )
    )


def classify_system_resource_tail(row: dict[str, Any]) -> list[str]:
    if not _is_system_resource_row(row):
        return []

    classes: list[str] = []
    explicit_trace = _has_explicit_system_resource_trace(row)
    route_handler_ms = _timing(row, "route_handler_ms", "handler_ms")
    job_wait_ms = _timing(row, "resource_job_wait_ms", "job_wait_ms", "job_collection_ms")
    cpu_probe_ms = _timing(row, "cpu_probe_ms")
    resource_probe_ms = _timing(row, "resource_probe_ms", "resource_status_probe_ms")
    hardware_probe_ms = _timing(row, "hardware_telemetry_probe_ms")
    network_probe_ms = _timing(row, "network_probe_ms")
    power_probe_ms = _timing(row, "battery_probe_ms", "power_probe_ms")
    storage_probe_ms = _timing(row, "storage_probe_ms")
    timeout_ms = _timing(row, "live_probe_timeout_ms", "system_probe_timeout_ms")
    cache_age_ms = _timing(row, "system_cache_age_ms", "system_resource_cache_age_ms")
    cache_hit = _timing_bool(row, "system_cache_hit", "system_resource_cache_hit")
    deferred = _timing_bool(row, "live_probe_deferred", "system_probe_deferred")
    freshness = _timing_str(row, "system_freshness_state", "system_resource_freshness_state").lower()

    if explicit_trace and cache_hit is False:
        classes.append("system_resource_cache_miss")
    if explicit_trace and (freshness == "stale" or cache_age_ms >= 30_000.0):
        classes.append("system_resource_cache_stale")
    if explicit_trace and deferred:
        classes.append("system_live_refresh_deferred")
    if explicit_trace and timeout_ms >= 250.0:
        classes.append("system_probe_timeout_bounded")
    if hardware_probe_ms >= 500.0:
        classes.append("hardware_telemetry_wait")
    if any(
        probe_ms >= 500.0
        for probe_ms in (cpu_probe_ms, resource_probe_ms, network_probe_ms, power_probe_ms, storage_probe_ms)
    ):
        classes.append("system_resource_probe_wait")
    if job_wait_ms >= 1_000.0 and not deferred:
        classes.append("job_manager_wait")
    if (
        route_handler_ms >= ROUTE_HANDLER_SLOW_THRESHOLD_MS
        and "system_resource_probe_wait" not in classes
        and not deferred
    ):
        classes.append("system_resource_tail_unknown")
    if (
        _as_float(row.get("chat_send_wall_ms")) >= BACKEND_SLOW_THRESHOLD_MS
        and not classes
    ):
        classes.append("system_resource_tail_unknown")
    return sorted(set(classes))


def classify_anchor_path(row: dict[str, Any]) -> list[str]:
    samples = list(row.get("anchor_samples") or []) + list(row.get("status_samples") or [])
    classes: list[str] = []
    for sample in samples:
        live_playback = bool(
            sample.get("live_playback_active")
            or sample.get("streaming_tts_active")
            or str(sample.get("active_playback_status") or "").lower()
            in {"started", "playing", "active"}
        )
        speaking_visual_active = bool(sample.get("speaking_visual_active"))
        anchor_state = str(sample.get("voice_anchor_state") or "").lower()
        if live_playback and not speaking_visual_active and anchor_state != "speaking":
            classes.append("anchor_state_not_propagated")
        if live_playback and sample.get("voice_audio_reactive_available") is False:
            classes.append("audio_envelope_unavailable")
    return sorted(set(classes))


def classify_row(row: dict[str, Any]) -> list[str]:
    classes: list[str] = []
    chat_send_wall_ms = _as_float(row.get("chat_send_wall_ms"))
    route_handler_ms = _timing(row, "route_handler_ms", "handler_ms")
    stage_total_ms = _timing(row, "total_latency_ms", "endpoint_dispatch_ms")
    response_json_bytes = int(_as_float(row.get("response_json_bytes")))

    if (
        route_handler_ms >= ROUTE_HANDLER_SLOW_THRESHOLD_MS
        or stage_total_ms >= BACKEND_SLOW_THRESHOLD_MS
        or (chat_send_wall_ms >= BACKEND_SLOW_THRESHOLD_MS and not _voice_was_scheduled(row))
    ):
        classes.append("backend_slow")
    if status_stalls(row.get("status_samples") or []):
        classes.append("status_polling_slow")
    if snapshot_stalls(row.get("snapshot_samples") or []):
        classes.append("snapshot_slow")
    if response_json_bytes >= LARGE_RESPONSE_BYTES:
        classes.append("response_payload_large")

    classes.extend(classify_weather_tail(row))
    classes.extend(classify_system_resource_tail(row))
    classes.extend(classify_anchor_path(row))

    if "status_polling_slow" in classes and _voice_was_scheduled(row):
        classes.append("voice_blocks_event_loop")
    if _voice_was_scheduled(row) and chat_send_wall_ms - stage_total_ms >= 1_000.0:
        classes.append("voice_blocks_event_loop")

    event_gaps = [
        _as_float(event.get("gap_since_previous_ms"))
        for event in row.get("event_stream_events") or []
    ]
    if event_gaps and max(event_gaps) >= 2_000.0:
        classes.append("event_stream_gap")

    return sorted(set(classes)) or ["ok"]


def compare_voice_modes(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        key = (str(row.get("prompt") or ""), str(row.get("path") or "direct_backend"))
        mode = str(row.get("mode") or "")
        if mode in {"voice_enabled", "voice_muted"}:
            grouped[key][mode] = row

    comparisons: list[dict[str, Any]] = []
    for (prompt, path), modes in sorted(grouped.items()):
        enabled = modes.get("voice_enabled")
        muted = modes.get("voice_muted")
        if not enabled or not muted:
            continue
        enabled_ms = _as_float(enabled.get("chat_send_wall_ms"))
        muted_ms = _as_float(muted.get("chat_send_wall_ms"))
        delta_ms = round(enabled_ms - muted_ms, 3)
        classification: list[str] = []
        if delta_ms >= 500.0:
            classification.append("voice_enabled_slower")
        if status_stalls(enabled.get("status_samples") or []):
            classification.append("voice_enabled_status_stalls")
        if not classification:
            classification.append("no_voice_delta")
        comparisons.append(
            {
                "prompt": prompt,
                "path": path,
                "voice_enabled_ms": enabled_ms,
                "voice_muted_ms": muted_ms,
                "delta_ms": delta_ms,
                "classification": classification,
            }
        )
    return comparisons


def build_summary(
    *,
    rows: list[dict[str, Any]],
    process_identity: dict[str, Any],
    config_gates: dict[str, Any],
    voice_doctor: dict[str, Any],
    ui_path_results: list[dict[str, Any]],
    started_at: str,
    finished_at: str,
    snapshot_path_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    classified_rows = []
    for row in rows:
        row_copy = dict(row)
        row_copy.update(enrich_route_posture_fields(row_copy))
        row_copy["classifications"] = classify_row(row_copy)
        classified_rows.append(row_copy)

    counts = Counter(
        classification
        for row in classified_rows
        for classification in row.get("classifications", [])
        if classification != "ok"
    )
    top_backend = sorted(
        classified_rows,
        key=lambda row: _as_float(row.get("chat_send_wall_ms")),
        reverse=True,
    )[:10]
    top_status = sorted(
        [
            {**sample, "prompt": row.get("prompt"), "mode": row.get("mode")}
            for row in classified_rows
            for sample in status_stalls(row.get("status_samples") or [])
        ],
        key=lambda sample: _as_float(sample.get("wall_ms")),
        reverse=True,
    )[:10]
    top_snapshot = sorted(
        [
            {**sample, "prompt": row.get("prompt"), "mode": row.get("mode")}
            for row in classified_rows
            for sample in snapshot_stalls(row.get("snapshot_samples") or [])
        ],
        key=lambda sample: _as_float(sample.get("wall_ms")),
        reverse=True,
    )[:10]

    weather_rows = [
        row
        for row in classified_rows
        if "weather" in str(row.get("prompt") or "").lower()
        or "weather" in str(row.get("route_family") or "").lower()
    ]
    system_resource_rows = [
        row for row in classified_rows if _is_system_resource_row(row)
    ]
    anchor_rows = [
        row
        for row in classified_rows
        if any(
            item in row.get("classifications", [])
            for item in ("anchor_state_not_propagated", "audio_envelope_unavailable")
        )
    ]
    voice_blocking_rows = [
        row
        for row in classified_rows
        if any(
            item in row.get("classifications", [])
            for item in ("voice_blocks_event_loop", "status_polling_slow", "event_stream_gap")
        )
    ]

    summary = {
        "schema_version": "live_runtime_latency_trace.v1",
        "started_at": started_at,
        "finished_at": finished_at,
        "process_identity": process_identity,
        "config_gates": config_gates,
        "voice_doctor": voice_doctor,
        "test_matrix": {
            "prompt_count": len({row.get("prompt_id") for row in classified_rows}),
            "row_count": len(classified_rows),
            "modes": sorted({str(row.get("mode") or "") for row in classified_rows}),
            "paths": sorted({str(row.get("path") or "") for row in classified_rows}),
        },
        "direct_backend_results": classified_rows,
        "ui_path_results": ui_path_results,
        "voice_enabled_vs_muted": compare_voice_modes(classified_rows),
        "top_10_slowest_backend_prompts": [
            _row_digest(row) for row in top_backend
        ],
        "top_10_ui_perceived_slow_prompts": [
            _row_digest(row) for row in sorted(
                ui_path_results,
                key=lambda row: _as_float(row.get("ui_total_wall_ms")),
                reverse=True,
            )[:10]
        ],
        "top_10_status_stalls": top_status,
        "top_10_snapshot_stalls": top_snapshot,
        "weather_breakdown": [_weather_digest(row) for row in weather_rows],
        "system_resource_breakdown": [
            _system_resource_digest(row) for row in system_resource_rows
        ],
        "voice_blocking_breakdown": [_voice_digest(row) for row in voice_blocking_rows],
        "anchor_breakdown": [_anchor_digest(row) for row in anchor_rows],
        "snapshot_path_analysis": snapshot_path_analysis or {},
        "root_cause_ranking": [
            {"classification": name, "count": count}
            for name, count in counts.most_common()
        ],
        "recommended_architecture_fixes": _recommended_fixes(counts),
    }
    return sanitize_for_report(summary)


def _row_digest(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_id": row.get("prompt_id"),
        "prompt": row.get("prompt"),
        "mode": row.get("mode"),
        "path": row.get("path"),
        "chat_send_wall_ms": row.get("chat_send_wall_ms"),
        "route_family": row.get("route_family"),
        "expected_posture": row.get("expected_posture"),
        "actual_posture": row.get("actual_posture"),
        "hot_path_budget_exceeded": row.get("hot_path_budget_exceeded"),
        "blocking_live_probe_detected": row.get("blocking_live_probe_detected"),
        "cache_hit": row.get("cache_hit"),
        "async_deferred": row.get("async_deferred"),
        "response_json_bytes": row.get("response_json_bytes"),
        "payload_size_bytes": row.get("payload_size_bytes"),
        "classifications": row.get("classifications", []),
    }


def _weather_digest(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_row_digest(row),
        "route_handler_ms": _timing(row, "route_handler_ms"),
        "job_wait_ms": _timing(
            row,
            "weather_job_wait_ms",
            "job_wait_ms",
            "job_submit_and_wait_ms",
        ),
        "location_lookup_ms": _timing(
            row,
            "weather_location_lookup_ms",
            "location_lookup_ms",
            "location_resolve_ms",
        ),
        "weather_provider_ms": _timing(
            row,
            "weather_provider_call_ms",
            "weather_provider_ms",
            "provider_call_ms",
        ),
        "weather_timeout_ms": _timing(row, "weather_timeout_ms"),
        "weather_tail_classification": classify_weather_tail(row),
    }


def _system_resource_digest(row: dict[str, Any]) -> dict[str, Any]:
    explicit_trace = _has_explicit_system_resource_trace(row)
    return {
        **_row_digest(row),
        "route_handler_ms": _timing(row, "route_handler_ms"),
        "job_wait_ms": _timing(row, "resource_job_wait_ms", "job_wait_ms", "job_collection_ms"),
        "cache_hit": _timing_bool(row, "system_cache_hit", "system_resource_cache_hit") if explicit_trace else None,
        "cache_age_ms": _timing(row, "system_cache_age_ms", "system_resource_cache_age_ms") if explicit_trace else None,
        "freshness_state": _timing_str(row, "system_freshness_state", "system_resource_freshness_state") if explicit_trace else "",
        "deferred": _timing_bool(row, "live_probe_deferred", "system_probe_deferred") if explicit_trace else None,
        "live_refresh_job_id": _timing_raw(row, "live_probe_job_id", "system_live_refresh_job_id"),
        "cpu_probe_ms": _timing(row, "cpu_probe_ms"),
        "resource_status_probe_ms": _timing(row, "resource_probe_ms", "resource_status_probe_ms"),
        "hardware_telemetry_probe_ms": _timing(row, "hardware_telemetry_probe_ms"),
        "network_probe_ms": _timing(row, "network_probe_ms"),
        "power_probe_ms": _timing(row, "power_probe_ms", "battery_probe_ms"),
        "storage_probe_ms": _timing(row, "storage_probe_ms"),
        "system_probe_timeout_ms": _timing(row, "live_probe_timeout_ms", "system_probe_timeout_ms"),
        "system_resource_classification": classify_system_resource_tail(row),
    }


def _voice_digest(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_row_digest(row),
        "voice_output": row.get("voice_output"),
        "status_stalls": status_stalls(row.get("status_samples") or []),
        "event_count": len(row.get("event_stream_events") or []),
    }


def _anchor_digest(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_row_digest(row),
        "anchor_samples": row.get("anchor_samples", [])[:8],
        "anchor_classification": classify_anchor_path(row),
    }


def _recommended_fixes(counts: Counter[str]) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    if counts.get("voice_blocks_event_loop") or counts.get("status_polling_slow"):
        recommendations.append(
            {
                "phase": "Runtime Hot Path Fix",
                "scope": "Move live speaker playback drain and status/event reads off blocking hot paths without changing Core speech authority.",
            }
        )
    if counts.get("snapshot_slow") or counts.get("response_payload_large"):
        recommendations.append(
            {
                "phase": "Ghost Snapshot Diet",
                "scope": "Split Ghost light snapshot/status needs from Deck detail payloads and keep UI polling bounded.",
            }
        )
    if counts.get("provider_or_tool_wait") or counts.get("weather_provider_wait"):
        recommendations.append(
            {
                "phase": "Weather Async/Cache/Timeout Conversion",
                "scope": "Bound weather provider/location waits, report deferred state honestly, and reuse cached location/weather where valid.",
            }
        )
    if (
        counts.get("system_resource_probe_wait")
        or counts.get("hardware_telemetry_wait")
        or counts.get("system_resource_tail_unknown")
    ):
        recommendations.append(
            {
                "phase": "System Resource Cached Telemetry Conversion",
                "scope": "Serve Ghost resource answers from fresh cached telemetry and refresh slow hardware probes in the background.",
            }
        )
    if counts.get("anchor_state_not_propagated") or counts.get("audio_envelope_unavailable"):
        recommendations.append(
            {
                "phase": "Anchor Live State Propagation Fix",
                "scope": "Make active live playback state win visually while preserving backend-owned command truth.",
            }
        )
    return recommendations


def _voice_was_scheduled(row: dict[str, Any]) -> bool:
    voice_output = row.get("voice_output") if isinstance(row.get("voice_output"), dict) else {}
    decision = row.get("voice_speak_decision") if isinstance(row.get("voice_speak_decision"), dict) else {}
    return bool(
        voice_output.get("scheduled")
        or decision.get("voice_service_called")
        or decision.get("speakable")
    )


def request_json(
    client: httpx.Client,
    method: str,
    path_or_url: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    start = time.perf_counter()
    raw = b""
    payload: Any = {}
    error = ""
    status_code = 0
    try:
        response = client.request(method, path_or_url, json=json_body, timeout=timeout)
        status_code = response.status_code
        raw = response.content
        try:
            payload = response.json() if raw else {}
        except Exception as exc:  # pragma: no cover - live defensive path
            error = f"json_parse_failed:{exc}"
        response.raise_for_status()
    except Exception as exc:
        error = error or str(exc)
    return {
        "method": method,
        "path": path_or_url,
        "started_at": utc_now(),
        "wall_ms": perf_ms(start),
        "status_code": status_code,
        "response_bytes": len(raw),
        "json": payload if isinstance(payload, dict) else {"value": payload},
        "error": error,
    }


def extract_chat_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    assistant_message = payload.get("assistant_message")
    if not isinstance(assistant_message, dict):
        return {}
    metadata = assistant_message.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def extract_route_family(metadata: dict[str, Any]) -> str:
    for key in (
        "route_family",
        "intent_family",
        "route",
        "selected_route_family",
    ):
        value = metadata.get(key)
        if value:
            return str(value)
    latency_trace = metadata.get("latency_trace")
    if isinstance(latency_trace, dict):
        for key in ("route_family", "intent_family", "route"):
            value = latency_trace.get(key)
            if value:
                return str(value)
    route_state = metadata.get("route_state")
    if isinstance(route_state, dict):
        return str(route_state.get("family") or route_state.get("route_family") or "")
    return ""


def extract_voice_output(metadata: dict[str, Any]) -> dict[str, Any]:
    value = metadata.get("voice_output")
    return dict(value) if isinstance(value, dict) else {}


def extract_voice_speak_decision(metadata: dict[str, Any]) -> dict[str, Any]:
    voice_output = extract_voice_output(metadata)
    decision = voice_output.get("decision")
    return dict(decision) if isinstance(decision, dict) else {}


def _voice_dict_from_status(status_payload: dict[str, Any]) -> dict[str, Any]:
    voice = status_payload.get("voice")
    return dict(voice) if isinstance(voice, dict) else {}


def extract_anchor_sample(status_payload: dict[str, Any], *, phase: str, wall_ms: float) -> dict[str, Any]:
    voice = _voice_dict_from_status(status_payload)
    flat = _lower_key_map(voice)
    playback = voice.get("playback") if isinstance(voice.get("playback"), dict) else {}
    visualizer = voice.get("visualizer") if isinstance(voice.get("visualizer"), dict) else {}
    anchor = voice.get("anchor") if isinstance(voice.get("anchor"), dict) else {}
    ui = voice.get("ui") if isinstance(voice.get("ui"), dict) else {}

    live_playback_active = bool(
        flat.get("live_playback_active")
        or flat.get("playback_active")
        or str(playback.get("status") or playback.get("active_playback_status") or "").lower()
        in {"started", "playing", "active"}
    )
    streaming_tts_active = bool(
        flat.get("streaming_tts_active")
        or flat.get("streaming_active")
        or flat.get("stream_active")
    )
    speaking_visual_active = bool(
        flat.get("speaking_visual_active")
        or anchor.get("speaking_visual_active")
        or ui.get("speaking_visual_active")
    )
    return {
        "phase": phase,
        "wall_ms": wall_ms,
        "voice_anchor_state": str(
            flat.get("voice_anchor_state")
            or anchor.get("state")
            or ui.get("voice_anchor_state")
            or voice.get("current_voice_state")
            or ""
        ),
        "speaking_visual_active": speaking_visual_active,
        "voice_motion_intensity": _as_float(
            flat.get("voice_motion_intensity") or visualizer.get("motion_intensity")
        ),
        "voice_audio_level": _as_float(flat.get("voice_audio_level") or visualizer.get("audio_level")),
        "voice_smoothed_output_level": _as_float(
            flat.get("voice_smoothed_output_level") or visualizer.get("smoothed_output_level")
        ),
        "voice_audio_reactive_available": flat.get("voice_audio_reactive_available"),
        "voice_audio_reactive_source": str(flat.get("voice_audio_reactive_source") or ""),
        "streaming_tts_active": streaming_tts_active,
        "live_playback_active": live_playback_active,
        "first_audio_started": bool(flat.get("first_audio_started")),
        "active_playback_status": str(
            flat.get("active_playback_status") or playback.get("status") or ""
        ),
    }


def sample_status_once(
    client: httpx.Client,
    *,
    phase: str,
    base_url: str,
) -> dict[str, Any]:
    result = request_json(client, "GET", f"{base_url}/status", timeout=15.0)
    payload = result.get("json") if isinstance(result.get("json"), dict) else {}
    sample = {
        "phase": phase,
        "started_at": result["started_at"],
        "wall_ms": result["wall_ms"],
        "status_code": result["status_code"],
        "response_bytes": result["response_bytes"],
        "error": result["error"],
    }
    sample.update(extract_anchor_sample(payload, phase=phase, wall_ms=result["wall_ms"]))
    return sample


def sample_snapshot_once(
    client: httpx.Client,
    *,
    base_url: str,
    profile: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    path = f"{base_url}/snapshot?{query}" if query else f"{base_url}/snapshot"
    result = request_json(client, "GET", path, timeout=30.0)
    payload = result.get("json") if isinstance(result.get("json"), dict) else {}
    return {
        "profile": profile,
        "started_at": result["started_at"],
        "wall_ms": result["wall_ms"],
        "status_code": result["status_code"],
        "response_bytes": result["response_bytes"],
        "error": result["error"],
        "top_level_keys": sorted(payload.keys())[:32],
    }


class EventStreamCollector:
    def __init__(self, *, base_url: str, session_id: str = "default") -> None:
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.stop_event = threading.Event()
        self.events: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> list[dict[str, Any]]:
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        return list(self.events)

    def _run(self) -> None:
        timeout = httpx.Timeout(connect=5.0, read=None, write=5.0, pool=5.0)
        event_name = "message"
        data_lines: list[str] = []
        last_arrival: float | None = None
        try:
            with httpx.Client(timeout=timeout) as client:
                url = (
                    f"{self.base_url}/events/stream?session_id={self.session_id}"
                    "&cursor=0&replay_limit=8&heartbeat_seconds=1"
                )
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if self.stop_event.is_set():
                            break
                        if line is None:
                            continue
                        text = str(line)
                        if not text:
                            arrival = time.perf_counter()
                            parsed = self._finish_event(event_name, data_lines)
                            if parsed is not None:
                                gap_ms = (
                                    round((arrival - last_arrival) * 1000.0, 3)
                                    if last_arrival is not None
                                    else 0.0
                                )
                                parsed["arrival_at"] = utc_now()
                                parsed["gap_since_previous_ms"] = gap_ms
                                self.events.append(parsed)
                                last_arrival = arrival
                            event_name = "message"
                            data_lines = []
                            continue
                        if text.startswith(":"):
                            continue
                        if text.startswith("event:"):
                            event_name = text.partition(":")[2].strip() or "message"
                        elif text.startswith("data:"):
                            data_lines.append(text.partition(":")[2].lstrip())
        except Exception as exc:  # pragma: no cover - live defensive path
            self.errors.append(str(exc))

    def _finish_event(self, event_name: str, data_lines: list[str]) -> dict[str, Any] | None:
        if not data_lines:
            return None
        try:
            payload = json.loads("\n".join(data_lines))
        except Exception as exc:
            return {"event_name": event_name, "parse_error": str(exc)}
        if not isinstance(payload, dict):
            payload = {"payload": payload}
        return {
            "event_name": event_name,
            "event_type": payload.get("event_type") or payload.get("type"),
            "cursor": payload.get("cursor"),
            "source": payload.get("source") or payload.get("subsystem"),
            "payload_digest": {
                "message": payload.get("message"),
                "severity": payload.get("severity") or payload.get("level"),
                "visibility_scope": payload.get("visibility_scope"),
                "payload_keys": sorted((payload.get("payload") or {}).keys())
                if isinstance(payload.get("payload"), dict)
                else [],
            },
        }


class StatusSampler:
    def __init__(
        self,
        *,
        base_url: str,
        interval_seconds: float = 0.25,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.chat_response_seen = threading.Event()
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def mark_chat_response_seen(self) -> None:
        self.chat_response_seen.set()

    def stop(self) -> list[dict[str, Any]]:
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        return list(self.samples)

    def _run(self) -> None:
        try:
            with httpx.Client() as client:
                while not self.stop_event.is_set():
                    phase = "after_response" if self.chat_response_seen.is_set() else "during_request"
                    sample = sample_status_once(client, phase=phase, base_url=self.base_url)
                    if sample.get("live_playback_active") or sample.get("streaming_tts_active"):
                        sample["phase"] = "during_playback"
                    self.samples.append(sample)
                    self.stop_event.wait(self.interval_seconds)
        except Exception as exc:  # pragma: no cover - live defensive path
            self.errors.append(str(exc))


def set_voice_mode(client: httpx.Client, *, base_url: str, mode: str) -> dict[str, Any]:
    status = request_json(client, "GET", f"{base_url}/status", timeout=10.0)
    voice = _voice_dict_from_status(status.get("json") or {})
    flat_voice = _lower_key_map(voice)
    playback = voice.get("playback") if isinstance(voice.get("playback"), dict) else {}
    should_stop = bool(
        flat_voice.get("live_playback_active")
        or flat_voice.get("streaming_tts_active")
        or flat_voice.get("speaking_visual_active")
        or playback.get("active_playback_interruptible")
    )
    if should_stop:
        request_json(
            client,
            "POST",
            f"{base_url}/voice/output/stop-speaking",
            json_body={"session_id": "default", "reason": "latency_trace_mode_switch"},
            timeout=10.0,
        )
        time.sleep(0.1)
    if mode == "voice_muted":
        path = "/voice/output/mute"
    elif mode == "voice_enabled":
        path = "/voice/output/unmute"
    else:
        return {"skipped": True, "mode": mode}
    return request_json(
        client,
        "POST",
        f"{base_url}{path}",
        json_body={"session_id": "default", "scope": "session", "reason": "latency_trace"},
        timeout=20.0,
    )


def run_direct_prompt(
    *,
    client: httpx.Client,
    base_url: str,
    prompt_spec: dict[str, Any],
    mode: str,
    post_sample_seconds: float,
    sample_snapshot: bool,
) -> dict[str, Any]:
    voice_control = set_voice_mode(client, base_url=base_url, mode=mode)
    status_before = sample_status_once(client, phase="baseline", base_url=base_url)
    snapshot_samples: list[dict[str, Any]] = []
    if sample_snapshot:
        snapshot_samples.append(
            sample_snapshot_once(
                client,
                base_url=base_url,
                profile="ghost_like_before",
                params={
                    "session_id": "default",
                    "event_limit": 5,
                    "job_limit": 5,
                    "note_limit": 5,
                    "history_limit": 5,
                },
            )
        )

    status_sampler = StatusSampler(base_url=base_url)
    event_collector = EventStreamCollector(base_url=base_url)
    status_sampler.start()
    event_collector.start()
    started_at = utc_now()
    chat_started = time.perf_counter()
    response = request_json(
        client,
        "POST",
        f"{base_url}/chat/send",
        json_body={
            "message": prompt_spec["prompt"],
            "session_id": "default",
            "surface_mode": "ghost",
            "active_module": "chartroom",
            "workspace_context": prompt_spec.get("workspace_context", {}),
            "input_context": prompt_spec.get("input_context", {}),
        },
        timeout=75.0,
    )
    chat_send_wall_ms = perf_ms(chat_started)
    status_sampler.mark_chat_response_seen()
    time.sleep(max(0.0, post_sample_seconds))
    status_samples = [status_before, *status_sampler.stop()]
    event_stream_events = event_collector.stop()
    if sample_snapshot:
        snapshot_samples.append(
            sample_snapshot_once(
                client,
                base_url=base_url,
                profile="ghost_like_after",
                params={
                    "session_id": "default",
                    "event_limit": 5,
                    "job_limit": 5,
                    "note_limit": 5,
                    "history_limit": 5,
                },
            )
        )

    payload = response.get("json") if isinstance(response.get("json"), dict) else {}
    metadata = extract_chat_metadata(payload)
    stage_timings_ms = metadata.get("stage_timings_ms")
    latency_trace = metadata.get("latency_trace")
    latency_summary = metadata.get("latency_summary")
    row = {
        "prompt_id": prompt_spec["id"],
        "prompt": prompt_spec["prompt"],
        "category": prompt_spec["category"],
        "mode": mode,
        "path": "direct_backend",
        "started_at": started_at,
        "voice_control": _control_digest(voice_control),
        "http_request_started_at": response.get("started_at"),
        "http_request_wall_ms": response.get("wall_ms"),
        "chat_send_wall_ms": chat_send_wall_ms,
        "chat_status_code": response.get("status_code"),
        "chat_error": response.get("error"),
        "response_json_bytes": response.get("response_bytes", 0),
        "stage_timings_ms": dict(stage_timings_ms) if isinstance(stage_timings_ms, dict) else {},
        "latency_trace": dict(latency_trace) if isinstance(latency_trace, dict) else {},
        "latency_summary": dict(latency_summary) if isinstance(latency_summary, dict) else {},
        "route_family": extract_route_family(metadata),
        "route_handler_subspans": _extract_route_subspans(metadata),
        "job_wait_ms": _timing({"stage_timings_ms": stage_timings_ms}, "job_wait_ms"),
        "provider_weather_location_subspans": _extract_weather_subspans(metadata),
        "system_resource_subspans": _extract_system_resource_subspans(metadata),
        "response_serialization_ms": _timing(
            {"stage_timings_ms": stage_timings_ms},
            "server_response_write_ms",
            "response_serialization_ms",
            "endpoint_return_to_asgi_ms",
        ),
        "voice_output": extract_voice_output(metadata),
        "voice_speak_decision": extract_voice_speak_decision(metadata),
        "voice_scheduling_time_ms": _timing(
            {"stage_timings_ms": stage_timings_ms, "latency_trace": latency_trace},
            "voice_scheduling_ms",
            "core_result_to_tts_start_ms",
        ),
        "tts_first_chunk_ms": _timing(
            {"stage_timings_ms": stage_timings_ms, "latency_trace": latency_trace},
            "tts_stream_first_chunk_ms",
            "voice_first_audio_ms",
            "core_result_to_first_audio_ms",
        ),
        "chat_send_waited_for_voice_completion": _chat_appears_to_wait_for_voice_completion(
            chat_send_wall_ms,
            status_samples,
        ),
        "status_samples": status_samples,
        "snapshot_samples": snapshot_samples,
        "event_stream_events": event_stream_events,
        "event_stream_errors": event_collector.errors,
        "anchor_samples": [
            sample
            for sample in status_samples
            if sample.get("live_playback_active") or sample.get("streaming_tts_active")
        ],
        "classifications": [],
    }
    row.update(enrich_route_posture_fields(row))
    row["classifications"] = classify_row(row)
    return sanitize_for_report(row)


def _extract_route_subspans(metadata: dict[str, Any]) -> dict[str, Any]:
    flat = _lower_key_map(metadata)
    wanted = {}
    for key, value in flat.items():
        if "route" in key and key.endswith("_ms"):
            wanted[key] = value
        elif key in {"triage_ms", "planner_ms", "tool_planning_ms", "route_handler_ms"}:
            wanted[key] = value
    return wanted


def _control_digest(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result.get("json"), dict) else {}
    voice = payload.get("voice") if isinstance(payload.get("voice"), dict) else {}
    return {
        "wall_ms": result.get("wall_ms"),
        "status_code": result.get("status_code"),
        "response_bytes": result.get("response_bytes"),
        "error": result.get("error"),
        "action": payload.get("action"),
        "voice_state": voice.get("voice_anchor_state") or voice.get("current_voice_state"),
        "spoken_output_muted": _lower_key_map(voice).get("spoken_output_muted"),
    }


def _extract_weather_subspans(metadata: dict[str, Any]) -> dict[str, Any]:
    flat = _lower_key_map(metadata)
    wanted = {}
    for key, value in flat.items():
        if any(part in key for part in ("weather", "location", "provider", "cache")):
            if key.endswith("_ms") or key.endswith("_seconds") or key in {"cache_hit", "provider_url"}:
                wanted[key] = value
    if "provider_url" in wanted:
        wanted["provider_url"] = _safe_provider_url(str(wanted["provider_url"]))
    return wanted


def _extract_system_resource_subspans(metadata: dict[str, Any]) -> dict[str, Any]:
    flat = _lower_key_map(metadata)
    wanted = {}
    markers = (
        "system_cache",
        "system_freshness",
        "system_resource",
        "resource_status",
        "resource_probe",
        "system_probe",
        "cpu",
        "hardware_telemetry",
        "network_probe",
        "power_probe",
        "battery_probe",
        "storage_probe",
        "live_probe",
        "live_refresh",
    )
    exact_keys = {
        "system_cache_hit",
        "system_cache_age_ms",
        "system_freshness_state",
        "system_resource_cache_hit",
        "system_resource_freshness_state",
        "system_probe_deferred",
        "system_live_refresh_job_id",
        "live_probe_deferred",
        "live_probe_job_id",
    }
    for key, value in flat.items():
        if key in exact_keys or any(marker in key for marker in markers):
            if (
                key.endswith("_ms")
                or key.endswith("_seconds")
                or key.endswith("_hit")
                or key.endswith("_state")
                or key.endswith("_deferred")
                or key.endswith("_id")
                or key.endswith("_status")
            ):
                wanted[key] = value
    return wanted


def _safe_provider_url(value: str) -> str:
    if "?" in value:
        return value.split("?", 1)[0] + "?[query-redacted]"
    return value


def _chat_appears_to_wait_for_voice_completion(
    chat_wall_ms: float,
    status_samples: list[dict[str, Any]],
) -> bool:
    active_after = any(
        sample.get("phase") in {"after_response", "during_playback"}
        and (sample.get("live_playback_active") or sample.get("streaming_tts_active"))
        for sample in status_samples
    )
    return bool(chat_wall_ms > 1_500.0 and not active_after)


def collect_snapshot_path_analysis(
    *,
    client: httpx.Client,
    base_url: str,
    include_heavy: bool,
) -> dict[str, Any]:
    samples = [
        sample_snapshot_once(
            client,
            base_url=base_url,
            profile="compact",
            params={"session_id": "default", "compact": "true"},
        ),
        sample_snapshot_once(
            client,
            base_url=base_url,
            profile="ghost_like",
            params={
                "session_id": "default",
                "event_limit": 5,
                "job_limit": 5,
                "note_limit": 5,
                "history_limit": 5,
            },
        ),
    ]
    if include_heavy:
        samples.append(
            sample_snapshot_once(
                client,
                base_url=base_url,
                profile="deck_detail_default",
                params={"session_id": "default", "profile": "deck_detail"},
            )
        )
    return {
        "samples": samples,
        "stalls": snapshot_stalls(samples),
        "heavy_snapshot_included": bool(include_heavy),
    }


def run_ui_bridge_prompt(
    *,
    base_url: str,
    prompt: str,
    timeout_seconds: float = 25.0,
) -> dict[str, Any]:
    started = time.perf_counter()
    result: dict[str, Any] = {
        "prompt": prompt,
        "path": "ui_bridge",
        "started_at": utc_now(),
        "events": [],
        "error": "",
    }
    try:
        with httpx.Client() as prep_client:
            request_json(
                prep_client,
                "POST",
                f"{base_url}/voice/output/stop-speaking",
                json_body={"session_id": "default", "reason": "ui_trace_prep"},
                timeout=10.0,
            )
            request_json(
                prep_client,
                "POST",
                f"{base_url}/voice/output/unmute",
                json_body={"session_id": "default", "scope": "session", "reason": "ui_trace_prep"},
                timeout=10.0,
            )
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtCore, QtGui

        from stormhelm.config.loader import load_config
        from stormhelm.ui.bridge import UiBridge
        from stormhelm.ui.client import CoreApiClient
        from stormhelm.ui.controllers.main_controller import MainController

        app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
        config = load_config(project_root=PROJECT_ROOT)
        bridge = UiBridge(config, parent=app)
        client = CoreApiClient(base_url, parent=bridge)
        controller = MainController(config=config, bridge=bridge, client=client)
        del controller

        tick_gaps: list[float] = []
        last_tick = time.perf_counter()
        tick_timer = QtCore.QTimer()
        tick_timer.setInterval(50)

        def tick() -> None:
            nonlocal last_tick
            now = time.perf_counter()
            tick_gaps.append(round((now - last_tick) * 1000.0, 3))
            last_tick = now

        tick_timer.timeout.connect(tick)

        def mark(name: str, payload: Any = None) -> None:
            event = {"name": name, "at_ms": perf_ms(started)}
            if payload is not None:
                event["payload_size"] = len(json.dumps(sanitize_for_report(payload), default=str))
            result["events"].append(event)
            if name == "chat_received":
                QtCore.QTimer.singleShot(3_000, app.quit)

        client.chat_received.connect(lambda payload: mark("chat_received", payload))
        client.snapshot_received.connect(lambda payload: mark("snapshot_received", payload))
        bridge.collectionsChanged.connect(lambda: mark("collections_changed"))
        bridge.statusChanged.connect(lambda: mark("status_changed"))
        bridge.voiceStateChanged.connect(lambda: mark("voice_state_changed", bridge.voiceState))
        bridge.assistantStateChanged.connect(lambda: mark("assistant_state_changed"))

        tick_timer.start()
        client.start_event_stream(session_id="default", cursor=None)
        client.fetch_health()
        client.fetch_snapshot()
        QtCore.QTimer.singleShot(500, lambda: bridge.sendMessage(prompt))
        QtCore.QTimer.singleShot(int(timeout_seconds * 1000), app.quit)
        app.exec()
        tick_timer.stop()
        events = list(result.get("events") or [])
        result["ui_total_wall_ms"] = perf_ms(started)
        result["max_event_loop_gap_ms"] = max(tick_gaps) if tick_gaps else 0.0
        result["event_loop_gap_count_over_250ms"] = sum(1 for gap in tick_gaps if gap >= 250.0)
        result["assistant_state"] = bridge.assistantState
        result["event_counts"] = dict(Counter(str(event.get("name")) for event in events))
        result["milestones_ms"] = _ui_milestones(events)
        result["events_sample"] = events[:40]
        result["events"] = []
        result["voice_state"] = _ui_voice_state_digest(bridge.voiceState)
    except Exception as exc:  # pragma: no cover - live optional path
        result["error"] = str(exc)
        result["ui_total_wall_ms"] = perf_ms(started)
    return sanitize_for_report(result)


def _ui_milestones(events: list[dict[str, Any]]) -> dict[str, Any]:
    milestones: dict[str, Any] = {}
    for event in events:
        name = str(event.get("name") or "")
        milestones.setdefault(name, event.get("at_ms"))
    return milestones


def _ui_voice_state_digest(state: dict[str, Any]) -> dict[str, Any]:
    anchor = state.get("voice_anchor") if isinstance(state.get("voice_anchor"), dict) else {}
    return {
        "voice_state": state.get("voice_state"),
        "voice_current_phase": state.get("voice_current_phase"),
        "voice_core_state": state.get("voice_core_state"),
        "voice_runtime_mode": state.get("voice_runtime_mode"),
        "voice_effective_mode": state.get("voice_effective_mode"),
        "typed_response_speech_enabled": state.get("typed_response_speech_enabled"),
        "speaker_backend_available": state.get("speaker_backend_available"),
        "speaking_visual_active": state.get("speaking_visual_active"),
        "currently_speaking": state.get("currently_speaking"),
        "voice_anchor_state": state.get("voice_anchor_state") or anchor.get("state"),
        "voice_motion_intensity": state.get("voice_motion_intensity") or anchor.get("motion_intensity"),
        "voice_audio_level": state.get("voice_audio_level") or anchor.get("output_level_rms"),
        "voice_smoothed_output_level": state.get("voice_smoothed_output_level")
        or anchor.get("smoothed_output_level"),
        "voice_audio_reactive_available": state.get("voice_audio_reactive_available")
        or anchor.get("audio_reactive_available"),
        "voice_audio_reactive_source": state.get("voice_audio_reactive_source")
        or anchor.get("audio_reactive_source"),
        "streaming_tts_active": anchor.get("streaming_tts_active"),
        "live_playback_active": anchor.get("live_playback_active"),
        "first_audio_started": anchor.get("first_audio_started"),
        "active_playback_status": state.get("active_playback_status"),
    }


def run_voice_doctor() -> dict[str, Any]:
    script = PROJECT_ROOT / "scripts" / "voice_doctor.py"
    try:
        completed = subprocess.run(
            [sys.executable, str(script), "--project-root", str(PROJECT_ROOT)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        payload = json.loads(completed.stdout or "{}")
        if isinstance(payload, dict):
            payload["exit_code"] = completed.returncode
            return sanitize_for_report(payload)
    except Exception as exc:
        return {"error": str(exc)}
    return {"error": "voice_doctor_no_json"}


def run_powershell_json(script: str) -> Any:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; {script}",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    stdout = completed.stdout.strip()
    if not stdout:
        return {"exit_code": completed.returncode, "stderr": completed.stderr.strip()}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": completed.stderr.strip(),
        }


def audit_process_identity(*, client: httpx.Client, base_url: str) -> dict[str, Any]:
    powershell = r"""
$procs = Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|powershell' -and ($_.CommandLine -match 'stormhelm.entrypoints.core|stormhelm.entrypoints.ui|run_core|run_ui') -and ($_.CommandLine -notmatch 'Get-CimInstance Win32_Process') } | ForEach-Object {
    [pscustomobject]@{
        process_id = $_.ProcessId
        parent_process_id = $_.ParentProcessId
        name = $_.Name
        executable_path = $_.ExecutablePath
        command_line = $_.CommandLine
    }
}
$tcp = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{
        local_address = $_.LocalAddress
        local_port = $_.LocalPort
        state = $_.State.ToString()
        owning_process = $_.OwningProcess
    }
}
[pscustomobject]@{ stormhelm_processes = @($procs); tcp_8765 = @($tcp) } | ConvertTo-Json -Depth 8
"""
    os_identity = run_powershell_json(powershell)
    health = request_json(client, "GET", f"{base_url}/health", timeout=10.0)
    status = request_json(client, "GET", f"{base_url}/status", timeout=20.0)
    snapshot = request_json(
        client,
        "GET",
        f"{base_url}/snapshot?session_id=default&event_limit=5&job_limit=5&note_limit=5&history_limit=5",
        timeout=30.0,
    )
    settings = request_json(client, "GET", f"{base_url}/settings", timeout=10.0)
    return sanitize_for_report(
        {
            "os": platform.platform(),
            "base_url": base_url,
            "processes": os_identity,
            "health": _baseline_digest(health),
            "status_baseline": _baseline_digest(status),
            "snapshot_baseline": _baseline_digest(snapshot),
            "runtime_identity": (
                health.get("json", {}).get("runtime_identity")
                if isinstance(health.get("json"), dict)
                else {}
            ),
            "settings_digest": config_gates_from_settings(
                settings.get("json") if isinstance(settings.get("json"), dict) else {}
            ),
        }
    )


def _baseline_digest(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result.get("json"), dict) else {}
    status_value = payload.get("status")
    return {
        "wall_ms": result.get("wall_ms"),
        "status_code": result.get("status_code"),
        "response_bytes": result.get("response_bytes"),
        "error": result.get("error"),
        "pid": payload.get("pid"),
        "status": status_value if isinstance(status_value, str) else None,
        "version": payload.get("version"),
        "runtime_mode": payload.get("runtime_mode"),
    }


def config_gates_from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    voice = settings.get("voice") if isinstance(settings.get("voice"), dict) else {}
    playback = voice.get("playback") if isinstance(voice.get("playback"), dict) else {}
    voice_openai = voice.get("openai") if isinstance(voice.get("openai"), dict) else {}
    openai = settings.get("openai") if isinstance(settings.get("openai"), dict) else {}
    weather = settings.get("weather") if isinstance(settings.get("weather"), dict) else {}
    network = settings.get("network") if isinstance(settings.get("network"), dict) else {}
    ui = settings.get("ui") if isinstance(settings.get("ui"), dict) else {}
    return sanitize_for_report(
        {
            "network": {
                "host": network.get("host"),
                "port": network.get("port"),
                "api_base_url": settings.get("api_base_url"),
            },
            "ui": {"poll_interval_ms": ui.get("poll_interval_ms")},
            "openai": {
                "enabled": openai.get("enabled"),
                "model": openai.get("model"),
                "api_key_present": bool(openai.get("api_key")),
            },
            "voice": {
                "enabled": voice.get("enabled"),
                "mode": voice.get("mode"),
                "spoken_responses_enabled": voice.get("spoken_responses_enabled"),
                "debug_mock_provider": voice.get("debug_mock_provider"),
                "stream_tts_outputs": voice_openai.get("stream_tts_outputs"),
                "tts_live_format": voice_openai.get("tts_live_format"),
                "playback_enabled": playback.get("enabled"),
                "playback_provider": playback.get("provider"),
                "playback_streaming_enabled": playback.get("streaming_enabled"),
                "allow_dev_playback": playback.get("allow_dev_playback"),
            },
            "weather": {
                "enabled": weather.get("enabled"),
                "provider_base_url": _safe_provider_url(str(weather.get("provider_base_url") or "")),
                "timeout_seconds": weather.get("timeout_seconds"),
                "units": weather.get("units"),
            },
            "runtime": settings.get("runtime"),
        }
    )


def write_artifacts(
    *,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    timestamp: str,
) -> Path:
    artifact_dir = ARTIFACT_ROOT / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)
    rows_path = artifact_dir / "rows.jsonl"
    summary_json_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"

    with rows_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(sanitize_for_report(row), sort_keys=True) + "\n")
    summary_json_path.write_text(
        json.dumps(sanitize_for_report(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    summary_md_path.write_text(render_markdown_summary(summary, artifact_dir), encoding="utf-8")
    return artifact_dir


def render_markdown_summary(summary: dict[str, Any], artifact_dir: Path) -> str:
    lines = [
        "# Stormhelm L6.3C Live Runtime Latency Trace",
        "",
        f"- Started: {summary.get('started_at')}",
        f"- Finished: {summary.get('finished_at')}",
        f"- Artifact directory: `{artifact_dir}`",
        f"- Rows: {summary.get('test_matrix', {}).get('row_count')}",
        f"- Modes: {', '.join(summary.get('test_matrix', {}).get('modes', []))}",
        "",
        "## Process Identity",
        "",
        "```json",
        json.dumps(summary.get("process_identity", {}), indent=2, sort_keys=True),
        "```",
        "",
        "## Root Cause Ranking",
        "",
    ]
    ranking = summary.get("root_cause_ranking") or []
    if ranking:
        for item in ranking:
            lines.append(f"- {item.get('classification')}: {item.get('count')}")
    else:
        lines.append("- No slow-path classifications were observed.")
    lines.extend(["", "## Top Backend Prompts", ""])
    for row in summary.get("top_10_slowest_backend_prompts") or []:
        lines.append(
            f"- P{row.get('prompt_id')} `{row.get('mode')}` {row.get('chat_send_wall_ms')} ms: {row.get('prompt')} posture={row.get('actual_posture')}/{row.get('expected_posture')} cache_hit={row.get('cache_hit')} async={row.get('async_deferred')} [{', '.join(row.get('classifications') or [])}]"
        )
    lines.extend(["", "## Voice Enabled Vs Muted", ""])
    for item in summary.get("voice_enabled_vs_muted") or []:
        lines.append(
            f"- {item.get('prompt')}: enabled {item.get('voice_enabled_ms')} ms, muted {item.get('voice_muted_ms')} ms, delta {item.get('delta_ms')} ms [{', '.join(item.get('classification') or [])}]"
        )
    lines.extend(["", "## Weather Breakdown", ""])
    for item in summary.get("weather_breakdown") or []:
        lines.append(
            f"- P{item.get('prompt_id')} `{item.get('mode')}` route {item.get('route_handler_ms')} ms, job wait {item.get('job_wait_ms')} ms, location {item.get('location_lookup_ms')} ms, provider {item.get('weather_provider_ms')} ms [{', '.join(item.get('weather_tail_classification') or [])}]"
        )
    lines.extend(["", "## System Resource Breakdown", ""])
    for item in summary.get("system_resource_breakdown") or []:
        lines.append(
            f"- P{item.get('prompt_id')} `{item.get('mode')}` {item.get('prompt')}: route {item.get('route_handler_ms')} ms, posture={item.get('actual_posture')}/{item.get('expected_posture')} cache_hit={item.get('cache_hit')} age={item.get('cache_age_ms')} ms freshness={item.get('freshness_state') or ''} deferred={item.get('deferred')} cpu={item.get('cpu_probe_ms')} ms resource={item.get('resource_status_probe_ms')} ms hardware={item.get('hardware_telemetry_probe_ms')} ms network={item.get('network_probe_ms')} ms power={item.get('power_probe_ms')} ms storage={item.get('storage_probe_ms')} ms [{', '.join(item.get('system_resource_classification') or [])}]"
        )
    if not summary.get("system_resource_breakdown"):
        lines.append("- No system-resource rows collected in this run.")
    lines.extend(["", "## Top Status Stalls", ""])
    for item in summary.get("top_10_status_stalls") or []:
        lines.append(
            f"- {item.get('phase')} `{item.get('mode')}` {item.get('wall_ms')} ms: {item.get('prompt')} status={item.get('status_code')} error={item.get('error') or ''} anchor={item.get('voice_anchor_state') or ''} live_playback={item.get('live_playback_active')}"
        )
    if not summary.get("top_10_status_stalls"):
        lines.append("- No status stalls over threshold.")

    lines.extend(["", "## Snapshot Path Analysis", ""])
    snapshot_analysis = summary.get("snapshot_path_analysis") or {}
    for item in snapshot_analysis.get("samples") or []:
        lines.append(
            f"- {item.get('profile')}: {item.get('wall_ms')} ms, {item.get('response_bytes')} bytes, status={item.get('status_code')} error={item.get('error') or ''}"
        )
    if not snapshot_analysis.get("samples"):
        lines.append("- No snapshot path samples collected.")

    lines.extend(["", "## Top Snapshot Stalls", ""])
    for item in summary.get("top_10_snapshot_stalls") or []:
        lines.append(
            f"- {item.get('phase')} `{item.get('mode')}` {item.get('wall_ms')} ms: {item.get('prompt')} bytes={item.get('response_bytes')} error={item.get('error') or ''}"
        )
    if not summary.get("top_10_snapshot_stalls"):
        lines.append("- No per-prompt snapshot stalls over threshold.")

    lines.extend(["", "## UI Path Results", ""])
    for item in summary.get("ui_path_results") or []:
        milestones = item.get("milestones_ms") or {}
        chat_ms = milestones.get("chat_received")
        voice_ms = milestones.get("voice_state_changed")
        status_ms = milestones.get("status_changed")
        lines.append(
            f"- {item.get('prompt')}: total {item.get('ui_total_wall_ms')} ms, chat_received={chat_ms}, voice_state_changed={voice_ms}, status_changed={status_ms}, max_event_loop_gap={item.get('max_event_loop_gap_ms')} ms"
        )
    if not summary.get("ui_path_results"):
        lines.append("- No UI bridge paths collected in this run.")

    lines.extend(["", "## Voice Blocking Breakdown", ""])
    for item in summary.get("voice_blocking_breakdown") or []:
        stalls = item.get("status_stalls") or []
        worst_stall = max((float(stall.get("wall_ms") or 0.0) for stall in stalls), default=0.0)
        voice_output = item.get("voice_output") or {}
        decision = voice_output.get("decision") if isinstance(voice_output, dict) else {}
        lines.append(
            f"- P{item.get('prompt_id')} `{item.get('mode')}` {item.get('prompt')}: scheduled={voice_output.get('scheduled')} speakable={decision.get('speakable') if isinstance(decision, dict) else None} worst_status_stall={round(worst_stall, 3)} ms [{', '.join(item.get('classifications') or [])}]"
        )
    if not summary.get("voice_blocking_breakdown"):
        lines.append("- No voice blocking rows classified.")

    lines.extend(["", "## Anchor Breakdown", ""])
    for item in summary.get("anchor_breakdown") or []:
        lines.append(
            f"- P{item.get('prompt_id')} `{item.get('mode')}` {item.get('prompt')}: [{', '.join(item.get('anchor_classification') or [])}]"
        )
    if not summary.get("anchor_breakdown"):
        lines.append("- No direct anchor missing-link classifications were emitted. Anchor state samples remain in rows.jsonl/status samples for manual inspection.")

    lines.extend(["", "## Recommended Fix Phases", ""])
    for item in summary.get("recommended_architecture_fixes") or []:
        lines.append(f"- **{item.get('phase')}**: {item.get('scope')}")
    return "\n".join(lines) + "\n"


def run_matrix(args: argparse.Namespace) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    started_at = utc_now()
    base_url = args.base_url.rstrip("/")
    rows: list[dict[str, Any]] = []
    ui_results: list[dict[str, Any]] = []

    with httpx.Client() as client:
        process_identity = audit_process_identity(client=client, base_url=base_url)
        settings_result = request_json(client, "GET", f"{base_url}/settings", timeout=10.0)
        config_gates = config_gates_from_settings(
            settings_result.get("json") if isinstance(settings_result.get("json"), dict) else {}
        )
        voice_doctor = run_voice_doctor()
        snapshot_path_analysis = collect_snapshot_path_analysis(
            client=client,
            base_url=base_url,
            include_heavy=args.heavy_snapshot,
        )
        if not args.skip_direct:
            prompt_pool = RESOURCE_HOT_PATH_PROMPTS if args.resource_hot_path else PROMPTS
            selected_prompts = (
                prompt_pool[: args.prompt_limit] if args.prompt_limit else prompt_pool
            )
            for prompt_spec in selected_prompts:
                for mode in ("voice_enabled", "voice_muted"):
                    print(
                        f"TRACE prompt={prompt_spec['id']} mode={mode} text={prompt_spec['prompt']}",
                        flush=True,
                    )
                    row = run_direct_prompt(
                        client=client,
                        base_url=base_url,
                        prompt_spec=prompt_spec,
                        mode=mode,
                        post_sample_seconds=args.post_sample_seconds,
                        sample_snapshot=args.sample_snapshot,
                    )
                    rows.append(row)
                    time.sleep(args.between_prompt_seconds)

        if args.ui_bridge_prompts:
            for prompt in args.ui_bridge_prompts:
                print(f"UI_TRACE text={prompt}", flush=True)
                ui_results.append(run_ui_bridge_prompt(base_url=base_url, prompt=prompt))

    finished_at = utc_now()
    summary = build_summary(
        rows=rows,
        process_identity=process_identity,
        config_gates=config_gates,
        voice_doctor=voice_doctor,
        ui_path_results=ui_results,
        started_at=started_at,
        finished_at=finished_at,
        snapshot_path_analysis=snapshot_path_analysis,
    )
    artifact_dir = write_artifacts(rows=rows, summary=summary, timestamp=timestamp)
    print(str(artifact_dir), flush=True)
    return artifact_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trace Stormhelm live runtime latency across backend, voice, status, snapshot, events, and UI bridge paths."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--prompt-limit", type=int, default=0)
    parser.add_argument(
        "--resource-hot-path",
        action="store_true",
        help="Run the focused L6.3D CPU/resource/system hot-path prompt matrix.",
    )
    parser.add_argument("--post-sample-seconds", type=float, default=4.0)
    parser.add_argument("--between-prompt-seconds", type=float, default=0.25)
    parser.add_argument("--sample-snapshot", action="store_true")
    parser.add_argument("--heavy-snapshot", action="store_true")
    parser.add_argument("--skip-direct", action="store_true")
    parser.add_argument(
        "--ui-bridge-prompts",
        nargs="*",
        default=[],
        help="Optional prompts to run through CoreApiClient + UiBridge without QML rendering.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_matrix(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
