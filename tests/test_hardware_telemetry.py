from __future__ import annotations

import subprocess

from stormhelm.core.system.hardware_telemetry import (
    HardwareTelemetryHelperClient,
    _run_powershell_json,
    build_helper_unreachable_snapshot,
    merge_hardware_snapshots,
    overlay_power_status,
    overlay_resource_status,
)


def test_helper_unreachable_snapshot_reports_fallback_capabilities() -> None:
    snapshot = build_helper_unreachable_snapshot(
        sampling_tier="active",
        reason="helper_missing",
        installed=False,
    )

    assert snapshot["capabilities"]["helper_installed"] is False
    assert snapshot["capabilities"]["helper_reachable"] is False
    assert snapshot["freshness"]["reason"] == "helper_missing"
    assert snapshot["sources"]["helper"]["state"] == "unreachable"


def test_helper_wrapper_and_provider_collectors_use_separate_timeouts(temp_config, monkeypatch) -> None:
    temp_config.hardware_telemetry.helper_timeout_seconds = 12.0
    temp_config.hardware_telemetry.provider_timeout_seconds = 5.0
    calls: list[tuple[list[str], float]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), float(kwargs["timeout"])))
        return subprocess.CompletedProcess(command, 0, "{}", "")

    monkeypatch.setattr("stormhelm.core.system.hardware_telemetry.subprocess.run", fake_run)

    HardwareTelemetryHelperClient(temp_config).snapshot(sampling_tier="active")
    _run_powershell_json(temp_config, "[pscustomobject]@{} | ConvertTo-Json -Compress")

    assert calls[0][1] == 12.0
    assert calls[1][1] == 5.0


def test_merge_hardware_snapshots_prefers_enrichment_values_without_dropping_existing_fields() -> None:
    primary = {
        "cpu": {"package_temperature_c": 61.0, "effective_clock_mhz": 4200},
        "sources": {"cpu": {"provider": "windows_native"}},
    }
    enrichment = {
        "cpu": {"package_temperature_c": 64.5},
        "sources": {"hwinfo": {"provider": "hwinfo_enrichment", "state": "available"}},
    }

    merged = merge_hardware_snapshots(primary, enrichment)

    assert merged["cpu"]["package_temperature_c"] == 64.5
    assert merged["cpu"]["effective_clock_mhz"] == 4200
    assert merged["sources"]["cpu"]["provider"] == "windows_native"
    assert merged["sources"]["hwinfo"]["provider"] == "hwinfo_enrichment"


def test_overlay_power_status_promotes_helper_measurements() -> None:
    base = {"available": True, "battery_percent": 52, "ac_line_status": "offline"}
    snapshot = {
        "power": {
            "battery_percent": 53,
            "instant_draw_w": 26.5,
            "rolling_average_draw_w": 22.25,
            "battery_current_ma": 2100,
            "remaining_capacity_mwh": 48000,
            "full_charge_capacity_mwh": 64000,
            "stabilized_estimate_seconds": 7200,
            "wear_percent": 8.0,
            "health_percent": 92.0,
        },
        "capabilities": {"helper_reachable": True, "power_current_available": True},
        "sources": {"power": {"provider": "windows_native"}},
        "freshness": {"sampling_tier": "active", "sample_age_seconds": 0.5},
        "monitoring": {"rolling_window_seconds": 180},
    }

    result = overlay_power_status(base, snapshot)

    assert result["battery_percent"] == 53
    assert result["instant_power_draw_watts"] == 26.5
    assert result["rolling_power_draw_watts"] == 22.25
    assert result["battery_current_ma"] == 2100
    assert result["seconds_remaining"] == 7200
    assert result["helper_available"] is True
    assert result["telemetry_capabilities"]["power_current_available"] is True


def test_overlay_resource_status_carries_helper_cpu_gpu_and_thermal_fields() -> None:
    base = {
        "cpu": {"name": "AMD Ryzen", "cores": 8, "logical_processors": 16},
        "memory": {"total_bytes": 32, "used_bytes": 16, "free_bytes": 16},
        "gpu": [{"name": "NVIDIA RTX", "driver_version": "555.10"}],
    }
    snapshot = {
        "cpu": {"package_temperature_c": 71.5, "effective_clock_mhz": 4380, "utilization_percent": 42.0},
        "gpu": {
            "adapters": [
                {
                    "name": "NVIDIA RTX",
                    "driver_version": "555.10",
                    "temperature_c": 66.0,
                    "utilization_percent": 58.0,
                    "power_w": 140.5,
                }
            ]
        },
        "thermal": {"sensors": [{"label": "CPU", "temperature_c": 71.5}]},
        "capabilities": {"gpu_deep_telemetry_available": True},
        "sources": {"gpu": {"provider": "windows_native"}},
        "freshness": {"sampling_tier": "active", "sample_age_seconds": 1.0},
        "monitoring": {"rolling_window_seconds": 180},
    }

    result = overlay_resource_status(base, snapshot)

    assert result["cpu"]["package_temperature_c"] == 71.5
    assert result["cpu"]["effective_clock_mhz"] == 4380
    assert result["gpu"][0]["temperature_c"] == 66.0
    assert result["gpu"][0]["power_w"] == 140.5
    assert result["thermal"]["sensors"][0]["label"] == "CPU"
    assert result["capabilities"]["gpu_deep_telemetry_available"] is True
