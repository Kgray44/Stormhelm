from __future__ import annotations

import ctypes
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil
import subprocess
import sys
from time import monotonic
from typing import Any

from stormhelm.config.models import AppConfig


HELPER_PROVIDER_NAME = "stormhelm_hardware_helper"
NATIVE_PROVIDER_NAME = "windows_native"
HWINFO_PROVIDER_NAME = "hwinfo_enrichment"
NVIDIA_SMI_PROVIDER_NAME = "nvidia_smi"
LIBRE_HARDWARE_MONITOR_PROVIDER_NAME = "libre_hardware_monitor"


def helper_cache_ttl_seconds(config: AppConfig, sampling_tier: str) -> float:
    tier = str(sampling_tier or "active").strip().lower()
    if tier == "burst":
        return max(float(config.hardware_telemetry.burst_cache_ttl_seconds), 0.0)
    if tier == "idle":
        return max(float(config.hardware_telemetry.idle_cache_ttl_seconds), 0.0)
    return max(float(config.hardware_telemetry.active_cache_ttl_seconds), 0.0)


def build_disabled_snapshot(*, sampling_tier: str = "idle", reason: str = "disabled") -> dict[str, Any]:
    snapshot = _empty_snapshot(sampling_tier=sampling_tier)
    snapshot["capabilities"].update(
        {
            "helper_installed": False,
            "helper_reachable": False,
            "cpu_deep_telemetry_available": False,
            "gpu_deep_telemetry_available": False,
            "thermal_sensor_availability": False,
            "power_current_available": False,
            "hwinfo_enrichment_available": False,
            "hwinfo_enrichment_active": False,
            "nvidia_smi_available": False,
            "libre_hardware_monitor_available": False,
        }
    )
    snapshot["freshness"]["reason"] = reason
    snapshot["sources"]["helper"] = {"provider": HELPER_PROVIDER_NAME, "state": "disabled", "detail": reason}
    return snapshot


def build_helper_unreachable_snapshot(
    *,
    sampling_tier: str = "active",
    reason: str,
    installed: bool = True,
    debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = _empty_snapshot(sampling_tier=sampling_tier)
    snapshot["capabilities"].update(
        {
            "helper_installed": bool(installed),
            "helper_reachable": False,
            "cpu_deep_telemetry_available": False,
            "gpu_deep_telemetry_available": False,
            "thermal_sensor_availability": False,
            "power_current_available": False,
            "hwinfo_enrichment_available": False,
            "hwinfo_enrichment_active": False,
            "nvidia_smi_available": False,
            "libre_hardware_monitor_available": False,
        }
    )
    snapshot["freshness"]["reason"] = reason
    snapshot["sources"]["helper"] = {"provider": HELPER_PROVIDER_NAME, "state": "unreachable", "detail": reason}
    if isinstance(debug, dict):
        snapshot["debug"] = deepcopy(debug)
    return snapshot


def merge_hardware_snapshots(primary: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(primary)
    _merge_value(merged, enrichment)
    return merged


def overlay_power_status(base_status: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base_status)
    power = snapshot.get("power", {}) if isinstance(snapshot.get("power"), dict) else {}
    capabilities = snapshot.get("capabilities", {}) if isinstance(snapshot.get("capabilities"), dict) else {}

    if _coerce_int(power.get("battery_percent")) is not None:
        merged["battery_percent"] = _coerce_int(power.get("battery_percent"))
        merged["available"] = True
    if str(power.get("ac_line_status", "")).strip():
        merged["ac_line_status"] = str(power.get("ac_line_status")).strip().lower()
        merged["power_source"] = str(power.get("power_source") or merged.get("power_source") or "unknown")
        merged["available"] = True

    for key in ("remaining_capacity_mwh", "full_charge_capacity_mwh", "design_capacity_mwh", "battery_voltage_mv"):
        value = _coerce_int(power.get(key))
        if value is not None:
            merged[key] = value

    charge_rate_w = _coerce_float(power.get("charge_rate_w"))
    if charge_rate_w is not None:
        merged["charge_rate_watts"] = round(charge_rate_w, 2)
        merged["charge_rate_mw"] = int(round(charge_rate_w * 1000))

    discharge_rate_w = _coerce_float(power.get("discharge_rate_w"))
    if discharge_rate_w is not None:
        merged["discharge_rate_watts"] = round(discharge_rate_w, 2)
        merged["discharge_rate_mw"] = int(round(discharge_rate_w * 1000))

    for source_key, target_key in (
        ("instant_draw_w", "instant_power_draw_watts"),
        ("rolling_average_draw_w", "rolling_power_draw_watts"),
        ("battery_current_ma", "battery_current_ma"),
        ("wear_percent", "wear_percent"),
        ("health_percent", "health_percent"),
    ):
        value = _coerce_float(power.get(source_key))
        if value is not None:
            merged[target_key] = round(value, 2)

    for key in ("time_to_full_seconds", "time_to_empty_seconds"):
        value = _coerce_int(power.get(key))
        if value is not None:
            merged[key] = value

    stabilized = _coerce_int(power.get("stabilized_estimate_seconds"))
    instant = _coerce_int(power.get("instant_estimate_seconds"))
    if stabilized is not None:
        merged["seconds_remaining"] = stabilized
    elif instant is not None:
        merged["seconds_remaining"] = instant

    merged["telemetry_capabilities"] = dict(capabilities)
    merged["telemetry_sources"] = deepcopy(snapshot.get("sources", {}))
    merged["telemetry_freshness"] = dict(snapshot.get("freshness", {}))
    merged["telemetry_monitoring"] = deepcopy(snapshot.get("monitoring", {}))
    merged["hardware_telemetry"] = deepcopy(snapshot)
    merged["helper_available"] = bool(capabilities.get("helper_reachable"))
    _overlay_power_metric_sources_from_status(merged)
    return merged


def overlay_resource_status(base_status: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "cpu": dict(base_status.get("cpu", {})) if isinstance(base_status.get("cpu"), dict) else {},
        "memory": dict(base_status.get("memory", {})) if isinstance(base_status.get("memory"), dict) else {},
        "gpu": [dict(item) for item in base_status.get("gpu", [])] if isinstance(base_status.get("gpu"), list) else [],
    }
    cpu = snapshot.get("cpu", {}) if isinstance(snapshot.get("cpu"), dict) else {}
    for key in ("package_temperature_c", "package_power_w", "base_clock_mhz", "effective_clock_mhz", "utilization_percent", "throttle_flags"):
        if _has_signal(cpu.get(key)):
            merged["cpu"][key] = cpu[key]

    adapters = ((snapshot.get("gpu") or {}).get("adapters", [])) if isinstance(snapshot.get("gpu"), dict) else []
    if isinstance(adapters, list):
        if not merged["gpu"]:
            merged["gpu"] = [dict(item) for item in adapters if isinstance(item, dict)]
        else:
            for index, adapter in enumerate(adapters):
                if not isinstance(adapter, dict):
                    continue
                target_index = _matched_gpu_index(merged["gpu"], adapter, fallback_index=index)
                if target_index >= len(merged["gpu"]):
                    merged["gpu"].append(dict(adapter))
                    continue
                for key in (
                    "temperature_c",
                    "hotspot_temperature_c",
                    "memory_junction_temperature_c",
                    "utilization_percent",
                    "core_clock_mhz",
                    "memory_clock_mhz",
                    "power_w",
                    "board_power_w",
                    "vram_total_bytes",
                    "vram_used_bytes",
                    "fan_rpm",
                    "fan_percent",
                    "perf_limit_flags",
                ):
                    if _has_signal(adapter.get(key)):
                        merged["gpu"][target_index][key] = adapter[key]
                if not merged["gpu"][target_index].get("name") and adapter.get("name"):
                    merged["gpu"][target_index]["name"] = adapter["name"]
                if not merged["gpu"][target_index].get("driver_version") and adapter.get("driver_version"):
                    merged["gpu"][target_index]["driver_version"] = adapter["driver_version"]
                if adapter.get("telemetry_provider"):
                    merged["gpu"][target_index]["telemetry_provider"] = adapter["telemetry_provider"]

    if isinstance(merged.get("gpu"), list):
        merged["gpu"].sort(key=_gpu_sort_key, reverse=True)

    merged["thermal"] = deepcopy(snapshot.get("thermal", {}))
    merged["capabilities"] = deepcopy(snapshot.get("capabilities", {}))
    merged["sources"] = deepcopy(snapshot.get("sources", {}))
    merged["freshness"] = deepcopy(snapshot.get("freshness", {}))
    merged["monitoring"] = deepcopy(snapshot.get("monitoring", {}))
    merged["hardware_telemetry"] = deepcopy(snapshot)
    return merged


def _overlay_power_metric_sources_from_status(status: dict[str, Any]) -> None:
    sources = status.get("telemetry_sources")
    if not isinstance(sources, dict):
        return
    metrics = sources.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
        sources["metrics"] = metrics

    fallback_metrics = (
        ("power.battery_percent", status.get("battery_percent"), "system_power_status", "Battery percent"),
        ("power.battery_current_ma", status.get("battery_current_ma"), "system_probe_floor", "Battery current"),
        ("power.charge_rate_w", status.get("charge_rate_watts"), "battery_report_history", "Charge rate"),
        ("power.discharge_rate_w", status.get("discharge_rate_watts"), "battery_report_history", "Discharge rate"),
        ("power.instant_draw_w", status.get("instant_power_draw_watts") or status.get("rolling_power_draw_watts") or status.get("discharge_rate_watts") or status.get("charge_rate_watts"), "battery_report_history", "Battery draw"),
        ("power.remaining_capacity_mwh", status.get("remaining_capacity_mwh"), "battery_report_history", "Remaining capacity"),
        ("power.full_charge_capacity_mwh", status.get("full_charge_capacity_mwh"), "battery_report_history", "Full-charge capacity"),
        ("power.design_capacity_mwh", status.get("design_capacity_mwh"), "battery_report_history", "Design capacity"),
        ("power.health_percent", status.get("health_percent"), "battery_report_history", "Battery health"),
        ("power.wear_percent", status.get("wear_percent"), "battery_report_history", "Battery wear"),
        ("power.time_to_full_seconds", status.get("time_to_full_seconds"), "battery_report_history", "Time to full"),
        ("power.time_to_empty_seconds", status.get("time_to_empty_seconds"), "battery_report_history", "Time to empty"),
    )
    for metric_key, value, provider, source_label in fallback_metrics:
        existing = metrics.get(metric_key)
        if not _has_signal(value):
            continue
        if isinstance(existing, dict) and existing.get("available"):
            continue
        metrics[metric_key] = _metric_entry(provider=provider, value=value, source=source_label)


class HardwareTelemetryHelperClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def snapshot(self, *, sampling_tier: str = "active") -> dict[str, Any]:
        if not self.config.hardware_telemetry.enabled:
            return build_disabled_snapshot(sampling_tier=sampling_tier)

        command = self._command(sampling_tier)
        if not command:
            return build_helper_unreachable_snapshot(sampling_tier=sampling_tier, reason="helper_missing", installed=False)

        env = os.environ.copy()
        source_path = (self.config.project_root / "src").resolve()
        if source_path.exists():
            existing = str(env.get("PYTHONPATH", "")).strip()
            env["PYTHONPATH"] = str(source_path) if not existing else os.pathsep.join([str(source_path), existing])

        timeout_seconds = max(float(self.config.hardware_telemetry.helper_timeout_seconds), 0.5)
        started = monotonic()
        wrapper_debug = {
            "provider": HELPER_PROVIDER_NAME,
            "command": list(command),
            "timeout_seconds": timeout_seconds,
            "sampling_tier": sampling_tier,
            "cwd": str(self.config.project_root),
        }
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
                cwd=str(self.config.project_root),
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            wrapper_debug.update(
                {
                    "state": "timeout",
                    "elapsed_seconds": round(max(monotonic() - started, 0.0), 2),
                    "stdout_bytes": len(exc.stdout or ""),
                    "stderr_preview": str(exc.stderr or "").strip()[:240],
                }
            )
            return build_helper_unreachable_snapshot(
                sampling_tier=sampling_tier,
                reason=f"helper_timeout_after_{timeout_seconds:.1f}s",
                installed=self.helper_installed(),
                debug={"wrapper": wrapper_debug, "providers": {}},
            )
        except Exception as exc:
            wrapper_debug.update(
                {
                    "state": "failed",
                    "elapsed_seconds": round(max(monotonic() - started, 0.0), 2),
                    "error": str(exc),
                }
            )
            return build_helper_unreachable_snapshot(
                sampling_tier=sampling_tier,
                reason=str(exc),
                installed=self.helper_installed(),
                debug={"wrapper": wrapper_debug, "providers": {}},
            )

        wrapper_debug.update(
            {
                "state": "exited",
                "elapsed_seconds": round(max(monotonic() - started, 0.0), 2),
                "returncode": int(completed.returncode),
                "stdout_bytes": len(completed.stdout or ""),
                "stderr_preview": completed.stderr.strip()[:240],
            }
        )

        if completed.returncode != 0:
            reason = completed.stderr.strip() or completed.stdout.strip() or f"helper_exit_{completed.returncode}"
            return build_helper_unreachable_snapshot(
                sampling_tier=sampling_tier,
                reason=reason,
                installed=self.helper_installed(),
                debug={"wrapper": wrapper_debug, "providers": {}},
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return build_helper_unreachable_snapshot(
                sampling_tier=sampling_tier,
                reason=f"invalid_helper_json:{exc}",
                installed=self.helper_installed(),
                debug={"wrapper": wrapper_debug, "providers": {}},
            )
        if not isinstance(payload, dict):
            return build_helper_unreachable_snapshot(
                sampling_tier=sampling_tier,
                reason="invalid_helper_payload",
                installed=self.helper_installed(),
                debug={"wrapper": wrapper_debug, "providers": {}},
            )
        payload_debug = payload.get("debug")
        if not isinstance(payload_debug, dict):
            payload_debug = {}
            payload["debug"] = payload_debug
        payload_debug["wrapper"] = wrapper_debug
        return payload

    def helper_installed(self) -> bool:
        return self._packaged_helper_path().exists() or (self.config.project_root / "src" / "stormhelm" / "entrypoints" / "telemetry_helper.py").exists()

    def _command(self, sampling_tier: str) -> list[str]:
        packaged = self._packaged_helper_path()
        if packaged.exists():
            return [str(packaged), "--tier", sampling_tier]
        return [sys.executable, "-m", "stormhelm.entrypoints.telemetry_helper", "--tier", sampling_tier, "--project-root", str(self.config.project_root)]

    def _packaged_helper_path(self) -> Path:
        return self.config.runtime.install_root / "stormhelm-telemetry-helper.exe"


def collect_helper_snapshot(config: AppConfig, *, sampling_tier: str = "active") -> dict[str, Any]:
    snapshot = _empty_snapshot(sampling_tier=sampling_tier)
    snapshot["capabilities"].update(
        {
            "helper_installed": True,
            "helper_reachable": True,
            "elevated_access_active": _is_elevated(),
        }
    )
    snapshot["sources"]["helper"] = {"provider": HELPER_PROVIDER_NAME, "state": "reachable", "detail": "Bundled helper responded."}
    provider_jobs = {
        NATIVE_PROVIDER_NAME: lambda: _run_provider_collector(NATIVE_PROVIDER_NAME, lambda: _collect_windows_native(config)),
        NVIDIA_SMI_PROVIDER_NAME: lambda: _run_provider_collector(NVIDIA_SMI_PROVIDER_NAME, lambda: _collect_nvidia_gpu(config)),
        LIBRE_HARDWARE_MONITOR_PROVIDER_NAME: lambda: _run_provider_collector(LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lambda: _collect_libre_hardware_monitor(config)),
    }
    provider_results: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=len(provider_jobs)) as executor:
        future_map = {name: executor.submit(job) for name, job in provider_jobs.items()}
        for name, future in future_map.items():
            provider_results[name] = future.result()
    native_payload, native_debug = provider_results[NATIVE_PROVIDER_NAME]
    nvidia_payload, nvidia_debug = provider_results[NVIDIA_SMI_PROVIDER_NAME]
    lhm_payload, lhm_debug = provider_results[LIBRE_HARDWARE_MONITOR_PROVIDER_NAME]

    snapshot["debug"]["providers"] = {
        NATIVE_PROVIDER_NAME: native_debug,
        NVIDIA_SMI_PROVIDER_NAME: nvidia_debug,
        LIBRE_HARDWARE_MONITOR_PROVIDER_NAME: lhm_debug,
    }
    snapshot["sources"][NATIVE_PROVIDER_NAME] = _provider_source_entry(native_payload, native_debug)
    snapshot["sources"][NVIDIA_SMI_PROVIDER_NAME] = _provider_source_entry(nvidia_payload, nvidia_debug)
    snapshot["sources"][LIBRE_HARDWARE_MONITOR_PROVIDER_NAME] = _provider_source_entry(lhm_payload, lhm_debug)

    snapshot["cpu"] = _merge_cpu_telemetry(snapshot, native_payload, lhm_payload)
    snapshot["gpu"] = _merge_gpu_telemetry(snapshot, native_payload, nvidia_payload, lhm_payload)
    snapshot["thermal"] = _merge_thermal_telemetry(snapshot, native_payload, lhm_payload)
    snapshot["power"] = _merge_power_telemetry(snapshot, native_payload)

    history = _load_history(config)
    _append_history_point(history, "power.instant_draw_w", snapshot["power"].get("instant_draw_w"))
    _append_history_point(history, "cpu.package_temperature_c", snapshot["cpu"].get("package_temperature_c"))
    gpu_adapters = snapshot["gpu"].get("adapters", []) if isinstance(snapshot["gpu"], dict) else []
    if gpu_adapters and isinstance(gpu_adapters[0], dict):
        _append_history_point(history, "gpu.primary_temperature_c", gpu_adapters[0].get("temperature_c"))

    power_series = history.get("power.instant_draw_w", [])
    snapshot["power"]["rolling_average_draw_w"] = _rolling_average(power_series, window_seconds=180)
    snapshot["power"]["recent_draw_w"] = _series_values(power_series, limit=6)
    if snapshot["power"].get("stabilized_estimate_seconds") is None:
        snapshot["power"]["stabilized_estimate_seconds"] = _estimate_seconds(snapshot["power"].get("remaining_capacity_mwh"), snapshot["power"].get("rolling_average_draw_w"))
    if snapshot["power"].get("time_to_empty_seconds") is None and snapshot["power"].get("stabilized_estimate_seconds") is not None:
        snapshot["power"]["time_to_empty_seconds"] = snapshot["power"]["stabilized_estimate_seconds"]

    cpu_series = history.get("cpu.package_temperature_c", [])
    gpu_series = history.get("gpu.primary_temperature_c", [])
    snapshot["thermal"]["recent_trend_c"] = (_series_values(cpu_series, limit=3) + _series_values(gpu_series, limit=3))[-6:]
    snapshot["monitoring"] = {
        "sampling_tier": snapshot["freshness"]["sampling_tier"],
        "history_points": {"power_draw": len(power_series), "cpu_temperature": len(cpu_series), "gpu_temperature": len(gpu_series)},
        "rolling_window_seconds": 180,
        "diagnostic_burst_active": snapshot["freshness"]["sampling_tier"] == "burst",
    }
    snapshot["freshness"]["rolling_window_available"] = bool(power_series or cpu_series or gpu_series)

    hwinfo_path = _resolve_hwinfo_path(config)
    snapshot["capabilities"].update(
        {
            "cpu_deep_telemetry_available": any(
                _metric_available(snapshot, metric_key)
                for metric_key in ("cpu.package_temperature_c", "cpu.utilization_percent", "cpu.effective_clock_mhz", "cpu.package_power_w")
            ),
            "gpu_deep_telemetry_available": any(
                _metric_available(snapshot, metric_key)
                for metric_key in (
                    "gpu.utilization_percent",
                    "gpu.temperature_c",
                    "gpu.power_w",
                    "gpu.vram_used_bytes",
                    "gpu.core_clock_mhz",
                )
            ),
            "thermal_sensor_availability": bool(snapshot["thermal"].get("sensors") or snapshot["thermal"].get("fans")),
            "power_current_available": _metric_available(snapshot, "power.battery_current_ma"),
            "nvidia_smi_available": str(nvidia_debug.get("state") or "").strip().lower() == "ready",
            "libre_hardware_monitor_available": str(lhm_debug.get("state") or "").strip().lower() == "ready",
            "hwinfo_enrichment_available": bool(hwinfo_path and hwinfo_path.exists()),
            "hwinfo_enrichment_active": False,
        }
    )
    snapshot["sources"].update(
        {
            "cpu": _domain_source_summary(snapshot, ("cpu.utilization_percent", "cpu.package_temperature_c", "cpu.effective_clock_mhz", "cpu.package_power_w"), fallback_provider=NATIVE_PROVIDER_NAME),
            "gpu": _domain_source_summary(snapshot, ("gpu.utilization_percent", "gpu.temperature_c", "gpu.power_w", "gpu.vram_used_bytes", "gpu.core_clock_mhz"), fallback_provider=NATIVE_PROVIDER_NAME),
            "thermal": _domain_source_summary(snapshot, ("thermal.sensor_count", "thermal.fan_count"), fallback_provider=NATIVE_PROVIDER_NAME),
            "power": _domain_source_summary(snapshot, ("power.battery_percent", "power.instant_draw_w", "power.health_percent", "power.time_to_full_seconds", "power.time_to_empty_seconds"), fallback_provider=NATIVE_PROVIDER_NAME),
            "hwinfo": {
                "provider": HWINFO_PROVIDER_NAME,
                "state": "available" if hwinfo_path and hwinfo_path.exists() else "unavailable",
                "detail": str(hwinfo_path) if hwinfo_path else "not_configured",
            },
        }
    )
    _save_history(config, history)
    return snapshot


def _empty_snapshot(*, sampling_tier: str) -> dict[str, Any]:
    return {
        "cpu": {"package_temperature_c": None, "package_power_w": None, "base_clock_mhz": None, "effective_clock_mhz": None, "utilization_percent": None, "throttle_flags": []},
        "gpu": {"adapters": []},
        "thermal": {"sensors": [], "fans": [], "pump_rpm": None, "recent_trend_c": []},
        "power": {"battery_percent": None, "ac_line_status": "unknown", "power_source": "unknown", "battery_current_ma": None, "battery_voltage_mv": None, "charge_rate_w": None, "discharge_rate_w": None, "remaining_capacity_mwh": None, "full_charge_capacity_mwh": None, "design_capacity_mwh": None, "wear_percent": None, "health_percent": None, "instant_draw_w": None, "rolling_average_draw_w": None, "instant_estimate_seconds": None, "stabilized_estimate_seconds": None, "time_to_full_seconds": None, "time_to_empty_seconds": None, "recent_draw_w": []},
        "capabilities": {
            "helper_installed": True,
            "helper_reachable": True,
            "elevated_access_active": False,
            "cpu_deep_telemetry_available": False,
            "gpu_deep_telemetry_available": False,
            "thermal_sensor_availability": False,
            "power_current_available": False,
            "hwinfo_enrichment_available": False,
            "hwinfo_enrichment_active": False,
            "nvidia_smi_available": False,
            "libre_hardware_monitor_available": False,
        },
        "sources": {"metrics": {}},
        "freshness": {"sampled_at": datetime.now(UTC).isoformat(), "sample_age_seconds": 0.0, "sampling_tier": str(sampling_tier or "active").strip().lower() or "active", "rolling_window_available": False},
        "monitoring": {"sampling_tier": str(sampling_tier or "active").strip().lower() or "active", "history_points": {}, "rolling_window_seconds": 0, "diagnostic_burst_active": False},
        "debug": {"wrapper": {}, "providers": {}},
    }


def _run_provider_collector(name: str, collector) -> tuple[dict[str, Any], dict[str, Any]]:
    started = monotonic()
    try:
        payload = collector()
    except Exception as exc:
        elapsed = round(max(monotonic() - started, 0.0), 2)
        return (
            {"provider": name, "available": False, "state": "failed", "detail": str(exc)},
            {"provider": name, "state": "failed", "detail": str(exc), "elapsed_seconds": elapsed},
        )
    if not isinstance(payload, dict):
        payload = {}
    elapsed = round(max(monotonic() - started, 0.0), 2)
    state = str(payload.get("state") or ("ready" if payload.get("available", True) else "unavailable")).strip() or "unavailable"
    detail = str(payload.get("detail") or "").strip()
    return payload, {"provider": name, "state": state, "detail": detail, "elapsed_seconds": elapsed}


def _provider_source_entry(payload: dict[str, Any], debug: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": str(debug.get("provider") or payload.get("provider") or "unknown").strip() or "unknown",
        "state": str(debug.get("state") or payload.get("state") or "unavailable").strip() or "unavailable",
        "detail": str(payload.get("detail") or debug.get("detail") or "").strip(),
        "elapsed_seconds": debug.get("elapsed_seconds"),
    }


def _metric_entry(
    *,
    provider: str,
    value: Any,
    source: str | None = None,
    sensor: str | None = None,
    unsupported_reason: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"provider": provider, "available": value is not None}
    if source:
        entry["source"] = source
    if sensor:
        entry["sensor"] = sensor
    if unsupported_reason:
        entry["unsupported_reason"] = unsupported_reason
    return entry


def _metric_available(snapshot: dict[str, Any], metric_key: str) -> bool:
    metrics = snapshot.get("sources", {}).get("metrics", {})
    if not isinstance(metrics, dict):
        return False
    metric = metrics.get(metric_key)
    return bool(metric.get("available")) if isinstance(metric, dict) else False


def _domain_source_summary(
    snapshot: dict[str, Any],
    metric_keys: tuple[str, ...],
    *,
    fallback_provider: str,
) -> dict[str, Any]:
    metrics = snapshot.get("sources", {}).get("metrics", {})
    providers: list[str] = []
    reasons: list[str] = []
    if isinstance(metrics, dict):
        for metric_key in metric_keys:
            metric = metrics.get(metric_key)
            if not isinstance(metric, dict):
                continue
            provider = str(metric.get("provider") or "").strip()
            if provider:
                providers.append(provider)
            reason = str(metric.get("unsupported_reason") or "").strip()
            if reason:
                reasons.append(reason)
    unique_providers = list(dict.fromkeys(providers))
    return {
        "provider": "+".join(unique_providers) if unique_providers else fallback_provider,
        "state": "ready" if unique_providers else "unavailable",
        "detail": f"Selected providers: {', '.join(unique_providers)}." if unique_providers else (reasons[0] if reasons else ""),
    }


def _collect_windows_native(config: AppConfig) -> dict[str, Any]:
    cpu = _collect_cpu(config)
    gpu = _collect_gpu(config)
    thermal = _collect_thermal(config)
    power = _collect_power(config)
    available = any(
        (
            _dict_has_signal(cpu, ("utilization_percent", "effective_clock_mhz", "base_clock_mhz", "package_temperature_c")),
            any(isinstance(adapter, dict) for adapter in gpu.get("adapters", []) if isinstance(gpu, dict)),
            bool(thermal.get("sensors")),
            _dict_has_signal(power, ("battery_percent", "charge_rate_w", "discharge_rate_w", "remaining_capacity_mwh")),
        )
    )
    return {
        "provider": NATIVE_PROVIDER_NAME,
        "available": available,
        "state": "ready" if available else "partial",
        "detail": "Windows counters and battery providers responded." if available else "Windows native telemetry did not yield a complete sample.",
        "cpu": cpu,
        "gpu": gpu,
        "thermal": thermal,
        "power": power,
    }


def _merge_cpu_telemetry(snapshot: dict[str, Any], native_payload: dict[str, Any], lhm_payload: dict[str, Any]) -> dict[str, Any]:
    native_cpu = native_payload.get("cpu", {}) if isinstance(native_payload.get("cpu"), dict) else {}
    lhm_cpu = lhm_payload.get("cpu", {}) if isinstance(lhm_payload.get("cpu"), dict) else {}
    cpu = {
        "package_temperature_c": None,
        "package_power_w": None,
        "base_clock_mhz": None,
        "effective_clock_mhz": None,
        "utilization_percent": None,
        "throttle_flags": [],
    }
    cpu["base_clock_mhz"], base_provider = _select_metric((NATIVE_PROVIDER_NAME, native_cpu.get("base_clock_mhz")), sanitize=_sanitize_clock)
    cpu["effective_clock_mhz"], clock_provider = _select_metric(
        (NATIVE_PROVIDER_NAME, native_cpu.get("effective_clock_mhz")),
        (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_cpu.get("effective_clock_mhz")),
        sanitize=_sanitize_clock,
    )
    cpu["utilization_percent"], utilization_provider = _select_metric(
        (NATIVE_PROVIDER_NAME, native_cpu.get("utilization_percent")),
        (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_cpu.get("utilization_percent")),
        sanitize=_sanitize_percent,
    )
    cpu["package_temperature_c"], temperature_provider = _select_metric(
        (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_cpu.get("package_temperature_c")),
        (NATIVE_PROVIDER_NAME, native_cpu.get("package_temperature_c")),
        sanitize=_sanitize_temperature,
    )
    cpu["package_power_w"], power_provider = _select_metric(
        (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_cpu.get("package_power_w")),
        (NATIVE_PROVIDER_NAME, native_cpu.get("package_power_w")),
        sanitize=_sanitize_power,
    )
    cpu["throttle_flags"] = _sanitize_flag_list(lhm_cpu.get("throttle_flags")) or _sanitize_flag_list(native_cpu.get("throttle_flags")) or []

    metrics = snapshot["sources"]["metrics"]
    metrics["cpu.base_clock_mhz"] = _metric_entry(provider=base_provider or NATIVE_PROVIDER_NAME, value=cpu["base_clock_mhz"], source="Win32_Processor.MaxClockSpeed", unsupported_reason="Windows is not exposing the CPU base clock on this machine." if cpu["base_clock_mhz"] is None else None)
    metrics["cpu.effective_clock_mhz"] = _metric_entry(provider=clock_provider or NATIVE_PROVIDER_NAME, value=cpu["effective_clock_mhz"], source="Current CPU clock", unsupported_reason="A current CPU clock sample was not exposed by the available providers." if cpu["effective_clock_mhz"] is None else None)
    metrics["cpu.utilization_percent"] = _metric_entry(provider=utilization_provider or NATIVE_PROVIDER_NAME, value=cpu["utilization_percent"], source="Current CPU utilization", unsupported_reason="A current CPU utilization sample was not exposed by the available providers." if cpu["utilization_percent"] is None else None)
    metrics["cpu.package_temperature_c"] = _metric_entry(provider=temperature_provider or LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, value=cpu["package_temperature_c"], source="CPU package temperature", unsupported_reason="No valid CPU package temperature sensor is exposed by the available non-HWiNFO providers on this machine." if cpu["package_temperature_c"] is None else None)
    metrics["cpu.package_power_w"] = _metric_entry(provider=power_provider or LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, value=cpu["package_power_w"], source="CPU package power", unsupported_reason="No valid CPU package power sensor is exposed by the available non-HWiNFO providers on this machine." if cpu["package_power_w"] is None else None)
    metrics["cpu.throttle_flags"] = _metric_entry(provider=LIBRE_HARDWARE_MONITOR_PROVIDER_NAME if cpu["throttle_flags"] else NATIVE_PROVIDER_NAME, value=cpu["throttle_flags"] if cpu["throttle_flags"] else None, source="CPU throttle flags", unsupported_reason="No CPU throttle or thermal limit flags were exposed by the available providers." if not cpu["throttle_flags"] else None)
    return cpu


def _merge_gpu_telemetry(
    snapshot: dict[str, Any],
    native_payload: dict[str, Any],
    nvidia_payload: dict[str, Any],
    lhm_payload: dict[str, Any],
) -> dict[str, Any]:
    native_adapters = _gpu_adapter_map((native_payload.get("gpu") or {}).get("adapters", []) if isinstance(native_payload.get("gpu"), dict) else [])
    nvidia_adapters = _gpu_adapter_map(nvidia_payload.get("adapters", []))
    lhm_adapters = _gpu_adapter_map(lhm_payload.get("adapters", []))
    adapter_keys = list(dict.fromkeys([*native_adapters.keys(), *nvidia_adapters.keys(), *lhm_adapters.keys()]))
    adapters: list[dict[str, Any]] = []

    for key in adapter_keys:
        native_adapter = native_adapters.get(key, {})
        nvidia_adapter = nvidia_adapters.get(key, {})
        lhm_adapter = lhm_adapters.get(key, {})
        name = str(native_adapter.get("name") or nvidia_adapter.get("name") or lhm_adapter.get("name") or "GPU").strip() or "GPU"
        is_nvidia = "nvidia" in name.lower()
        adapter: dict[str, Any] = {
            "name": name,
            "driver_version": native_adapter.get("driver_version") or nvidia_adapter.get("driver_version"),
            "adapter_ram": native_adapter.get("adapter_ram"),
            "fan_rpm": None,
            "fan_percent": None,
            "perf_limit_flags": [],
        }
        utilization_candidates = ((NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("utilization_percent")), (NATIVE_PROVIDER_NAME, native_adapter.get("utilization_percent")), (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("utilization_percent"))) if is_nvidia else ((LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("utilization_percent")), (NATIVE_PROVIDER_NAME, native_adapter.get("utilization_percent")), (NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("utilization_percent")))
        temperature_candidates = ((NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("temperature_c")), (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("temperature_c")), (NATIVE_PROVIDER_NAME, native_adapter.get("temperature_c"))) if is_nvidia else ((LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("temperature_c")), (NATIVE_PROVIDER_NAME, native_adapter.get("temperature_c")), (NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("temperature_c")))
        power_candidates = ((NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("power_w")), (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("power_w")), (NATIVE_PROVIDER_NAME, native_adapter.get("power_w"))) if is_nvidia else ((LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("power_w")), (NATIVE_PROVIDER_NAME, native_adapter.get("power_w")), (NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("power_w")))
        core_clock_candidates = ((NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("core_clock_mhz")), (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("core_clock_mhz")), (NATIVE_PROVIDER_NAME, native_adapter.get("core_clock_mhz"))) if is_nvidia else ((LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("core_clock_mhz")), (NATIVE_PROVIDER_NAME, native_adapter.get("core_clock_mhz")), (NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("core_clock_mhz")))
        memory_clock_candidates = ((NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("memory_clock_mhz")), (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("memory_clock_mhz")), (NATIVE_PROVIDER_NAME, native_adapter.get("memory_clock_mhz"))) if is_nvidia else ((LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("memory_clock_mhz")), (NATIVE_PROVIDER_NAME, native_adapter.get("memory_clock_mhz")), (NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("memory_clock_mhz")))

        adapter["utilization_percent"], utilization_provider = _select_metric(*utilization_candidates, sanitize=_sanitize_percent)
        adapter["temperature_c"], temperature_provider = _select_metric(*temperature_candidates, sanitize=_sanitize_temperature)
        adapter["power_w"], power_provider = _select_metric(*power_candidates, sanitize=_sanitize_power)
        adapter["board_power_w"] = adapter["power_w"]
        adapter["core_clock_mhz"], core_clock_provider = _select_metric(*core_clock_candidates, sanitize=_sanitize_clock)
        adapter["memory_clock_mhz"], memory_clock_provider = _select_metric(*memory_clock_candidates, sanitize=_sanitize_clock)
        adapter["vram_total_bytes"], vram_total_provider = _select_metric((NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("vram_total_bytes")), (NATIVE_PROVIDER_NAME, native_adapter.get("vram_total_bytes")), (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("vram_total_bytes")), sanitize=_sanitize_bytes)
        adapter["vram_used_bytes"], vram_used_provider = _select_metric((NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("vram_used_bytes")), (NATIVE_PROVIDER_NAME, native_adapter.get("vram_used_bytes")), (LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("vram_used_bytes")), sanitize=_sanitize_bytes)
        adapter["hotspot_temperature_c"], hotspot_provider = _select_metric((LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("hotspot_temperature_c")), sanitize=_sanitize_temperature)
        adapter["memory_junction_temperature_c"], memory_junction_provider = _select_metric((LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("memory_junction_temperature_c")), sanitize=_sanitize_temperature)
        adapter["fan_rpm"], fan_provider = _select_metric((LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, lhm_adapter.get("fan_rpm")), sanitize=_sanitize_rpm)
        adapter["fan_percent"], fan_percent_provider = _select_metric((NVIDIA_SMI_PROVIDER_NAME, nvidia_adapter.get("fan_percent")), sanitize=_sanitize_percent)
        adapter["perf_limit_flags"] = _sanitize_flag_list(nvidia_adapter.get("perf_limit_flags")) or _sanitize_flag_list(lhm_adapter.get("perf_limit_flags")) or []
        adapter["telemetry_provider"] = _first_non_empty(utilization_provider, temperature_provider, power_provider, core_clock_provider, vram_used_provider, NATIVE_PROVIDER_NAME)
        adapters.append(adapter)

    adapters.sort(key=_gpu_sort_key, reverse=True)
    primary = adapters[0] if adapters else {}
    metrics = snapshot["sources"]["metrics"]
    metrics["gpu.adapter_count"] = _metric_entry(provider=NATIVE_PROVIDER_NAME, value=len(adapters) if adapters else None, source="GPU adapter inventory", unsupported_reason="No GPU adapters were reported by the active providers." if not adapters else None)
    metrics["gpu.utilization_percent"] = _metric_entry(provider=str(primary.get("telemetry_provider") or NATIVE_PROVIDER_NAME), value=primary.get("utilization_percent"), source="Primary GPU utilization", unsupported_reason="No valid GPU utilization sample was exposed by the available providers." if not primary or primary.get("utilization_percent") is None else None)
    metrics["gpu.temperature_c"] = _metric_entry(provider=str(primary.get("telemetry_provider") or NATIVE_PROVIDER_NAME), value=primary.get("temperature_c"), source="Primary GPU core temperature", unsupported_reason="No valid GPU core temperature sensor is exposed by the available providers." if not primary or primary.get("temperature_c") is None else None)
    metrics["gpu.hotspot_temperature_c"] = _metric_entry(provider=hotspot_provider or LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, value=primary.get("hotspot_temperature_c"), source="Primary GPU hotspot", unsupported_reason="No GPU hotspot sensor is exposed by the available non-HWiNFO providers on this machine." if not primary or primary.get("hotspot_temperature_c") is None else None)
    metrics["gpu.memory_junction_temperature_c"] = _metric_entry(provider=memory_junction_provider or LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, value=primary.get("memory_junction_temperature_c"), source="Primary GPU memory junction", unsupported_reason="No GPU memory junction sensor is exposed by the available non-HWiNFO providers on this machine." if not primary or primary.get("memory_junction_temperature_c") is None else None)
    metrics["gpu.power_w"] = _metric_entry(provider=str(primary.get("telemetry_provider") or NATIVE_PROVIDER_NAME), value=primary.get("power_w"), source="Primary GPU power draw", unsupported_reason="No valid GPU power sensor is exposed by the available providers." if not primary or primary.get("power_w") is None else None)
    metrics["gpu.core_clock_mhz"] = _metric_entry(provider=core_clock_provider or str(primary.get("telemetry_provider") or NATIVE_PROVIDER_NAME), value=primary.get("core_clock_mhz"), source="Primary GPU graphics clock", unsupported_reason="No current GPU core clock sample was exposed by the available providers." if not primary or primary.get("core_clock_mhz") is None else None)
    metrics["gpu.memory_clock_mhz"] = _metric_entry(provider=memory_clock_provider or str(primary.get("telemetry_provider") or NATIVE_PROVIDER_NAME), value=primary.get("memory_clock_mhz"), source="Primary GPU memory clock", unsupported_reason="No current GPU memory clock sample was exposed by the available providers." if not primary or primary.get("memory_clock_mhz") is None else None)
    metrics["gpu.vram_total_bytes"] = _metric_entry(provider=vram_total_provider or str(primary.get("telemetry_provider") or NATIVE_PROVIDER_NAME), value=primary.get("vram_total_bytes"), source="Primary GPU VRAM total", unsupported_reason="No GPU VRAM capacity reading was exposed by the available providers." if not primary or primary.get("vram_total_bytes") is None else None)
    metrics["gpu.vram_used_bytes"] = _metric_entry(provider=vram_used_provider or str(primary.get("telemetry_provider") or NATIVE_PROVIDER_NAME), value=primary.get("vram_used_bytes"), source="Primary GPU VRAM used", unsupported_reason="No live GPU VRAM usage sample was exposed by the available providers." if not primary or primary.get("vram_used_bytes") is None else None)
    metrics["gpu.fan_rpm"] = _metric_entry(provider=fan_provider or LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, value=primary.get("fan_rpm"), source="Primary GPU fan RPM", unsupported_reason="No GPU fan RPM sensor is exposed by the available non-HWiNFO providers on this machine." if not primary or primary.get("fan_rpm") is None else None)
    metrics["gpu.fan_percent"] = _metric_entry(provider=fan_percent_provider or NVIDIA_SMI_PROVIDER_NAME, value=primary.get("fan_percent"), source="Primary GPU fan percent", unsupported_reason="No GPU fan percentage reading is exposed by the available providers." if not primary or primary.get("fan_percent") is None else None)
    metrics["gpu.perf_limit_flags"] = _metric_entry(provider=NVIDIA_SMI_PROVIDER_NAME if primary.get("perf_limit_flags") else str(primary.get("telemetry_provider") or NATIVE_PROVIDER_NAME), value=primary.get("perf_limit_flags") if primary and primary.get("perf_limit_flags") else None, source="Primary GPU perf limits", unsupported_reason="No GPU performance limit flags were exposed by the available providers." if not primary or not primary.get("perf_limit_flags") else None)
    return {"adapters": adapters}


def _merge_thermal_telemetry(snapshot: dict[str, Any], native_payload: dict[str, Any], lhm_payload: dict[str, Any]) -> dict[str, Any]:
    native_thermal = native_payload.get("thermal", {}) if isinstance(native_payload.get("thermal"), dict) else {}
    lhm_thermal = lhm_payload.get("thermal", {}) if isinstance(lhm_payload.get("thermal"), dict) else {}
    sensors: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source_sensors in (lhm_thermal.get("sensors", []), native_thermal.get("sensors", [])):
        if not isinstance(source_sensors, list):
            continue
        for sensor in source_sensors:
            if not isinstance(sensor, dict):
                continue
            label = str(sensor.get("label") or "").strip() or "Sensor"
            source_name = str(sensor.get("source") or "").strip() or "provider"
            temperature = _sanitize_temperature(sensor.get("temperature_c"))
            if temperature is None:
                continue
            key = (label.lower(), source_name.lower())
            if key in seen:
                continue
            seen.add(key)
            sensors.append({"label": label, "temperature_c": temperature, "source": source_name})
    fans: list[dict[str, Any]] = []
    for source_fans in (lhm_thermal.get("fans", []), native_thermal.get("fans", [])):
        if not isinstance(source_fans, list):
            continue
        for fan in source_fans:
            if not isinstance(fan, dict):
                continue
            rpm = _sanitize_rpm(fan.get("rpm"))
            if rpm is None:
                continue
            fans.append({"label": str(fan.get("label") or "Fan").strip() or "Fan", "rpm": rpm, "source": str(fan.get("source") or LIBRE_HARDWARE_MONITOR_PROVIDER_NAME).strip() or LIBRE_HARDWARE_MONITOR_PROVIDER_NAME})
    snapshot["sources"]["metrics"]["thermal.sensor_count"] = _metric_entry(provider=LIBRE_HARDWARE_MONITOR_PROVIDER_NAME if sensors else NATIVE_PROVIDER_NAME, value=len(sensors) if sensors else None, source="Thermal sensor inventory", unsupported_reason="No thermal sensors were exposed by the available providers." if not sensors else None)
    snapshot["sources"]["metrics"]["thermal.fan_count"] = _metric_entry(provider=LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, value=len(fans) if fans else None, source="Fan sensor inventory", unsupported_reason="No fan sensors were exposed by the available non-HWiNFO providers on this machine." if not fans else None)
    return {"sensors": sensors, "fans": fans, "pump_rpm": _sanitize_rpm(lhm_thermal.get("pump_rpm")), "recent_trend_c": []}


def _merge_power_telemetry(snapshot: dict[str, Any], native_payload: dict[str, Any]) -> dict[str, Any]:
    power = dict(native_payload.get("power", {})) if isinstance(native_payload.get("power"), dict) else {}
    charge_rate_w = _sanitize_power(power.get("charge_rate_w"))
    discharge_rate_w = _sanitize_power(power.get("discharge_rate_w"))
    power["charge_rate_w"] = charge_rate_w
    power["discharge_rate_w"] = discharge_rate_w
    power["instant_draw_w"] = discharge_rate_w if discharge_rate_w is not None else charge_rate_w
    voltage_mv = _sanitize_int(power.get("battery_voltage_mv"))
    if power.get("battery_current_ma") is None and power.get("instant_draw_w") is not None and voltage_mv:
        power["battery_current_ma"] = round((float(power["instant_draw_w"]) * 1000.0) / float(voltage_mv), 2)

    metric_specs = (
        ("power.battery_percent", _sanitize_int(power.get("battery_percent")), "Battery percent", "The active battery provider did not expose a battery percentage."),
        ("power.battery_current_ma", _sanitize_float(power.get("battery_current_ma")), "Battery current", "The active battery providers did not expose live battery current on this machine."),
        ("power.battery_voltage_mv", _sanitize_int(power.get("battery_voltage_mv")), "Battery voltage", "The active battery providers did not expose battery voltage on this machine."),
        ("power.charge_rate_w", charge_rate_w, "Charge rate", "The active battery providers did not expose a live charge-rate reading on this machine."),
        ("power.discharge_rate_w", discharge_rate_w, "Discharge rate", "The active battery providers did not expose a live discharge-rate reading on this machine."),
        ("power.instant_draw_w", _sanitize_power(power.get("instant_draw_w")), "Instant battery draw", "The active battery providers did not expose a live battery-draw reading on this machine."),
        ("power.remaining_capacity_mwh", _sanitize_int(power.get("remaining_capacity_mwh")), "Remaining capacity", "The active battery providers did not expose remaining battery capacity on this machine."),
        ("power.full_charge_capacity_mwh", _sanitize_int(power.get("full_charge_capacity_mwh")), "Full-charge capacity", "The active battery providers did not expose full-charge capacity on this machine."),
        ("power.design_capacity_mwh", _sanitize_int(power.get("design_capacity_mwh")), "Design capacity", "The active battery providers did not expose design capacity on this machine."),
        ("power.health_percent", _sanitize_percent(power.get("health_percent")), "Battery health", "The active battery providers did not expose battery health on this machine."),
        ("power.wear_percent", _sanitize_percent(power.get("wear_percent")), "Battery wear", "The active battery providers did not expose battery wear on this machine."),
        ("power.time_to_full_seconds", _sanitize_int(power.get("time_to_full_seconds")), "Time to full", "The active battery providers did not expose a reliable time-to-full estimate on this machine."),
        ("power.time_to_empty_seconds", _sanitize_int(power.get("time_to_empty_seconds")), "Time to empty", "The active battery providers did not expose a reliable time-to-empty estimate on this machine."),
    )
    for metric_key, value, source_label, reason in metric_specs:
        snapshot["sources"]["metrics"][metric_key] = _metric_entry(provider=NATIVE_PROVIDER_NAME, value=value, source=source_label, unsupported_reason=reason if value is None else None)
    return power


def _select_metric(*candidates: tuple[str, Any], sanitize) -> tuple[Any, str | None]:
    for provider, raw_value in candidates:
        value = sanitize(raw_value)
        if value is not None:
            return value, provider
    return None, None


def _gpu_adapter_map(adapters: Any) -> dict[str, dict[str, Any]]:
    if isinstance(adapters, dict):
        adapters = [adapters]
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(adapters, list):
        return result
    for index, adapter in enumerate(adapters):
        if not isinstance(adapter, dict):
            continue
        key = _adapter_key(adapter, index=index)
        result[key] = dict(adapter)
    return result


def _adapter_key(adapter: dict[str, Any], *, index: int) -> str:
    name = str(adapter.get("name") or "").strip().lower()
    if name:
        return name
    bus_id = str(adapter.get("pci_bus_id") or "").strip().lower()
    if bus_id:
        return bus_id
    return f"adapter-{index}"


def _gpu_sort_key(adapter: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(adapter.get("utilization_percent") or 0.0),
        float(adapter.get("power_w") or 0.0),
        float(adapter.get("vram_used_bytes") or 0.0),
        float(adapter.get("temperature_c") or 0.0),
    )


def _sanitize_percent(value: Any) -> float | None:
    numeric = _sanitize_float(value)
    if numeric is None or numeric < 0 or numeric > 100:
        return None
    return round(numeric, 2)


def _sanitize_temperature(value: Any) -> float | None:
    numeric = _sanitize_float(value)
    if numeric is None or numeric <= 0 or numeric > 200:
        return None
    return round(numeric, 1)


def _sanitize_power(value: Any) -> float | None:
    numeric = _sanitize_float(value)
    if numeric is None or numeric <= 0 or numeric > 2000:
        return None
    return round(numeric, 2)


def _sanitize_clock(value: Any) -> float | None:
    numeric = _sanitize_float(value)
    if numeric is None or numeric <= 0:
        return None
    return round(numeric, 0)


def _sanitize_bytes(value: Any) -> int | None:
    numeric = _sanitize_int(value)
    if numeric is None or numeric < 0:
        return None
    return numeric


def _sanitize_rpm(value: Any) -> int | None:
    numeric = _sanitize_int(value)
    if numeric is None or numeric <= 0:
        return None
    return numeric


def _sanitize_int(value: Any) -> int | None:
    numeric = _coerce_int(value)
    if numeric is None:
        return None
    return int(numeric)


def _sanitize_float(value: Any) -> float | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    return float(numeric)


def _sanitize_flag_list(value: Any) -> list[str]:
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned
    text = str(value or "").strip()
    if not text or text in {"0", "0x0000000000000000", "[]"}:
        return []
    return [text]


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _collect_cpu(config: AppConfig) -> dict[str, Any]:
    payload = _run_powershell_json(
        config,
        """
        $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed
        $util = $null; $freq = $null
        try { $sample = Get-Counter -Counter '\\Processor Information(_Total)\\% Processor Utility','\\Processor Information(_Total)\\Processor Frequency' -ErrorAction Stop; foreach ($item in $sample.CounterSamples) { if ($item.Path -like '*% Processor Utility') { $util = [math]::Round($item.CookedValue, 2) }; if ($item.Path -like '*Processor Frequency') { $freq = [math]::Round($item.CookedValue, 0) } } } catch {}
        $temp = $null
        try { $zones = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop; $values = @($zones | Where-Object { $_.CurrentTemperature -gt 0 } | ForEach-Object { [math]::Round(($_.CurrentTemperature / 10.0) - 273.15, 1) }); if ($values.Count -gt 0) { $temp = [math]::Round((($values | Measure-Object -Average).Average), 1) } } catch {}
        [pscustomobject]@{ name = $cpu.Name; cores = $cpu.NumberOfCores; logical_processors = $cpu.NumberOfLogicalProcessors; base_clock_mhz = $cpu.MaxClockSpeed; effective_clock_mhz = $freq; utilization_percent = $util; package_temperature_c = $temp; package_power_w = $null; throttle_flags = @() } | ConvertTo-Json -Compress -Depth 4
        """,
    )
    return payload if isinstance(payload, dict) else {"package_temperature_c": None, "package_power_w": None, "base_clock_mhz": None, "effective_clock_mhz": None, "utilization_percent": None, "throttle_flags": []}


def _collect_gpu(config: AppConfig) -> dict[str, Any]:
    payload = _run_powershell_json(
        config,
        """
        $adapters = @(); try { $adapters = @(Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion) } catch {}
        $utilByIndex = @{}; try { $sample = Get-Counter -Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction Stop; foreach ($item in $sample.CounterSamples) { if ($item.InstanceName -notmatch 'engtype_3D|engtype_Compute') { continue }; $gpuIndex = 0; if ($item.InstanceName -match 'phys_(\\d+)') { $gpuIndex = [int]$Matches[1] }; $current = 0.0; if ($utilByIndex.ContainsKey($gpuIndex)) { $current = [double]$utilByIndex[$gpuIndex] }; $utilByIndex[$gpuIndex] = [math]::Round($current + $item.CookedValue, 2) } } catch {}
        $memoryByIndex = @{}; try { $sample = Get-Counter -Counter '\\GPU Adapter Memory(*)\\Dedicated Usage' -ErrorAction Stop; foreach ($item in $sample.CounterSamples) { $gpuIndex = 0; if ($item.InstanceName -match 'phys_(\\d+)') { $gpuIndex = [int]$Matches[1] }; $memoryByIndex[$gpuIndex] = [int64]$item.CookedValue } } catch {}
        $items = @(); for ($i = 0; $i -lt $adapters.Count; $i++) { $adapter = $adapters[$i]; $items += [pscustomobject]@{ index = $i; name = $adapter.Name; driver_version = $adapter.DriverVersion; adapter_ram = [int64]$adapter.AdapterRAM; utilization_percent = $(if ($utilByIndex.ContainsKey($i)) { $utilByIndex[$i] } else { $null }); vram_total_bytes = [int64]$adapter.AdapterRAM; vram_used_bytes = $(if ($memoryByIndex.ContainsKey($i)) { [int64]$memoryByIndex[$i] } else { $null }); temperature_c = $null; hotspot_temperature_c = $null; memory_junction_temperature_c = $null; power_w = $null; board_power_w = $null; core_clock_mhz = $null; memory_clock_mhz = $null; fan_rpm = $null; perf_limit_flags = @() } }; [pscustomobject]@{ adapters = $items } | ConvertTo-Json -Compress -Depth 5
        """,
    )
    if not isinstance(payload, dict):
        return {"adapters": []}
    adapters = payload.get("adapters")
    if isinstance(adapters, dict):
        payload["adapters"] = [adapters]
    elif not isinstance(adapters, list):
        payload["adapters"] = []
    return payload


def _collect_thermal(config: AppConfig) -> dict[str, Any]:
    payload = _run_powershell_json(
        config,
        """
        $sensors = @(); try { $zones = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop; foreach ($zone in $zones) { if ($zone.CurrentTemperature -le 0) { continue }; $sensors += [pscustomobject]@{ label = [string]$zone.InstanceName; temperature_c = [math]::Round(($zone.CurrentTemperature / 10.0) - 273.15, 1); source = 'MSAcpiThermalZoneTemperature' } } } catch {}
        [pscustomobject]@{ sensors = $sensors; fans = @(); pump_rpm = $null; recent_trend_c = @() } | ConvertTo-Json -Compress -Depth 5
        """,
    )
    return payload if isinstance(payload, dict) else {"sensors": [], "fans": [], "pump_rpm": None, "recent_trend_c": []}


def _collect_power(config: AppConfig) -> dict[str, Any]:
    payload = _run_powershell_json(
        config,
        """
        $battery = $null; try { $battery = Get-CimInstance Win32_Battery | Select-Object -First 1 EstimatedChargeRemaining, BatteryStatus, DesignVoltage, EstimatedRunTime } catch {}
        $wmi = $null; try { $wmi = Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus -ErrorAction Stop | Select-Object -First 1 RemainingCapacity, DischargeRate, ChargeRate, Voltage } catch {}
        $report = $null; try { Add-Type -AssemblyName System.Runtime.WindowsRuntime; $null = [Windows.Devices.Power.Battery, Windows, ContentType=WindowsRuntime]; $report = [Windows.Devices.Power.Battery]::AggregateBattery.GetReport() } catch {}
        $batteryPercent = $null; if ($battery) { $batteryPercent = $battery.EstimatedChargeRemaining }
        $acLineStatus = 'unknown'; if ($battery) { $status = [int]$battery.BatteryStatus; if ($status -in @(2, 6, 7, 8, 9)) { $acLineStatus = 'online' } elseif ($status -gt 0) { $acLineStatus = 'offline' } }
        $remainingCapacity = $null; if ($report -and $report.RemainingCapacityInMilliwattHours) { $remainingCapacity = [int]$report.RemainingCapacityInMilliwattHours } elseif ($wmi -and $wmi.RemainingCapacity) { $remainingCapacity = [int]$wmi.RemainingCapacity }
        $fullChargeCapacity = $null; if ($report -and $report.FullChargeCapacityInMilliwattHours) { $fullChargeCapacity = [int]$report.FullChargeCapacityInMilliwattHours }
        $designCapacity = $null; if ($report -and $report.DesignCapacityInMilliwattHours) { $designCapacity = [int]$report.DesignCapacityInMilliwattHours }
        $chargeRateMw = $null; if ($report -and $report.ChargeRateInMilliwatts -gt 0) { $chargeRateMw = [int]$report.ChargeRateInMilliwatts } elseif ($wmi -and $wmi.ChargeRate) { $chargeRateMw = [int]$wmi.ChargeRate }
        $dischargeRateMw = $null; if ($wmi -and $wmi.DischargeRate) { $dischargeRateMw = [int]$wmi.DischargeRate } elseif ($report -and $report.ChargeRateInMilliwatts -lt 0) { $dischargeRateMw = [math]::Abs([int]$report.ChargeRateInMilliwatts) }
        $voltageMv = $null; if ($wmi -and $wmi.Voltage) { $voltageMv = [int]$wmi.Voltage } elseif ($battery -and $battery.DesignVoltage) { $voltageMv = [int]$battery.DesignVoltage }
        [pscustomobject]@{ battery_percent = $batteryPercent; ac_line_status = $acLineStatus; power_source = $(if ($acLineStatus -eq 'online') { 'ac' } elseif ($acLineStatus -eq 'offline') { 'battery' } else { 'unknown' }); battery_current_ma = $null; battery_voltage_mv = $voltageMv; charge_rate_w = $(if ($chargeRateMw) { [math]::Round($chargeRateMw / 1000.0, 2) } else { $null }); discharge_rate_w = $(if ($dischargeRateMw) { [math]::Round($dischargeRateMw / 1000.0, 2) } else { $null }); remaining_capacity_mwh = $remainingCapacity; full_charge_capacity_mwh = $fullChargeCapacity; design_capacity_mwh = $designCapacity } | ConvertTo-Json -Compress -Depth 4
        """,
    )
    if not isinstance(payload, dict):
        return {"battery_percent": None, "ac_line_status": "unknown", "power_source": "unknown", "battery_current_ma": None, "battery_voltage_mv": None, "charge_rate_w": None, "discharge_rate_w": None, "remaining_capacity_mwh": None, "full_charge_capacity_mwh": None, "design_capacity_mwh": None, "wear_percent": None, "health_percent": None, "instant_draw_w": None, "rolling_average_draw_w": None, "instant_estimate_seconds": None, "stabilized_estimate_seconds": None, "time_to_full_seconds": None, "time_to_empty_seconds": None, "recent_draw_w": []}
    charge_rate_w = _coerce_float(payload.get("charge_rate_w"))
    discharge_rate_w = _coerce_float(payload.get("discharge_rate_w"))
    payload["instant_draw_w"] = discharge_rate_w if discharge_rate_w is not None else charge_rate_w
    voltage_mv = _coerce_int(payload.get("battery_voltage_mv"))
    if payload.get("battery_current_ma") is None and payload.get("instant_draw_w") is not None and voltage_mv:
        payload["battery_current_ma"] = round((float(payload["instant_draw_w"]) * 1000.0) / float(voltage_mv), 2)
    payload["instant_estimate_seconds"] = _estimate_seconds(payload.get("remaining_capacity_mwh"), discharge_rate_w)
    payload["stabilized_estimate_seconds"] = None
    payload["time_to_empty_seconds"] = payload["instant_estimate_seconds"]
    payload["time_to_full_seconds"] = _estimate_seconds_to_full(payload.get("remaining_capacity_mwh"), payload.get("full_charge_capacity_mwh"), charge_rate_w)
    if _coerce_int(payload.get("full_charge_capacity_mwh")) and _coerce_int(payload.get("design_capacity_mwh")):
        health = round((_coerce_int(payload["full_charge_capacity_mwh"]) / _coerce_int(payload["design_capacity_mwh"])) * 100.0, 2)
        payload["health_percent"] = health
        payload["wear_percent"] = round(max(100.0 - health, 0.0), 2)
    else:
        payload["health_percent"] = None
        payload["wear_percent"] = None
    payload["recent_draw_w"] = []
    return payload


def _collect_nvidia_gpu(config: AppConfig) -> dict[str, Any]:
    executable = _resolve_nvidia_smi_path()
    if executable is None:
        return {"provider": NVIDIA_SMI_PROVIDER_NAME, "available": False, "state": "unavailable", "detail": "nvidia-smi is not installed or is not on PATH.", "adapters": []}
    query_fields = [
        "index",
        "pci.bus_id",
        "name",
        "driver_version",
        "utilization.gpu",
        "temperature.gpu",
        "temperature.memory",
        "power.draw",
        "clocks.current.graphics",
        "clocks.current.memory",
        "fan.speed",
        "memory.total",
        "memory.used",
        "clocks_throttle_reasons.active",
    ]
    try:
        completed = subprocess.run(
            [str(executable), f"--query-gpu={','.join(query_fields)}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=max(float(config.hardware_telemetry.provider_timeout_seconds), 0.5),
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"provider": NVIDIA_SMI_PROVIDER_NAME, "available": False, "state": "timeout", "detail": "nvidia-smi did not return before the provider timeout.", "adapters": []}
    except Exception as exc:
        return {"provider": NVIDIA_SMI_PROVIDER_NAME, "available": False, "state": "failed", "detail": str(exc), "adapters": []}
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "nvidia-smi returned a non-zero exit code."
        return {"provider": NVIDIA_SMI_PROVIDER_NAME, "available": False, "state": "failed", "detail": detail, "adapters": []}

    adapters: list[dict[str, Any]] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != len(query_fields):
            continue
        item = dict(zip(query_fields, parts, strict=False))
        adapters.append(
            {
                "index": _sanitize_int(item.get("index")),
                "pci_bus_id": str(item.get("pci.bus_id") or "").strip() or None,
                "name": str(item.get("name") or "").strip() or None,
                "driver_version": str(item.get("driver_version") or "").strip() or None,
                "utilization_percent": _sanitize_percent(_parse_vendor_number(item.get("utilization.gpu"))),
                "temperature_c": _sanitize_temperature(_parse_vendor_number(item.get("temperature.gpu"))),
                "memory_junction_temperature_c": _sanitize_temperature(_parse_vendor_number(item.get("temperature.memory"))),
                "power_w": _sanitize_power(_parse_vendor_number(item.get("power.draw"))),
                "core_clock_mhz": _sanitize_clock(_parse_vendor_number(item.get("clocks.current.graphics"))),
                "memory_clock_mhz": _sanitize_clock(_parse_vendor_number(item.get("clocks.current.memory"))),
                "fan_percent": _sanitize_percent(_parse_vendor_number(item.get("fan.speed"))),
                "vram_total_bytes": _mib_to_bytes(_parse_vendor_number(item.get("memory.total"))),
                "vram_used_bytes": _mib_to_bytes(_parse_vendor_number(item.get("memory.used"))),
                "perf_limit_flags": _parse_perf_limit_flags(item.get("clocks_throttle_reasons.active")),
            }
        )
    return {
        "provider": NVIDIA_SMI_PROVIDER_NAME,
        "available": bool(adapters),
        "state": "ready" if adapters else "unavailable",
        "detail": "nvidia-smi returned live NVIDIA GPU telemetry." if adapters else "nvidia-smi returned no GPU rows.",
        "adapters": adapters,
    }


def _collect_libre_hardware_monitor(config: AppConfig) -> dict[str, Any]:
    dll_path = _resolve_libre_hardware_monitor_path()
    if dll_path is None:
        return {
            "provider": LIBRE_HARDWARE_MONITOR_PROVIDER_NAME,
            "available": False,
            "state": "unavailable",
            "detail": "LibreHardwareMonitor is not installed in a known local path.",
            "cpu": {},
            "adapters": [],
            "thermal": {"sensors": [], "fans": [], "pump_rpm": None},
        }
    escaped_dll = str(dll_path).replace("'", "''")
    payload = _run_powershell_json(
        config,
        f"""
        $dll = '{escaped_dll}'
        if (-not (Test-Path $dll)) {{
            [pscustomobject]@{{ provider = '{LIBRE_HARDWARE_MONITOR_PROVIDER_NAME}'; available = $false; state = 'unavailable'; detail = 'LibreHardwareMonitor DLL not found.'; cpu = $null; adapters = @(); thermal = [pscustomobject]@{{ sensors = @(); fans = @(); pump_rpm = $null }} }} | ConvertTo-Json -Compress -Depth 8
            return
        }}
        try {{
            Add-Type -Path $dll -ErrorAction Stop
            $computer = [LibreHardwareMonitor.Hardware.Computer]::new()
            $computer.IsCpuEnabled = $true
            $computer.IsGpuEnabled = $true
            $computer.IsMotherboardEnabled = $true
            $computer.IsControllerEnabled = $true
            $computer.Open()
        }} catch {{
            [pscustomobject]@{{ provider = '{LIBRE_HARDWARE_MONITOR_PROVIDER_NAME}'; available = $false; state = 'failed'; detail = $_.Exception.Message; cpu = $null; adapters = @(); thermal = [pscustomobject]@{{ sensors = @(); fans = @(); pump_rpm = $null }} }} | ConvertTo-Json -Compress -Depth 8
            return
        }}
        function Update-HardwareTree($hardware) {{
            $hardware.Update()
            foreach ($sub in @($hardware.SubHardware)) {{
                Update-HardwareTree $sub
            }}
        }}
        foreach ($hardware in @($computer.Hardware)) {{
            Update-HardwareTree $hardware
        }}
        $cpuPayload = $null
        $gpuPayloads = @()
        $thermalSensors = @()
        $fanSensors = @()
        foreach ($hardware in @($computer.Hardware)) {{
            $hardwareName = [string]$hardware.Name
            $hardwareType = [string]$hardware.HardwareType
            $sensors = @($hardware.Sensors)
            if ($hardwareType -eq 'Cpu') {{
                $cpuPayload = [pscustomobject]@{{ name = $hardwareName; utilization_percent = $null; package_temperature_c = $null; package_power_w = $null; effective_clock_mhz = $null; throttle_flags = @() }}
                $cpuUtilSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Load' -and [string]$_.Name -eq 'CPU Total' }} | Select-Object -First 1
                if ($cpuUtilSensor -and $cpuUtilSensor.Value -ne $null) {{ $cpuPayload.utilization_percent = [math]::Round([double]$cpuUtilSensor.Value, 2) }}
                $cpuTempSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Temperature' -and ([string]$_.Name -match 'Package|Tctl|Tdie') -and $_.Value -gt 0 -and $_.Value -lt 200 }} | Select-Object -First 1
                if ($cpuTempSensor -and $cpuTempSensor.Value -ne $null) {{ $cpuPayload.package_temperature_c = [math]::Round([double]$cpuTempSensor.Value, 1) }}
                $cpuPowerSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Power' -and ([string]$_.Name -match 'Package|CPU Package') -and $_.Value -gt 0 }} | Select-Object -First 1
                if ($cpuPowerSensor -and $cpuPowerSensor.Value -ne $null) {{ $cpuPayload.package_power_w = [math]::Round([double]$cpuPowerSensor.Value, 2) }}
                $cpuClockSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Clock' -and ([string]$_.Name -match 'Core Average|Bus Speed|Core #') -and $_.Value -gt 0 }} | Sort-Object Value -Descending | Select-Object -First 1
                if ($cpuClockSensor -and $cpuClockSensor.Value -ne $null) {{ $cpuPayload.effective_clock_mhz = [math]::Round([double]$cpuClockSensor.Value, 0) }}
            }}
            if ($hardwareType -match '^Gpu') {{
                $gpuPayload = [pscustomobject]@{{ name = $hardwareName; utilization_percent = $null; temperature_c = $null; hotspot_temperature_c = $null; memory_junction_temperature_c = $null; power_w = $null; core_clock_mhz = $null; memory_clock_mhz = $null; vram_total_bytes = $null; vram_used_bytes = $null; fan_rpm = $null; perf_limit_flags = @() }}
                $gpuUtilSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Load' -and ([string]$_.Name -eq 'GPU Core' -or [string]$_.Name -match 'D3D 3D') -and $_.Value -ge 0 }} | Sort-Object Value -Descending | Select-Object -First 1
                if ($gpuUtilSensor -and $gpuUtilSensor.Value -ne $null) {{ $gpuPayload.utilization_percent = [math]::Round([double]$gpuUtilSensor.Value, 2) }}
                $gpuTempSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Temperature' -and ([string]$_.Name -eq 'GPU Core' -or [string]$_.Name -match 'VR SoC|Core') -and $_.Value -gt 0 -and $_.Value -lt 200 }} | Select-Object -First 1
                if ($gpuTempSensor -and $gpuTempSensor.Value -ne $null) {{ $gpuPayload.temperature_c = [math]::Round([double]$gpuTempSensor.Value, 1) }}
                $gpuHotspotSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Temperature' -and [string]$_.Name -match 'Hot Spot' -and $_.Value -gt 0 -and $_.Value -lt 200 }} | Select-Object -First 1
                if ($gpuHotspotSensor -and $gpuHotspotSensor.Value -ne $null) {{ $gpuPayload.hotspot_temperature_c = [math]::Round([double]$gpuHotspotSensor.Value, 1) }}
                $gpuMemoryJunctionSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Temperature' -and [string]$_.Name -match 'Memory Junction' -and $_.Value -gt 0 -and $_.Value -lt 200 }} | Select-Object -First 1
                if ($gpuMemoryJunctionSensor -and $gpuMemoryJunctionSensor.Value -ne $null) {{ $gpuPayload.memory_junction_temperature_c = [math]::Round([double]$gpuMemoryJunctionSensor.Value, 1) }}
                $gpuPowerSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Power' -and ([string]$_.Name -match 'Package|GPU Core') -and $_.Value -gt 0 }} | Sort-Object Value -Descending | Select-Object -First 1
                if ($gpuPowerSensor -and $gpuPowerSensor.Value -ne $null) {{ $gpuPayload.power_w = [math]::Round([double]$gpuPowerSensor.Value, 2) }}
                $gpuCoreClockSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Clock' -and [string]$_.Name -eq 'GPU Core' -and $_.Value -gt 0 }} | Select-Object -First 1
                if ($gpuCoreClockSensor -and $gpuCoreClockSensor.Value -ne $null) {{ $gpuPayload.core_clock_mhz = [math]::Round([double]$gpuCoreClockSensor.Value, 0) }}
                $gpuMemoryClockSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Clock' -and [string]$_.Name -eq 'GPU Memory' -and $_.Value -gt 0 }} | Select-Object -First 1
                if ($gpuMemoryClockSensor -and $gpuMemoryClockSensor.Value -ne $null) {{ $gpuPayload.memory_clock_mhz = [math]::Round([double]$gpuMemoryClockSensor.Value, 0) }}
                $gpuMemoryTotalSensor = $sensors | Where-Object {{ ([string]$_.SensorType -eq 'SmallData' -or [string]$_.SensorType -eq 'Data') -and [string]$_.Name -match 'Memory Total' -and $_.Value -gt 0 }} | Select-Object -First 1
                if ($gpuMemoryTotalSensor -and $gpuMemoryTotalSensor.Value -ne $null) {{ $gpuPayload.vram_total_bytes = [int64]([double]$gpuMemoryTotalSensor.Value * 1MB) }}
                $gpuMemoryUsedSensor = $sensors | Where-Object {{ ([string]$_.SensorType -eq 'SmallData' -or [string]$_.SensorType -eq 'Data') -and [string]$_.Name -match 'Memory Used' -and $_.Value -ge 0 }} | Select-Object -First 1
                if ($gpuMemoryUsedSensor -and $gpuMemoryUsedSensor.Value -ne $null) {{ $gpuPayload.vram_used_bytes = [int64]([double]$gpuMemoryUsedSensor.Value * 1MB) }}
                $gpuFanSensor = $sensors | Where-Object {{ [string]$_.SensorType -eq 'Fan' -and $_.Value -gt 0 }} | Select-Object -First 1
                if ($gpuFanSensor -and $gpuFanSensor.Value -ne $null) {{ $gpuPayload.fan_rpm = [int]([math]::Round([double]$gpuFanSensor.Value, 0)) }}
                $gpuPayloads += $gpuPayload
            }}
            foreach ($sensor in $sensors) {{
                $sensorType = [string]$sensor.SensorType
                if ($sensorType -eq 'Temperature' -and $sensor.Value -gt 0 -and $sensor.Value -lt 200) {{
                    $thermalSensors += [pscustomobject]@{{ label = if ($hardwareName) {{ "$hardwareName - $($sensor.Name)" }} else {{ [string]$sensor.Name }}; temperature_c = [math]::Round([double]$sensor.Value, 1); source = '{LIBRE_HARDWARE_MONITOR_PROVIDER_NAME}' }}
                }}
                if ($sensorType -eq 'Fan' -and $sensor.Value -gt 0) {{
                    $fanSensors += [pscustomobject]@{{ label = if ($hardwareName) {{ "$hardwareName - $($sensor.Name)" }} else {{ [string]$sensor.Name }}; rpm = [int]([math]::Round([double]$sensor.Value, 0)); source = '{LIBRE_HARDWARE_MONITOR_PROVIDER_NAME}' }}
                }}
            }}
        }}
        try {{ $computer.Close() }} catch {{}}
        [pscustomobject]@{{ provider = '{LIBRE_HARDWARE_MONITOR_PROVIDER_NAME}'; available = $true; state = 'ready'; detail = "LibreHardwareMonitor sensors loaded from $dll"; cpu = $cpuPayload; adapters = @($gpuPayloads); thermal = [pscustomobject]@{{ sensors = @($thermalSensors); fans = @($fanSensors); pump_rpm = $null }} }} | ConvertTo-Json -Compress -Depth 8
        """,
    )
    if not isinstance(payload, dict):
        return {"provider": LIBRE_HARDWARE_MONITOR_PROVIDER_NAME, "available": False, "state": "failed", "detail": "LibreHardwareMonitor did not return a valid payload.", "cpu": {}, "adapters": [], "thermal": {"sensors": [], "fans": [], "pump_rpm": None}}
    adapters = payload.get("adapters")
    if isinstance(adapters, dict):
        payload["adapters"] = [adapters]
    elif not isinstance(adapters, list):
        payload["adapters"] = []
    return payload


def _run_powershell_json(config: AppConfig, script: str) -> Any:
    try:
        completed = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=max(float(config.hardware_telemetry.provider_timeout_seconds), 0.5),
            shell=False,
        )
    except Exception:
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def _load_history(config: AppConfig) -> dict[str, Any]:
    path = config.storage.state_dir / "hardware-telemetry-helper.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _save_history(config: AppConfig, history: dict[str, Any]) -> None:
    path = config.storage.state_dir / "hardware-telemetry-helper.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2, sort_keys=True), encoding="utf-8")


def _append_history_point(history: dict[str, Any], key: str, value: Any) -> None:
    numeric = _coerce_float(value)
    if numeric is None:
        return
    sampled_at = datetime.now(UTC)
    points = history.get(key, [])
    if not isinstance(points, list):
        points = []
    cutoff = sampled_at - timedelta(minutes=20)
    retained = [point for point in points if isinstance(point, dict) and _parse_timestamp(str(point.get("sampled_at", ""))) and _parse_timestamp(str(point.get("sampled_at", ""))) >= cutoff]
    retained.append({"sampled_at": sampled_at.isoformat(), "value": round(numeric, 4)})
    history[key] = retained[-180:]


def _rolling_average(points: Any, *, window_seconds: int) -> float | None:
    if not isinstance(points, list) or window_seconds <= 0:
        return None
    cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)
    values = [
        _coerce_float(point.get("value"))
        for point in points
        if isinstance(point, dict) and (timestamp := _parse_timestamp(str(point.get("sampled_at", "")))) and timestamp >= cutoff
    ]
    clean_values = [value for value in values if value is not None]
    if not clean_values:
        return None
    return round(sum(clean_values) / len(clean_values), 2)


def _series_values(points: Any, *, limit: int) -> list[float]:
    if not isinstance(points, list) or limit <= 0:
        return []
    values = [_coerce_float(point.get("value")) for point in points if isinstance(point, dict)]
    return [round(value, 2) for value in values if value is not None][-limit:]


def _estimate_seconds(remaining_capacity_mwh: Any, draw_watts: Any) -> int | None:
    capacity = _coerce_float(remaining_capacity_mwh)
    draw = _coerce_float(draw_watts)
    if capacity is None or draw is None or draw <= 0:
        return None
    return max(int((capacity * 3600) / (draw * 1000)), 0)


def _estimate_seconds_to_full(remaining_capacity_mwh: Any, full_charge_capacity_mwh: Any, charge_watts: Any) -> int | None:
    remaining = _coerce_float(remaining_capacity_mwh)
    full = _coerce_float(full_charge_capacity_mwh)
    rate = _coerce_float(charge_watts)
    if remaining is None or full is None or rate is None or rate <= 0 or full <= remaining:
        return None
    return max(int(((full - remaining) * 3600) / (rate * 1000)), 0)


def _merge_value(target: dict[str, Any], overlay: dict[str, Any]) -> None:
    for key, value in overlay.items():
        if isinstance(value, dict):
            existing = target.get(key)
            if not isinstance(existing, dict):
                target[key] = deepcopy(value)
                continue
            _merge_value(existing, value)
            continue
        if isinstance(value, list):
            target[key] = deepcopy(value)
            continue
        if value not in {None, ""}:
            target[key] = value


def _matched_gpu_index(adapters: list[dict[str, Any]], candidate: dict[str, Any], *, fallback_index: int) -> int:
    candidate_name = str(candidate.get("name") or "").strip().lower()
    if candidate_name:
        for index, adapter in enumerate(adapters):
            if str(adapter.get("name") or "").strip().lower() == candidate_name:
                return index
    return fallback_index


def _coerce_int(value: Any) -> int | None:
    if value in {None, "", 0xFFFFFFFF}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value in {None, "", 0xFFFFFFFF}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dict_has_signal(payload: Any, keys: tuple[str, ...]) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(_has_signal(payload.get(key)) for key in keys)


def _has_signal(value: Any) -> bool:
    return value not in (None, "") and value != [] and value != {}


def _parse_timestamp(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _resolve_nvidia_smi_path() -> Path | None:
    discovered = shutil.which("nvidia-smi")
    if discovered:
        return Path(discovered)
    candidates = [
        Path(os.environ.get("SystemRoot", "")) / "System32" / "nvidia-smi.exe",
        Path(os.environ.get("ProgramFiles", "")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
        Path(os.environ.get("ProgramW6432", "")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
    ]
    for candidate in candidates:
        if str(candidate).strip() and candidate.exists():
            return candidate
    return None


def _resolve_libre_hardware_monitor_path() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "RivaTuner Statistics Server" / "Plugins" / "Client" / "LHMDataProvider" / "LibreHardwareMonitorLib.dll",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "CapFrameX" / "LibreHardwareMonitorLib.dll",
        Path(os.environ.get("ProgramFiles", "")) / "RivaTuner Statistics Server" / "Plugins" / "Client" / "LHMDataProvider" / "LibreHardwareMonitorLib.dll",
    ]
    for candidate in candidates:
        if str(candidate).strip() and candidate.exists():
            return candidate
    return None


def _parse_vendor_number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"n/a", "[n/a]", "nan"}:
        return None
    text = text.replace("[", "").replace("]", "")
    try:
        return float(text)
    except ValueError:
        return None


def _mib_to_bytes(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 1024 * 1024))


def _parse_perf_limit_flags(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text in {"0", "0x0000000000000000", "N/A", "[N/A]"}:
        return []
    return [text]


def _is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _resolve_hwinfo_path(config: AppConfig) -> Path | None:
    telemetry_config = config.hardware_telemetry
    if not telemetry_config.hwinfo_enabled:
        return None
    configured = str(telemetry_config.hwinfo_executable_path or "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.exists() else path

    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "HWiNFO64" / "HWiNFO64.EXE",
        Path(os.environ.get("ProgramFiles", "")) / "HWiNFO64" / "HWiNFO64.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "HWiNFO64" / "HWiNFO64.EXE",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "HWiNFO64" / "HWiNFO64.exe",
    ]
    for candidate in candidates:
        if str(candidate).strip() and candidate.exists():
            return candidate
    return None
