from __future__ import annotations

import ctypes
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
import sys
from typing import Any

from stormhelm.config.models import AppConfig


HELPER_PROVIDER_NAME = "stormhelm_hardware_helper"
NATIVE_PROVIDER_NAME = "windows_native"
HWINFO_PROVIDER_NAME = "hwinfo_enrichment"


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
        }
    )
    snapshot["freshness"]["reason"] = reason
    snapshot["sources"]["helper"] = {"provider": HELPER_PROVIDER_NAME, "state": "unreachable", "detail": reason}
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
                if index >= len(merged["gpu"]):
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
                    "perf_limit_flags",
                ):
                    if _has_signal(adapter.get(key)):
                        merged["gpu"][index][key] = adapter[key]
                if not merged["gpu"][index].get("name") and adapter.get("name"):
                    merged["gpu"][index]["name"] = adapter["name"]
                if not merged["gpu"][index].get("driver_version") and adapter.get("driver_version"):
                    merged["gpu"][index]["driver_version"] = adapter["driver_version"]

    merged["thermal"] = deepcopy(snapshot.get("thermal", {}))
    merged["capabilities"] = deepcopy(snapshot.get("capabilities", {}))
    merged["sources"] = deepcopy(snapshot.get("sources", {}))
    merged["freshness"] = deepcopy(snapshot.get("freshness", {}))
    merged["monitoring"] = deepcopy(snapshot.get("monitoring", {}))
    merged["hardware_telemetry"] = deepcopy(snapshot)
    return merged


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

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(float(self.config.hardware_telemetry.helper_timeout_seconds), 0.5),
                env=env,
                cwd=str(self.config.project_root),
                shell=False,
            )
        except Exception as exc:
            return build_helper_unreachable_snapshot(sampling_tier=sampling_tier, reason=str(exc), installed=self.helper_installed())

        if completed.returncode != 0:
            reason = completed.stderr.strip() or completed.stdout.strip() or f"helper_exit_{completed.returncode}"
            return build_helper_unreachable_snapshot(sampling_tier=sampling_tier, reason=reason, installed=self.helper_installed())

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return build_helper_unreachable_snapshot(sampling_tier=sampling_tier, reason=f"invalid_helper_json:{exc}", installed=self.helper_installed())
        if not isinstance(payload, dict):
            return build_helper_unreachable_snapshot(sampling_tier=sampling_tier, reason="invalid_helper_payload", installed=self.helper_installed())
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
    snapshot["capabilities"].update({"helper_installed": True, "helper_reachable": True, "elevated_access_active": _is_elevated()})
    snapshot["sources"]["helper"] = {"provider": HELPER_PROVIDER_NAME, "state": "reachable", "detail": "Bundled helper responded."}

    snapshot["cpu"] = _collect_cpu(config)
    snapshot["gpu"] = _collect_gpu(config)
    snapshot["thermal"] = _collect_thermal(config)
    snapshot["power"] = _collect_power(config)

    snapshot["capabilities"].update(
        {
            "cpu_deep_telemetry_available": _dict_has_signal(snapshot["cpu"], ("package_temperature_c", "utilization_percent", "effective_clock_mhz")),
            "gpu_deep_telemetry_available": any(_dict_has_signal(adapter, ("utilization_percent", "temperature_c", "power_w", "vram_used_bytes")) for adapter in snapshot["gpu"].get("adapters", []) if isinstance(adapter, dict)),
            "thermal_sensor_availability": bool(snapshot["thermal"].get("sensors") or snapshot["thermal"].get("fans")),
            "power_current_available": snapshot["power"].get("battery_current_ma") is not None,
        }
    )
    snapshot["sources"].update(
        {
            "cpu": {"provider": NATIVE_PROVIDER_NAME, "confidence": "best_effort"},
            "gpu": {"provider": NATIVE_PROVIDER_NAME, "confidence": "best_effort"},
            "thermal": {"provider": NATIVE_PROVIDER_NAME, "confidence": "best_effort"},
            "power": {"provider": NATIVE_PROVIDER_NAME, "confidence": "measured"},
        }
    )

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
    snapshot["capabilities"]["hwinfo_enrichment_available"] = bool(hwinfo_path and hwinfo_path.exists())
    snapshot["capabilities"]["hwinfo_enrichment_active"] = False
    snapshot["sources"]["hwinfo"] = {"provider": HWINFO_PROVIDER_NAME, "state": "available" if hwinfo_path and hwinfo_path.exists() else "unavailable", "detail": str(hwinfo_path) if hwinfo_path else "not_configured"}
    _save_history(config, history)
    return snapshot


def _empty_snapshot(*, sampling_tier: str) -> dict[str, Any]:
    return {
        "cpu": {"package_temperature_c": None, "package_power_w": None, "base_clock_mhz": None, "effective_clock_mhz": None, "utilization_percent": None, "throttle_flags": []},
        "gpu": {"adapters": []},
        "thermal": {"sensors": [], "fans": [], "pump_rpm": None, "recent_trend_c": []},
        "power": {"battery_percent": None, "ac_line_status": "unknown", "power_source": "unknown", "battery_current_ma": None, "battery_voltage_mv": None, "charge_rate_w": None, "discharge_rate_w": None, "remaining_capacity_mwh": None, "full_charge_capacity_mwh": None, "design_capacity_mwh": None, "wear_percent": None, "health_percent": None, "instant_draw_w": None, "rolling_average_draw_w": None, "instant_estimate_seconds": None, "stabilized_estimate_seconds": None, "time_to_full_seconds": None, "time_to_empty_seconds": None, "recent_draw_w": []},
        "capabilities": {"helper_installed": True, "helper_reachable": True, "elevated_access_active": False, "cpu_deep_telemetry_available": False, "gpu_deep_telemetry_available": False, "thermal_sensor_availability": False, "power_current_available": False, "hwinfo_enrichment_available": False, "hwinfo_enrichment_active": False},
        "sources": {"metrics": {}},
        "freshness": {"sampled_at": datetime.now(UTC).isoformat(), "sample_age_seconds": 0.0, "sampling_tier": str(sampling_tier or "active").strip().lower() or "active", "rolling_window_available": False},
        "monitoring": {"sampling_tier": str(sampling_tier or "active").strip().lower() or "active", "history_points": {}, "rolling_window_seconds": 0, "diagnostic_burst_active": False},
    }


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


def _run_powershell_json(config: AppConfig, script: str) -> Any:
    try:
        completed = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=max(float(config.hardware_telemetry.helper_timeout_seconds), 0.5),
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
