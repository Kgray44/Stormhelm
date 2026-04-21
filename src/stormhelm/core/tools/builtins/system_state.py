from __future__ import annotations

from typing import Any

from stormhelm.core.network.formatter import NetworkResponseFormatter
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.system.probe import SystemProbe
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


def _probe(context: ToolContext) -> SystemProbe:
    return context.system_probe or SystemProbe(context.config, preferences=context.preferences)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return None
    return normalized


def _focus_payload(*, module: str, section: str = "overview", state_hint: str = "") -> dict[str, Any]:
    return {
        "action": {
            "type": "workspace_focus",
            "target": "deck",
            "module": module,
            "section": section,
            "state_hint": state_hint,
        }
    }


def _merge_data_with_focus(
    data: dict[str, Any],
    *,
    present_in: str,
    module: str,
    section: str = "overview",
    state_hint: str = "",
) -> dict[str, Any]:
    payload = dict(data)
    if present_in == "deck":
        payload.update(_focus_payload(module=module, section=section, state_hint=state_hint))
    return payload


def _location_permission_guidance(location: dict[str, Any]) -> str:
    reason = str(
        location.get("fallback_reason")
        or location.get("live_reason")
        or location.get("reason")
        or location.get("approximate_reason")
        or ""
    ).strip().lower()
    if any(token in reason for token in {"permission", "denied", "disabled", "consent", "access"}):
        return " For precise device bearings, enable Windows Settings > Privacy & security > Location, or say 'open location settings'."
    return ""


def _has_numeric_signal(value: object) -> bool:
    return isinstance(value, (int, float))


def _format_percent(value: object) -> str | None:
    if not _has_numeric_signal(value):
        return None
    return f"{int(round(float(value)))}%"


def _format_temperature(value: object) -> str | None:
    if not _has_numeric_signal(value):
        return None
    return f"{int(round(float(value)))} C"


def _format_clock(value: object) -> str | None:
    if not _has_numeric_signal(value):
        return None
    return f"{int(round(float(value)))} MHz"


def _format_power(value: object) -> str | None:
    if not _has_numeric_signal(value):
        return None
    return f"{float(value):.1f} W"


def _format_bytes_compact(value: object) -> str | None:
    if not _has_numeric_signal(value):
        return None
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.1f} {units[index]}"


def _format_bytes_ratio(used_bytes: object, total_bytes: object) -> str | None:
    used = _format_bytes_compact(used_bytes)
    total = _format_bytes_compact(total_bytes)
    if used and total:
        return f"{used} of {total}"
    return used or total


def _primary_gpu(data: dict[str, Any]) -> dict[str, Any]:
    gpu = data.get("gpu")
    if isinstance(gpu, list):
        candidates = [item for item in gpu if isinstance(item, dict)]
        if candidates:
            candidates.sort(
                key=lambda adapter: (
                    float(adapter.get("utilization_percent") or 0.0),
                    float(adapter.get("power_w") or 0.0),
                    float(adapter.get("vram_used_bytes") or 0.0),
                    float(adapter.get("temperature_c") or 0.0),
                ),
                reverse=True,
            )
            return candidates[0]
    return {}


def _telemetry_capabilities(data: dict[str, Any]) -> dict[str, Any]:
    capabilities = data.get("capabilities")
    return dict(capabilities) if isinstance(capabilities, dict) else {}


def _telemetry_sources(data: dict[str, Any]) -> dict[str, Any]:
    sources = data.get("sources")
    if isinstance(sources, dict):
        return dict(sources)
    sources = data.get("telemetry_sources")
    return dict(sources) if isinstance(sources, dict) else {}


def _telemetry_freshness(data: dict[str, Any]) -> dict[str, Any]:
    freshness = data.get("freshness")
    if isinstance(freshness, dict):
        return dict(freshness)
    freshness = data.get("telemetry_freshness")
    return dict(freshness) if isinstance(freshness, dict) else {}


def _reason_text(value: object) -> str:
    return str(value or "").replace("_", " ").strip()


def _age_text(value: object) -> str | None:
    if not _has_numeric_signal(value):
        return None
    seconds = max(int(round(float(value))), 0)
    if seconds <= 5:
        return "just now"
    if seconds < 60:
        return f"{seconds} seconds ago"
    minutes = max(int(round(seconds / 60.0)), 1)
    return f"{minutes} minute{'s' if minutes != 1 else ''} ago"


def _source_provider(source: object, fallback: str) -> str:
    if isinstance(source, dict):
        provider = str(source.get("provider") or "").strip()
        if provider:
            return provider
    return fallback


def _metric_source_map(data: dict[str, Any]) -> dict[str, Any]:
    sources = _telemetry_sources(data)
    metrics = sources.get("metrics")
    return dict(metrics) if isinstance(metrics, dict) else {}


def _resource_metric_keys(*, focus: str, metric: str) -> list[str]:
    mapping = {
        ("cpu", "usage"): ["cpu.utilization_percent"],
        ("cpu", "temperature"): ["cpu.package_temperature_c"],
        ("cpu", "clock"): ["cpu.effective_clock_mhz", "cpu.base_clock_mhz"],
        ("cpu", "power"): ["cpu.package_power_w"],
        ("gpu", "usage"): ["gpu.utilization_percent"],
        ("gpu", "temperature"): ["gpu.temperature_c", "gpu.hotspot_temperature_c"],
        ("gpu", "memory"): ["gpu.vram_used_bytes", "gpu.vram_total_bytes"],
        ("gpu", "power"): ["gpu.power_w"],
        ("gpu", "clock"): ["gpu.core_clock_mhz", "gpu.memory_clock_mhz"],
        ("ram", "usage"): [],
        ("ram", "free"): [],
        ("ram", "pressure"): [],
        ("overview", "overview"): ["cpu.utilization_percent", "gpu.utilization_percent"],
    }
    return mapping.get((focus, metric), [])


def _power_metric_keys(metric: str) -> list[str]:
    mapping = {
        "overview": ["power.battery_percent", "power.instant_draw_w", "power.health_percent"],
        "level": ["power.battery_percent"],
        "charging": ["power.battery_percent", "power.charge_rate_w"],
        "eta": ["power.time_to_full_seconds", "power.time_to_empty_seconds"],
        "power_draw": ["power.instant_draw_w"],
        "drain_rate": ["power.discharge_rate_w", "power.instant_draw_w"],
        "time_to_empty": ["power.time_to_empty_seconds"],
    }
    return mapping.get(metric, [])


def _preferred_metric_source(metric_map: dict[str, Any], metric_keys: list[str]) -> dict[str, Any]:
    for metric_key in metric_keys:
        source = metric_map.get(metric_key)
        if isinstance(source, dict):
            return source
    return {}


def _resource_metric_label(*, focus: str, metric: str) -> str:
    labels = {
        ("overview", "overview"): "live resource telemetry",
        ("cpu", "usage"): "CPU usage",
        ("cpu", "temperature"): "CPU temperature",
        ("cpu", "clock"): "CPU clock telemetry",
        ("cpu", "power"): "CPU package power",
        ("gpu", "usage"): "GPU usage",
        ("gpu", "temperature"): "GPU temperature",
        ("gpu", "memory"): "GPU VRAM telemetry",
        ("gpu", "power"): "GPU power telemetry",
        ("gpu", "clock"): "GPU clock telemetry",
        ("ram", "usage"): "current memory usage",
        ("ram", "free"): "free memory",
        ("ram", "pressure"): "memory pressure",
    }
    return labels.get((focus, metric), f"{focus.upper()} telemetry")


def _resource_metric_present(data: dict[str, Any], *, focus: str, metric: str) -> bool:
    cpu = data.get("cpu", {}) if isinstance(data.get("cpu"), dict) else {}
    memory = data.get("memory", {}) if isinstance(data.get("memory"), dict) else {}
    gpu = _primary_gpu(data)

    if focus == "overview":
        return any(
            (
                _has_numeric_signal(cpu.get("utilization_percent")),
                _has_numeric_signal(memory.get("used_bytes")) and _has_numeric_signal(memory.get("total_bytes")),
                _has_numeric_signal(gpu.get("utilization_percent")),
            )
        )
    if focus == "cpu":
        if metric in {"usage", "overview"}:
            return _has_numeric_signal(cpu.get("utilization_percent")) or _has_numeric_signal(cpu.get("package_temperature_c"))
        if metric == "temperature":
            return _has_numeric_signal(cpu.get("package_temperature_c"))
        if metric == "clock":
            return _has_numeric_signal(cpu.get("effective_clock_mhz"))
        if metric == "power":
            return _has_numeric_signal(cpu.get("package_power_w"))
    if focus == "gpu":
        if metric in {"usage", "overview"}:
            return _has_numeric_signal(gpu.get("utilization_percent")) or _has_numeric_signal(gpu.get("temperature_c"))
        if metric == "temperature":
            return _has_numeric_signal(gpu.get("temperature_c"))
        if metric == "memory":
            return _has_numeric_signal(gpu.get("vram_used_bytes")) or _has_numeric_signal(gpu.get("vram_total_bytes"))
        if metric == "power":
            return _has_numeric_signal(gpu.get("power_w"))
        if metric == "clock":
            return _has_numeric_signal(gpu.get("core_clock_mhz")) or _has_numeric_signal(gpu.get("memory_clock_mhz"))
    if focus == "ram":
        if metric in {"usage", "overview", "pressure"}:
            return _has_numeric_signal(memory.get("used_bytes")) and _has_numeric_signal(memory.get("total_bytes"))
        if metric == "free":
            return _has_numeric_signal(memory.get("free_bytes"))
    return False


def _resource_metric_contract(data: dict[str, Any], *, focus: str, metric: str) -> dict[str, Any]:
    capabilities = _telemetry_capabilities(data)
    sources = _telemetry_sources(data)
    metric_sources = _metric_source_map(data)
    freshness = _telemetry_freshness(data)
    helper_source = sources.get("helper") if isinstance(sources.get("helper"), dict) else {}
    domain_key = "memory" if focus == "ram" else focus
    domain_source = sources.get(domain_key) if isinstance(sources.get(domain_key), dict) else {}
    metric_source = _preferred_metric_source(metric_sources, _resource_metric_keys(focus=focus, metric=metric))
    label = _resource_metric_label(focus=focus, metric=metric)
    helper_reachable = bool(capabilities.get("helper_reachable"))
    helper_installed = bool(capabilities.get("helper_installed"))
    sample_age = freshness.get("sample_age_seconds")
    provider = _source_provider(metric_source, _source_provider(domain_source, _source_provider(helper_source, "system_probe_floor")))
    capability_key = {
        "cpu": "cpu_deep_telemetry_available",
        "gpu": "gpu_deep_telemetry_available",
    }.get(focus)
    domain_supported = True if capability_key is None else bool(capabilities.get(capability_key))
    available = _resource_metric_present(data, focus=focus, metric=metric) or bool(metric_source.get("available"))
    unsupported_reason = None

    if not available:
        exact_reason = str(metric_source.get("unsupported_reason") or "").strip()
        if exact_reason:
            unsupported_reason = exact_reason
        elif focus == "ram":
            unsupported_reason = f"{label} isn't exposed by the current OS memory snapshot."
        elif helper_installed and not helper_reachable:
            helper_reason = _reason_text(freshness.get("reason") or helper_source.get("detail") or "helper_unreachable")
            unsupported_reason = (
                f"{label} is unavailable because the helper telemetry path is unreachable"
                f"{f' ({helper_reason})' if helper_reason else ''}. Stormhelm is on the coarse probe floor for this metric."
            )
        elif helper_reachable and not domain_supported:
            unsupported_reason = f"{label} isn't supported by the active helper/provider path on this machine."
        elif helper_reachable:
            unsupported_reason = f"{label} isn't present in the latest helper-backed sample."
        else:
            unsupported_reason = f"{label} isn't exposed by the current probe floor."

    return {
        "requested_focus": focus,
        "requested_metric": metric,
        "label": label,
        "available": available,
        "provider": provider,
        "helper_installed": helper_installed,
        "helper_reachable": helper_reachable,
        "helper_state": str(helper_source.get("state") or ("reachable" if helper_reachable else "unavailable")).strip() or "unavailable",
        "sample_age_seconds": sample_age,
        "sample_age_label": _age_text(sample_age),
        "sampling_tier": freshness.get("sampling_tier"),
        "unsupported_reason": unsupported_reason,
    }


def _power_metric_contract(status: dict[str, Any], *, metric: str) -> dict[str, Any]:
    capabilities = dict(status.get("telemetry_capabilities", {})) if isinstance(status.get("telemetry_capabilities"), dict) else {}
    sources = dict(status.get("telemetry_sources", {})) if isinstance(status.get("telemetry_sources"), dict) else {}
    metric_sources = dict(sources.get("metrics", {})) if isinstance(sources.get("metrics"), dict) else {}
    freshness = dict(status.get("telemetry_freshness", {})) if isinstance(status.get("telemetry_freshness"), dict) else {}
    helper_source = sources.get("helper") if isinstance(sources.get("helper"), dict) else {}
    power_source = sources.get("power") if isinstance(sources.get("power"), dict) else {}
    metric_source = _preferred_metric_source(metric_sources, _power_metric_keys(metric))
    helper_reachable = bool(capabilities.get("helper_reachable"))
    helper_installed = bool(capabilities.get("helper_installed"))
    provider = _source_provider(metric_source, _source_provider(power_source, _source_provider(helper_source, "system_probe_floor")))
    sample_age = freshness.get("sample_age_seconds")
    label = {
        "overview": "power status",
        "level": "battery percentage",
        "charging": "charge state",
        "eta": "battery projection",
        "power_draw": "battery draw",
        "drain_rate": "battery drain rate",
        "time_to_empty": "time-to-empty projection",
    }.get(metric, metric.replace("_", " "))

    available = bool(status.get("available"))
    unsupported_reason = None
    exact_reason = str(metric_source.get("unsupported_reason") or "").strip()
    if metric == "level" and status.get("battery_percent") is None:
        unsupported_reason = exact_reason or "Battery percentage isn't exposed by the current power provider."
    elif metric == "eta" and status.get("time_to_full_seconds") is None and status.get("time_to_empty_seconds") is None and status.get("seconds_remaining") is None:
        if exact_reason:
            unsupported_reason = exact_reason
        elif helper_installed and not helper_reachable:
            helper_reason = _reason_text(freshness.get("reason") or helper_source.get("detail") or "helper_unreachable")
            unsupported_reason = (
                "A reliable battery ETA is unavailable because the helper telemetry path is unreachable"
                f"{f' ({helper_reason})' if helper_reason else ''}."
            )
        else:
            unsupported_reason = "This machine is not exposing a reliable battery ETA right now."
    elif metric in {"power_draw", "drain_rate"} and not any(
        _has_numeric_signal(status.get(key))
        for key in ("instant_power_draw_watts", "rolling_power_draw_watts", "discharge_rate_watts", "charge_rate_watts")
    ):
        if exact_reason:
            unsupported_reason = exact_reason
        elif helper_installed and not helper_reachable:
            helper_reason = _reason_text(freshness.get("reason") or helper_source.get("detail") or "helper_unreachable")
            unsupported_reason = (
                "Live battery draw is unavailable because the helper telemetry path is unreachable"
                f"{f' ({helper_reason})' if helper_reason else ''}."
            )
        elif helper_reachable and not bool(capabilities.get("power_current_available")):
            unsupported_reason = "The helper is reachable, but current-sense battery telemetry is not supported on this machine."
        else:
            unsupported_reason = "Windows is not exposing a reliable live battery-draw reading on this machine."

    return {
        "requested_metric": metric,
        "label": label,
        "available": available,
        "provider": provider,
        "helper_installed": helper_installed,
        "helper_reachable": helper_reachable,
        "helper_state": str(helper_source.get("state") or ("reachable" if helper_reachable else "unavailable")).strip() or "unavailable",
        "sample_age_seconds": sample_age,
        "sample_age_label": _age_text(sample_age),
        "sampling_tier": freshness.get("sampling_tier"),
        "unsupported_reason": unsupported_reason,
    }


def _power_overview_summary(status: dict[str, Any]) -> str:
    percent = status.get("battery_percent")
    ac_line = str(status.get("ac_line_status", "unknown")).strip().lower() or "unknown"
    ac_text = "on AC" if ac_line == "online" else "on battery" if ac_line == "offline" else f"with AC line {ac_line}"
    draw = status.get("rolling_power_draw_watts")
    draw_label = "avg draw"
    if not _has_numeric_signal(draw):
        draw = status.get("instant_power_draw_watts") or status.get("discharge_rate_watts") or status.get("charge_rate_watts")
        draw_label = "draw"
    health = status.get("health_percent")
    wear = status.get("wear_percent")
    eta_seconds = status.get("time_to_full_seconds") if ac_line == "online" else status.get("time_to_empty_seconds") or status.get("seconds_remaining")

    parts = []
    if percent is not None:
        parts.append(f"Power is holding at {percent}% {ac_text}.")
    else:
        parts.append(f"Power bearings are live {ac_text}.")
    if _has_numeric_signal(draw):
        parts.append(f"Current {draw_label} is {float(draw):.1f} W.")
    if isinstance(eta_seconds, int):
        minutes = max(int(eta_seconds // 60), 0)
        if ac_line == "online":
            parts.append(f"About {minutes} more minute{'s' if minutes != 1 else ''} to full.")
        else:
            parts.append(f"About {minutes} more minute{'s' if minutes != 1 else ''} remaining.")
    if _has_numeric_signal(health):
        parts.append(f"Battery health is {int(round(float(health)))}%.")
    elif _has_numeric_signal(wear):
        parts.append(f"Battery wear is {int(round(float(wear)))}%.")
    return " ".join(parts)


def _resource_unavailable_summary(data: dict[str, Any], *, focus: str, metric: str) -> str:
    contract = _resource_metric_contract(data, focus=focus, metric=metric)
    return str(contract.get("unsupported_reason") or "Live resource telemetry isn't available here.")


def _resource_identity_summary(data: dict[str, Any], *, focus: str) -> str:
    cpu = data.get("cpu", {}) if isinstance(data.get("cpu"), dict) else {}
    memory = data.get("memory", {}) if isinstance(data.get("memory"), dict) else {}
    gpu = _primary_gpu(data)

    if focus == "cpu":
        name = str(cpu.get("name", "")).strip()
        return f"CPU is {name}." if name else "CPU identity isn't available here."
    if focus == "gpu":
        name = str(gpu.get("name", "")).strip()
        return f"GPU is {name}." if name else "GPU identity isn't available here."
    if focus == "ram":
        total = _format_bytes_compact(memory.get("total_bytes"))
        return f"Installed memory is {total}." if total else "Memory capacity isn't available here."

    parts: list[str] = []
    cpu_name = str(cpu.get("name", "")).strip()
    gpu_name = str(gpu.get("name", "")).strip()
    total = _format_bytes_compact(memory.get("total_bytes"))
    if cpu_name:
        parts.append(f"CPU is {cpu_name}")
    if gpu_name:
        parts.append(f"GPU is {gpu_name}")
    if total:
        parts.append(f"memory is {total}")
    if not parts:
        return "Hardware identity isn't available here."
    return ". ".join(parts) + "."


def _resource_telemetry_summary(data: dict[str, Any], *, focus: str, metric: str) -> str:
    cpu = data.get("cpu", {}) if isinstance(data.get("cpu"), dict) else {}
    memory = data.get("memory", {}) if isinstance(data.get("memory"), dict) else {}
    gpu = _primary_gpu(data)

    if focus == "cpu":
        if metric in {"usage", "overview"}:
            usage = _format_percent(cpu.get("utilization_percent"))
            if usage:
                summary = f"CPU usage is {usage} right now."
                if metric == "overview":
                    temperature = _format_temperature(cpu.get("package_temperature_c"))
                    if temperature:
                        summary += f" CPU temperature is {temperature}."
                return summary
            if metric == "overview":
                temperature = _format_temperature(cpu.get("package_temperature_c"))
                if temperature:
                    return f"CPU temperature is {temperature} right now."
            return _resource_unavailable_summary(data, focus="cpu", metric="usage")
        if metric == "temperature":
            temperature = _format_temperature(cpu.get("package_temperature_c"))
            if temperature:
                return f"CPU temperature is {temperature} right now."
            return _resource_unavailable_summary(data, focus="cpu", metric="temperature")
        if metric == "clock":
            clock = _format_clock(cpu.get("effective_clock_mhz"))
            if clock:
                return f"CPU clock is {clock} right now."
            return _resource_unavailable_summary(data, focus="cpu", metric="clock")
        if metric == "power":
            power = _format_power(cpu.get("package_power_w"))
            if power:
                return f"CPU package power is {power} right now."
            return _resource_unavailable_summary(data, focus="cpu", metric="power")

    if focus == "gpu":
        if metric in {"usage", "overview"}:
            usage = _format_percent(gpu.get("utilization_percent"))
            if usage:
                summary = f"GPU usage is {usage} right now."
                if metric == "overview":
                    vram = _format_bytes_ratio(gpu.get("vram_used_bytes"), gpu.get("vram_total_bytes"))
                    if vram:
                        summary += f" VRAM use is {vram}."
                    elif _format_temperature(gpu.get("temperature_c")):
                        summary += f" GPU temperature is {_format_temperature(gpu.get('temperature_c'))}."
                return summary
            if metric == "overview":
                temperature = _format_temperature(gpu.get("temperature_c"))
                if temperature:
                    return f"GPU temperature is {temperature} right now."
            return _resource_unavailable_summary(data, focus="gpu", metric="usage")
        if metric == "temperature":
            temperature = _format_temperature(gpu.get("temperature_c"))
            if temperature:
                return f"GPU temperature is {temperature} right now."
            return _resource_unavailable_summary(data, focus="gpu", metric="temperature")
        if metric == "memory":
            vram = _format_bytes_ratio(gpu.get("vram_used_bytes"), gpu.get("vram_total_bytes"))
            if vram:
                return f"GPU memory use is {vram} right now."
            return _resource_unavailable_summary(data, focus="gpu", metric="memory")
        if metric == "power":
            power = _format_power(gpu.get("power_w"))
            if power:
                return f"GPU power draw is {power} right now."
            return _resource_unavailable_summary(data, focus="gpu", metric="power")
        if metric == "clock":
            core_clock = _format_clock(gpu.get("core_clock_mhz"))
            memory_clock = _format_clock(gpu.get("memory_clock_mhz"))
            if core_clock and memory_clock:
                return f"GPU clocks are {core_clock} core and {memory_clock} memory right now."
            if core_clock:
                return f"GPU core clock is {core_clock} right now."
            if memory_clock:
                return f"GPU memory clock is {memory_clock} right now."
            return _resource_unavailable_summary(data, focus="gpu", metric="clock")

    if focus == "ram":
        total = memory.get("total_bytes")
        used = memory.get("used_bytes")
        free = memory.get("free_bytes")
        if metric in {"usage", "overview"}:
            ratio = _format_bytes_ratio(used, total)
            if ratio:
                summary = f"Memory usage is {ratio} right now."
                if metric == "overview":
                    free_text = _format_bytes_compact(free)
                    if free_text:
                        summary += f" {free_text} is still free."
                return summary
            return _resource_unavailable_summary(data, focus="ram", metric="usage")
        if metric == "free":
            free_text = _format_bytes_compact(free)
            if free_text:
                return f"Free memory is {free_text} right now."
            return _resource_unavailable_summary(data, focus="ram", metric="free")
        if metric == "pressure":
            total_value = float(total or 0)
            used_value = float(used or 0)
            if total_value > 0:
                pressure = _format_percent((used_value / total_value) * 100)
                if pressure:
                    return f"Memory usage is {pressure} right now."
            return _resource_unavailable_summary(data, focus="ram", metric="pressure")

    cpu_usage = _format_percent(cpu.get("utilization_percent"))
    memory_ratio = _format_bytes_ratio(memory.get("used_bytes"), memory.get("total_bytes"))
    gpu_usage = _format_percent(gpu.get("utilization_percent"))
    parts = []
    if cpu_usage:
        parts.append(f"CPU {cpu_usage}")
    if memory_ratio:
        parts.append(f"memory {memory_ratio}")
    if gpu_usage:
        parts.append(f"GPU {gpu_usage}")
    if parts:
        return "Current resource usage: " + ", ".join(parts) + "."
    return "Live resource telemetry isn't available here."


def _usage_level_label(percent: object) -> str | None:
    if not _has_numeric_signal(percent):
        return None
    value = float(percent)
    if value >= 85.0:
        return "high"
    if value >= 45.0:
        return "moderate"
    return "low"


def _thermal_level_label(temperature_c: object, *, focus: str) -> str | None:
    if not _has_numeric_signal(temperature_c):
        return None
    value = float(temperature_c)
    threshold = 85.0 if focus == "gpu" else 90.0
    if value >= threshold:
        return "high"
    if value >= threshold - 10.0:
        return "elevated"
    return "steady"


def _resource_diagnostic_summary(data: dict[str, Any], *, focus: str, metric: str) -> str:
    cpu = data.get("cpu", {}) if isinstance(data.get("cpu"), dict) else {}
    memory = data.get("memory", {}) if isinstance(data.get("memory"), dict) else {}
    gpu = _primary_gpu(data)

    if focus == "gpu":
        if metric == "temperature":
            temperature = _format_temperature(gpu.get("temperature_c"))
            level = _thermal_level_label(gpu.get("temperature_c"), focus="gpu")
            if temperature and level:
                return f"GPU temperature is {level} at {temperature}."
            return _resource_unavailable_summary(data, focus="gpu", metric="temperature")
        usage = _format_percent(gpu.get("utilization_percent"))
        level = _usage_level_label(gpu.get("utilization_percent"))
        if usage and level:
            return f"GPU load is {level} at {usage} right now."
        return _resource_unavailable_summary(data, focus="gpu", metric="usage")

    if focus == "cpu":
        if metric == "temperature":
            temperature = _format_temperature(cpu.get("package_temperature_c"))
            level = _thermal_level_label(cpu.get("package_temperature_c"), focus="cpu")
            if temperature and level:
                return f"CPU temperature is {level} at {temperature}."
            return _resource_unavailable_summary(data, focus="cpu", metric="temperature")
        usage = _format_percent(cpu.get("utilization_percent"))
        level = _usage_level_label(cpu.get("utilization_percent"))
        if usage and level:
            return f"CPU load is {level} at {usage} right now."
        return _resource_unavailable_summary(data, focus="cpu", metric="usage")

    if focus == "ram":
        total = float(memory.get("total_bytes") or 0)
        used = float(memory.get("used_bytes") or 0)
        if total > 0:
            used_percent = (used / total) * 100
            level = "high" if used_percent >= 85.0 else "elevated" if used_percent >= 70.0 else "steady"
            return f"Memory pressure is {level} at {int(round(used_percent))}% in use right now."
        return _resource_unavailable_summary(data, focus="ram", metric="pressure")

    return _resource_telemetry_summary(data, focus="overview", metric="overview")


class MachineStatusTool(BaseTool):
    name = "machine_status"
    display_name = "Machine Status"
    description = "Return Stormhelm's current machine identity, OS details, time zone, and local clock."
    category = "system"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "enum": ["overview", "identity", "time"], "default": "overview"},
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        focus = str(arguments.get("focus", "overview")).strip().lower() or "overview"
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {"focus": focus, "present_in": present_in}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).machine_status()
        persona = PersonaContract(context.config)
        focus = arguments["focus"]
        if focus == "time":
            summary = persona.report(
                f"Local time is {str(data.get('local_time', '')).replace('T', ' ')} with timezone {data.get('timezone', 'unknown')}."
            )
        elif focus == "identity":
            summary = persona.report(
                f"Systems report {data.get('machine_name', 'this machine')} running {data.get('system', 'unknown')} {data.get('release', '')}."
            )
        else:
            summary = persona.report(
                f"Systems report {data.get('machine_name', 'this machine')} on {data.get('platform', 'unknown platform')} in {data.get('timezone', 'unknown')}."
            )
        payload = _merge_data_with_focus(data, present_in=arguments["present_in"], module="systems", state_hint="machine")
        return ToolResult(success=True, summary=summary, data=payload)


class PowerStatusTool(BaseTool):
    name = "power_status"
    display_name = "Power Status"
    description = "Return current battery and AC power bearings when available."
    category = "system"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "enum": ["overview", "level", "charging", "eta"], "default": "overview"},
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        focus = str(arguments.get("focus", "overview")).strip().lower() or "overview"
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {"focus": focus, "present_in": present_in}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).power_status()
        persona = PersonaContract(context.config)
        focus = arguments["focus"]
        contract = _power_metric_contract(data, metric=focus)
        if not data.get("available"):
            summary = persona.report(str(contract.get("unsupported_reason") or "Power bearings are not available on this machine."))
        elif focus == "charging":
            if data.get("battery_percent") is None:
                summary = persona.report(
                    str(contract.get("unsupported_reason") or f"AC line is {data.get('ac_line_status', 'unknown')}, but the battery percentage is not available.")
                )
            else:
                summary = persona.report(
                    f"Battery is {data.get('battery_percent')}% and AC line is {data.get('ac_line_status', 'unknown')}."
                )
        elif focus == "eta":
            seconds_remaining = data.get("time_to_empty_seconds") or data.get("seconds_remaining")
            if data.get("ac_line_status") == "online" and data.get("time_to_full_seconds") is not None:
                minutes = max(int(int(data.get("time_to_full_seconds") or 0) // 60), 0)
                summary = persona.report(f"Charging course projects about {minutes} more minute{'s' if minutes != 1 else ''} to full.")
            elif data.get("ac_line_status") == "online":
                summary = persona.report(str(contract.get("unsupported_reason") or "Power bearings show the battery percentage and charging state, but this machine is not exposing a reliable time-to-full estimate."))
            elif isinstance(seconds_remaining, int):
                minutes = max(int(seconds_remaining // 60), 0)
                summary = persona.report(f"Battery endurance is holding for about {minutes} more minute{'s' if minutes != 1 else ''}.")
            else:
                summary = persona.report(str(contract.get("unsupported_reason") or "Power bearings show the battery percentage, but the system is not exposing a reliable remaining-time estimate."))
        elif focus == "level":
            if data.get("battery_percent") is None:
                summary = persona.report(str(contract.get("unsupported_reason") or "Battery percentage is not available from this machine right now."))
            else:
                summary = persona.report(f"Power is holding at {data.get('battery_percent')}%.")
        else:
            if data.get("battery_percent") is None:
                summary = persona.report(str(contract.get("unsupported_reason") or f"AC line is {data.get('ac_line_status', 'unknown')} and no battery percentage is available."))
            else:
                summary = persona.report(_power_overview_summary(data))
        payload = _merge_data_with_focus(data, present_in=arguments["present_in"], module="systems", state_hint="power")
        payload["metric_contract"] = contract
        return ToolResult(success=True, summary=summary, data=payload)


class PowerProjectionTool(BaseTool):
    name = "power_projection"
    display_name = "Power Projection"
    description = "Return deterministic power draw and threshold projection bearings for charging, discharge, and target battery levels."
    category = "power"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["time_to_percent", "time_to_empty", "power_draw", "drain_rate"],
                    "default": "time_to_percent",
                },
                "target_percent": {"type": "integer", "minimum": 0, "maximum": 100},
                "assume_unplugged": {"type": "boolean", "default": False},
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        metric = str(arguments.get("metric", "time_to_percent")).strip().lower() or "time_to_percent"
        target_percent = arguments.get("target_percent")
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {
            "metric": metric,
            "target_percent": int(target_percent) if isinstance(target_percent, (int, float)) else None,
            "assume_unplugged": bool(arguments.get("assume_unplugged", False)),
            "present_in": present_in,
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        probe = _probe(context)
        data = probe.power_projection(
            metric=arguments["metric"],
            target_percent=arguments["target_percent"],
            assume_unplugged=arguments["assume_unplugged"],
        )
        status_snapshot = probe.power_status()
        persona = PersonaContract(context.config)
        metric = arguments["metric"]
        notes = [str(note).strip() for note in data.get("notes", []) if str(note).strip()]
        minutes = data.get("projection_minutes")
        target_percent = arguments["target_percent"]
        assume_unplugged = arguments["assume_unplugged"]
        contract = _power_metric_contract(status_snapshot, metric=metric)

        if not data.get("available"):
            summary = persona.report(str(contract.get("unsupported_reason") or "Power projection bearings are unavailable on this machine right now."))
        elif metric == "power_draw":
            if data.get("power_draw_watts") is not None:
                summary = persona.report(f"Current power draw is holding around {data.get('power_draw_watts')} W.")
            else:
                summary = persona.report(str(contract.get("unsupported_reason") or "Stormhelm can see the current charge state, but this machine is not exposing a reliable live power-draw reading."))
        elif metric == "drain_rate":
            if data.get("power_draw_watts") is not None:
                summary = persona.report(f"Battery drain is running at about {data.get('power_draw_watts')} W.")
            else:
                summary = persona.report(str(contract.get("unsupported_reason") or "Stormhelm can see the current charge state, but this machine is not exposing a reliable drain-rate reading yet."))
        elif metric == "time_to_empty":
            if data.get("reliable") and isinstance(minutes, int):
                summary = persona.report(f"If the present discharge holds, battery endurance is about {minutes} more minute{'s' if minutes != 1 else ''}.")
            else:
                detail = notes[0] if notes else str(contract.get("unsupported_reason") or "The system is not exposing a reliable time-to-empty estimate.")
                summary = persona.report(detail)
        else:
            if data.get("reliable") and isinstance(minutes, int) and isinstance(target_percent, int):
                if assume_unplugged:
                    summary = persona.report(
                        f"If you unplug now, power should cross {target_percent}% in about {minutes} minute{'s' if minutes != 1 else ''}."
                    )
                elif target_percent == 100:
                    summary = persona.report(f"Charging course projects about {minutes} minute{'s' if minutes != 1 else ''} until full.")
                else:
                    summary = persona.report(
                        f"Power should reach {target_percent}% in about {minutes} minute{'s' if minutes != 1 else ''} on the current course."
                    )
            else:
                detail = notes[0] if notes else str(contract.get("unsupported_reason") or "Stormhelm can see the current charge and power state, but not a reliable threshold projection yet.")
                summary = persona.report(detail)
        payload = _merge_data_with_focus(
            data,
            present_in=arguments["present_in"],
            module="systems",
            section="overview",
            state_hint="power_projection",
        )
        payload["metric_contract"] = contract
        payload["status_snapshot"] = status_snapshot
        return ToolResult(success=True, summary=summary, data=payload)


class ResourceStatusTool(BaseTool):
    name = "resource_status"
    display_name = "Resource Status"
    description = "Return CPU, RAM, and GPU bearings for the current machine."
    category = "system"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "enum": ["overview", "cpu", "ram", "gpu"], "default": "overview"},
                "query_kind": {"type": "string", "enum": ["telemetry", "identity", "diagnostic"], "default": "telemetry"},
                "metric": {
                    "type": "string",
                    "enum": ["overview", "identity", "usage", "temperature", "memory", "power", "clock", "free", "pressure"],
                    "default": "overview",
                },
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        focus = str(arguments.get("focus", "overview")).strip().lower() or "overview"
        query_kind = str(arguments.get("query_kind", "telemetry")).strip().lower() or "telemetry"
        metric = str(arguments.get("metric", "overview")).strip().lower() or "overview"
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {"focus": focus, "query_kind": query_kind, "metric": metric, "present_in": present_in}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).resource_status()
        persona = PersonaContract(context.config)
        focus = arguments["focus"]
        query_kind = arguments["query_kind"]
        metric = arguments["metric"]

        if query_kind == "identity":
            summary = persona.report(_resource_identity_summary(data, focus=focus))
        elif query_kind == "diagnostic":
            summary = persona.report(_resource_diagnostic_summary(data, focus=focus, metric=metric))
        else:
            summary = persona.report(_resource_telemetry_summary(data, focus=focus, metric=metric))
        payload = _merge_data_with_focus(data, present_in=arguments["present_in"], module="systems", state_hint="resources")
        payload["metric_contract"] = _resource_metric_contract(data, focus=focus, metric=metric)
        return ToolResult(success=True, summary=summary, data=payload)


class StorageStatusTool(BaseTool):
    name = "storage_status"
    display_name = "Storage Status"
    description = "Return disk and free-space bearings for mounted local drives."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).storage_status()
        drives = data.get("drives", [])
        persona = PersonaContract(context.config)
        if not drives:
            summary = persona.report("Storage bearings are unavailable right now.")
        else:
            primary = drives[0]
            free_text = _format_bytes_compact(primary.get("free_bytes"))
            total_text = _format_bytes_compact(primary.get("total_bytes"))
            used_percent: str | None = None
            if _has_numeric_signal(primary.get("used_bytes")) and _has_numeric_signal(primary.get("total_bytes")) and float(primary.get("total_bytes") or 0) > 0:
                used_percent = _format_percent((float(primary.get("used_bytes") or 0) / float(primary.get("total_bytes") or 0)) * 100)
            if used_percent and free_text and total_text:
                summary = persona.report(
                    f"Storage usage is {used_percent} on {primary.get('drive', 'the primary drive')} with {free_text} free of {total_text}."
                )
            elif free_text and total_text:
                summary = persona.report(
                    f"Storage shows {free_text} free on {primary.get('drive', 'the primary drive')} out of {total_text}."
                )
            else:
                summary = persona.report("Storage usage isn't available here.")
        return ToolResult(success=True, summary=summary, data=data)


class NetworkStatusTool(BaseTool):
    name = "network_status"
    display_name = "Network Status"
    description = "Return current host and network interface bearings."
    category = "system"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "enum": ["overview", "network", "ip", "signal"], "default": "overview"},
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        focus = str(arguments.get("focus", "overview")).strip().lower() or "overview"
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {"focus": focus, "present_in": present_in}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).network_status()
        persona = PersonaContract(context.config)
        summary = persona.report(NetworkResponseFormatter().format_status_response(data, focus=arguments["focus"]))
        payload = _merge_data_with_focus(data, present_in=arguments["present_in"], module="systems", state_hint="network")
        return ToolResult(success=True, summary=summary, data=payload)


class NetworkThroughputTool(BaseTool):
    name = "network_throughput"
    display_name = "Network Throughput"
    description = "Return current observed network download and upload throughput, or the exact reason it cannot be sampled."
    category = "network"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "enum": ["internet_speed", "download_speed", "upload_speed"], "default": "internet_speed"},
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        metric = str(arguments.get("metric", "internet_speed")).strip().lower() or "internet_speed"
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {"metric": metric, "present_in": present_in}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).network_throughput(metric=arguments["metric"])
        persona = PersonaContract(context.config)
        summary = persona.report(NetworkResponseFormatter().format_throughput_response(data))
        payload = _merge_data_with_focus(
            data,
            present_in=arguments["present_in"],
            module="systems",
            section="network",
            state_hint="network-throughput",
        )
        payload["metric_contract"] = {
            "requested_metric": arguments["metric"],
            "provider": data.get("source"),
            "state": data.get("state"),
            "sample_age_seconds": data.get("last_sample_age_seconds"),
            "sample_age_label": _age_text(data.get("last_sample_age_seconds")),
            "sample_window_seconds": data.get("sample_window_seconds"),
            "unsupported_code": data.get("unsupported_code"),
            "unsupported_reason": data.get("unsupported_reason"),
        }
        return ToolResult(success=True, summary=summary, data=payload)


class NetworkDiagnosisTool(BaseTool):
    name = "network_diagnosis"
    display_name = "Network Diagnosis"
    description = "Interpret recent network telemetry into local-link, upstream, DNS, and instability bearings."
    category = "network"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "enum": ["overview", "attribution", "packet_loss", "jitter", "latency", "dns", "history"],
                    "default": "overview",
                },
                "diagnostic_burst": {"type": "boolean", "default": False},
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        focus = str(arguments.get("focus", "overview")).strip().lower() or "overview"
        diagnostic_burst = bool(arguments.get("diagnostic_burst", False))
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {
            "focus": focus,
            "diagnostic_burst": diagnostic_burst,
            "present_in": present_in,
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).network_diagnosis(
            focus=arguments["focus"],
            diagnostic_burst=arguments["diagnostic_burst"],
        )
        persona = PersonaContract(context.config)
        analysis = data.get("assessment", {}) if isinstance(data.get("assessment"), dict) else {}
        summary = persona.report(NetworkResponseFormatter().format_diagnostic_response(analysis, data))
        payload = _merge_data_with_focus(data, present_in=arguments["present_in"], module="systems", section="network", state_hint="network-diagnosis")
        return ToolResult(success=True, summary=summary, data=payload)


class LocationStatusTool(BaseTool):
    name = "location_status"
    display_name = "Location Status"
    description = "Resolve Stormhelm's current or saved location bearings with explicit source handling."
    category = "location"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["auto", "current", "home", "named"], "default": "auto"},
                "named_location": {"type": "string"},
                "named_location_type": {"type": "string", "enum": ["auto", "saved_alias", "place_query"], "default": "auto"},
                "allow_home_fallback": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        mode = str(arguments.get("mode", "auto")).strip().lower() or "auto"
        allow_home_fallback = bool(arguments.get("allow_home_fallback", True))
        named_location = _optional_string(arguments.get("named_location"))
        named_location_type = str(arguments.get("named_location_type", "auto")).strip().lower() or "auto"
        return {
            "mode": mode,
            "named_location": named_location,
            "named_location_type": named_location_type,
            "allow_home_fallback": allow_home_fallback,
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).resolve_best_location_for_request(
            mode=arguments["mode"],
            named_location=arguments["named_location"],
            named_location_type=arguments["named_location_type"],
            allow_home_fallback=arguments["allow_home_fallback"],
        )
        persona = PersonaContract(context.config)
        guidance = _location_permission_guidance(data)
        if not data.get("resolved"):
            requested_name = str(data.get("requested_name") or "").strip()
            home = _probe(context).resolve_location(mode="home", allow_home_fallback=False)
            if arguments["mode"] == "current" and home.get("resolved"):
                failure = str(data.get("live_reason") or data.get("reason") or "").replace("_", " ").strip()
                summary = persona.report(
                    f"Current live location is unavailable right now{f' ({failure})' if failure else ''}. Saved home bearings are held for {home.get('label', 'the configured home location')}.{guidance}"
                )
            elif requested_name and data.get("reason") in {"saved_named_location_not_found", "queried_place_not_found"}:
                summary = persona.report(f"Stormhelm could not resolve location bearings for {requested_name}.")
            else:
                summary = persona.report(f"Location bearings are unavailable right now.{guidance}")
            return ToolResult(success=True, summary=summary, data=data)

        if data.get("used_home_fallback"):
            failure = str(data.get("fallback_reason") or "").replace("_", " ").strip()
            summary = persona.report(
                f"Live device bearings were unavailable{f' ({failure})' if failure else ''}, so Stormhelm fell back to the saved home location at {data.get('label', 'the configured home location')}.{guidance}"
            )
        elif data.get("source") == "saved_home":
            summary = persona.report(f"Using saved home bearings for {data.get('label', 'the configured home location')}.")
        elif data.get("source") == "saved_named":
            summary = persona.report(f"Using saved location bearings for {data.get('label', data.get('name', 'the requested location'))}.")
        elif data.get("source") == "queried_place":
            summary = persona.report(f"Using requested place bearings for {data.get('label', data.get('name', 'the requested location'))}.")
        elif data.get("source") == "device_live":
            summary = persona.report(f"Current live device location resolves to {data.get('label', 'the current area')}.")
        elif data.get("source") == "approximate_device":
            summary = persona.report(f"Current position resolves approximately from device bearings near {data.get('label', 'the current area')}.")
        elif data.get("source") == "ip_estimate":
            summary = persona.report(
                f"Only an IP-based estimate is available right now, placing you roughly near {data.get('label', 'the current area')}.{guidance}"
            )
        else:
            summary = persona.report(f"Current location resolves to {data.get('label', 'the current area')}.")
        return ToolResult(success=True, summary=summary, data=data)


class SavedLocationsTool(BaseTool):
    name = "saved_locations"
    display_name = "Saved Locations"
    description = "Return saved home bearings and any named saved locations held in Stormhelm memory."
    category = "location"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["all", "home"], "default": "all"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        mode = str(arguments.get("mode", "all")).strip().lower() or "all"
        return {"mode": mode}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        probe = _probe(context)
        persona = PersonaContract(context.config)
        if arguments["mode"] == "home":
            home = probe.get_saved_home_location()
            if not home:
                return ToolResult(
                    success=True,
                    summary=persona.report("Stormhelm is not holding a saved home location yet."),
                    data={"locations": []},
                )
            return ToolResult(
                success=True,
                summary=persona.report(f"Saved home bearings are set to {home.get('label', 'the configured home location')}."),
                data={"locations": [home]},
            )

        locations = probe.get_saved_locations()
        if not locations:
            summary = persona.report("Stormhelm is not holding any saved location bearings yet.")
        else:
            summary = persona.report(f"Stormhelm is holding {len(locations)} saved location bearing{'s' if len(locations) != 1 else ''}.")
        return ToolResult(success=True, summary=summary, data={"locations": locations})


class SaveLocationTool(BaseTool):
    name = "save_location"
    display_name = "Save Location"
    description = "Save the current resolved location as home bearings or under a named saved-location entry."
    category = "location"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": ["home", "named"], "default": "home"},
                "name": {"type": "string"},
                "source_mode": {"type": "string", "enum": ["current", "home"], "default": "current"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        target = str(arguments.get("target", "home")).strip().lower() or "home"
        source_mode = str(arguments.get("source_mode", "current")).strip().lower() or "current"
        name = str(arguments.get("name", "")).strip() or None
        return {
            "target": target,
            "source_mode": source_mode,
            "name": name,
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        probe = _probe(context)
        persona = PersonaContract(context.config)
        target = arguments["target"]
        source_mode = arguments["source_mode"]
        resolved = probe.resolve_best_location_for_request(
            mode="home" if source_mode == "home" else "current",
            allow_home_fallback=(source_mode != "current"),
        )
        if not resolved.get("resolved"):
            return ToolResult(
                success=True,
                summary=persona.report("Stormhelm could not secure location bearings strongly enough to save them yet."),
                data=resolved,
            )

        if target == "home":
            saved = probe.save_home_location(
                label=str(resolved.get("label") or "Saved home"),
                latitude=float(resolved.get("latitude")),
                longitude=float(resolved.get("longitude")),
                timezone=str(resolved.get("timezone") or "").strip() or None,
                address_text=str(resolved.get("address_text") or "").strip() or None,
                source=str(resolved.get("source") or source_mode),
                approximate=bool(resolved.get("approximate", False)),
            )
            return ToolResult(
                success=True,
                summary=persona.report(f"Home bearings are now set to {saved.get('label', 'the saved home location')}."),
                data={"saved_location": saved},
            )

        name = arguments["name"]
        if not name:
            return ToolResult(
                success=True,
                summary=persona.report("Stormhelm needs a location name before it can store a named bearing."),
                data={"saved_location": None},
            )
        saved = probe.save_named_location(
            name=name,
            label=str(resolved.get("label") or name),
            latitude=float(resolved.get("latitude")),
            longitude=float(resolved.get("longitude")),
            timezone=str(resolved.get("timezone") or "").strip() or None,
            address_text=str(resolved.get("address_text") or "").strip() or None,
            source=str(resolved.get("source") or source_mode),
            approximate=bool(resolved.get("approximate", False)),
        )
        return ToolResult(
            success=True,
            summary=persona.report(f"Saved location '{saved.get('name', name)}' is now on watch at {saved.get('label', name)}."),
            data={"saved_location": saved},
        )


class WeatherCurrentTool(BaseTool):
    name = "weather_current"
    display_name = "Current Weather"
    description = "Resolve location bearings, fetch structured current weather, and optionally open a weather page in Stormhelm or externally."
    category = "weather"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "location_mode": {"type": "string", "enum": ["auto", "current", "home", "named"], "default": "auto"},
                "named_location": {"type": "string"},
                "named_location_type": {"type": "string", "enum": ["auto", "saved_alias", "place_query"], "default": "auto"},
                "allow_home_fallback": {"type": "boolean", "default": True},
                "forecast_target": {"type": "string", "enum": ["current", "tomorrow", "tonight", "weekend"], "default": "current"},
                "open_target": {"type": "string", "enum": ["none", "deck", "external"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        location_mode = str(arguments.get("location_mode", "auto")).strip().lower() or "auto"
        named_location = _optional_string(arguments.get("named_location"))
        named_location_type = str(arguments.get("named_location_type", "auto")).strip().lower() or "auto"
        allow_home_fallback = bool(arguments.get("allow_home_fallback", True))
        forecast_target = str(arguments.get("forecast_target", "current")).strip().lower() or "current"
        open_target = str(arguments.get("open_target", "none")).strip().lower() or "none"
        return {
            "location_mode": location_mode,
            "named_location": named_location,
            "named_location_type": named_location_type,
            "allow_home_fallback": allow_home_fallback,
            "forecast_target": forecast_target,
            "open_target": open_target,
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).weather_status(
            location_mode=arguments["location_mode"],
            named_location=arguments["named_location"],
            named_location_type=arguments["named_location_type"],
            allow_home_fallback=arguments["allow_home_fallback"],
            forecast_target=arguments["forecast_target"],
            units=context.config.weather.units,
        )
        persona = PersonaContract(context.config)
        if not data.get("available"):
            reason = data.get("reason", "weather_unavailable")
            guidance = _location_permission_guidance(data.get("location", {}) if isinstance(data.get("location"), dict) else {})
            location = data.get("location", {}) if isinstance(data.get("location"), dict) else {}
            requested_name = str(location.get("requested_name") or "").strip()
            if reason == "location_unavailable":
                summary = persona.report(
                    f"Weather bearings are unavailable because Stormhelm could not secure a current or saved location.{guidance}"
                )
            elif reason == "queried_place_not_found" and requested_name:
                summary = persona.report(f"Stormhelm could not resolve weather bearings for {requested_name}.")
            else:
                summary = persona.report("Weather bearings are unavailable right now.")
            return ToolResult(success=True, summary=summary, data=data)

        location = data.get("location", {})
        temperature = data.get("temperature", {})
        condition = data.get("condition", {})
        label = str(location.get("label", "the current area"))
        source = str(location.get("source", "current"))
        source_text = (
            f"Live device bearings were unavailable, so Stormhelm used saved home bearings for {label}."
            if location.get("used_home_fallback")
            else
            f"Using saved home bearings for {label}."
            if source == "saved_home"
            else f"Using saved location bearings for {label}."
            if source == "saved_named"
            else f"Using requested place bearings for {label}."
            if source == "queried_place"
            else f"Using live device location for {label}."
            if source == "device_live"
            else f"Using approximate device location near {label}."
            if source == "approximate_device"
            else f"Using an IP-based location estimate near {label}."
            if source == "ip_estimate"
            else f"Using approximate current location near {label}."
            if source == "approximate"
            else f"Using current location for {label}."
        )
        source_text = f"{source_text}{_location_permission_guidance(location)}"
        forecast_target = arguments["forecast_target"]
        if forecast_target == "tomorrow":
            summary = persona.report(
                f"Tomorrow's weather for {label} is lining up around {condition.get('summary', 'unsettled conditions')} with a high near {temperature.get('high')} {temperature.get('unit', '')} and a low near {temperature.get('low')} {temperature.get('unit', '')}. {source_text}"
            )
        elif forecast_target == "tonight":
            summary = persona.report(
                f"Tonight over {label}, the field is tracking {condition.get('summary', 'unsettled conditions')} near {temperature.get('current')} {temperature.get('unit', '')}. {source_text}"
            )
        elif forecast_target == "weekend":
            summary = persona.report(
                f"The weekend forecast around {label} points to {condition.get('summary', 'unsettled conditions')} with temperatures ranging from {temperature.get('low')} to {temperature.get('high')} {temperature.get('unit', '')}. {source_text}"
            )
        else:
            summary = persona.report(
                f"Current weather for {label} is {temperature.get('current')} {temperature.get('unit', '')} with {condition.get('summary', 'unsettled conditions')}. {source_text}"
            )

        payload = dict(data)
        open_target = arguments["open_target"]
        deck_url = str(data.get("deck_url", "")).strip()
        if open_target == "deck" and deck_url:
            payload["action"] = {
                "type": "workspace_open",
                "target": "deck",
                "module": "browser",
                "section": "references",
                "item": {
                    "kind": "browser",
                    "viewer": "browser",
                    "title": f"Weather | {label}",
                    "subtitle": source_text,
                    "url": deck_url,
                },
            }
        elif open_target == "external" and deck_url:
            payload["action"] = {
                "type": "open_external",
                "kind": "url",
                "url": deck_url,
                "title": f"Weather | {label}",
            }
        return ToolResult(success=True, summary=summary, data=payload)


class ActiveAppsTool(BaseTool):
    name = "active_apps"
    display_name = "Active Apps"
    description = "Return the current visible desktop applications and windows."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).active_apps()
        apps = data.get("applications", [])
        persona = PersonaContract(context.config)
        if apps:
            summary = persona.report(f"Watch has {len(apps)} visible application windows in view.")
        else:
            summary = persona.report("Watch does not currently see any visible application windows.")
        return ToolResult(success=True, summary=summary, data=data)


class AppControlTool(BaseTool):
    name = "app_control"
    display_name = "App Control"
    description = "Launch, focus, close, quit, force-quit, or restart a local desktop application."
    category = "system"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["launch", "focus", "minimize", "maximize", "restore", "close", "quit", "force_quit", "restart"],
                },
                "app_name": {"type": "string"},
                "app_path": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": str(arguments.get("action", "")).strip().lower(),
            "app_name": _optional_string(arguments.get("app_name")),
            "app_path": _optional_string(arguments.get("app_path")),
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).app_control(
            action=arguments["action"],
            app_name=arguments.get("app_name"),
            app_path=arguments.get("app_path"),
        )
        persona = PersonaContract(context.config)
        action = str(data.get("action") or arguments["action"]).replace("_", " ").strip()
        label = str(data.get("window_title") or data.get("process_name") or arguments.get("app_name") or arguments.get("app_path") or "the requested app").strip()
        if data.get("success"):
            if action == "focus":
                summary = persona.report(f"Focused {label}.")
            elif action == "minimize":
                summary = persona.report(f"Minimized {label}.")
            elif action == "maximize":
                summary = persona.report(f"Maximized {label}.")
            elif action == "restore":
                summary = persona.report(f"Restored {label}.")
            elif action == "close":
                summary = persona.report(f"Closed {label}.")
            elif action == "quit":
                summary = persona.report(f"Quit {label}.")
            elif action == "force quit":
                summary = persona.report(f"Force-quit {label}.")
            elif action == "restart":
                summary = persona.report(f"Restarted {label}.")
            else:
                summary = persona.report(f"Launched {label}.")
        else:
            reason = str(data.get("reason") or "").replace("_", " ").strip()
            if reason in {"app not found", "app not running"}:
                summary = persona.report(f"{label} was not running.")
            elif reason == "missing target":
                summary = persona.report("Need an app name or path.")
            elif reason == "no matching window found":
                summary = persona.report(f"No matching {label} window was found.")
            elif reason == "no matching process found":
                summary = persona.report(f"No matching {label} process was found.")
            elif reason == "multiple matches":
                summary = persona.report(f"Found multiple {label} matches; need the target clarified.")
            elif reason == "graceful close unavailable":
                summary = persona.report(f"Found {label}, but graceful close was unavailable.")
            elif reason == "process termination denied":
                summary = persona.report(f"Found {label}, but process termination was denied.")
            elif reason == "window process unresolved":
                summary = persona.report(f"Found the {label} window, but couldn't resolve its process.")
            elif reason == "builtin app target unresolved":
                summary = persona.report(f"Force-quit is supported here, but I couldn't resolve a running {label} process.")
            elif reason == "capability unavailable":
                summary = persona.report("That control capability isn't available in this environment.")
            elif reason == "partial process termination":
                summary = persona.report(f"Only some matching {label} processes were terminated.")
            else:
                summary = persona.report(f"Couldn't {action} {label}.")
        return ToolResult(success=bool(data.get("success")), summary=summary, data=data)


class WindowStatusTool(BaseTool):
    name = "window_status"
    display_name = "Window Status"
    description = "Return the current focused window, visible windows, and monitor bearings."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).window_status()
        windows = data.get("windows", [])
        focused = data.get("focused_window") or {}
        persona = PersonaContract(context.config)
        if focused:
            label = str(focused.get("window_title") or focused.get("process_name") or "the focused window").strip()
            summary = persona.report(f"Focused window is {label}.")
        elif windows:
            summary = persona.report(f"Window watch sees {len(windows)} visible windows.")
        else:
            summary = persona.report("No visible windows are in view.")
        return ToolResult(success=True, summary=summary, data=data)


class WindowControlTool(BaseTool):
    name = "window_control"
    display_name = "Window Control"
    description = "Move, resize, snap, focus, or reposition windows deterministically."
    category = "system"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "focus",
                        "move",
                        "resize",
                        "move_by",
                        "resize_by",
                        "snap_left",
                        "snap_right",
                        "maximize",
                        "minimize",
                        "restore",
                        "move_to_monitor",
                    ],
                },
                "app_name": {"type": "string"},
                "target_mode": {"type": "string", "enum": ["app", "focused"]},
                "monitor_index": {"type": "integer", "minimum": 1},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "width": {"type": "integer", "minimum": 100},
                "height": {"type": "integer", "minimum": 100},
                "delta_x": {"type": "integer"},
                "delta_y": {"type": "integer"},
                "delta_width": {"type": "integer"},
                "delta_height": {"type": "integer"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": str(arguments.get("action", "")).strip().lower(),
            "app_name": _optional_string(arguments.get("app_name")),
            "target_mode": str(arguments.get("target_mode", "app")).strip().lower() or "app",
            "monitor_index": int(arguments["monitor_index"]) if isinstance(arguments.get("monitor_index"), (int, float)) else None,
            "x": int(arguments["x"]) if isinstance(arguments.get("x"), (int, float)) else None,
            "y": int(arguments["y"]) if isinstance(arguments.get("y"), (int, float)) else None,
            "width": int(arguments["width"]) if isinstance(arguments.get("width"), (int, float)) else None,
            "height": int(arguments["height"]) if isinstance(arguments.get("height"), (int, float)) else None,
            "delta_x": int(arguments["delta_x"]) if isinstance(arguments.get("delta_x"), (int, float)) else None,
            "delta_y": int(arguments["delta_y"]) if isinstance(arguments.get("delta_y"), (int, float)) else None,
            "delta_width": int(arguments["delta_width"]) if isinstance(arguments.get("delta_width"), (int, float)) else None,
            "delta_height": int(arguments["delta_height"]) if isinstance(arguments.get("delta_height"), (int, float)) else None,
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).window_control(**arguments)
        persona = PersonaContract(context.config)
        action = str(data.get("action") or arguments["action"]).replace("_", " ").strip()
        label = str(data.get("window_title") or data.get("process_name") or arguments.get("app_name") or "the window").strip()
        if data.get("success"):
            if action == "snap right":
                summary = persona.report(f"Snapped {label} right.")
            elif action == "snap left":
                summary = persona.report(f"Snapped {label} left.")
            elif action == "move to monitor":
                summary = persona.report(f"Moved {label} to monitor {data.get('monitor_index')}.")
            elif action == "move":
                summary = persona.report(f"Moved {label}.")
            elif action == "resize":
                summary = persona.report(f"Resized {label}.")
            elif action == "move by":
                summary = persona.report(f"Moved {label}.")
            elif action == "resize by":
                summary = persona.report(f"Resized {label}.")
            elif action == "focus":
                summary = persona.report(f"Focused {label}.")
            else:
                summary = persona.report(f"{action.capitalize()}d {label}.")
        else:
            reason = str(data.get("reason") or "").replace("_", " ").strip()
            if reason in {"window not found", "focused window unavailable"}:
                summary = persona.report(f"Couldn't find {label}.")
            elif reason == "monitor not found":
                summary = persona.report("That monitor isn't available.")
            elif reason == "unsupported action":
                summary = persona.report("That window action isn't available.")
            else:
                summary = persona.report(f"Couldn't {action} {label}.")
        return ToolResult(success=bool(data.get("success")), summary=summary, data=data)


class SystemControlTool(BaseTool):
    name = "system_control"
    display_name = "System Control"
    description = "Run safe core computer controls like volume, lock, settings pages, and system tools."
    category = "system"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "mute",
                        "unmute",
                        "volume_up",
                        "volume_down",
                        "set_volume",
                        "brightness_up",
                        "brightness_down",
                        "set_brightness",
                        "lock",
                        "sleep_display",
                        "toggle_wifi",
                        "toggle_bluetooth",
                        "open_task_manager",
                        "open_device_manager",
                        "open_resource_monitor",
                        "open_settings_page",
                    ],
                },
                "value": {"type": "integer", "minimum": 0, "maximum": 100},
                "state": {"type": "string", "enum": ["on", "off"]},
                "target": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": str(arguments.get("action", "")).strip().lower(),
            "value": int(arguments["value"]) if isinstance(arguments.get("value"), (int, float)) else None,
            "state": _optional_string(arguments.get("state")),
            "target": _optional_string(arguments.get("target")),
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = _probe(context).system_control(**arguments)
        persona = PersonaContract(context.config)
        action = str(data.get("action") or arguments["action"]).replace("_", " ").strip()
        if data.get("success"):
            if action == "open task manager":
                summary = persona.report("Opened Task Manager.")
            elif action == "open device manager":
                summary = persona.report("Opened Device Manager.")
            elif action == "open resource monitor":
                summary = persona.report("Opened Resource Monitor.")
            elif action == "open settings page":
                target = str(arguments.get("target") or "settings").strip()
                summary = persona.report(f"Opened {target} settings.")
            elif action == "toggle wifi":
                summary = persona.report(f"Turned Wi-Fi {str(data.get('state') or arguments.get('state') or '').strip() or 'on'}.")
            elif action == "toggle bluetooth":
                summary = persona.report(f"Turned Bluetooth {str(data.get('state') or arguments.get('state') or '').strip() or 'on'}.")
            elif action == "set volume":
                summary = persona.report(f"Set volume to {data.get('value', arguments.get('value'))}%.")
            elif action == "volume up":
                summary = persona.report("Raised the volume.")
            elif action == "volume down":
                summary = persona.report("Lowered the volume.")
            elif action == "set brightness":
                summary = persona.report(f"Set brightness to {data.get('value', arguments.get('value'))}%.")
            elif action == "brightness up":
                summary = persona.report("Raised the brightness.")
            elif action == "brightness down":
                summary = persona.report("Lowered the brightness.")
            elif action == "sleep display":
                summary = persona.report("Slept the display.")
            elif action == "lock":
                summary = persona.report("Locked the computer.")
            elif action == "mute":
                summary = persona.report("Muted the volume.")
            elif action == "unmute":
                summary = persona.report("Unmuted the volume.")
            else:
                summary = persona.report(f"{action.capitalize()}.")
        else:
            reason = str(data.get("reason") or "").replace("_", " ").strip()
            if reason == "unsupported":
                summary = persona.report(f"{action.capitalize()} isn't available here.")
            elif reason == "adapter not found":
                summary = persona.report("Stormhelm couldn't find the Wi-Fi adapter.")
            else:
                summary = persona.report(f"Couldn't {action}.")
        return ToolResult(success=bool(data.get("success")), summary=summary, data=data)


class ControlCapabilitiesTool(BaseTool):
    name = "control_capabilities"
    display_name = "Control Capabilities"
    description = "Return which deterministic control actions Stormhelm supports on this machine."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).control_capabilities()
        persona = PersonaContract(context.config)
        summary = persona.report("Control capabilities are ready.")
        return ToolResult(success=True, summary=summary, data=data)


class RecentFilesTool(BaseTool):
    name = "recent_files"
    display_name = "Recent Files"
    description = "Return recently modified files from Stormhelm's allowlisted local bearings."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).recent_files()
        files = data.get("files", [])
        persona = PersonaContract(context.config)
        if files:
            summary = persona.report(f"Recent file bearings recovered {len(files)} local items from the current watch.")
        else:
            summary = persona.report("Recent file bearings are empty right now.")
        return ToolResult(success=True, summary=summary, data=data)
