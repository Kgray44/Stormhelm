from __future__ import annotations

import ctypes
import html
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import re
import urllib.parse
import urllib.request
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any

from stormhelm.config.models import AppConfig
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.network.providers import ObservedThroughputProvider
from stormhelm.core.system.hardware_telemetry import (
    HardwareTelemetryHelperClient,
    helper_cache_ttl_seconds,
    overlay_power_status,
    overlay_resource_status,
)

if TYPE_CHECKING:
    from stormhelm.core.network.monitor import NetworkMonitor


_COMMON_APP_COMPATIBILITY: dict[str, dict[str, Any]] = {
    "snipping tool": {
        "builtin": True,
        "aliases": {
            "snipping tool",
            "snippingtool",
            "snip sketch",
            "screen clipping host",
            "screenclippinghost",
            "screen sketch",
            "screensketch",
        },
        "process_names": {"snippingtool", "screenclippinghost"},
        "executables": {"snippingtool", "screenclippinghost"},
        "window_titles": {"snipping tool", "snip sketch"},
        "package_terms": {"microsoft screensketch", "screensketch", "snippingtool"},
        "host_processes": {"applicationframehost"},
    },
    "discord": {
        "builtin": False,
        "aliases": {"discord"},
        "process_names": {"discord"},
        "executables": {"discord"},
        "window_titles": {"discord"},
        "package_terms": set(),
        "host_processes": set(),
    },
    "calculator": {
        "builtin": True,
        "aliases": {"calculator", "calc", "calculatorapp"},
        "process_names": {"calculatorapp", "calculator"},
        "executables": {"calc", "calculatorapp"},
        "window_titles": {"calculator"},
        "package_terms": {"windowscalculator", "microsoft windowscalculator"},
        "host_processes": {"applicationframehost"},
    },
    "notepad": {
        "builtin": True,
        "aliases": {"notepad", "windows notepad", "windowsnotepad"},
        "process_names": {"notepad"},
        "executables": {"notepad"},
        "window_titles": {"notepad"},
        "package_terms": {"windowsnotepad", "microsoft windowsnotepad"},
        "host_processes": set(),
    },
    "paint": {
        "builtin": True,
        "aliases": {"paint", "mspaint", "paint app"},
        "process_names": {"mspaint"},
        "executables": {"mspaint"},
        "window_titles": {"paint"},
        "package_terms": {"mspaint", "paint"},
        "host_processes": set(),
    },
    "task manager": {
        "builtin": True,
        "aliases": {"task manager", "taskmgr", "taskmgr exe"},
        "process_names": {"taskmgr"},
        "executables": {"taskmgr"},
        "window_titles": {"task manager"},
        "package_terms": set(),
        "host_processes": set(),
    },
    "settings": {
        "builtin": True,
        "aliases": {"settings", "windows settings", "system settings", "immersivecontrolpanel"},
        "process_names": {"systemsettings", "immersivecontrolpanel"},
        "executables": {"systemsettings", "immersivecontrolpanel"},
        "window_titles": {"settings", "windows settings"},
        "package_terms": {"immersivecontrolpanel"},
        "host_processes": {"applicationframehost"},
    },
    "photos": {
        "builtin": True,
        "aliases": {"photos", "microsoft photos", "photos app"},
        "process_names": {"photos"},
        "executables": {"photos", "microsoft photos"},
        "window_titles": {"photos", "microsoft photos"},
        "package_terms": {"windows photos", "microsoft windows photos", "microsoft photos"},
        "host_processes": {"applicationframehost"},
    },
    "file explorer": {
        "builtin": True,
        "aliases": {"file explorer", "explorer", "windows explorer", "explorer exe"},
        "process_names": {"explorer"},
        "executables": {"explorer"},
        "window_titles": {"file explorer", "windows explorer"},
        "package_terms": set(),
        "host_processes": set(),
    },
}

_BUILTIN_APP_ALIAS_GROUPS: dict[str, set[str]] = {
    key: {
        key,
        *{str(term) for group_name, terms in profile.items() if group_name != "builtin" for term in (terms if isinstance(terms, set) else [])},
    }
    for key, profile in _COMMON_APP_COMPATIBILITY.items()
    if bool(profile.get("builtin"))
}

_GENERIC_APP_MATCH_TOKENS = {
    "app",
    "application",
    "applications",
    "desktop",
    "exe",
    "experience",
    "frame",
    "helper",
    "host",
    "launcher",
    "microsoft",
    "service",
    "system",
    "tool",
    "tools",
    "windows",
}


def _hidden_console_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {}
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0) or 0)
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0) or 0)
        kwargs["startupinfo"] = startupinfo
    return kwargs


@dataclass(slots=True)
class SystemProbe:
    config: AppConfig
    preferences: PreferencesRepository | None = None
    network_monitor: NetworkMonitor | None = None
    _battery_report_cache: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _battery_report_cached_at: float = field(default=0.0, init=False, repr=False)
    _hardware_telemetry_cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _hardware_telemetry_cached_at: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    _HOME_LOCATION_KEY = "location.saved.home"
    _NAMED_LOCATIONS_KEY = "location.saved.named"

    def machine_status(self) -> dict[str, Any]:
        now = datetime.now().astimezone()
        return {
            "machine_name": os.environ.get("COMPUTERNAME") or platform.node(),
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "local_time": now.isoformat(),
            "timezone": str(now.tzinfo),
        }

    def hardware_telemetry_snapshot(
        self,
        *,
        sampling_tier: str = "active",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        tier = str(sampling_tier or "active").strip().lower() or "active"
        now = monotonic()
        cached = self._hardware_telemetry_cache.get(tier)
        cached_at = self._hardware_telemetry_cached_at.get(tier, 0.0)
        if not force_refresh and cached is not None and (now - cached_at) < helper_cache_ttl_seconds(self.config, tier):
            snapshot = deepcopy(cached)
            freshness = snapshot.get("freshness")
            if isinstance(freshness, dict):
                freshness["sample_age_seconds"] = round(max(now - cached_at, 0.0), 2)
            return snapshot

        snapshot = HardwareTelemetryHelperClient(self.config).snapshot(sampling_tier=tier)
        if not isinstance(snapshot, dict):
            snapshot = {"capabilities": {"helper_reachable": False}, "freshness": {"sampling_tier": tier}}
        freshness = snapshot.get("freshness")
        if isinstance(freshness, dict):
            freshness["sampling_tier"] = tier
            freshness["sample_age_seconds"] = 0.0

        completed_at = monotonic()
        self._hardware_telemetry_cache[tier] = deepcopy(snapshot)
        self._hardware_telemetry_cached_at[tier] = completed_at
        return snapshot

    def power_status(self) -> dict[str, Any]:
        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_byte),
                ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte),
                ("Reserved1", ctypes.c_byte),
                ("BatteryLifeTime", ctypes.c_uint32),
                ("BatteryFullLifeTime", ctypes.c_uint32),
            ]

        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return overlay_power_status({"available": False}, self.hardware_telemetry_snapshot(sampling_tier="active"))
        percent = None if status.BatteryLifePercent == 255 else int(status.BatteryLifePercent)
        nt_battery = self._nt_battery_state()
        remaining_capacity_mwh = self._coerce_int(nt_battery.get("remaining_capacity_mwh"))
        full_charge_capacity_mwh = self._coerce_int(nt_battery.get("full_charge_capacity_mwh"))
        design_capacity_mwh = None
        charge_rate_mw = self._coerce_int(nt_battery.get("charge_rate_mw"))
        discharge_rate_mw = self._coerce_int(nt_battery.get("discharge_rate_mw"))
        battery_report = self._battery_report_summary()
        if full_charge_capacity_mwh is None:
            full_charge_capacity_mwh = self._coerce_int(battery_report.get("full_charge_capacity_mwh"))
        if design_capacity_mwh is None:
            design_capacity_mwh = self._coerce_int(battery_report.get("design_capacity_mwh"))
        if charge_rate_mw is None:
            charge_rate_mw = self._coerce_int(battery_report.get("estimated_charge_rate_mw"))
        if discharge_rate_mw is None:
            discharge_rate_mw = self._coerce_int(battery_report.get("estimated_discharge_rate_mw"))
        if remaining_capacity_mwh is None and full_charge_capacity_mwh is not None and percent is not None:
            remaining_capacity_mwh = int(full_charge_capacity_mwh * percent / 100)
        time_to_full_seconds = None
        if charge_rate_mw and full_charge_capacity_mwh and remaining_capacity_mwh is not None and full_charge_capacity_mwh > remaining_capacity_mwh:
            time_to_full_seconds = int(max((full_charge_capacity_mwh - remaining_capacity_mwh) * 3600 / charge_rate_mw, 0))
        time_to_empty_seconds = self._coerce_int(nt_battery.get("time_to_empty_seconds"))
        if discharge_rate_mw and remaining_capacity_mwh is not None:
            time_to_empty_seconds = int(max(remaining_capacity_mwh * 3600 / discharge_rate_mw, 0))
        result = {
            "available": True,
            "ac_line_status": {0: "offline", 1: "online"}.get(int(status.ACLineStatus), "unknown"),
            "battery_percent": percent,
            "battery_flag": int(status.BatteryFlag),
            "battery_saver": bool(int(status.BatteryFlag) & 8),
            "seconds_remaining": None if status.BatteryLifeTime == 0xFFFFFFFF else int(status.BatteryLifeTime),
            "power_source": "ac" if int(status.ACLineStatus) == 1 else "battery" if int(status.ACLineStatus) == 0 else "unknown",
            "remaining_capacity_mwh": remaining_capacity_mwh,
            "full_charge_capacity_mwh": full_charge_capacity_mwh,
            "design_capacity_mwh": design_capacity_mwh,
            "charge_rate_mw": charge_rate_mw,
            "discharge_rate_mw": discharge_rate_mw,
            "charge_rate_watts": round(charge_rate_mw / 1000, 2) if charge_rate_mw else None,
            "discharge_rate_watts": round(discharge_rate_mw / 1000, 2) if discharge_rate_mw else None,
            "time_to_full_seconds": time_to_full_seconds,
            "time_to_empty_seconds": time_to_empty_seconds,
            "power_history_source": str(battery_report.get("source", "")).strip() or None,
        }
        return overlay_power_status(result, self.hardware_telemetry_snapshot(sampling_tier="active"))

    def power_projection(
        self,
        *,
        metric: str = "time_to_percent",
        target_percent: int | None = None,
        assume_unplugged: bool = False,
    ) -> dict[str, Any]:
        status = self.power_status()
        if not status.get("available"):
            return {"available": False, "metric": metric, "reliable": False, "reason": "power_unavailable"}

        battery_report = self._battery_report_summary()
        battery_percent = self._coerce_int(status.get("battery_percent"))
        ac_line_status = str(status.get("ac_line_status", "unknown"))
        remaining_capacity_mwh = self._coerce_int(status.get("remaining_capacity_mwh"))
        full_charge_capacity_mwh = self._coerce_int(status.get("full_charge_capacity_mwh"))
        charge_rate_mw = self._coerce_int(status.get("charge_rate_mw"))
        discharge_rate_mw = self._coerce_int(status.get("discharge_rate_mw"))
        charge_rate_watts = status.get("charge_rate_watts")
        discharge_rate_watts = status.get("discharge_rate_watts")
        instant_power_draw_watts = status.get("instant_power_draw_watts")
        rolling_power_draw_watts = status.get("rolling_power_draw_watts")
        helper_stabilized_discharge_watts = rolling_power_draw_watts if ac_line_status != "online" else None
        helper_instant_discharge_watts = discharge_rate_watts or (instant_power_draw_watts if ac_line_status != "online" else None)
        seconds_remaining = self._coerce_int(status.get("seconds_remaining"))
        report_full_charge_capacity_mwh = self._coerce_int(battery_report.get("full_charge_capacity_mwh"))
        report_charge_rate_mw = self._coerce_int(battery_report.get("estimated_charge_rate_mw"))
        report_discharge_rate_mw = self._coerce_int(battery_report.get("estimated_discharge_rate_mw"))
        used_report_capacity = False
        used_report_charge_rate = False
        used_report_discharge_rate = False

        if full_charge_capacity_mwh is None and report_full_charge_capacity_mwh is not None:
            full_charge_capacity_mwh = report_full_charge_capacity_mwh
            used_report_capacity = True
        if charge_rate_mw is None and report_charge_rate_mw is not None:
            charge_rate_mw = report_charge_rate_mw
            used_report_charge_rate = True
        if discharge_rate_mw is None and report_discharge_rate_mw is not None:
            discharge_rate_mw = report_discharge_rate_mw
            used_report_discharge_rate = True
        if charge_rate_mw is None and charge_rate_watts is not None:
            charge_rate_mw = int(round(float(charge_rate_watts) * 1000))
        if discharge_rate_mw is None and discharge_rate_watts is not None:
            discharge_rate_mw = int(round(float(discharge_rate_watts) * 1000))
        if remaining_capacity_mwh is None and full_charge_capacity_mwh is not None and battery_percent is not None:
            remaining_capacity_mwh = int(full_charge_capacity_mwh * battery_percent / 100)
            used_report_capacity = used_report_capacity or report_full_charge_capacity_mwh is not None

        notes: list[str] = []
        reliable = False
        projection_seconds: int | None = None
        rate_source = "unavailable"

        if metric == "power_draw":
            watts = instant_power_draw_watts or rolling_power_draw_watts or discharge_rate_watts or charge_rate_watts
            if watts is None:
                fallback_rate_mw = discharge_rate_mw or charge_rate_mw
                watts = round(fallback_rate_mw / 1000, 2) if fallback_rate_mw else None
                reliable = watts is not None
                rate_source = "battery_report_history" if reliable else "unavailable"
            else:
                reliable = True
                rate_source = "helper_instant" if instant_power_draw_watts is not None else "helper_rolling_average" if rolling_power_draw_watts is not None else "system_rate"
            return {
                "available": True,
                "metric": metric,
                "battery_percent": battery_percent,
                "ac_line_status": ac_line_status,
                "power_draw_watts": watts,
                "reliable": reliable,
                "rate_source": rate_source,
                "notes": notes,
            }

        if metric == "drain_rate":
            watts = helper_instant_discharge_watts or helper_stabilized_discharge_watts
            if watts is not None:
                reliable = True
                rate_source = "helper_instant" if helper_instant_discharge_watts is not None else "helper_rolling_average"
            elif discharge_rate_mw is not None:
                watts = round(discharge_rate_mw / 1000, 2)
                reliable = True
                rate_source = "battery_report_history"
            else:
                notes.append("The current discharge rate is not exposed by the OS on this machine.")
            return {
                "available": True,
                "metric": metric,
                "battery_percent": battery_percent,
                "ac_line_status": ac_line_status,
                "power_draw_watts": watts,
                "reliable": reliable,
                "rate_source": rate_source,
                "notes": notes,
            }

        if metric == "time_to_empty":
            if ac_line_status == "online" and not assume_unplugged:
                notes.append("The battery is currently on AC power, so time-to-empty is not active until it is discharging.")
            if helper_stabilized_discharge_watts and remaining_capacity_mwh is not None:
                projection_seconds = int(max(remaining_capacity_mwh * 3600 / (helper_stabilized_discharge_watts * 1000), 0))
                reliable = True
                rate_source = "helper_rolling_average"
            elif helper_instant_discharge_watts and remaining_capacity_mwh is not None:
                projection_seconds = int(max(remaining_capacity_mwh * 3600 / (helper_instant_discharge_watts * 1000), 0))
                reliable = True
                rate_source = "helper_instant"
            elif discharge_rate_mw and remaining_capacity_mwh is not None:
                projection_seconds = int(max(remaining_capacity_mwh * 3600 / discharge_rate_mw, 0))
                reliable = True
                rate_source = "battery_report_history" if used_report_discharge_rate or used_report_capacity else "capacity_rate"
            elif seconds_remaining is not None:
                projection_seconds = seconds_remaining
                reliable = True
                rate_source = "system_estimate"
            else:
                notes.append("The system is not exposing a reliable time-to-empty estimate.")

        if metric == "time_to_percent":
            requested = target_percent if isinstance(target_percent, int) else None
            if requested is None:
                requested = 100
            if battery_percent is None:
                notes.append("The current battery percentage is unavailable, so threshold projection cannot be computed.")
            elif assume_unplugged and requested >= battery_percent:
                notes.append("That threshold would move upward while the battery is assumed to be discharging, so the projection is not physically meaningful.")
            elif assume_unplugged:
                helper_rate_watts = helper_stabilized_discharge_watts or helper_instant_discharge_watts
                if helper_rate_watts and remaining_capacity_mwh is not None:
                    if full_charge_capacity_mwh:
                        target_capacity = int(full_charge_capacity_mwh * requested / 100)
                        delta_capacity = max(remaining_capacity_mwh - target_capacity, 0)
                        projection_seconds = int(delta_capacity * 3600 / (helper_rate_watts * 1000))
                        reliable = True
                        rate_source = "helper_rolling_average" if helper_stabilized_discharge_watts is not None else "helper_instant"
                    else:
                        notes.append("The helper measured draw, but the system did not expose enough capacity data to project that threshold.")
                elif discharge_rate_mw and remaining_capacity_mwh is not None:
                    if full_charge_capacity_mwh:
                        target_capacity = int(full_charge_capacity_mwh * requested / 100)
                        delta_capacity = max(remaining_capacity_mwh - target_capacity, 0)
                        projection_seconds = int(delta_capacity * 3600 / discharge_rate_mw) if discharge_rate_mw else None
                        reliable = projection_seconds is not None
                        rate_source = "battery_report_history" if reliable and (used_report_discharge_rate or used_report_capacity) else "capacity_rate" if reliable else "unavailable"
                    else:
                        notes.append("The system is not exposing enough capacity data to project the unplugged threshold reliably.")
                elif seconds_remaining is not None and battery_percent and requested < battery_percent:
                    projection_seconds = int(seconds_remaining * ((battery_percent - requested) / max(battery_percent, 1)))
                    reliable = True
                    rate_source = "system_estimate"
                else:
                    notes.append("The system is not exposing a reliable discharge estimate for that unplugged projection.")
            else:
                if requested <= (battery_percent or 0):
                    projection_seconds = 0
                    reliable = True
                    rate_source = "already_at_threshold"
                elif charge_rate_watts and full_charge_capacity_mwh is not None and remaining_capacity_mwh is not None:
                    target_capacity = int(full_charge_capacity_mwh * requested / 100)
                    delta_capacity = max(target_capacity - remaining_capacity_mwh, 0)
                    projection_seconds = int(delta_capacity * 3600 / (charge_rate_watts * 1000))
                    reliable = True
                    rate_source = "helper_instant"
                elif charge_rate_mw and full_charge_capacity_mwh is not None and remaining_capacity_mwh is not None:
                    target_capacity = int(full_charge_capacity_mwh * requested / 100)
                    delta_capacity = max(target_capacity - remaining_capacity_mwh, 0)
                    projection_seconds = int(delta_capacity * 3600 / charge_rate_mw)
                    reliable = True
                    rate_source = "battery_report_history" if used_report_charge_rate or used_report_capacity else "capacity_rate"
                elif status.get("time_to_full_seconds") is not None and battery_percent is not None:
                    delta = requested - battery_percent
                    remaining_delta = max(100 - battery_percent, 1)
                    projection_seconds = int(status["time_to_full_seconds"] * (delta / remaining_delta))
                    reliable = True
                    rate_source = "capacity_rate"
                else:
                    notes.append("The system is not exposing a reliable time-to-full estimate for this charging threshold.")

        return {
            "available": True,
            "metric": metric,
            "target_percent": target_percent,
            "assume_unplugged": assume_unplugged,
            "battery_percent": battery_percent,
            "ac_line_status": ac_line_status,
            "power_draw_watts": rolling_power_draw_watts
            or instant_power_draw_watts
            or status.get("discharge_rate_watts")
            or status.get("charge_rate_watts")
            or (round((discharge_rate_mw or charge_rate_mw) / 1000, 2) if (discharge_rate_mw or charge_rate_mw) else None),
            "projection_seconds": projection_seconds,
            "projection_minutes": int(projection_seconds // 60) if projection_seconds is not None else None,
            "reliable": reliable,
            "rate_source": rate_source,
            "notes": notes,
        }

    def resource_status(self) -> dict[str, Any]:
        details = self._run_powershell_json(
            """
            $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed
            $os = Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory
            $gpu = Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion
            [pscustomobject]@{ cpu = $cpu; os = $os; gpu = $gpu } | ConvertTo-Json -Compress -Depth 5
            """
        ) or {}
        os_block = details.get("os") or {}
        total_kb = int(os_block.get("TotalVisibleMemorySize") or 0)
        free_kb = int(os_block.get("FreePhysicalMemory") or 0)
        result = {
            "cpu": {
                "name": (details.get("cpu") or {}).get("Name", platform.processor()),
                "cores": int((details.get("cpu") or {}).get("NumberOfCores") or 0),
                "logical_processors": int((details.get("cpu") or {}).get("NumberOfLogicalProcessors") or (os.cpu_count() or 0)),
                "max_clock_mhz": int((details.get("cpu") or {}).get("MaxClockSpeed") or 0),
            },
            "memory": {
                "total_bytes": total_kb * 1024,
                "free_bytes": free_kb * 1024,
                "used_bytes": max(total_kb - free_kb, 0) * 1024,
            },
            "gpu": [
                {
                    "name": str(item.get("Name", "")),
                    "adapter_ram": int(item.get("AdapterRAM") or 0),
                    "driver_version": str(item.get("DriverVersion", "")),
                }
                for item in self._ensure_list(details.get("gpu"))
                if isinstance(item, dict)
            ],
        }
        return overlay_resource_status(result, self.hardware_telemetry_snapshot(sampling_tier="active"))

    def storage_status(self) -> dict[str, Any]:
        drives = list(os.listdrives()) if hasattr(os, "listdrives") else [str(self.config.project_root.drive) + "\\"]
        entries: list[dict[str, Any]] = []
        for drive in drives:
            try:
                usage = shutil.disk_usage(drive)
            except OSError:
                continue
            entries.append(
                {
                    "drive": drive,
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                }
            )
        entries.sort(key=lambda item: item["drive"])
        return {"drives": entries}

    def network_status(self) -> dict[str, Any]:
        base = self._network_interface_status()
        snapshot = self.network_monitor.snapshot(diagnostic_burst=False) if self.network_monitor is not None else self._fallback_network_telemetry(base)
        merged = dict(base)
        merged.update(
            {
                "monitoring": snapshot.get("monitoring", {}),
                "quality": snapshot.get("quality", {}),
                "dns": snapshot.get("dns", {}),
                "throughput": snapshot.get("throughput", {}),
                "events": snapshot.get("events", []),
                "trend_points": snapshot.get("trend_points", []),
                "providers": snapshot.get("providers", {}),
                "source_debug": snapshot.get("source_debug", {}),
                "assessment": snapshot.get("assessment", {}),
            }
        )
        return merged

    def network_diagnosis(self, *, focus: str = "overview", diagnostic_burst: bool = False) -> dict[str, Any]:
        base = self._network_interface_status()
        telemetry = self.network_monitor.snapshot(diagnostic_burst=diagnostic_burst) if self.network_monitor is not None else self._fallback_network_telemetry(base)
        merged = dict(base)
        merged.update(telemetry)
        merged["focus"] = focus
        return merged

    def network_throughput(self, *, metric: str = "internet_speed") -> dict[str, Any]:
        normalized_metric = str(metric or "internet_speed").strip().lower() or "internet_speed"
        status = self.network_status()
        throughput = status.get("throughput", {}) if isinstance(status.get("throughput"), dict) else {}
        interfaces = status.get("interfaces", []) if isinstance(status.get("interfaces"), list) else []
        primary = interfaces[0] if interfaces and isinstance(interfaces[0], dict) else {}

        if (not throughput.get("available")) or throughput.get("state") in {"stale", "provider_unavailable", "waiting_for_baseline", "interval_too_short"}:
            measured = ObservedThroughputProvider(self).measure_current(primary_interface=primary)
            if isinstance(measured, dict):
                throughput = measured
                providers = dict(status.get("providers", {})) if isinstance(status.get("providers"), dict) else {}
                providers["observed_throughput"] = {
                    "state": measured.get("state"),
                    "label": measured.get("label"),
                    "detail": measured.get("detail"),
                    "available": measured.get("available"),
                    "source": measured.get("source"),
                    "sampled_at": measured.get("sampled_at"),
                    "last_sample_age_seconds": measured.get("last_sample_age_seconds"),
                    "unsupported_code": measured.get("unsupported_code"),
                    "unsupported_reason": measured.get("unsupported_reason"),
                }
                source_debug = dict(status.get("source_debug", {})) if isinstance(status.get("source_debug"), dict) else {}
                source_debug["throughput_primary"] = str(measured.get("source") or "net_adapter_statistics")
                source_debug["throughput_resolution"] = "active_measurement"
                status["providers"] = providers
                status["source_debug"] = source_debug
                status["throughput"] = measured

        selected_value = None
        if normalized_metric == "download_speed":
            selected_value = throughput.get("download_mbps")
        elif normalized_metric == "upload_speed":
            selected_value = throughput.get("upload_mbps")

        return {
            "available": bool(throughput.get("available")),
            "metric": normalized_metric,
            "metric_value_mbps": selected_value,
            "download_mbps": throughput.get("download_mbps"),
            "upload_mbps": throughput.get("upload_mbps"),
            "current": bool(throughput.get("current")) if throughput.get("available") else False,
            "stale": bool(throughput.get("stale")) if throughput.get("available") else False,
            "sample_kind": throughput.get("sample_kind"),
            "sample_window_seconds": throughput.get("sample_window_seconds"),
            "sampled_at": throughput.get("sampled_at"),
            "last_sample_age_seconds": throughput.get("last_sample_age_seconds"),
            "receive_link_mbps": throughput.get("receive_link_mbps"),
            "transmit_link_mbps": throughput.get("transmit_link_mbps"),
            "source": throughput.get("source"),
            "state": throughput.get("state"),
            "detail": throughput.get("detail"),
            "unsupported_code": throughput.get("unsupported_code") or throughput.get("state"),
            "unsupported_reason": throughput.get("unsupported_reason"),
            "interfaces": interfaces,
            "quality": status.get("quality", {}),
            "monitoring": status.get("monitoring", {}),
            "providers": status.get("providers", {}),
            "source_debug": status.get("source_debug", {}),
        }

    def attach_network_monitor(self, monitor: NetworkMonitor) -> None:
        self.network_monitor = monitor

    def _network_interface_status(self) -> dict[str, Any]:
        profiles = self._run_powershell_json(
            """
            Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' } | ForEach-Object {
                [pscustomobject]@{
                    interface_alias = $_.InterfaceAlias
                    profile = $_.NetProfile.Name
                    status = $_.NetAdapter.Status
                    ipv4 = @($_.IPv4Address | ForEach-Object { $_.IPv4Address })
                    gateway = @($_.IPv4DefaultGateway | ForEach-Object { $_.NextHop })
                    dns_servers = @($_.DNSServer.ServerAddresses)
                }
            } | ConvertTo-Json -Compress -Depth 5
            """
        )
        interfaces = [item for item in self._ensure_list(profiles) if isinstance(item, dict)]
        wireless = self._wireless_interface_details()
        for interface in interfaces:
            alias = str(interface.get("interface_alias") or "").strip().lower()
            if alias in {"wi-fi", "wifi", "wlan"}:
                interface.update(wireless)
        return {
            "hostname": socket.gethostname(),
            "fqdn": socket.getfqdn(),
            "interfaces": interfaces,
        }

    def _network_interface_counters(self) -> list[dict[str, Any]]:
        payload = self._run_powershell_json(
            """
            if (-not (Get-Command Get-NetAdapterStatistics -ErrorAction SilentlyContinue)) {
                @() | ConvertTo-Json -Compress -Depth 4
            } else {
                Get-NetAdapterStatistics | ForEach-Object {
                    [pscustomobject]@{
                        interface_alias = $_.Name
                        received_bytes = [int64]$_.ReceivedBytes
                        sent_bytes = [int64]$_.SentBytes
                    }
                } | ConvertTo-Json -Compress -Depth 4
            }
            """
        )
        return [
            {
                "interface_alias": str(item.get("interface_alias") or "").strip(),
                "received_bytes": self._coerce_int(item.get("received_bytes")),
                "sent_bytes": self._coerce_int(item.get("sent_bytes")),
            }
            for item in self._ensure_list(payload)
            if isinstance(item, dict) and str(item.get("interface_alias") or "").strip()
        ]

    def _wireless_interface_details(self) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
                **_hidden_console_subprocess_kwargs(),
            )
        except Exception:
            return {}
        if completed.returncode != 0:
            return {}
        details: dict[str, Any] = {}
        for raw_line in completed.stdout.splitlines():
            if ":" not in raw_line:
                continue
            key, value = raw_line.split(":", 1)
            normalized = key.strip().lower()
            cleaned = value.strip()
            if normalized == "ssid":
                details["ssid"] = cleaned
            elif normalized == "bssid":
                details["bssid"] = cleaned
            elif normalized == "signal":
                percent = self._coerce_int(cleaned.replace("%", "").strip())
                details["signal_quality_pct"] = percent
            elif normalized == "profile":
                details["profile"] = cleaned
            elif normalized == "receive rate (mbps)":
                details["receive_rate_mbps"] = self._coerce_int(cleaned)
            elif normalized == "transmit rate (mbps)":
                details["transmit_rate_mbps"] = self._coerce_int(cleaned)
            elif normalized == "radio type":
                details["radio_type"] = cleaned
            elif normalized == "state":
                details["wireless_state"] = cleaned
        return details

    def _network_probe(self, target: str, *, timeout_ms: int = 1000) -> dict[str, Any]:
        target = str(target or "").strip()
        if not target:
            return {"target": "", "reachable": False, "latency_ms": None, "timed_out": True}
        try:
            completed = subprocess.run(
                ["ping", "-n", "1", "-w", str(timeout_ms), target],
                capture_output=True,
                text=True,
                timeout=max(timeout_ms / 1000 + 1.5, 2.0),
                check=False,
                **_hidden_console_subprocess_kwargs(),
            )
        except Exception:
            return {"target": target, "reachable": False, "latency_ms": None, "timed_out": True}
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        latency_ms = None
        timed_out = "timed out" in output.lower()
        match = re.search(r"time[=<]\s*(\d+)\s*ms", output, re.IGNORECASE)
        if match:
            latency_ms = int(match.group(1))
            timed_out = False
        elif "time<1ms" in output.lower():
            latency_ms = 1
            timed_out = False
        return {
            "target": target,
            "reachable": completed.returncode == 0 and latency_ms is not None,
            "latency_ms": latency_ms,
            "timed_out": timed_out or completed.returncode != 0,
        }

    def _dns_health(self, *, hostname: str = "cloudflare.com") -> dict[str, Any]:
        started = monotonic()
        try:
            socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            latency_ms = round((monotonic() - started) * 1000, 1)
            return {"hostname": hostname, "latency_ms": latency_ms, "failed": False}
        except Exception:
            return {"hostname": hostname, "latency_ms": None, "failed": True}

    def _fallback_network_telemetry(self, base: dict[str, Any]) -> dict[str, Any]:
        interfaces = base.get("interfaces", []) if isinstance(base.get("interfaces"), list) else []
        primary = interfaces[0] if interfaces and isinstance(interfaces[0], dict) else {}
        connected = str(primary.get("status", "")).strip().lower() == "up"
        gateway = primary.get("gateway", []) if isinstance(primary.get("gateway"), list) else []
        dns_servers = primary.get("dns_servers", []) if isinstance(primary.get("dns_servers"), list) else []
        throughput_detail = "Stormhelm's throughput monitor is not attached in this environment."
        local_detail_parts = [str(primary.get("ssid") or primary.get("profile") or primary.get("interface_alias") or "Active interface").strip()]
        if gateway:
            local_detail_parts.append(f"gateway {gateway[0]}")
        if dns_servers:
            local_detail_parts.append(f"DNS {', '.join(str(item) for item in dns_servers[:2])}")
        signal_quality = primary.get("signal_quality_pct")
        if signal_quality is not None:
            local_detail_parts.append(f"signal {int(round(float(signal_quality)))}%")

        return {
            "monitoring": {"history_ready": False, "sample_count": 0, "diagnostic_burst_active": False, "last_sample_age_seconds": None},
            "quality": {
                "latency_ms": None,
                "gateway_latency_ms": None,
                "external_latency_ms": None,
                "jitter_ms": None,
                "gateway_jitter_ms": None,
                "external_jitter_ms": None,
                "packet_loss_pct": None,
                "gateway_packet_loss_pct": None,
                "external_packet_loss_pct": None,
                "signal_strength_dbm": None,
                "signal_quality_pct": signal_quality,
                "connected": connected,
                "source_precedence": ["local_link", "upstream_external", "cloudflare_quality_enrichment"],
                "source_status": {
                    "local_link_available": bool(primary),
                    "upstream_available": False,
                    "cloudflare_available": False,
                },
            },
            "dns": {"latency_ms": None, "failures": 0},
            "throughput": {
                "state": "provider_unavailable",
                "available": False,
                "label": "Observed throughput",
                "detail": throughput_detail,
                "source": "net_adapter_statistics",
                "unsupported_code": "provider_unavailable",
                "unsupported_reason": throughput_detail,
            },
            "events": [],
            "trend_points": [],
            "providers": {
                "local_status": {
                    "state": "ready" if primary else "no_active_interface",
                    "label": "Local link telemetry",
                    "detail": " | ".join(part for part in local_detail_parts if part) if primary else "No active interface is being reported right now.",
                    "available": bool(primary),
                    "source": "net_ip_configuration",
                    "interface_alias": primary.get("interface_alias"),
                    "profile": primary.get("ssid") or primary.get("profile"),
                    "gateway": gateway,
                    "dns_servers": dns_servers,
                    "signal_quality_pct": signal_quality,
                    "last_sample_age_seconds": None,
                },
                "upstream_path": {
                    "state": "no_external_probe_data",
                    "label": "Upstream path probes",
                    "detail": "Stormhelm does not have current external probe data yet.",
                    "available": False,
                    "source": "icmp_external_probes",
                    "last_sample_age_seconds": None,
                },
                "observed_throughput": {
                    "state": "provider_unavailable",
                    "label": "Observed throughput",
                    "detail": throughput_detail,
                    "available": False,
                    "source": "net_adapter_statistics",
                    "sampled_at": None,
                    "last_sample_age_seconds": None,
                    "unsupported_code": "provider_unavailable",
                    "unsupported_reason": throughput_detail,
                },
                "cloudflare_quality": {
                    "state": "unsupported",
                    "label": "Cloudflare quality",
                    "detail": "No external quality provider is attached.",
                    "available": False,
                },
            },
            "source_debug": {
                "status_primary": "local_status",
                "diagnosis_inputs": ["local_status"],
                "throughput_primary": "net_adapter_statistics",
                "throughput_resolution": "monitor_unavailable",
            },
            "assessment": {
                "kind": "insufficient_evidence",
                "headline": "Network monitoring limited",
                "summary": "Stormhelm can read current link status, but recent diagnostic telemetry is not attached yet.",
                "confidence": "low",
                "attribution": "unclear",
                "evidence_sufficiency": "gathering",
                "next_checks": ["Attach the network monitor to gather recent path and quality evidence."],
            },
        }

    def active_apps(self) -> dict[str, Any]:
        payload = self._run_powershell_json(
            """
            Get-Process | Where-Object { $_.MainWindowTitle } | Sort-Object CPU -Descending | Select-Object -First 12 ProcessName, MainWindowTitle, MainWindowHandle, Id, Path | ConvertTo-Json -Compress
            """
        )
        items = [
            {
                "process_name": str(item.get("ProcessName", "")),
                "window_title": str(item.get("MainWindowTitle", "")),
                "window_handle": int(item.get("MainWindowHandle") or 0),
                "pid": int(item.get("Id") or 0),
                "path": str(item.get("Path", "")).strip() or None,
            }
            for item in self._ensure_list(payload)
            if isinstance(item, dict)
        ]
        return {"applications": items}

    def _running_processes(self) -> list[dict[str, Any]]:
        payload = self._run_powershell_json(
            """
            Get-Process | Sort-Object CPU -Descending | Select-Object ProcessName, Id, Path | ConvertTo-Json -Compress
            """
        )
        return [
            {
                "process_name": str(item.get("ProcessName", "")),
                "pid": int(item.get("Id") or 0),
                "path": str(item.get("Path", "")).strip() or None,
            }
            for item in self._ensure_list(payload)
            if isinstance(item, dict)
        ]

    def app_control(
        self,
        *,
        action: str,
        app_name: str | None = None,
        app_path: str | None = None,
    ) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        requested_name = " ".join(str(app_name or "").split()).strip()
        requested_path = " ".join(str(app_path or "").split()).strip()

        if platform.system().lower() != "windows":
            return {"success": False, "action": normalized_action, "reason": "capability_unavailable"}
        if normalized_action not in {"launch", "focus", "close", "quit", "force_quit", "restart", "minimize", "maximize", "restore"}:
            return {"success": False, "action": normalized_action, "reason": "unsupported_action"}
        if normalized_action == "launch":
            if requested_name:
                existing = self._matching_active_app(requested_name)
                if existing is not None:
                    payload = self.app_control(action="focus", app_name=requested_name)
                    if isinstance(payload, dict):
                        payload["action"] = "launch"
                        payload["already_running"] = True
                    return payload
            target = requested_path or requested_name
            if not target:
                return {"success": False, "action": normalized_action, "reason": "missing_target"}
            payload = self._run_powershell_json(
                f"""
                $target = {json.dumps(target)}
                try {{
                    $proc = Start-Process -FilePath $target -PassThru
                    [pscustomobject]@{{
                        success = $true
                        action = "launch"
                        process_name = $proc.ProcessName
                        pid = $proc.Id
                        target = $target
                    }} | ConvertTo-Json -Compress
                }} catch {{
                    [pscustomobject]@{{
                        success = $false
                        action = "launch"
                        reason = $_.Exception.Message
                        target = $target
                    }} | ConvertTo-Json -Compress
                }}
                """
            )
            return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "launch_failed", "target": target}

        if not requested_name:
            return {"success": False, "action": normalized_action, "reason": "missing_target"}

        known_target = self._is_known_app_target(requested_name)
        not_running_reason = "app_not_running" if known_target else "app_not_found"
        window_matches = self._matching_window_targets(requested_name)
        selected_window = self._select_single_window_match(window_matches)
        process_matches = self._matching_running_processes(requested_name)
        process_group = self._select_process_group(requested_name, process_matches)
        process_count = len(self._unique_process_targets(process_matches))

        if normalized_action == "close":
            if selected_window == "ambiguous":
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "multiple_matches",
                    "requested_name": requested_name,
                    "match_scope": "window",
                    "match_count": len(window_matches),
                }
            if isinstance(selected_window, dict):
                return self._execute_graceful_exit(
                    action="close",
                    requested_name=requested_name,
                    matches=[selected_window],
                    resolution_source=str(selected_window.get("resolution_source") or "window_title"),
                )
            if process_count:
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "no_matching_window_found",
                    "requested_name": requested_name,
                    "process_count": process_count,
                }
            return {
                "success": False,
                "action": normalized_action,
                "reason": not_running_reason,
                "requested_name": requested_name,
            }

        if normalized_action == "quit":
            if process_group == "ambiguous":
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "multiple_matches",
                    "requested_name": requested_name,
                    "match_scope": "process",
                    "match_count": process_count,
                }
            if process_group:
                return self._execute_graceful_exit(
                    action="quit",
                    requested_name=requested_name,
                    matches=process_group,
                    resolution_source="process_group",
                )
            if selected_window == "ambiguous":
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "multiple_matches",
                    "requested_name": requested_name,
                    "match_scope": "window",
                    "match_count": len(window_matches),
                }
            if isinstance(selected_window, dict):
                return self._execute_graceful_exit(
                    action="quit",
                    requested_name=requested_name,
                    matches=[selected_window],
                    resolution_source=str(selected_window.get("resolution_source") or "window_title"),
                )
            if process_count:
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "builtin_app_target_unresolved" if known_target else "graceful_close_unavailable",
                    "requested_name": requested_name,
                    "process_count": process_count,
                }
            return {
                "success": False,
                "action": normalized_action,
                "reason": not_running_reason,
                "requested_name": requested_name,
            }

        if normalized_action == "force_quit":
            if process_group == "ambiguous":
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "multiple_matches",
                    "requested_name": requested_name,
                    "match_scope": "process",
                    "match_count": process_count,
                }
            if process_group:
                return self._execute_force_quit(
                    requested_name=requested_name,
                    matches=process_group,
                    resolution_source="process_group",
                )
            if selected_window == "ambiguous":
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "multiple_matches",
                    "requested_name": requested_name,
                    "match_scope": "window",
                    "match_count": len(window_matches),
                }
            if isinstance(selected_window, dict):
                pid = int(selected_window.get("pid") or 0)
                if pid <= 0 or self._is_host_process_for_target(requested_name, selected_window):
                    return {
                        "success": False,
                        "action": normalized_action,
                        "reason": "builtin_app_target_unresolved" if known_target else "window_process_unresolved",
                        "requested_name": requested_name,
                        "process_name": str(selected_window.get("process_name") or "").strip() or None,
                        "window_title": str(selected_window.get("window_title") or "").strip() or None,
                        "resolution_source": str(selected_window.get("resolution_source") or "window_title"),
                    }
                fallback_match = dict(selected_window)
                fallback_match["resolution_source"] = "window_process"
                return self._execute_force_quit(
                    requested_name=requested_name,
                    matches=[fallback_match],
                    resolution_source="window_process",
                )
            if process_count:
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "builtin_app_target_unresolved" if known_target else "no_matching_process_found",
                    "requested_name": requested_name,
                    "process_count": process_count,
                }
            return {
                "success": False,
                "action": normalized_action,
                "reason": not_running_reason,
                "requested_name": requested_name,
            }

        if normalized_action == "restart":
            if process_group == "ambiguous":
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "multiple_matches",
                    "requested_name": requested_name,
                    "match_scope": "process",
                    "match_count": process_count,
                }
            restart_match = process_group[0] if process_group else None
            if restart_match is None and selected_window == "ambiguous":
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "multiple_matches",
                    "requested_name": requested_name,
                    "match_scope": "window",
                    "match_count": len(window_matches),
                }
            if restart_match is None and isinstance(selected_window, dict):
                if int(selected_window.get("pid") or 0) <= 0 or self._is_host_process_for_target(requested_name, selected_window):
                    return {
                        "success": False,
                        "action": normalized_action,
                        "reason": "builtin_app_target_unresolved" if known_target else "window_process_unresolved",
                        "requested_name": requested_name,
                        "process_name": str(selected_window.get("process_name") or "").strip() or None,
                        "window_title": str(selected_window.get("window_title") or "").strip() or None,
                        "resolution_source": str(selected_window.get("resolution_source") or "window_title"),
                    }
                restart_match = dict(selected_window)
                restart_match["resolution_source"] = "window_process"
            if restart_match is None:
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "builtin_app_target_unresolved" if (known_target and process_count) else not_running_reason,
                    "requested_name": requested_name,
                    "process_count": process_count or None,
                }
            match = restart_match
        else:
            if selected_window == "ambiguous":
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "multiple_matches",
                    "requested_name": requested_name,
                    "match_scope": "window",
                    "match_count": len(window_matches),
                }
            if not isinstance(selected_window, dict):
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "no_matching_window_found" if process_count else not_running_reason,
                    "requested_name": requested_name,
                    "process_count": process_count or None,
                }
            match = selected_window

        pid = int(match.get("pid") or 0)
        if pid <= 0:
            return {"success": False, "action": normalized_action, "reason": "missing_pid", "requested_name": requested_name}
        window_title = str(match.get("window_title") or "").strip()
        process_name = str(match.get("process_name") or "").strip()
        window_handle = int(match.get("window_handle") or 0)
        process_path = str(match.get("path") or "").strip()
        resolution_source = str(match.get("resolution_source") or "").strip() or None

        if normalized_action in {"minimize", "maximize", "restore"}:
            if window_handle <= 0:
                return {
                    "success": False,
                    "action": normalized_action,
                    "reason": "window_handle_unavailable",
                    "requested_name": requested_name,
                    "process_name": process_name,
                    "resolution_source": resolution_source,
                }
            show_flag = {"minimize": 6, "maximize": 3, "restore": 9}[normalized_action]
            payload = self._run_powershell_json(
                f"""
                Add-Type @"
                using System;
                using System.Runtime.InteropServices;
                public static class StormhelmWindowApi {{
                    [DllImport("user32.dll")]
                    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
                }}
                "@
                $handle = [intptr]{window_handle}
                try {{
                    $result = [StormhelmWindowApi]::ShowWindowAsync($handle, {show_flag})
                    [pscustomobject]@{{
                        success = [bool]$result
                        action = {json.dumps(normalized_action)}
                        pid = {pid}
                        process_name = {json.dumps(process_name)}
                        window_title = {json.dumps(window_title)}
                        resolution_source = {json.dumps(resolution_source)}
                    }} | ConvertTo-Json -Compress
                }} catch {{
                    [pscustomobject]@{{
                        success = $false
                        action = {json.dumps(normalized_action)}
                        pid = {pid}
                        process_name = {json.dumps(process_name)}
                        window_title = {json.dumps(window_title)}
                        resolution_source = {json.dumps(resolution_source)}
                        reason = $_.Exception.Message
                    }} | ConvertTo-Json -Compress
                }}
                """
            )
            return payload if isinstance(payload, dict) else {
                "success": False,
                "action": normalized_action,
                "pid": pid,
                "process_name": process_name,
                "window_title": window_title,
                "resolution_source": resolution_source,
            }

        if normalized_action == "focus":
            payload = self._run_powershell_json(
                f"""
                $pid = {pid}
                $title = {json.dumps(window_title)}
                try {{
                    $shell = New-Object -ComObject WScript.Shell
                    $activated = $false
                    if ($title) {{
                        $activated = [bool]$shell.AppActivate($title)
                    }}
                    if (-not $activated) {{
                        $activated = [bool]$shell.AppActivate($pid)
                    }}
                    [pscustomobject]@{{
                        success = $activated
                        action = "focus"
                        pid = $pid
                        process_name = {json.dumps(process_name)}
                        window_title = $title
                        resolution_source = {json.dumps(resolution_source)}
                    }} | ConvertTo-Json -Compress
                }} catch {{
                    [pscustomobject]@{{
                        success = $false
                        action = "focus"
                        pid = $pid
                        process_name = {json.dumps(process_name)}
                        window_title = $title
                        resolution_source = {json.dumps(resolution_source)}
                        reason = $_.Exception.Message
                    }} | ConvertTo-Json -Compress
                }}
                """
            )
            return payload if isinstance(payload, dict) else {
                "success": False,
                "action": normalized_action,
                "pid": pid,
                "process_name": process_name,
                "window_title": window_title,
                "resolution_source": resolution_source,
            }

        restart_payload = self._run_powershell_json(
            f"""
            $pid = {pid}
            try {{
                $proc = Get-Process -Id $pid -ErrorAction Stop
                $path = $proc.Path
                if (-not $path) {{
                    $path = {json.dumps(process_path or requested_path)}
                }}
                if (-not $path) {{
                    throw "path_unavailable"
                }}
                Stop-Process -Id $pid -Force -ErrorAction Stop
                $newProc = Start-Process -FilePath $path -PassThru
                [pscustomobject]@{{
                    success = $true
                    action = "restart"
                    pid = $newProc.Id
                    process_name = $newProc.ProcessName
                    window_title = {json.dumps(window_title)}
                    target = $path
                    resolution_source = {json.dumps(resolution_source)}
                }} | ConvertTo-Json -Compress
            }} catch {{
                [pscustomobject]@{{
                    success = $false
                    action = "restart"
                    pid = $pid
                    process_name = {json.dumps(process_name)}
                    window_title = {json.dumps(window_title)}
                    resolution_source = {json.dumps(resolution_source)}
                    reason = $_.Exception.Message
                }} | ConvertTo-Json -Compress
            }}
            """
        )
        return restart_payload if isinstance(restart_payload, dict) else {
            "success": False,
            "action": "restart",
            "pid": pid,
            "process_name": process_name,
            "window_title": window_title,
            "resolution_source": resolution_source,
        }

    def _execute_graceful_exit(
        self,
        *,
        action: str,
        requested_name: str,
        matches: list[dict[str, Any]],
        resolution_source: str,
    ) -> dict[str, Any]:
        targets = self._unique_process_targets(matches)
        if not targets:
            return {
                "success": False,
                "action": action,
                "reason": "no_matching_window_found" if action == "close" else "graceful_close_unavailable",
                "requested_name": requested_name,
            }
        primary = targets[0]
        payload = self._run_powershell_json(
            f"""
            $targets = @(ConvertFrom-Json @'
            {json.dumps(targets)}
            '@)
            Add-Type @"
            using System;
            using System.Runtime.InteropServices;
            public static class StormhelmWindowApi {{
                [DllImport("user32.dll", SetLastError=true)]
                public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
            }}
            "@
            $results = @()
            foreach ($target in $targets) {{
                $pid = [int]$target.pid
                $windowHandle = [intptr]([int64]($target.window_handle))
                try {{
                    $proc = Get-Process -Id $pid -ErrorAction Stop
                    $closed = $false
                    try {{
                        $closed = [bool]$proc.CloseMainWindow()
                    }} catch {{
                        $closed = $false
                    }}
                    if (-not $closed -and $windowHandle -ne [intptr]::Zero) {{
                        $closed = [bool][StormhelmWindowApi]::PostMessage($windowHandle, 0x0010, [intptr]::Zero, [intptr]::Zero)
                    }}
                    $results += [pscustomobject]@{{
                        pid = $pid
                        process_name = $proc.ProcessName
                        closed = [bool]$closed
                        window_handle = [int64]$windowHandle
                    }}
                }} catch {{
                    $results += [pscustomobject]@{{
                        pid = $pid
                        process_name = {json.dumps(str(primary.get("process_name") or ""))}
                        closed = $false
                        error = $_.Exception.Message
                        window_handle = [int64]$windowHandle
                    }}
                }}
            }}
            $closed = @($results | Where-Object {{ $_.closed }})
            [pscustomobject]@{{
                success = [bool]($closed.Count -gt 0)
                action = {json.dumps(action)}
                pid = {int(primary.get("pid") or 0)}
                pids = @($results | ForEach-Object {{ [int]$_.pid }})
                affected_pids = @($closed | ForEach-Object {{ [int]$_.pid }})
                attempted_count = [int]$results.Count
                successful_count = [int]$closed.Count
                graceful_close_attempted = $true
                process_name = {json.dumps(str(primary.get("process_name") or ""))}
                window_title = {json.dumps(str(primary.get("window_title") or ""))}
                resolution_source = {json.dumps(resolution_source)}
                reason = if ($closed.Count -gt 0) {{ $null }} else {{ "graceful_close_unavailable" }}
            }} | ConvertTo-Json -Compress -Depth 5
            """
        )
        if isinstance(payload, dict):
            payload.setdefault("requested_name", requested_name)
            return payload
        return {
            "success": False,
            "action": action,
            "reason": "graceful_close_unavailable",
            "requested_name": requested_name,
            "pid": int(primary.get("pid") or 0),
            "process_name": str(primary.get("process_name") or "").strip() or None,
            "window_title": str(primary.get("window_title") or "").strip() or None,
            "resolution_source": resolution_source,
        }

    def _execute_force_quit(
        self,
        *,
        requested_name: str,
        matches: list[dict[str, Any]],
        resolution_source: str,
    ) -> dict[str, Any]:
        targets = self._unique_process_targets(matches)
        if not targets:
            return {
                "success": False,
                "action": "force_quit",
                "reason": "no_matching_process_found",
                "requested_name": requested_name,
            }
        primary = targets[0]
        payload = self._run_powershell_json(
            f"""
            $targets = @(ConvertFrom-Json @'
            {json.dumps(targets)}
            '@)
            $results = @()
            foreach ($target in $targets) {{
                $pid = [int]$target.pid
                try {{
                    $proc = Get-Process -Id $pid -ErrorAction Stop
                    Stop-Process -Id $pid -Force -ErrorAction Stop
                    $results += [pscustomobject]@{{
                        pid = $pid
                        process_name = $proc.ProcessName
                        terminated = $true
                    }}
                }} catch {{
                    $results += [pscustomobject]@{{
                        pid = $pid
                        process_name = {json.dumps(str(primary.get("process_name") or ""))}
                        terminated = $false
                        error = $_.Exception.Message
                    }}
                }}
            }}
            $terminated = @($results | Where-Object {{ $_.terminated }})
            $errors = @($results | Where-Object {{ -not $_.terminated -and $_.error }})
            $accessDenied = @($errors | Where-Object {{ $_.error -match "access is denied" }})
            [pscustomobject]@{{
                success = [bool]($terminated.Count -eq $results.Count -and $results.Count -gt 0)
                action = "force_quit"
                pid = {int(primary.get("pid") or 0)}
                pids = @($results | ForEach-Object {{ [int]$_.pid }})
                terminated_pids = @($terminated | ForEach-Object {{ [int]$_.pid }})
                terminated_count = [int]$terminated.Count
                attempted_count = [int]$results.Count
                process_name = {json.dumps(str(primary.get("process_name") or ""))}
                window_title = {json.dumps(str(primary.get("window_title") or ""))}
                resolution_source = {json.dumps(resolution_source)}
                reason = if ($terminated.Count -eq $results.Count -and $results.Count -gt 0) {{
                    $null
                }} elseif ($accessDenied.Count -gt 0 -and $terminated.Count -eq 0) {{
                    "process_termination_denied"
                }} elseif ($terminated.Count -gt 0) {{
                    "partial_process_termination"
                }} else {{
                    "no_matching_process_found"
                }}
            }} | ConvertTo-Json -Compress -Depth 5
            """
        )
        if isinstance(payload, dict):
            payload.setdefault("requested_name", requested_name)
            return payload
        return {
            "success": False,
            "action": "force_quit",
            "reason": "no_matching_process_found",
            "requested_name": requested_name,
            "pid": int(primary.get("pid") or 0),
            "process_name": str(primary.get("process_name") or "").strip() or None,
            "window_title": str(primary.get("window_title") or "").strip() or None,
            "resolution_source": resolution_source,
        }

    def _unique_process_targets(self, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        seen_pids: set[int] = set()
        for item in matches:
            pid = int(item.get("pid") or 0)
            if pid <= 0 or pid in seen_pids:
                continue
            seen_pids.add(pid)
            targets.append(
                {
                    "pid": pid,
                    "window_handle": int(item.get("window_handle") or 0),
                    "process_name": str(item.get("process_name") or "").strip() or None,
                    "window_title": str(item.get("window_title") or "").strip() or None,
                    "path": str(item.get("path") or "").strip() or None,
                }
            )
        return targets

    def recent_files(self, limit: int = 12) -> dict[str, Any]:
        roots = [Path(path) for path in self.config.safety.allowed_read_dirs if Path(path).exists()]
        entries: list[dict[str, Any]] = []
        visited = 0
        skip_names = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".runtime", "release"}
        for root in roots:
            for current_root, dirnames, filenames in os.walk(root):
                dirnames[:] = [name for name in dirnames if name not in skip_names and not name.startswith(".")]
                for filename in filenames:
                    visited += 1
                    if visited > 4000:
                        break
                    path = Path(current_root) / filename
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    entries.append(
                        {
                            "path": str(path),
                            "name": path.name,
                            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
                            "size_bytes": stat.st_size,
                        }
                    )
                if visited > 4000:
                    break
            if visited > 4000:
                break
        entries.sort(key=lambda item: item["modified_at"], reverse=True)
        return {"files": entries[:limit]}

    def window_status(self) -> dict[str, Any]:
        payload = self._run_powershell_json(
            """
            Add-Type -AssemblyName System.Windows.Forms
            Add-Type @"
            using System;
            using System.Runtime.InteropServices;
            using System.Text;
            public static class StormhelmWindowApi {
                public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
                [StructLayout(LayoutKind.Sequential)]
                public struct RECT {
                    public int Left;
                    public int Top;
                    public int Right;
                    public int Bottom;
                }
                [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
                [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
                [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
                [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
                [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
                [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);
                [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
                [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
            }
            "@

            $foreground = [StormhelmWindowApi]::GetForegroundWindow()
            $windows = New-Object System.Collections.Generic.List[object]
            $screens = [System.Windows.Forms.Screen]::AllScreens
            [StormhelmWindowApi]::EnumWindows({
                param($hWnd, $lParam)
                if (-not [StormhelmWindowApi]::IsWindowVisible($hWnd)) { return $true }
                $length = [StormhelmWindowApi]::GetWindowTextLength($hWnd)
                if ($length -le 0) { return $true }
                $buffer = New-Object System.Text.StringBuilder ($length + 1)
                [StormhelmWindowApi]::GetWindowText($hWnd, $buffer, $buffer.Capacity) | Out-Null
                $title = $buffer.ToString()
                if ([string]::IsNullOrWhiteSpace($title)) { return $true }
                $rect = New-Object StormhelmWindowApi+RECT
                if (-not [StormhelmWindowApi]::GetWindowRect($hWnd, [ref]$rect)) { return $true }
                $pid = [uint32]0
                [StormhelmWindowApi]::GetWindowThreadProcessId($hWnd, [ref]$pid) | Out-Null
                $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                $screen = [System.Windows.Forms.Screen]::FromHandle($hWnd)
                $screenIndex = 1
                for ($i = 0; $i -lt $screens.Length; $i++) {
                    if ($screens[$i].DeviceName -eq $screen.DeviceName) {
                        $screenIndex = $i + 1
                        break
                    }
                }
                $windows.Add([pscustomobject]@{
                    process_name = if ($proc) { $proc.ProcessName } else { $null }
                    window_title = $title
                    window_handle = [int64]$hWnd
                    pid = [int]$pid
                    minimized = [bool][StormhelmWindowApi]::IsIconic($hWnd)
                    is_focused = ($hWnd -eq $foreground)
                    x = [int]$rect.Left
                    y = [int]$rect.Top
                    width = [int]($rect.Right - $rect.Left)
                    height = [int]($rect.Bottom - $rect.Top)
                    monitor_index = $screenIndex
                    monitor_device = $screen.DeviceName
                    path = if ($proc) { $proc.Path } else { $null }
                }) | Out-Null
                return $true
            }, [intptr]::Zero) | Out-Null

            $monitors = for ($i = 0; $i -lt $screens.Length; $i++) {
                $screen = $screens[$i]
                [pscustomobject]@{
                    index = $i + 1
                    device_name = $screen.DeviceName
                    is_primary = [bool]$screen.Primary
                    bounds_x = [int]$screen.Bounds.X
                    bounds_y = [int]$screen.Bounds.Y
                    bounds_width = [int]$screen.Bounds.Width
                    bounds_height = [int]$screen.Bounds.Height
                    work_x = [int]$screen.WorkingArea.X
                    work_y = [int]$screen.WorkingArea.Y
                    work_width = [int]$screen.WorkingArea.Width
                    work_height = [int]$screen.WorkingArea.Height
                }
            }

            [pscustomobject]@{
                focused_window = ($windows | Where-Object { $_.is_focused } | Select-Object -First 1)
                windows = @($windows)
                monitors = @($monitors)
            } | ConvertTo-Json -Compress -Depth 6
            """
        )
        if not isinstance(payload, dict):
            return {"focused_window": None, "windows": [], "monitors": []}
        windows = [self._sanitize_window_entry(item) for item in self._ensure_list(payload.get("windows")) if isinstance(item, dict)]
        monitors = [self._sanitize_monitor_entry(item) for item in self._ensure_list(payload.get("monitors")) if isinstance(item, dict)]
        focused_window = payload.get("focused_window") if isinstance(payload.get("focused_window"), dict) else None
        return {
            "focused_window": self._sanitize_window_entry(focused_window) if focused_window else None,
            "windows": windows,
            "monitors": monitors,
        }

    def window_control(
        self,
        *,
        action: str,
        app_name: str | None = None,
        target_mode: str | None = None,
        monitor_index: int | None = None,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
        delta_x: int | None = None,
        delta_y: int | None = None,
        delta_width: int | None = None,
        delta_height: int | None = None,
    ) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        normalized_target_mode = str(target_mode or "app").strip().lower() or "app"
        if normalized_action not in {
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
        }:
            return {"success": False, "action": normalized_action, "reason": "unsupported_action"}

        status = self.window_status()
        target = self._resolve_window_target(status, app_name=app_name, target_mode=normalized_target_mode)
        if target is None:
            reason = "focused_window_unavailable" if normalized_target_mode == "focused" else "window_not_found"
            return {"success": False, "action": normalized_action, "reason": reason, "requested_name": app_name}
        handle = int(target.get("window_handle") or 0)
        if handle <= 0:
            return {
                "success": False,
                "action": normalized_action,
                "reason": "window_handle_unavailable",
                "requested_name": app_name,
                "process_name": target.get("process_name"),
            }

        if normalized_action == "focus":
            payload = self._run_powershell_json(
                f"""
                Add-Type @"
                using System;
                using System.Runtime.InteropServices;
                public static class StormhelmWindowApi {{
                    [DllImport("user32.dll")]
                    public static extern bool SetForegroundWindow(IntPtr hWnd);
                    [DllImport("user32.dll")]
                    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
                }}
                "@
                $handle = [intptr]{handle}
                try {{
                    [StormhelmWindowApi]::ShowWindowAsync($handle, 9) | Out-Null
                    $result = [StormhelmWindowApi]::SetForegroundWindow($handle)
                    [pscustomobject]@{{
                        success = [bool]$result
                        action = "focus"
                        process_name = {json.dumps(str(target.get("process_name") or ""))}
                        window_title = {json.dumps(str(target.get("window_title") or ""))}
                        pid = {int(target.get("pid") or 0)}
                    }} | ConvertTo-Json -Compress
                }} catch {{
                    [pscustomobject]@{{
                        success = $false
                        action = "focus"
                        process_name = {json.dumps(str(target.get("process_name") or ""))}
                        window_title = {json.dumps(str(target.get("window_title") or ""))}
                        pid = {int(target.get("pid") or 0)}
                        reason = $_.Exception.Message
                    }} | ConvertTo-Json -Compress
                }}
                """
            )
            return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "focus_failed"}

        if normalized_action in {"maximize", "minimize", "restore"}:
            show_flag = {"minimize": 6, "maximize": 3, "restore": 9}[normalized_action]
            payload = self._run_powershell_json(
                f"""
                Add-Type @"
                using System;
                using System.Runtime.InteropServices;
                public static class StormhelmWindowApi {{
                    [DllImport("user32.dll")]
                    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
                }}
                "@
                $handle = [intptr]{handle}
                try {{
                    $result = [StormhelmWindowApi]::ShowWindowAsync($handle, {show_flag})
                    [pscustomobject]@{{
                        success = [bool]$result
                        action = {json.dumps(normalized_action)}
                        process_name = {json.dumps(str(target.get("process_name") or ""))}
                        window_title = {json.dumps(str(target.get("window_title") or ""))}
                        pid = {int(target.get("pid") or 0)}
                    }} | ConvertTo-Json -Compress
                }} catch {{
                    [pscustomobject]@{{
                        success = $false
                        action = {json.dumps(normalized_action)}
                        process_name = {json.dumps(str(target.get("process_name") or ""))}
                        window_title = {json.dumps(str(target.get("window_title") or ""))}
                        pid = {int(target.get("pid") or 0)}
                        reason = $_.Exception.Message
                    }} | ConvertTo-Json -Compress
                }}
                """
            )
            return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "window_state_failed"}

        current_x = int(target.get("x") or 0)
        current_y = int(target.get("y") or 0)
        current_width = max(int(target.get("width") or 0), 320)
        current_height = max(int(target.get("height") or 0), 240)
        monitors = status.get("monitors") if isinstance(status.get("monitors"), list) else []
        current_monitor = self._monitor_entry(monitors, int(target.get("monitor_index") or 0)) or self._primary_monitor(monitors)

        new_x = current_x
        new_y = current_y
        new_width = current_width
        new_height = current_height

        if normalized_action == "move":
            new_x = int(x if x is not None else current_x)
            new_y = int(y if y is not None else current_y)
        elif normalized_action == "resize":
            new_width = max(int(width if width is not None else current_width), 320)
            new_height = max(int(height if height is not None else current_height), 240)
        elif normalized_action == "move_by":
            new_x = current_x + int(delta_x or 0)
            new_y = current_y + int(delta_y or 0)
        elif normalized_action == "resize_by":
            new_width = max(current_width + int(delta_width or 0), 320)
            new_height = max(current_height + int(delta_height or 0), 240)
        elif normalized_action in {"snap_left", "snap_right"}:
            if not current_monitor:
                return {"success": False, "action": normalized_action, "reason": "monitor_unavailable"}
            work_x = int(current_monitor.get("work_x") or 0)
            work_y = int(current_monitor.get("work_y") or 0)
            work_width = max(int(current_monitor.get("work_width") or 0), 800)
            work_height = max(int(current_monitor.get("work_height") or 0), 600)
            half_width = max(work_width // 2, 400)
            new_x = work_x if normalized_action == "snap_left" else work_x + half_width
            new_y = work_y
            new_width = half_width if normalized_action == "snap_left" else max(work_width - half_width, 400)
            new_height = work_height
        elif normalized_action == "move_to_monitor":
            target_monitor = self._monitor_entry(monitors, int(monitor_index or 0))
            if not target_monitor:
                return {"success": False, "action": normalized_action, "reason": "monitor_not_found", "monitor_index": monitor_index}
            work_x = int(target_monitor.get("work_x") or 0)
            work_y = int(target_monitor.get("work_y") or 0)
            work_width = max(int(target_monitor.get("work_width") or 0), 800)
            work_height = max(int(target_monitor.get("work_height") or 0), 600)
            new_width = min(current_width, work_width)
            new_height = min(current_height, work_height)
            new_x = work_x + max((work_width - new_width) // 2, 0)
            new_y = work_y + max((work_height - new_height) // 2, 0)

        payload = self._run_powershell_json(
            f"""
            Add-Type @"
            using System;
            using System.Runtime.InteropServices;
            public static class StormhelmWindowApi {{
                [DllImport("user32.dll")]
                public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
                [DllImport("user32.dll")]
                public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
            }}
            "@
            $handle = [intptr]{handle}
            try {{
                [StormhelmWindowApi]::ShowWindowAsync($handle, 9) | Out-Null
                $result = [StormhelmWindowApi]::SetWindowPos($handle, [intptr]::Zero, {int(new_x)}, {int(new_y)}, {int(new_width)}, {int(new_height)}, 0x0014)
                [pscustomobject]@{{
                    success = [bool]$result
                    action = {json.dumps(normalized_action)}
                    process_name = {json.dumps(str(target.get("process_name") or ""))}
                    window_title = {json.dumps(str(target.get("window_title") or ""))}
                    pid = {int(target.get("pid") or 0)}
                    x = {int(new_x)}
                    y = {int(new_y)}
                    width = {int(new_width)}
                    height = {int(new_height)}
                    monitor_index = {int(monitor_index or target.get("monitor_index") or 0)}
                }} | ConvertTo-Json -Compress
            }} catch {{
                [pscustomobject]@{{
                    success = $false
                    action = {json.dumps(normalized_action)}
                    process_name = {json.dumps(str(target.get("process_name") or ""))}
                    window_title = {json.dumps(str(target.get("window_title") or ""))}
                    pid = {int(target.get("pid") or 0)}
                    reason = $_.Exception.Message
                }} | ConvertTo-Json -Compress
            }}
            """
        )
        return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "window_move_failed"}

    def system_control(
        self,
        *,
        action: str,
        value: int | None = None,
        state: str | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        normalized_state = str(state or "").strip().lower() or None
        normalized_target = str(target or "").strip().lower() or None
        capabilities = self.control_capabilities()
        system_caps = capabilities.get("system") if isinstance(capabilities.get("system"), dict) else {}

        capability_map = {
            "mute": "volume",
            "unmute": "volume",
            "volume_up": "volume",
            "volume_down": "volume",
            "set_volume": "volume",
            "brightness_up": "brightness",
            "brightness_down": "brightness",
            "set_brightness": "brightness",
            "lock": "lock",
            "sleep_display": "sleep_display",
            "toggle_wifi": "wifi_toggle",
            "toggle_bluetooth": "bluetooth_toggle",
            "open_task_manager": "task_manager",
            "open_device_manager": "device_manager",
            "open_resource_monitor": "resource_monitor",
            "open_settings_page": "settings",
        }
        required_capability = capability_map.get(normalized_action)
        if not required_capability:
            return {"success": False, "action": normalized_action, "reason": "unsupported_action"}
        if not bool(system_caps.get(required_capability)):
            return {"success": False, "action": normalized_action, "reason": "unsupported", "capability": required_capability}

        if normalized_action in {"mute", "unmute", "volume_up", "volume_down", "set_volume"}:
            target_percent = max(0, min(int(value if value is not None else 50), 100))
            key_map = {
                "mute": {"down": 0, "up": 0, "mute": 1},
                "unmute": {"down": 0, "up": 1, "mute": 0},
                "volume_up": {"down": 0, "up": max(1, round(target_percent / 2)), "mute": 0},
                "volume_down": {"down": max(1, round(target_percent / 2)), "up": 0, "mute": 0},
                "set_volume": {"down": 50, "up": round(target_percent / 2), "mute": 0},
            }[normalized_action]
            payload = self._run_powershell_json(
                f"""
                Add-Type @"
                using System;
                using System.Runtime.InteropServices;
                public static class StormhelmAudioApi {{
                    [DllImport("user32.dll", SetLastError=true)]
                    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
                }}
                "@
                function Invoke-StormhelmKey([byte]$key, [int]$count) {{
                    for ($i = 0; $i -lt $count; $i++) {{
                        [StormhelmAudioApi]::keybd_event($key, 0, 0, [UIntPtr]::Zero)
                        Start-Sleep -Milliseconds 8
                        [StormhelmAudioApi]::keybd_event($key, 0, 2, [UIntPtr]::Zero)
                        Start-Sleep -Milliseconds 8
                    }}
                }}
                try {{
                    Invoke-StormhelmKey 0xAE {int(key_map["down"])}
                    Invoke-StormhelmKey 0xAF {int(key_map["up"])}
                    Invoke-StormhelmKey 0xAD {int(key_map["mute"])}
                    [pscustomobject]@{{
                        success = $true
                        action = {json.dumps(normalized_action)}
                        value = {int(target_percent)}
                    }} | ConvertTo-Json -Compress
                }} catch {{
                    [pscustomobject]@{{
                        success = $false
                        action = {json.dumps(normalized_action)}
                        value = {int(target_percent)}
                        reason = $_.Exception.Message
                    }} | ConvertTo-Json -Compress
                }}
                """
            )
            return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "volume_control_failed", "value": target_percent}

        if normalized_action in {"brightness_up", "brightness_down", "set_brightness"}:
            brightness_value = max(0, min(int(value if value is not None else 50), 100))
            payload = self._run_powershell_json(
                f"""
                $methods = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue
                $levels = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue
                if (-not $methods) {{
                    [pscustomobject]@{{ success = $false; action = {json.dumps(normalized_action)}; reason = "unsupported" }} | ConvertTo-Json -Compress
                    return
                }}
                $current = if ($levels) {{ [int]($levels | Select-Object -First 1).CurrentBrightness }} else {{ 50 }}
                $target = switch ({json.dumps(normalized_action)}) {{
                    "brightness_up" {{ [Math]::Min($current + 10, 100) }}
                    "brightness_down" {{ [Math]::Max($current - 10, 0) }}
                    default {{ {int(brightness_value)} }}
                }}
                try {{
                    $methods | ForEach-Object {{ $_.WmiSetBrightness(1, $target) | Out-Null }}
                    [pscustomobject]@{{ success = $true; action = {json.dumps(normalized_action)}; value = $target }} | ConvertTo-Json -Compress
                }} catch {{
                    [pscustomobject]@{{ success = $false; action = {json.dumps(normalized_action)}; value = $target; reason = $_.Exception.Message }} | ConvertTo-Json -Compress
                }}
                """
            )
            return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "brightness_control_failed"}

        if normalized_action == "lock":
            payload = self._run_powershell_json(
                """
                Add-Type @"
                using System;
                using System.Runtime.InteropServices;
                public static class StormhelmSystemApi {
                    [DllImport("user32.dll", SetLastError=true)]
                    public static extern bool LockWorkStation();
                }
                "@
                try {
                    $result = [StormhelmSystemApi]::LockWorkStation()
                    [pscustomobject]@{ success = [bool]$result; action = "lock" } | ConvertTo-Json -Compress
                } catch {
                    [pscustomobject]@{ success = $false; action = "lock"; reason = $_.Exception.Message } | ConvertTo-Json -Compress
                }
                """
            )
            return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "lock_failed"}

        if normalized_action == "sleep_display":
            payload = self._run_powershell_json(
                """
                Add-Type @"
                using System;
                using System.Runtime.InteropServices;
                public static class StormhelmSystemApi {
                    [DllImport("user32.dll", SetLastError=true)]
                    public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
                }
                "@
                try {
                    [StormhelmSystemApi]::SendMessage([intptr]0xffff, 0x0112, [intptr]0xF170, [intptr]2) | Out-Null
                    [pscustomobject]@{ success = $true; action = "sleep_display" } | ConvertTo-Json -Compress
                } catch {
                    [pscustomobject]@{ success = $false; action = "sleep_display"; reason = $_.Exception.Message } | ConvertTo-Json -Compress
                }
                """
            )
            return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "sleep_display_failed"}

        if normalized_action == "toggle_wifi":
            desired_state = "off" if normalized_state == "off" else "on"
            payload = self._run_powershell_json(
                f"""
                $wifi = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {{
                    $_.InterfaceDescription -match 'Wireless|Wi-Fi|802\\.11' -or $_.Name -match 'Wi-Fi|WiFi|WLAN'
                }} | Select-Object -First 1
                if (-not $wifi) {{
                    [pscustomobject]@{{ success = $false; action = "toggle_wifi"; state = {json.dumps(desired_state)}; reason = "adapter_not_found" }} | ConvertTo-Json -Compress
                    return
                }}
                try {{
                    if ({json.dumps(desired_state)} -eq "off") {{
                        Disable-NetAdapter -Name $wifi.Name -Confirm:$false -ErrorAction Stop | Out-Null
                    }} else {{
                        Enable-NetAdapter -Name $wifi.Name -Confirm:$false -ErrorAction Stop | Out-Null
                    }}
                    [pscustomobject]@{{ success = $true; action = "toggle_wifi"; state = {json.dumps(desired_state)}; adapter = $wifi.Name }} | ConvertTo-Json -Compress
                }} catch {{
                    [pscustomobject]@{{ success = $false; action = "toggle_wifi"; state = {json.dumps(desired_state)}; adapter = $wifi.Name; reason = $_.Exception.Message }} | ConvertTo-Json -Compress
                }}
                """
            )
            return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "wifi_toggle_failed"}

        if normalized_action == "toggle_bluetooth":
            return {"success": False, "action": normalized_action, "reason": "unsupported"}

        if normalized_action == "open_task_manager":
            command = "taskmgr"
        elif normalized_action == "open_device_manager":
            command = "devmgmt.msc"
        elif normalized_action == "open_resource_monitor":
            command = "resmon"
        else:
            uri = self._settings_uri_for_target(normalized_target)
            if not uri:
                return {"success": False, "action": normalized_action, "reason": "unsupported_target", "target": normalized_target}
            command = uri

        payload = self._run_powershell_json(
            f"""
            try {{
                Start-Process -FilePath {json.dumps(command)} | Out-Null
                [pscustomobject]@{{ success = $true; action = {json.dumps(normalized_action)}; target = {json.dumps(command)} }} | ConvertTo-Json -Compress
            }} catch {{
                [pscustomobject]@{{ success = $false; action = {json.dumps(normalized_action)}; target = {json.dumps(command)}; reason = $_.Exception.Message }} | ConvertTo-Json -Compress
            }}
            """
        )
        return payload if isinstance(payload, dict) else {"success": False, "action": normalized_action, "reason": "system_open_failed", "target": command}

    def flush_dns_cache(self) -> dict[str, Any]:
        payload = self._run_powershell_json(
            """
            try {
                ipconfig /flushdns | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    [pscustomobject]@{ success = $false; action = "flush_dns"; reason = "flushdns_failed" } | ConvertTo-Json -Compress
                    return
                }
                [pscustomobject]@{ success = $true; action = "flush_dns" } | ConvertTo-Json -Compress
            } catch {
                [pscustomobject]@{ success = $false; action = "flush_dns"; reason = $_.Exception.Message } | ConvertTo-Json -Compress
            }
            """
        )
        return payload if isinstance(payload, dict) else {"success": False, "action": "flush_dns", "reason": "flushdns_failed"}

    def restart_network_adapter(self) -> dict[str, Any]:
        payload = self._run_powershell_json(
            """
            if (-not (Get-Command Restart-NetAdapter -ErrorAction SilentlyContinue)) {
                [pscustomobject]@{ success = $false; action = "restart_network_adapter"; reason = "unsupported" } | ConvertTo-Json -Compress
                return
            }
            $adapter = Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
                Where-Object { $_.Status -eq 'Up' } |
                Sort-Object -Property InterfaceMetric, ifIndex |
                Select-Object -First 1
            if (-not $adapter) {
                [pscustomobject]@{ success = $false; action = "restart_network_adapter"; reason = "adapter_not_found" } | ConvertTo-Json -Compress
                return
            }
            try {
                Restart-NetAdapter -Name $adapter.Name -Confirm:$false -ErrorAction Stop | Out-Null
                [pscustomobject]@{ success = $true; action = "restart_network_adapter"; adapter = $adapter.Name } | ConvertTo-Json -Compress
            } catch {
                [pscustomobject]@{ success = $false; action = "restart_network_adapter"; adapter = $adapter.Name; reason = $_.Exception.Message } | ConvertTo-Json -Compress
            }
            """
        )
        return payload if isinstance(payload, dict) else {"success": False, "action": "restart_network_adapter", "reason": "restart_netadapter_failed"}

    def restart_explorer_shell(self) -> dict[str, Any]:
        payload = self._run_powershell_json(
            """
            try {
                Get-Process explorer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Process explorer.exe | Out-Null
                [pscustomobject]@{ success = $true; action = "restart_explorer_shell" } | ConvertTo-Json -Compress
            } catch {
                [pscustomobject]@{ success = $false; action = "restart_explorer_shell"; reason = $_.Exception.Message } | ConvertTo-Json -Compress
            }
            """
        )
        return payload if isinstance(payload, dict) else {"success": False, "action": "restart_explorer_shell", "reason": "restart_explorer_failed"}

    def control_capabilities(self) -> dict[str, Any]:
        is_windows = platform.system().strip().lower() == "windows"
        monitor_count = 0
        if is_windows:
            try:
                monitor_count = len(self.window_status().get("monitors") or [])
            except Exception:
                monitor_count = 0
        return {
            "platform": platform.system(),
            "app": {
                "launch": is_windows,
                "focus": is_windows,
                "close": is_windows,
                "quit": is_windows,
                "restart": is_windows,
            },
            "process": {
                "force_quit": is_windows,
                "terminate": is_windows,
            },
            "window": {
                "inspect": is_windows,
                "focus": is_windows,
                "move": is_windows,
                "resize": is_windows,
                "snap": is_windows,
                "maximize": is_windows,
                "minimize": is_windows,
                "restore": is_windows,
                "monitor_move": is_windows and monitor_count > 1,
                "monitor_count": monitor_count,
            },
            "system": {
                "volume": is_windows,
                "brightness": self._brightness_control_supported() if is_windows else False,
                "lock": is_windows,
                "sleep_display": is_windows,
                "wifi_toggle": self._wifi_toggle_supported() if is_windows else False,
                "bluetooth_toggle": self._bluetooth_toggle_supported() if is_windows else False,
                "settings": is_windows,
                "task_manager": is_windows,
                "device_manager": is_windows,
                "resource_monitor": is_windows,
            },
            "search": {
                "workspace_files": bool(self.config.safety.allowed_read_dirs),
                "recent_files": bool(self.config.safety.allowed_read_dirs),
                "apps": is_windows,
                "windows": is_windows,
                "browser_tabs": False,
                "notes": False,
            },
            "repair": {
                "connectivity_checks": True,
                "flush_dns": is_windows,
                "restart_network_adapter": is_windows,
                "restart_explorer": is_windows,
                "relaunch_app": is_windows,
            },
            "power": {
                "saved_routines": True,
                "scheduled_routines": False,
                "trusted_hooks": True,
                "script_hooks": True,
                "file_operations": True,
                "dry_run_preview": True,
                "maintenance": True,
            },
        }

    def get_saved_home_location(self) -> dict[str, Any] | None:
        return self._saved_home_location()

    def get_saved_locations(self) -> list[dict[str, Any]]:
        locations: list[dict[str, Any]] = []
        home = self._saved_home_location()
        if home:
            locations.append(dict(home))
        for location in self._saved_named_locations():
            entry = dict(location)
            entry.setdefault("source", "saved_named")
            entry.setdefault("resolved", True)
            entry.setdefault("approximate", False)
            entry.setdefault("used_home_fallback", False)
            locations.append(entry)
        return locations

    def save_home_location(
        self,
        *,
        label: str,
        latitude: float,
        longitude: float,
        timezone: str | None = None,
        address_text: str | None = None,
        source: str = "manual",
        approximate: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "label": label.strip() or "Saved home",
            "latitude": float(latitude),
            "longitude": float(longitude),
            "timezone": timezone,
            "address_text": address_text.strip() if isinstance(address_text, str) and address_text.strip() else None,
            "source": source,
            "approximate": bool(approximate),
            "saved_at": datetime.now().astimezone().isoformat(),
        }
        self._set_preference(self._HOME_LOCATION_KEY, payload)
        return self._saved_home_location() or {
            "resolved": True,
            "source": "saved_home",
            "label": payload["label"],
            "latitude": payload["latitude"],
            "longitude": payload["longitude"],
            "timezone": payload["timezone"],
            "approximate": payload["approximate"],
            "used_home_fallback": False,
        }

    def save_named_location(
        self,
        *,
        name: str,
        label: str,
        latitude: float,
        longitude: float,
        timezone: str | None = None,
        address_text: str | None = None,
        source: str = "manual",
        approximate: bool = False,
    ) -> dict[str, Any]:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise ValueError("Location name is required.")
        locations = self._named_locations_map()
        locations[normalized_name] = {
            "name": name.strip(),
            "label": label.strip() or name.strip(),
            "latitude": float(latitude),
            "longitude": float(longitude),
            "timezone": timezone,
            "address_text": address_text.strip() if isinstance(address_text, str) and address_text.strip() else None,
            "source": source,
            "approximate": bool(approximate),
            "saved_at": datetime.now().astimezone().isoformat(),
        }
        self._set_preference(self._NAMED_LOCATIONS_KEY, locations)
        saved = dict(locations[normalized_name])
        saved.update(
            {
                "resolved": True,
                "source": "saved_named",
                "used_home_fallback": False,
            }
        )
        return saved

    def resolve_best_location_for_request(
        self,
        *,
        mode: str = "auto",
        allow_home_fallback: bool = True,
        named_location: str | None = None,
        named_location_type: str = "auto",
    ) -> dict[str, Any]:
        if isinstance(named_location, str) and named_location.strip().lower() in {"", "none", "null"}:
            named_location = None
        if named_location:
            normalized_type = (named_location_type or "auto").strip().lower() or "auto"
            if normalized_type != "place_query":
                named = self._saved_named_location(named_location)
                if named:
                    return named
                if normalized_type == "saved_alias":
                    return {
                        "resolved": False,
                        "mode": "named",
                        "source": "saved_named",
                        "reason": "saved_named_location_not_found",
                        "requested_name": named_location,
                    }
            queried = self._query_location_lookup(named_location)
            if queried:
                return queried
            return {
                "resolved": False,
                "mode": "named",
                "source": "queried_place",
                "reason": "queried_place_not_found",
                "requested_name": named_location,
            }
        return self.resolve_location(mode=mode, allow_home_fallback=allow_home_fallback)

    def resolve_location(self, *, mode: str = "auto", allow_home_fallback: bool = True) -> dict[str, Any]:
        normalized_mode = (mode or "auto").strip().lower()
        if normalized_mode == "home":
            home = self._saved_home_location()
            if home:
                return home
            return {
                "resolved": False,
                "mode": "home",
                "source": "saved_home",
                "reason": "saved_home_not_configured",
            }

        live = self._live_device_location()
        live_reason = None
        if isinstance(live, dict) and live.get("resolved"):
            return live
        if isinstance(live, dict):
            live_reason = str(live.get("reason") or "").strip() or None

        approximate_device = self._approximate_device_location()
        approximate_reason = None
        if isinstance(approximate_device, dict) and approximate_device.get("resolved"):
            return approximate_device
        if isinstance(approximate_device, dict):
            approximate_reason = str(approximate_device.get("reason") or "").strip() or None

        if allow_home_fallback:
            home = self._saved_home_location()
            if home:
                home["used_home_fallback"] = True
                if live_reason:
                    home["fallback_reason"] = live_reason
                elif approximate_reason:
                    home["fallback_reason"] = approximate_reason
                return home

        ip_estimate = self._ip_estimate_location()
        if ip_estimate:
            if live_reason:
                ip_estimate["fallback_reason"] = live_reason
            elif approximate_reason:
                ip_estimate["fallback_reason"] = approximate_reason
            return ip_estimate

        return {
            "resolved": False,
            "mode": normalized_mode,
            "source": "unavailable",
            "reason": "location_unavailable",
            "live_reason": live_reason,
            "approximate_reason": approximate_reason,
        }

    def weather_status(
        self,
        *,
        location_mode: str = "auto",
        named_location: str | None = None,
        named_location_type: str = "auto",
        allow_home_fallback: bool = True,
        forecast_target: str = "current",
        units: str | None = None,
    ) -> dict[str, Any]:
        resolved = self.resolve_best_location_for_request(
            mode=location_mode,
            named_location=named_location,
            named_location_type=named_location_type,
            allow_home_fallback=allow_home_fallback,
        )
        if not resolved.get("resolved"):
            return {
                "available": False,
                "location": resolved,
                "reason": resolved.get("reason", "location_unavailable"),
            }

        latitude = resolved.get("latitude")
        longitude = resolved.get("longitude")
        if latitude is None or longitude is None:
            return {
                "available": False,
                "location": resolved,
                "reason": "missing_coordinates",
            }

        normalized_units = (units or self.config.weather.units or "imperial").strip().lower()
        temperature_unit = "fahrenheit" if normalized_units == "imperial" else "celsius"
        wind_unit = "mph" if normalized_units == "imperial" else "kmh"
        query = urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "hourly": "temperature_2m,apparent_temperature,weather_code,precipitation_probability",
                "forecast_days": 7,
                "temperature_unit": temperature_unit,
                "wind_speed_unit": wind_unit,
                "timezone": "auto",
            }
        )
        payload = self._fetch_json(
            f"{self.config.weather.provider_base_url}/forecast?{query}",
            timeout=self.config.weather.timeout_seconds,
        )
        if not isinstance(payload, dict):
            return {
                "available": False,
                "location": resolved,
                "reason": "weather_unavailable",
            }

        current = payload.get("current", {}) if isinstance(payload.get("current"), dict) else {}
        daily = payload.get("daily", {}) if isinstance(payload.get("daily"), dict) else {}
        forecast = self._select_weather_forecast(payload, forecast_target=forecast_target)
        weather_code = int(forecast.get("weather_code") or current.get("weather_code") or 0)
        return {
            "available": True,
            "location": resolved,
            "forecast_target": forecast_target,
            "temperature": {
                "current": forecast.get("temperature") if forecast.get("temperature") is not None else current.get("temperature_2m"),
                "apparent": forecast.get("apparent_temperature") if forecast.get("apparent_temperature") is not None else current.get("apparent_temperature"),
                "high": forecast.get("high"),
                "low": forecast.get("low"),
                "unit": "F" if normalized_units == "imperial" else "C",
            },
            "condition": {
                "code": weather_code,
                "summary": self._weather_code_label(weather_code),
            },
            "wind": {
                "speed": current.get("wind_speed_10m"),
                "unit": "mph" if normalized_units == "imperial" else "km/h",
            },
            "humidity_percent": current.get("relative_humidity_2m"),
            "deck_url": self._weather_page_url(float(latitude), float(longitude)),
        }

    def _run_powershell_json(self, script: str) -> Any:
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
                **_hidden_console_subprocess_kwargs(),
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        output = completed.stdout.strip()
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return None

    def _matching_active_app(self, app_name: str) -> dict[str, Any] | None:
        apps = self.active_apps().get("applications", [])
        matches = self._matching_entries(app_name, apps, resolution_source="active_app")
        return matches[0] if matches else None

    def _matching_window_targets(self, app_name: str) -> list[dict[str, Any]]:
        active_apps = self.active_apps().get("applications", [])
        active_matches = self._matching_entries(app_name, active_apps, resolution_source="active_app")
        status = self.window_status()
        windows = [item for item in self._ensure_list(status.get("windows")) if isinstance(item, dict)]
        window_matches = self._matching_entries(app_name, windows, resolution_source="window_title")
        return self._dedupe_ranked_matches(active_matches + window_matches, self._window_identity_key)

    def _resolve_app_match(self, app_name: str, *, allow_background: bool) -> dict[str, Any] | None:
        window_matches = self._matching_window_targets(app_name)
        selected_window = self._select_single_window_match(window_matches)
        if isinstance(selected_window, dict):
            return selected_window
        if allow_background:
            process_matches = self._matching_running_processes(app_name)
            process_group = self._select_process_group(app_name, process_matches)
            if isinstance(process_group, list) and process_group:
                return process_group[0]
        return None

    def _matching_running_processes(self, app_name: str) -> list[dict[str, Any]]:
        processes = self._running_processes()
        return self._matching_entries(app_name, processes, resolution_source="process_name")

    def _matching_running_process(self, app_name: str) -> dict[str, Any] | None:
        matches = self._matching_running_processes(app_name)
        return matches[0] if matches else None

    def _matching_window(self, app_name: str, windows: list[dict[str, Any]]) -> dict[str, Any] | None:
        matches = self._matching_entries(app_name, windows, resolution_source="window_title")
        return matches[0] if matches else None

    def _matching_entries(
        self,
        app_name: str,
        entries: Any,
        *,
        resolution_source: str,
    ) -> list[dict[str, Any]]:
        requested = self._normalize_app_match_value(app_name)
        items = [item for item in self._ensure_list(entries) if isinstance(item, dict)]
        if not requested:
            return []
        requested_variants = self._app_match_variants(requested)
        requested_tokens = self._informative_match_tokens(requested_variants)
        matches: list[dict[str, Any]] = []
        for item in items:
            best_score = 0
            for candidate in self._entry_match_variants(item):
                best_score = max(best_score, self._candidate_match_score(requested_variants, requested_tokens, candidate))
            if best_score < 40:
                continue
            match = dict(item)
            match["_match_score"] = best_score
            match["resolution_source"] = resolution_source
            matches.append(match)
        matches.sort(
            key=lambda item: (
                int(item.get("_match_score") or 0),
                int(bool(item.get("window_handle"))),
                int(bool(item.get("window_title"))),
                int(bool(item.get("path"))),
                int(item.get("pid") or 0),
            ),
            reverse=True,
        )
        return matches

    def _candidate_match_score(
        self,
        requested_variants: set[str],
        requested_tokens: set[str],
        candidate: str,
    ) -> int:
        if not candidate:
            return 0
        if candidate in requested_variants:
            return 100
        if any(variant and (variant in candidate or candidate in variant) for variant in requested_variants):
            return 80
        candidate_tokens = self._informative_match_tokens({candidate})
        overlap = requested_tokens & candidate_tokens
        if len(overlap) >= 2:
            return 60 + min(len(overlap), 3) * 10
        if len(overlap) == 1:
            token = next(iter(overlap))
            return 45 if len(token) >= 6 else 0
        return 0

    def _informative_match_tokens(self, values: set[str]) -> set[str]:
        tokens: set[str] = set()
        for value in values:
            for token in str(value or "").split():
                if token and token not in _GENERIC_APP_MATCH_TOKENS:
                    tokens.add(token)
        return tokens

    def _dedupe_ranked_matches(
        self,
        matches: list[dict[str, Any]],
        key_fn,
    ) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for item in matches:
            key = key_fn(item)
            existing = deduped.get(key)
            if existing is None or int(item.get("_match_score") or 0) > int(existing.get("_match_score") or 0):
                deduped[key] = item
        return sorted(
            deduped.values(),
            key=lambda item: (
                int(item.get("_match_score") or 0),
                int(bool(item.get("window_handle"))),
                int(bool(item.get("window_title"))),
                int(bool(item.get("path"))),
                int(item.get("pid") or 0),
            ),
            reverse=True,
        )

    def _select_single_window_match(self, matches: list[dict[str, Any]]) -> dict[str, Any] | str | None:
        if not matches:
            return None
        best_score = int(matches[0].get("_match_score") or 0)
        top_matches = [match for match in matches if int(match.get("_match_score") or 0) == best_score]
        unique_targets = {self._window_identity_key(match) for match in top_matches}
        if len(unique_targets) > 1:
            return "ambiguous"
        return top_matches[0]

    def _select_process_group(self, requested_name: str, matches: list[dict[str, Any]]) -> list[dict[str, Any]] | str | None:
        if not matches:
            return None
        non_host_matches = [match for match in matches if not self._is_host_process_for_target(requested_name, match)]
        if non_host_matches:
            working_matches = non_host_matches
        elif self._requested_target_prefers_non_host_process(requested_name):
            return None
        else:
            working_matches = matches
        best_score = int(working_matches[0].get("_match_score") or 0)
        top_matches = [match for match in working_matches if int(match.get("_match_score") or 0) == best_score]
        top_groups = {self._process_group_key(match, requested_name) for match in top_matches}
        if len(top_groups) > 1:
            return "ambiguous"
        best_group = self._process_group_key(working_matches[0], requested_name)
        selected = [dict(match) for match in working_matches if self._process_group_key(match, requested_name) == best_group]
        for match in selected:
            match["resolution_source"] = "process_group"
        return selected

    def _window_identity_key(self, item: dict[str, Any]) -> str:
        handle = int(item.get("window_handle") or 0)
        if handle > 0:
            return f"handle:{handle}"
        pid = int(item.get("pid") or 0)
        title = self._normalize_app_match_value(item.get("window_title"))
        process_name = self._normalize_app_match_value(item.get("process_name"))
        return f"pid:{pid}:title:{title}:process:{process_name}"

    def _process_group_key(self, item: dict[str, Any], requested_name: str) -> str:
        requested_profiles = self._app_profile_keys(requested_name)
        path_value = str(item.get("path") or "").strip()
        values = [
            self._normalize_app_match_value(item.get("process_name")),
            self._normalize_app_match_value(Path(path_value).stem if path_value else ""),
        ]
        for value in values:
            if not value:
                continue
            candidate_profiles = self._app_profile_keys(value)
            overlap = requested_profiles & candidate_profiles if requested_profiles else candidate_profiles
            if overlap:
                return sorted(overlap)[0]
        for value in values:
            if value:
                return value
        return str(int(item.get("pid") or 0))

    def _requested_target_prefers_non_host_process(self, requested_name: str) -> bool:
        for profile_key in self._app_profile_keys(requested_name):
            profile = _COMMON_APP_COMPATIBILITY.get(profile_key) or {}
            if profile.get("host_processes"):
                return True
        return False

    def _is_host_process_for_target(self, requested_name: str, item: dict[str, Any]) -> bool:
        path_value = str(item.get("path") or "").strip()
        candidates = {
            self._normalize_app_match_value(item.get("process_name")),
            self._normalize_app_match_value(Path(path_value).stem if path_value else ""),
        }
        for profile_key in self._app_profile_keys(requested_name, include_hosts=True):
            profile = _COMMON_APP_COMPATIBILITY.get(profile_key) or {}
            host_processes = {self._normalize_app_match_value(value) for value in profile.get("host_processes", set())}
            if any(candidate and candidate in host_processes for candidate in candidates):
                return True
        return False

    def _resolve_window_target(
        self,
        status: dict[str, Any],
        *,
        app_name: str | None,
        target_mode: str,
    ) -> dict[str, Any] | None:
        focused = status.get("focused_window")
        if isinstance(focused, dict) and target_mode == "focused":
            return focused
        windows = [item for item in self._ensure_list(status.get("windows")) if isinstance(item, dict)]
        if app_name:
            return self._matching_window(app_name, windows)
        if isinstance(focused, dict):
            return focused
        return windows[0] if windows else None

    def _sanitize_window_entry(self, item: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        return {
            "process_name": str(item.get("process_name") or "").strip() or None,
            "window_title": str(item.get("window_title") or "").strip() or None,
            "window_handle": int(item.get("window_handle") or 0),
            "pid": int(item.get("pid") or 0),
            "x": int(item.get("x") or 0),
            "y": int(item.get("y") or 0),
            "width": int(item.get("width") or 0),
            "height": int(item.get("height") or 0),
            "monitor_index": int(item.get("monitor_index") or 0),
            "monitor_device": str(item.get("monitor_device") or "").strip() or None,
            "path": str(item.get("path") or "").strip() or None,
            "minimized": bool(item.get("minimized", False)),
            "is_focused": bool(item.get("is_focused", False)),
        }

    def _sanitize_monitor_entry(self, item: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        return {
            "index": int(item.get("index") or 0),
            "device_name": str(item.get("device_name") or "").strip() or None,
            "is_primary": bool(item.get("is_primary", False)),
            "bounds_x": int(item.get("bounds_x") or 0),
            "bounds_y": int(item.get("bounds_y") or 0),
            "bounds_width": int(item.get("bounds_width") or 0),
            "bounds_height": int(item.get("bounds_height") or 0),
            "work_x": int(item.get("work_x") or 0),
            "work_y": int(item.get("work_y") or 0),
            "work_width": int(item.get("work_width") or 0),
            "work_height": int(item.get("work_height") or 0),
        }

    def _monitor_entry(self, monitors: list[dict[str, Any]], monitor_index: int) -> dict[str, Any] | None:
        for monitor in monitors:
            if int(monitor.get("index") or 0) == int(monitor_index):
                return monitor
        return None

    def _primary_monitor(self, monitors: list[dict[str, Any]]) -> dict[str, Any] | None:
        for monitor in monitors:
            if bool(monitor.get("is_primary")):
                return monitor
        return monitors[0] if monitors else None

    def _settings_uri_for_target(self, target: str | None) -> str | None:
        normalized = str(target or "").strip().lower()
        if not normalized:
            return "ms-settings:"
        mapping = {
            "bluetooth": "ms-settings:bluetooth",
            "wifi": "ms-settings:network-wifi",
            "wi-fi": "ms-settings:network-wifi",
            "network": "ms-settings:network",
            "sound": "ms-settings:sound",
            "display": "ms-settings:display",
            "location": "ms-settings:privacy-location",
            "privacy": "ms-settings:privacy",
        }
        return mapping.get(normalized)

    def _brightness_control_supported(self) -> bool:
        payload = self._run_powershell_json(
            """
            $methods = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue
            [bool]($methods | Select-Object -First 1) | ConvertTo-Json -Compress
            """
        )
        return bool(payload)

    def _wifi_toggle_supported(self) -> bool:
        payload = self._run_powershell_json(
            """
            [bool](Get-Command Disable-NetAdapter -ErrorAction SilentlyContinue) | ConvertTo-Json -Compress
            """
        )
        return bool(payload)

    def _bluetooth_toggle_supported(self) -> bool:
        return False

    def _entry_match_variants(self, item: dict[str, Any]) -> set[str]:
        path_value = str(item.get("path") or "").strip()
        path_obj = Path(path_value) if path_value else None
        parent_name = path_obj.parent.name if path_obj else ""
        grandparent_name = path_obj.parent.parent.name if path_obj and len(path_obj.parents) > 1 else ""
        normalized_parent = self._normalize_app_match_value(parent_name)
        values = {
            self._normalize_app_match_value(item.get("process_name")),
            self._normalize_app_match_value(item.get("window_title")),
            self._normalize_app_match_value(path_obj.stem if path_obj else ""),
            self._normalize_app_match_value(grandparent_name),
            self._normalize_app_match_value(path_value),
        }
        if normalized_parent and (" " in normalized_parent or any(marker in parent_name for marker in {"_", "."})):
            values.add(normalized_parent)
        variants: set[str] = set()
        for value in values:
            variants.update(self._app_match_variants(value))
        return {variant for variant in variants if variant}

    def _app_match_variants(self, value: Any) -> set[str]:
        normalized = self._normalize_app_match_value(value)
        if not normalized:
            return set()
        alias_groups = {
            "vscode": {"vscode", "vs code", "visual studio code", "code"},
            "visual studio code": {"vscode", "vs code", "visual studio code", "code"},
            "code": {"vscode", "vs code", "visual studio code", "code"},
            "msedge": {"msedge", "edge", "microsoft edge"},
            "microsoft edge": {"msedge", "edge", "microsoft edge"},
            "edge": {"msedge", "edge", "microsoft edge"},
            "chrome": {"chrome", "google chrome"},
            "google chrome": {"chrome", "google chrome"},
            "spotify": {"spotify"},
            "discord": {"discord"},
            "steam": {"steam"},
        }
        variants = {normalized}
        tokens = normalized.split()
        if tokens:
            variants.add(" ".join(tokens))
        for key, group in alias_groups.items():
            if normalized == key or normalized in group:
                variants.update(group)
        for profile_key in self._app_profile_keys(normalized):
            profile = _COMMON_APP_COMPATIBILITY.get(profile_key) or {}
            for group_name in ("aliases", "process_names", "executables", "window_titles", "package_terms"):
                variants.update({self._normalize_app_match_value(term) for term in profile.get(group_name, set())})
            if normalized == profile_key or normalized in {self._normalize_app_match_value(profile_key)}:
                variants.add(self._normalize_app_match_value(profile_key))
        return {variant for variant in variants if variant}

    def _normalize_app_match_value(self, value: Any) -> str:
        text = re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower())
        return " ".join(text.split())

    def _app_profile_keys(self, value: Any, *, include_hosts: bool = False) -> set[str]:
        normalized = self._normalize_app_match_value(value)
        if not normalized:
            return set()
        matches: set[str] = set()
        for key, profile in _COMMON_APP_COMPATIBILITY.items():
            terms: set[str] = {self._normalize_app_match_value(key)}
            for group_name in ("aliases", "process_names", "executables", "window_titles", "package_terms"):
                terms.update({self._normalize_app_match_value(term) for term in profile.get(group_name, set())})
            if include_hosts:
                terms.update({self._normalize_app_match_value(term) for term in profile.get("host_processes", set())})
            if normalized in terms:
                matches.add(key)
                continue
            partial_terms = {
                self._normalize_app_match_value(term)
                for term in profile.get("package_terms", set())
            }
            partial_terms.update(
                {
                    self._normalize_app_match_value(term)
                    for term in profile.get("window_titles", set())
                    if " " in self._normalize_app_match_value(term)
                }
            )
            partial_terms.update({term for term in terms if " " in term})
            if any(term and len(term) >= 4 and term in normalized for term in partial_terms):
                matches.add(key)
        return matches

    def _is_known_app_target(self, value: Any) -> bool:
        normalized = self._normalize_app_match_value(value)
        if not normalized:
            return False
        if normalized in _BUILTIN_APP_ALIAS_GROUPS:
            return True
        if any(normalized in group for group in _BUILTIN_APP_ALIAS_GROUPS.values()):
            return True
        return bool(self._app_profile_keys(normalized))

    def _ensure_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _battery_report_summary(self) -> dict[str, Any]:
        if self._battery_report_cache is not None and (monotonic() - self._battery_report_cached_at) < 300:
            return dict(self._battery_report_cache)

        text = self._read_battery_report_text()
        summary = self._parse_battery_report_summary(text) if text else {"source": "unavailable"}
        self._battery_report_cache = dict(summary)
        self._battery_report_cached_at = monotonic()
        return dict(summary)

    def _read_battery_report_text(self) -> str | None:
        report_path = Path(tempfile.gettempdir()) / "stormhelm-battery-report.html"
        try:
            completed = subprocess.run(
                ["powercfg", "/batteryreport", "/output", str(report_path)],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                **_hidden_console_subprocess_kwargs(),
            )
        except Exception:
            return None
        if completed.returncode != 0 or not report_path.exists():
            return None
        try:
            return report_path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            return None

    def _nt_battery_state(self) -> dict[str, Any]:
        class SYSTEM_BATTERY_STATE(ctypes.Structure):
            _fields_ = [
                ("AcOnLine", ctypes.c_ubyte),
                ("BatteryPresent", ctypes.c_ubyte),
                ("Charging", ctypes.c_ubyte),
                ("Discharging", ctypes.c_ubyte),
                ("Spare1", ctypes.c_ubyte * 4),
                ("MaxCapacity", ctypes.c_uint32),
                ("RemainingCapacity", ctypes.c_uint32),
                ("Rate", ctypes.c_int32),
                ("EstimatedTime", ctypes.c_uint32),
                ("DefaultAlert1", ctypes.c_uint32),
                ("DefaultAlert2", ctypes.c_uint32),
            ]

        state = SYSTEM_BATTERY_STATE()
        try:
            status = ctypes.windll.powrprof.CallNtPowerInformation(5, None, 0, ctypes.byref(state), ctypes.sizeof(state))
        except Exception:
            return {}
        if status != 0 or not bool(state.BatteryPresent):
            return {}
        raw_rate = int(state.Rate)
        charge_rate_mw = None
        discharge_rate_mw = None
        if raw_rate:
            if bool(state.Charging) or (raw_rate > 0 and not bool(state.Discharging)):
                charge_rate_mw = abs(raw_rate)
            else:
                discharge_rate_mw = abs(raw_rate)
        return {
            "remaining_capacity_mwh": None if state.RemainingCapacity == 0xFFFFFFFF else int(state.RemainingCapacity),
            "full_charge_capacity_mwh": None if state.MaxCapacity == 0xFFFFFFFF else int(state.MaxCapacity),
            "charge_rate_mw": charge_rate_mw,
            "discharge_rate_mw": discharge_rate_mw,
            "time_to_empty_seconds": None if state.EstimatedTime == 0xFFFFFFFF else int(state.EstimatedTime),
        }

    def _parse_battery_report_summary(self, text: str) -> dict[str, Any]:
        design_capacity_mwh = self._extract_report_capacity(text, "DESIGN CAPACITY")
        full_charge_capacity_mwh = self._extract_report_capacity(text, "FULL CHARGE CAPACITY")
        recent_usage = self._parse_battery_recent_usage_rows(text)
        battery_usage = self._parse_battery_usage_rows(text)
        estimated_charge_rate_mw = self._estimate_charge_rate_from_recent_usage(recent_usage)
        estimated_discharge_rate_mw = self._estimate_discharge_rate_from_usage(battery_usage)
        source = "battery_report_history" if any(
            value is not None
            for value in (
                design_capacity_mwh,
                full_charge_capacity_mwh,
                estimated_charge_rate_mw,
                estimated_discharge_rate_mw,
            )
        ) else "unavailable"
        return {
            "source": source,
            "design_capacity_mwh": design_capacity_mwh,
            "full_charge_capacity_mwh": full_charge_capacity_mwh,
            "estimated_charge_rate_mw": estimated_charge_rate_mw,
            "estimated_discharge_rate_mw": estimated_discharge_rate_mw,
            "recent_usage_sample_count": len(recent_usage),
            "battery_usage_sample_count": len(battery_usage),
        }

    def _extract_report_capacity(self, text: str, label: str) -> int | None:
        compact = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())
        match = re.search(rf"{re.escape(label)}\s+([\d,]+)\s*mWh", compact, flags=re.IGNORECASE)
        if not match:
            return None
        return self._coerce_int(match.group(1).replace(",", ""))

    def _parse_battery_recent_usage_rows(self, text: str) -> list[dict[str, Any]]:
        section = self._extract_report_section(text, "Recent usage", "Battery usage")
        if not section:
            return []
        rows: list[dict[str, Any]] = []
        current_date: str | None = None
        for row in self._extract_report_rows(section):
            if 'class="dateTime"' not in row:
                continue
            date_match = re.search(
                r'<td[^>]*class="[^"]*dateTime[^"]*"[^>]*><span class="date">(?P<date>[^<]*)</span><span class="time">(?P<time>[^<]*)</span>',
                row,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not date_match:
                continue
            date_text = " ".join(html.unescape(date_match.group("date")).split()).strip()
            time_text = " ".join(html.unescape(date_match.group("time")).split()).strip()
            source_text = self._extract_td_content(row, "acdc")
            state_text = self._extract_td_content(row, "state")
            capacity_text = self._extract_td_content(row, "mw")
            percent_text = self._extract_td_content(row, "percent")
            capacity_mwh = self._coerce_int(capacity_text.replace("mWh", "").replace(",", "").strip() if capacity_text else None)
            percent_match = re.search(r"(\d{1,3})", percent_text or "")
            percent = self._coerce_int(percent_match.group(1)) if percent_match else None
            if date_text:
                current_date = date_text
            timestamp = None
            if current_date and time_text:
                try:
                    timestamp = datetime.fromisoformat(f"{current_date} {time_text}")
                except ValueError:
                    timestamp = None
            if capacity_mwh is None or timestamp is None:
                continue
            rows.append(
                {
                    "timestamp": timestamp,
                    "source": source_text.lower(),
                    "state": state_text.lower(),
                    "capacity_mwh": capacity_mwh,
                    "percent": percent,
                }
            )
        return rows

    def _parse_battery_usage_rows(self, text: str) -> list[dict[str, Any]]:
        section = self._extract_report_section(text, "Battery usage", "Usage history")
        if not section:
            return []
        rows: list[dict[str, Any]] = []
        current_date: str | None = None
        for row in self._extract_report_rows(section):
            if 'class="dateTime"' not in row or " dc " not in f" {row} ":
                continue
            date_match = re.search(
                r'<td[^>]*class="[^"]*dateTime[^"]*"[^>]*><span class="date">(?P<date>[^<]*)</span><span class="time">(?P<time>[^<]*)</span>',
                row,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not date_match:
                continue
            date_text = " ".join(html.unescape(date_match.group("date")).split()).strip()
            time_text = " ".join(html.unescape(date_match.group("time")).split()).strip()
            state_text = self._extract_td_content(row, "state")
            duration_seconds = self._parse_hms_to_seconds(self._extract_td_content(row, "hms"))
            energy_text = self._extract_td_content(row, "mw")
            energy_mwh = self._coerce_int(energy_text.replace("mWh", "").replace(",", "").strip() if energy_text else None)
            percent_text = self._extract_td_content(row, "percent") or self._extract_td_content(row, "nullValue")
            percent_match = re.search(r"(\d{1,3})", percent_text or "")
            if date_text:
                current_date = date_text
            timestamp = None
            if current_date and time_text:
                try:
                    timestamp = datetime.fromisoformat(f"{current_date} {time_text}")
                except ValueError:
                    timestamp = None
            if duration_seconds is None or energy_mwh is None or duration_seconds <= 0:
                continue
            rows.append(
                {
                    "timestamp": timestamp,
                    "state": state_text.lower(),
                    "duration_seconds": duration_seconds,
                    "energy_mwh": energy_mwh,
                    "percent_drained": self._coerce_int(percent_match.group(1)) if percent_match else None,
                }
            )
        return rows

    def _estimate_charge_rate_from_recent_usage(self, rows: list[dict[str, Any]]) -> int | None:
        charge_mwh = 0
        charge_hours = 0.0
        for current, nxt in zip(rows, rows[1:]):
            current_timestamp = current.get("timestamp")
            next_timestamp = nxt.get("timestamp")
            if not isinstance(current_timestamp, datetime) or not isinstance(next_timestamp, datetime):
                continue
            elapsed_hours = (next_timestamp - current_timestamp).total_seconds() / 3600
            if elapsed_hours <= 0 or elapsed_hours > 24:
                continue
            current_capacity = self._coerce_int(current.get("capacity_mwh"))
            next_capacity = self._coerce_int(nxt.get("capacity_mwh"))
            if current_capacity is None or next_capacity is None or next_capacity <= current_capacity:
                continue
            sources = {str(current.get("source") or "").strip().lower(), str(nxt.get("source") or "").strip().lower()}
            if "ac" not in sources:
                continue
            charge_mwh += next_capacity - current_capacity
            charge_hours += elapsed_hours
        if charge_hours <= 0:
            return None
        return int(round(charge_mwh / charge_hours))

    def _estimate_discharge_rate_from_usage(self, rows: list[dict[str, Any]]) -> int | None:
        discharge_mwh = 0
        discharge_hours = 0.0
        for row in rows:
            duration_seconds = self._coerce_int(row.get("duration_seconds"))
            energy_mwh = self._coerce_int(row.get("energy_mwh"))
            if duration_seconds is None or energy_mwh is None or duration_seconds <= 0:
                continue
            discharge_mwh += energy_mwh
            discharge_hours += duration_seconds / 3600
        if discharge_hours <= 0:
            return None
        return int(round(discharge_mwh / discharge_hours))

    def _extract_report_section(self, text: str, start_heading: str, end_heading: str) -> str:
        start = text.find(start_heading)
        if start < 0:
            return ""
        end = text.find(end_heading, start)
        if end < 0:
            end = len(text)
        return text[start:end]

    def _extract_report_rows(self, section: str) -> list[str]:
        return re.findall(r"<tr[^>]*>.*?</tr>", section, flags=re.IGNORECASE | re.DOTALL)

    def _extract_td_content(self, row: str, class_name: str) -> str:
        match = re.search(
            rf'<td[^>]*class="[^"]*{re.escape(class_name)}[^"]*"[^>]*>(.*?)</td>',
            row,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return ""
        cleaned = re.sub(r"<[^>]+>", " ", match.group(1))
        return " ".join(html.unescape(cleaned).split()).strip()

    def _parse_hms_to_seconds(self, raw: str) -> int | None:
        cleaned = " ".join(html.unescape(raw).split()).strip()
        if not cleaned or cleaned == "-":
            return None
        parts = cleaned.split(":")
        if len(parts) != 3:
            return None
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
        except ValueError:
            return None
        return hours * 3600 + minutes * 60 + seconds

    def _saved_home_location(self) -> dict[str, Any] | None:
        saved_home = self._preference_dict(self._HOME_LOCATION_KEY)
        if saved_home:
            return {
                "resolved": True,
                "source": "saved_home",
                "label": str(saved_home.get("label") or "Saved home"),
                "latitude": float(saved_home["latitude"]),
                "longitude": float(saved_home["longitude"]),
                "timezone": saved_home.get("timezone"),
                "address_text": saved_home.get("address_text"),
                "approximate": bool(saved_home.get("approximate", False)),
                "used_home_fallback": False,
                "saved_at": saved_home.get("saved_at"),
            }
        latitude = self.config.location.home_latitude
        longitude = self.config.location.home_longitude
        if latitude is None or longitude is None:
            return None
        label_parts = [
            self.config.location.home_label,
            self.config.location.home_city,
            self.config.location.home_region,
            self.config.location.home_country,
        ]
        label = ", ".join(part for part in label_parts if part)
        return {
            "resolved": True,
            "source": "saved_home",
            "label": label or "Saved home",
            "latitude": latitude,
            "longitude": longitude,
            "timezone": self.config.location.home_timezone,
            "approximate": False,
            "used_home_fallback": False,
        }

    def _saved_named_locations(self) -> list[dict[str, Any]]:
        locations = self._named_locations_map()
        ordered = sorted(
            locations.values(),
            key=lambda item: str(item.get("name") or item.get("label") or "").lower(),
        )
        return [
            {
                "resolved": True,
                "source": "saved_named",
                "name": str(item.get("name") or item.get("label") or "Saved location"),
                "label": str(item.get("label") or item.get("name") or "Saved location"),
                "latitude": float(item["latitude"]),
                "longitude": float(item["longitude"]),
                "timezone": item.get("timezone"),
                "address_text": item.get("address_text"),
                "approximate": bool(item.get("approximate", False)),
                "used_home_fallback": False,
                "saved_at": item.get("saved_at"),
            }
            for item in ordered
            if isinstance(item, dict) and item.get("latitude") is not None and item.get("longitude") is not None
        ]

    def _saved_named_location(self, name: str) -> dict[str, Any] | None:
        normalized_name = name.strip().lower()
        if not normalized_name:
            return None
        locations = self._named_locations_map()
        item = locations.get(normalized_name)
        if not isinstance(item, dict):
            return None
        return {
            "resolved": True,
            "source": "saved_named",
            "name": str(item.get("name") or name.strip()),
            "label": str(item.get("label") or item.get("name") or name.strip()),
            "latitude": float(item["latitude"]),
            "longitude": float(item["longitude"]),
            "timezone": item.get("timezone"),
            "address_text": item.get("address_text"),
            "approximate": bool(item.get("approximate", False)),
            "used_home_fallback": False,
            "saved_at": item.get("saved_at"),
        }

    def _named_locations_map(self) -> dict[str, dict[str, Any]]:
        raw = self._preference_value(self._NAMED_LOCATIONS_KEY)
        if not isinstance(raw, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            if value.get("latitude") is None or value.get("longitude") is None:
                continue
            result[key.strip().lower()] = dict(value)
        return result

    def _preference_value(self, key: str) -> object | None:
        if self.preferences is None:
            return None
        return self.preferences.get_all().get(key)

    def _preference_dict(self, key: str) -> dict[str, Any] | None:
        value = self._preference_value(key)
        if isinstance(value, dict) and value.get("latitude") is not None and value.get("longitude") is not None:
            return dict(value)
        return None

    def _set_preference(self, key: str, value: object) -> None:
        if self.preferences is not None:
            self.preferences.set_preference(key, value)

    def _live_device_location(self) -> dict[str, Any] | None:
        return self._run_windows_location_lookup(allow_coarse=False)

    def _approximate_device_location(self) -> dict[str, Any] | None:
        return self._run_windows_location_lookup(allow_coarse=True)

    def _ip_estimate_location(self) -> dict[str, Any] | None:
        if not self.config.location.allow_approximate_lookup:
            return None
        payload = self._fetch_json(
            "https://ipapi.co/json/",
            timeout=self.config.location.lookup_timeout_seconds,
        )
        if not isinstance(payload, dict):
            return None
        latitude = payload.get("latitude")
        longitude = payload.get("longitude")
        if latitude in {None, ""} or longitude in {None, ""}:
            return None
        city = str(payload.get("city", "")).strip()
        region = str(payload.get("region", "")).strip()
        country = str(payload.get("country_name", "")).strip()
        label = ", ".join(part for part in (city, region or country) if part) or "Approximate current location"
        return {
            "resolved": True,
            "source": "ip_estimate",
            "label": label,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "timezone": str(payload.get("timezone", "")).strip() or None,
            "approximate": True,
            "used_home_fallback": False,
            "ip": str(payload.get("ip", "")).strip() or None,
        }

    def _query_location_lookup(self, query: str) -> dict[str, Any] | None:
        normalized_query = " ".join(str(query or "").split()).strip(" ,.;:!?")
        if not normalized_query:
            return None
        zip_lookup = self._zip_location_lookup(normalized_query)
        if zip_lookup:
            return zip_lookup
        return self._geocode_location_lookup(normalized_query)

    def _zip_location_lookup(self, query: str) -> dict[str, Any] | None:
        match = re.fullmatch(r"(?P<zip>\d{5})(?:-\d{4})?", query.strip())
        if not match:
            return None
        zip_code = match.group("zip")
        payload = self._fetch_json(
            f"https://api.zippopotam.us/us/{zip_code}",
            timeout=self.config.location.lookup_timeout_seconds,
        )
        if not isinstance(payload, dict):
            return None
        places = payload.get("places")
        if not isinstance(places, list) or not places or not isinstance(places[0], dict):
            return None
        place = places[0]
        city = str(place.get("place name", "")).strip()
        state = str(place.get("state", "")).strip()
        country = str(payload.get("country", "")).strip()
        label_parts = [part for part in (city, state) if part]
        label = ", ".join(label_parts)
        if zip_code:
            label = f"{label} {zip_code}".strip() if label else zip_code
        if not label and country:
            label = f"{country} {zip_code}".strip()
        latitude = place.get("latitude")
        longitude = place.get("longitude")
        if latitude in {None, ""} or longitude in {None, ""}:
            return None
        return {
            "resolved": True,
            "source": "queried_place",
            "name": query,
            "label": label or query,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "timezone": None,
            "address_text": query,
            "approximate": False,
            "used_home_fallback": False,
            "query_type": "zip_code",
        }

    def _geocode_location_lookup(self, query: str) -> dict[str, Any] | None:
        params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1})
        payload = self._fetch_json(
            f"https://nominatim.openstreetmap.org/search?{params}",
            timeout=self.config.location.lookup_timeout_seconds,
        )
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            return None
        entry = payload[0]
        latitude = entry.get("latitude")
        longitude = entry.get("longitude")
        if latitude in {None, ""} or longitude in {None, ""}:
            latitude = entry.get("lat")
            longitude = entry.get("lon")
        if latitude in {None, ""} or longitude in {None, ""}:
            return None
        address = entry.get("address") if isinstance(entry.get("address"), dict) else {}
        name = str(entry.get("name", "")).strip() or query
        region = ""
        country = ""
        if isinstance(address, dict):
            region = str(address.get("state") or address.get("region") or address.get("county") or "").strip()
            country = str(address.get("country") or "").strip()
        label_parts: list[str] = []
        for part in (name, region, country):
            if part and part not in label_parts:
                label_parts.append(part)
        return {
            "resolved": True,
            "source": "queried_place",
            "name": query,
            "label": ", ".join(label_parts) or query,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "timezone": str(entry.get("timezone", "")).strip() or None,
            "address_text": query,
            "approximate": False,
            "used_home_fallback": False,
            "query_type": "place_query",
        }

    def _run_windows_location_lookup(self, *, allow_coarse: bool) -> dict[str, Any] | None:
        payload = self._run_powershell_json(
            f"""
            Add-Type -AssemblyName System.Runtime.WindowsRuntime
            $null = [Windows.Devices.Geolocation.Geolocator, Windows, ContentType=WindowsRuntime]
            $null = [Windows.Devices.Geolocation.GeolocationAccessStatus, Windows, ContentType=WindowsRuntime]
            $null = [Windows.Devices.Geolocation.Geoposition, Windows, ContentType=WindowsRuntime]
            function Await-Result($operation, [Type]$resultType) {{
                $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{
                    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.ToString().Contains('IAsyncOperation`1')
                }} | Select-Object -First 1
                if (-not $method) {{ throw 'missing_astask' }}
                $task = $method.MakeGenericMethod($resultType).Invoke($null, @($operation))
                $null = $task.Wait(4000)
                if (-not $task.IsCompleted) {{ throw 'timeout' }}
                return $task.Result
            }}
            try {{
                $geolocator = [Windows.Devices.Geolocation.Geolocator]::new()
                $geolocator.DesiredAccuracyInMeters = 750
                if ({'$'}{str(allow_coarse).lower()}) {{
                    try {{ $geolocator.AllowFallbackToConsentlessPositions() }} catch {{ }}
                }} else {{
                    $access = Await-Result -operation ([Windows.Devices.Geolocation.Geolocator]::RequestAccessAsync()) -resultType ([Windows.Devices.Geolocation.GeolocationAccessStatus])
                    if ($access -ne [Windows.Devices.Geolocation.GeolocationAccessStatus]::Allowed) {{
                        [pscustomobject]@{{ resolved = $false; reason = "permission_" + $access.ToString().ToLower() }} | ConvertTo-Json -Compress
                        return
                    }}
                }}
                $position = Await-Result -operation ($geolocator.GetGeopositionAsync([TimeSpan]::FromMinutes(15), [TimeSpan]::FromSeconds(5))) -resultType ([Windows.Devices.Geolocation.Geoposition])
                $coordinate = $position.Coordinate
                $point = $coordinate.Point.Position
                [pscustomobject]@{{
                    resolved = $true
                    source = "{'approximate_device' if allow_coarse else 'device_live'}"
                    label = "Device location"
                    latitude = $point.Latitude
                    longitude = $point.Longitude
                    approximate = {str(allow_coarse).lower()}
                    used_home_fallback = $false
                    accuracy_meters = $coordinate.Accuracy
                    timestamp = $position.Coordinate.Timestamp.ToString("o")
                }} | ConvertTo-Json -Compress
            }} catch {{
                [pscustomobject]@{{ resolved = $false; reason = $_.Exception.Message }} | ConvertTo-Json -Compress
            }}
            """
        )
        if not isinstance(payload, dict):
            return None
        if not payload.get("resolved"):
            payload.setdefault("source", "approximate_device" if allow_coarse else "device_live")
            return payload
        payload["label"] = str(payload.get("label") or "Device location")
        return payload

    def _select_weather_forecast(self, payload: dict[str, Any], *, forecast_target: str) -> dict[str, Any]:
        current = payload.get("current", {}) if isinstance(payload.get("current"), dict) else {}
        daily = payload.get("daily", {}) if isinstance(payload.get("daily"), dict) else {}
        hourly = payload.get("hourly", {}) if isinstance(payload.get("hourly"), dict) else {}
        if forecast_target == "current":
            highs = daily.get("temperature_2m_max") if isinstance(daily.get("temperature_2m_max"), list) else []
            lows = daily.get("temperature_2m_min") if isinstance(daily.get("temperature_2m_min"), list) else []
            return {
                "temperature": current.get("temperature_2m"),
                "apparent_temperature": current.get("apparent_temperature"),
                "weather_code": current.get("weather_code"),
                "high": highs[0] if highs else None,
                "low": lows[0] if lows else None,
            }

        dates = daily.get("time") if isinstance(daily.get("time"), list) else []
        highs = daily.get("temperature_2m_max") if isinstance(daily.get("temperature_2m_max"), list) else []
        lows = daily.get("temperature_2m_min") if isinstance(daily.get("temperature_2m_min"), list) else []
        codes = daily.get("weather_code") if isinstance(daily.get("weather_code"), list) else []
        if forecast_target == "tomorrow" and len(dates) > 1:
            return {
                "temperature": highs[1] if len(highs) > 1 else None,
                "apparent_temperature": None,
                "weather_code": codes[1] if len(codes) > 1 else None,
                "high": highs[1] if len(highs) > 1 else None,
                "low": lows[1] if len(lows) > 1 else None,
            }
        if forecast_target == "weekend":
            for index, raw in enumerate(dates):
                try:
                    stamp = datetime.fromisoformat(str(raw))
                except ValueError:
                    continue
                if stamp.weekday() in {5, 6}:
                    return {
                        "temperature": highs[index] if len(highs) > index else None,
                        "apparent_temperature": None,
                        "weather_code": codes[index] if len(codes) > index else None,
                        "high": highs[index] if len(highs) > index else None,
                        "low": lows[index] if len(lows) > index else None,
                    }

        if forecast_target == "tonight":
            hours = hourly.get("time") if isinstance(hourly.get("time"), list) else []
            temps = hourly.get("temperature_2m") if isinstance(hourly.get("temperature_2m"), list) else []
            apparent = hourly.get("apparent_temperature") if isinstance(hourly.get("apparent_temperature"), list) else []
            hourly_codes = hourly.get("weather_code") if isinstance(hourly.get("weather_code"), list) else []
            for index, raw in enumerate(hours):
                try:
                    stamp = datetime.fromisoformat(str(raw))
                except ValueError:
                    continue
                if stamp.hour >= 18:
                    return {
                        "temperature": temps[index] if len(temps) > index else None,
                        "apparent_temperature": apparent[index] if len(apparent) > index else None,
                        "weather_code": hourly_codes[index] if len(hourly_codes) > index else None,
                        "high": None,
                        "low": None,
                    }

        return {
            "temperature": current.get("temperature_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "weather_code": current.get("weather_code"),
            "high": highs[0] if highs else None,
            "low": lows[0] if lows else None,
        }

    def _fetch_json(self, url: str, *, timeout: float) -> Any:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Stormhelm/0.1"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return json.loads(response.read().decode(charset))
        except Exception:
            return None

    def _weather_code_label(self, code: int) -> str:
        labels = {
            0: "Clear sky",
            1: "Mostly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Drizzle",
            55: "Dense drizzle",
            56: "Freezing drizzle",
            57: "Dense freezing drizzle",
            61: "Light rain",
            63: "Rain",
            65: "Heavy rain",
            66: "Freezing rain",
            67: "Heavy freezing rain",
            71: "Light snow",
            73: "Snow",
            75: "Heavy snow",
            77: "Snow grains",
            80: "Rain showers",
            81: "Heavy rain showers",
            82: "Violent rain showers",
            85: "Snow showers",
            86: "Heavy snow showers",
            95: "Thunderstorm",
            96: "Thunderstorm with hail",
            99: "Severe thunderstorm with hail",
        }
        return labels.get(code, "Unsettled conditions")

    def _weather_page_url(self, latitude: float, longitude: float) -> str:
        return f"https://weather.com/weather/today/l/{latitude:.4f},{longitude:.4f}"

    def _coerce_int(self, value: Any) -> int | None:
        if value in {None, "", 0xFFFFFFFF}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
