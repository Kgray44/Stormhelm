from __future__ import annotations

import subprocess

import pytest

from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.system.probe import SystemProbe


def test_resolve_location_prefers_live_device_source(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(
        SystemProbe,
        "_live_device_location",
        lambda self: {
            "resolved": True,
            "source": "device_live",
            "label": "Live Device",
            "latitude": 1.0,
            "longitude": 2.0,
            "approximate": False,
            "used_home_fallback": False,
        },
    )
    monkeypatch.setattr(SystemProbe, "_approximate_device_location", lambda self: None)
    monkeypatch.setattr(SystemProbe, "_saved_home_location", lambda self: None)
    monkeypatch.setattr(SystemProbe, "_ip_estimate_location", lambda self: None)

    result = probe.resolve_location(mode="auto", allow_home_fallback=True)

    assert result["source"] == "device_live"


def test_resolve_location_falls_back_to_saved_home_before_ip(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(SystemProbe, "_live_device_location", lambda self: None)
    monkeypatch.setattr(SystemProbe, "_approximate_device_location", lambda self: None)
    monkeypatch.setattr(
        SystemProbe,
        "_saved_home_location",
        lambda self: {
            "resolved": True,
            "source": "saved_home",
            "label": "Brooklyn Home",
            "latitude": 40.0,
            "longitude": -73.0,
            "approximate": False,
            "used_home_fallback": False,
        },
    )
    monkeypatch.setattr(
        SystemProbe,
        "_ip_estimate_location",
        lambda self: {
            "resolved": True,
            "source": "ip_estimate",
            "label": "Queens, New York",
            "latitude": 40.7,
            "longitude": -73.8,
            "approximate": True,
            "used_home_fallback": False,
        },
    )

    result = probe.resolve_location(mode="auto", allow_home_fallback=True)

    assert result["source"] == "saved_home"
    assert result["used_home_fallback"] is True


def test_resolve_location_uses_ip_estimate_when_home_fallback_is_disabled(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(SystemProbe, "_live_device_location", lambda self: None)
    monkeypatch.setattr(SystemProbe, "_approximate_device_location", lambda self: None)
    monkeypatch.setattr(
        SystemProbe,
        "_saved_home_location",
        lambda self: {
            "resolved": True,
            "source": "saved_home",
            "label": "Brooklyn Home",
            "latitude": 40.0,
            "longitude": -73.0,
            "approximate": False,
            "used_home_fallback": False,
        },
    )
    monkeypatch.setattr(
        SystemProbe,
        "_ip_estimate_location",
        lambda self: {
            "resolved": True,
            "source": "ip_estimate",
            "label": "Queens, New York",
            "latitude": 40.7,
            "longitude": -73.8,
            "approximate": True,
            "used_home_fallback": False,
        },
    )

    result = probe.resolve_location(mode="current", allow_home_fallback=False)

    assert result["source"] == "ip_estimate"


def test_saved_home_location_prefers_persistent_memory_over_config(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    preferences = PreferencesRepository(database)
    temp_config.location.home_label = "Config Home"
    temp_config.location.home_latitude = 41.0
    temp_config.location.home_longitude = -74.0
    probe = SystemProbe(temp_config, preferences=preferences)

    probe.save_home_location(
        label="Persistent Home",
        latitude=40.6782,
        longitude=-73.9442,
        timezone="America/New_York",
        source="saved_home",
    )

    result = probe.resolve_location(mode="home", allow_home_fallback=False)

    assert result["source"] == "saved_home"
    assert result["label"] == "Persistent Home"
    assert result["latitude"] == pytest.approx(40.6782)


def test_hardware_telemetry_cache_uses_completion_time_for_freshness(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    temp_config.hardware_telemetry.active_cache_ttl_seconds = 8.0
    call_count = 0

    def fake_snapshot(self, *, sampling_tier: str = "active") -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {
            "capabilities": {"helper_reachable": True},
            "freshness": {"sampling_tier": sampling_tier, "sample_age_seconds": 0.0},
        }

    monotonic_values = iter([100.0, 109.0, 110.0])
    monkeypatch.setattr("stormhelm.core.system.probe.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("stormhelm.core.system.probe.HardwareTelemetryHelperClient.snapshot", fake_snapshot)

    first = probe.hardware_telemetry_snapshot(sampling_tier="active")
    second = probe.hardware_telemetry_snapshot(sampling_tier="active")

    assert call_count == 1
    assert first["freshness"]["sample_age_seconds"] == 0.0
    assert second["freshness"]["sample_age_seconds"] == pytest.approx(1.0)


def test_saved_named_location_is_available_to_best_resolver(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    preferences = PreferencesRepository(database)
    probe = SystemProbe(temp_config, preferences=preferences)

    probe.save_named_location(
        name="studio",
        label="Studio",
        latitude=40.7,
        longitude=-73.9,
        timezone="America/New_York",
        source="manual",
    )

    result = probe.resolve_best_location_for_request(named_location="studio")

    assert result["resolved"] is True
    assert result["source"] == "saved_named"
    assert result["label"] == "Studio"


def test_resolve_best_location_geocodes_explicit_place_query_when_not_saved(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(SystemProbe, "_saved_named_location", lambda self, name: None)
    monkeypatch.setattr(
        SystemProbe,
        "_query_location_lookup",
        lambda self, query: {
            "resolved": True,
            "source": "queried_place",
            "label": "Concord, New Hampshire",
            "name": query,
            "latitude": 43.2081,
            "longitude": -71.5376,
            "timezone": "America/New_York",
            "approximate": False,
            "used_home_fallback": False,
        },
    )

    result = probe.resolve_best_location_for_request(named_location="Concord, New Hampshire")

    assert result["resolved"] is True
    assert result["source"] == "queried_place"
    assert result["label"] == "Concord, New Hampshire"


def test_query_location_lookup_prefers_zip_lookup_for_zip_code(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(
        SystemProbe,
        "_zip_location_lookup",
        lambda self, query: {
            "resolved": True,
            "source": "queried_place",
            "label": "Beverly Hills, California 90210",
            "name": query,
            "latitude": 34.0901,
            "longitude": -118.4065,
            "timezone": "America/Los_Angeles",
            "approximate": False,
            "used_home_fallback": False,
        },
    )
    monkeypatch.setattr(
        SystemProbe,
        "_geocode_location_lookup",
        lambda self, query: pytest.fail("ZIP lookups should not fall through to general geocoding first."),
    )

    result = probe._query_location_lookup("90210")

    assert result is not None
    assert result["resolved"] is True
    assert result["source"] == "queried_place"
    assert result["label"] == "Beverly Hills, California 90210"


def test_power_projection_falls_back_to_battery_report_charge_rate(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(
        SystemProbe,
        "power_status",
        lambda self: {
            "available": True,
            "battery_percent": 99,
            "ac_line_status": "online",
            "seconds_remaining": None,
            "remaining_capacity_mwh": None,
            "full_charge_capacity_mwh": None,
            "charge_rate_mw": None,
            "discharge_rate_mw": None,
            "charge_rate_watts": None,
            "discharge_rate_watts": None,
            "time_to_full_seconds": None,
            "time_to_empty_seconds": None,
        },
    )
    monkeypatch.setattr(
        SystemProbe,
        "_battery_report_summary",
        lambda self: {
            "full_charge_capacity_mwh": 63438,
            "design_capacity_mwh": 76088,
            "estimated_charge_rate_mw": 12000,
            "estimated_discharge_rate_mw": 15000,
        },
    )

    result = probe.power_projection(metric="time_to_percent", target_percent=100, assume_unplugged=False)

    assert result["reliable"] is True
    assert result["rate_source"] == "battery_report_history"
    assert result["projection_minutes"] is not None


def test_power_projection_falls_back_to_battery_report_discharge_rate_for_unplugged_threshold(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(
        SystemProbe,
        "power_status",
        lambda self: {
            "available": True,
            "battery_percent": 99,
            "ac_line_status": "online",
            "seconds_remaining": None,
            "remaining_capacity_mwh": None,
            "full_charge_capacity_mwh": None,
            "charge_rate_mw": None,
            "discharge_rate_mw": None,
            "charge_rate_watts": None,
            "discharge_rate_watts": None,
            "time_to_full_seconds": None,
            "time_to_empty_seconds": None,
        },
    )
    monkeypatch.setattr(
        SystemProbe,
        "_battery_report_summary",
        lambda self: {
            "full_charge_capacity_mwh": 63438,
            "design_capacity_mwh": 76088,
            "estimated_charge_rate_mw": 12000,
            "estimated_discharge_rate_mw": 15000,
        },
    )

    result = probe.power_projection(metric="time_to_percent", target_percent=50, assume_unplugged=True)

    assert result["reliable"] is True
    assert result["rate_source"] == "battery_report_history"
    assert result["projection_minutes"] is not None


def test_power_projection_prefers_helper_measured_draw(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(
        SystemProbe,
        "power_status",
        lambda self: {
            "available": True,
            "battery_percent": 50,
            "ac_line_status": "offline",
            "seconds_remaining": None,
            "remaining_capacity_mwh": 50000,
            "full_charge_capacity_mwh": 80000,
            "charge_rate_mw": None,
            "discharge_rate_mw": None,
            "charge_rate_watts": None,
            "discharge_rate_watts": None,
            "instant_power_draw_watts": 30.0,
            "rolling_power_draw_watts": 25.0,
            "time_to_full_seconds": None,
            "time_to_empty_seconds": None,
        },
    )
    monkeypatch.setattr(
        SystemProbe,
        "_battery_report_summary",
        lambda self: {
            "full_charge_capacity_mwh": 80000,
            "estimated_discharge_rate_mw": 15000,
        },
    )

    result = probe.power_projection(metric="time_to_empty")

    assert result["reliable"] is True
    assert result["rate_source"] == "helper_rolling_average"
    assert result["projection_seconds"] == 7200
    assert result["power_draw_watts"] == 25.0


def test_resource_status_overlays_helper_snapshot(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {
            "cpu": {
                "Name": "AMD Ryzen",
                "NumberOfCores": 8,
                "NumberOfLogicalProcessors": 16,
                "MaxClockSpeed": 4200,
            },
            "os": {"TotalVisibleMemorySize": 1024, "FreePhysicalMemory": 512},
            "gpu": [{"Name": "NVIDIA RTX", "AdapterRAM": 17179869184, "DriverVersion": "555.10"}],
        },
    )
    monkeypatch.setattr(
        SystemProbe,
        "hardware_telemetry_snapshot",
        lambda self, sampling_tier="active", force_refresh=False: {
            "cpu": {"package_temperature_c": 72.0, "effective_clock_mhz": 4360, "utilization_percent": 48.0},
            "gpu": {"adapters": [{"name": "NVIDIA RTX", "temperature_c": 67.0, "utilization_percent": 61.0, "power_w": 155.5}]},
            "thermal": {"sensors": [{"label": "CPU", "temperature_c": 72.0}]},
            "capabilities": {"helper_reachable": True},
            "sources": {"gpu": {"provider": "windows_native"}},
            "freshness": {"sampling_tier": "active", "sample_age_seconds": 1.0},
            "monitoring": {"rolling_window_seconds": 180},
        },
    )

    result = probe.resource_status()

    assert result["cpu"]["package_temperature_c"] == 72.0
    assert result["cpu"]["effective_clock_mhz"] == 4360
    assert result["gpu"][0]["temperature_c"] == 67.0
    assert result["gpu"][0]["power_w"] == 155.5
    assert result["thermal"]["sensors"][0]["label"] == "CPU"


def test_network_probe_hides_console_window_on_windows(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    captured: dict[str, object] = {}

    class FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = None

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="Reply from 1.1.1.1: bytes=32 time=27ms TTL=57",
            stderr="",
        )

    monkeypatch.setattr("stormhelm.core.system.probe.os.name", "nt")
    monkeypatch.setattr("stormhelm.core.system.probe.subprocess.CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr("stormhelm.core.system.probe.subprocess.STARTUPINFO", FakeStartupInfo, raising=False)
    monkeypatch.setattr("stormhelm.core.system.probe.subprocess.STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr("stormhelm.core.system.probe.subprocess.SW_HIDE", 0, raising=False)
    monkeypatch.setattr("stormhelm.core.system.probe.subprocess.run", fake_run)

    result = probe._network_probe("1.1.1.1", timeout_ms=1200)

    assert result["reachable"] is True
    assert captured["command"] == ["ping", "-n", "1", "-w", "1200", "1.1.1.1"]
    assert captured["creationflags"] == 0x08000000
    assert isinstance(captured["startupinfo"], FakeStartupInfo)
    assert captured["startupinfo"].dwFlags == 1
    assert captured["startupinfo"].wShowWindow == 0


def test_app_control_focuses_matching_visible_app(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    def fake_run(self, script: str):
        scripts.append(script)
        if "Get-Process" in script and "MainWindowTitle" in script:
            return [
                {
                    "ProcessName": "Code",
                    "MainWindowTitle": "Visual Studio Code",
                    "Id": 4120,
                }
            ]
        return {
            "success": True,
            "action": "focus",
            "process_name": "Code",
            "window_title": "Visual Studio Code",
            "pid": 4120,
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="focus", app_name="visual studio code")

    assert result["success"] is True
    assert result["action"] == "focus"
    assert result["process_name"] == "Code"
    assert any("AppActivate" in script for script in scripts)


def test_app_control_force_quits_matching_process(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    def fake_run(self, script: str):
        scripts.append(script)
        if "Get-Process" in script and "MainWindowTitle" in script:
            return [
                {
                    "ProcessName": "chrome",
                    "MainWindowTitle": "Chrome",
                    "Id": 9001,
                }
            ]
        return {
            "success": True,
            "action": "force_quit",
            "process_name": "chrome",
            "window_title": "Chrome",
            "pid": 9001,
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="force_quit", app_name="chrome")

    assert result["success"] is True
    assert result["action"] == "force_quit"
    assert result["pid"] == 9001
    assert any("Stop-Process" in script for script in scripts)


def test_app_control_minimizes_matching_visible_app(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    def fake_run(self, script: str):
        scripts.append(script)
        if "MainWindowTitle" in script:
            return [
                {
                    "ProcessName": "Spotify",
                    "MainWindowTitle": "Spotify Premium",
                    "MainWindowHandle": 4421,
                    "Id": 4110,
                }
            ]
        return {
            "success": True,
            "action": "minimize",
            "process_name": "Spotify",
            "window_title": "Spotify Premium",
            "pid": 4110,
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="minimize", app_name="spotify")

    assert result["success"] is True
    assert result["action"] == "minimize"
    assert any("ShowWindowAsync" in script for script in scripts)


def test_app_control_maximizes_matching_visible_app(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    def fake_run(self, script: str):
        scripts.append(script)
        if "MainWindowTitle" in script:
            return [
                {
                    "ProcessName": "Discord",
                    "MainWindowTitle": "Discord",
                    "MainWindowHandle": 2211,
                    "Id": 3221,
                }
            ]
        return {
            "success": True,
            "action": "maximize",
            "process_name": "Discord",
            "window_title": "Discord",
            "pid": 3221,
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="maximize", app_name="discord")

    assert result["success"] is True
    assert result["action"] == "maximize"
    assert any("ShowWindowAsync" in script for script in scripts)


def test_app_control_alias_matching_finds_vscode_process(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)

    def fake_run(self, script: str):
        if "MainWindowTitle" in script:
            return [
                {
                    "ProcessName": "Code",
                    "MainWindowTitle": "Visual Studio Code",
                    "MainWindowHandle": 991,
                    "Id": 4120,
                }
            ]
        return {
            "success": True,
            "action": "focus",
            "process_name": "Code",
            "window_title": "Visual Studio Code",
            "pid": 4120,
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="focus", app_name="vscode")

    assert result["success"] is True
    assert result["process_name"] == "Code"


def test_app_control_force_quits_background_process_when_window_is_missing(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    def fake_run(self, script: str):
        scripts.append(script)
        if "MainWindowTitle" in script:
            return []
        if "Select-Object ProcessName, Id, Path" in script:
            return [
                {
                    "ProcessName": "node",
                    "Id": 5050,
                    "Path": "C:/Program Files/nodejs/node.exe",
                }
            ]
        return {
            "success": True,
            "action": "force_quit",
            "process_name": "node",
            "pid": 5050,
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="force_quit", app_name="node")

    assert result["success"] is True
    assert result["pid"] == 5050
    assert any("Stop-Process" in script for script in scripts)


def test_app_control_force_quits_all_matching_discord_processes_when_resolved_as_process_group(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {"focused_window": None, "windows": [], "monitors": []},
    )
    monkeypatch.setattr(
        SystemProbe,
        "_running_processes",
        lambda self: [
            {
                "process_name": "Discord",
                "pid": 9360,
                "path": "C:/Users/test/AppData/Local/Discord/app-1.0.9233/Discord.exe",
            },
            {
                "process_name": "Discord",
                "pid": 16364,
                "path": "C:/Users/test/AppData/Local/Discord/app-1.0.9233/Discord.exe",
            },
            {
                "process_name": "Discord",
                "pid": 19512,
                "path": "C:/Users/test/AppData/Local/Discord/app-1.0.9233/Discord.exe",
            },
            {
                "process_name": "Update",
                "pid": 4444,
                "path": "C:/Users/test/AppData/Local/Discord/Update.exe",
            },
        ],
    )

    def fake_run(self, script: str):
        scripts.append(script)
        if all(str(pid) in script for pid in (9360, 16364, 19512)) and "4444" not in script:
            return {
                "success": True,
                "action": "force_quit",
                "process_name": "Discord",
                "pid": 9360,
                "pids": [9360, 16364, 19512],
                "terminated_pids": [9360, 16364, 19512],
                "terminated_count": 3,
                "resolution_source": "process_group",
            }
        return {"success": False, "action": "force_quit", "reason": "single_pid_only"}

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="force_quit", app_name="Discord")

    assert result["success"] is True
    assert result["resolution_source"] == "process_group"
    assert result["terminated_count"] == 3
    assert result["pids"] == [9360, 16364, 19512]
    assert any("Stop-Process" in script for script in scripts)


def test_app_control_closes_snipping_tool_via_window_title_resolution(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {
            "focused_window": None,
            "windows": [
                {
                    "process_name": "ScreenClippingHost",
                    "window_title": "Snipping Tool",
                    "window_handle": 5511,
                    "pid": 8421,
                    "path": "C:/Windows/SystemApps/Microsoft.ScreenSketch_8wekyb3d8bbwe/ScreenClippingHost.exe",
                }
            ],
            "monitors": [],
        },
    )
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])

    def fake_run(self, script: str):
        scripts.append(script)
        return {
            "success": True,
            "action": "close",
            "process_name": "ScreenClippingHost",
            "window_title": "Snipping Tool",
            "pid": 8421,
            "resolution_source": "window_title",
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="close", app_name="Snipping Tool")

    assert result["success"] is True
    assert result["window_title"] == "Snipping Tool"
    assert result["resolution_source"] == "window_title"
    assert any("CloseMainWindow" in script or "PostMessage" in script for script in scripts)


def test_app_control_force_quits_snipping_tool_preferring_real_process_over_false_positive_package_match(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {"focused_window": None, "windows": [], "monitors": []},
    )
    monkeypatch.setattr(
        SystemProbe,
        "_running_processes",
        lambda self: [
            {
                "process_name": "PhoneExperienceHost",
                "pid": 19184,
                "path": "C:/Program Files/WindowsApps/Microsoft.YourPhone_1.26022.64.0_x64__8wekyb3d8bbwe/PhoneExperienceHost.exe",
            },
            {
                "process_name": "SnippingTool",
                "pid": 8180,
                "path": "C:/Program Files/WindowsApps/Microsoft.ScreenSketch_11.2601.2.0_x64__8wekyb3d8bbwe/SnippingTool/SnippingTool.exe",
            },
        ],
    )

    def fake_run(self, script: str):
        scripts.append(script)
        if "8180" in script and "19184" not in script:
            return {
                "success": True,
                "action": "force_quit",
                "process_name": "SnippingTool",
                "pid": 8180,
                "terminated_pids": [8180],
                "resolution_source": "process_name",
            }
        return {"success": False, "action": "force_quit", "reason": "wrong_process_target"}

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="force_quit", app_name="Snipping Tool")

    assert result["success"] is True
    assert result["process_name"] == "SnippingTool"
    assert result["pid"] == 8180
    assert result["resolution_source"] == "process_name"
    assert any("Stop-Process" in script for script in scripts)


def test_app_control_force_quits_snipping_tool_using_resolved_process_instead_of_host_window(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {
            "focused_window": None,
            "windows": [
                {
                    "process_name": "ApplicationFrameHost",
                    "window_title": "Snipping Tool",
                    "window_handle": 5511,
                    "pid": 28700,
                    "path": "C:/WINDOWS/system32/ApplicationFrameHost.exe",
                }
            ],
            "monitors": [],
        },
    )
    monkeypatch.setattr(
        SystemProbe,
        "_running_processes",
        lambda self: [
            {
                "process_name": "SnippingTool",
                "pid": 8180,
                "path": "C:/Program Files/WindowsApps/Microsoft.ScreenSketch_11.2601.2.0_x64__8wekyb3d8bbwe/SnippingTool/SnippingTool.exe",
            }
        ],
    )

    def fake_run(self, script: str):
        scripts.append(script)
        if "8180" in script and "28700" not in script:
            return {
                "success": True,
                "action": "force_quit",
                "process_name": "SnippingTool",
                "pid": 8180,
                "terminated_pids": [8180],
                "resolution_source": "window_process",
            }
        return {"success": False, "action": "force_quit", "reason": "host_window_pid_used"}

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="force_quit", app_name="Snipping Tool")

    assert result["success"] is True
    assert result["process_name"] == "SnippingTool"
    assert result["pid"] == 8180
    assert result["resolution_source"] == "window_process"
    assert any("Stop-Process" in script for script in scripts)


def test_app_control_force_quits_snipping_tool_via_builtin_alias_background_process(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {"focused_window": None, "windows": [], "monitors": []},
    )
    monkeypatch.setattr(
        SystemProbe,
        "_running_processes",
        lambda self: [
            {
                "process_name": "ScreenClippingHost",
                "pid": 8421,
                "path": "C:/Windows/SystemApps/Microsoft.ScreenSketch_8wekyb3d8bbwe/ScreenClippingHost.exe",
            }
        ],
    )

    def fake_run(self, script: str):
        scripts.append(script)
        return {
            "success": True,
            "action": "force_quit",
            "process_name": "ScreenClippingHost",
            "pid": 8421,
            "resolution_source": "process_name",
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.app_control(action="force_quit", app_name="Snipping Tool")

    assert result["success"] is True
    assert result["process_name"] == "ScreenClippingHost"
    assert result["resolution_source"] == "process_name"
    assert any("Stop-Process" in script for script in scripts)


def test_app_control_reports_builtin_app_not_running_precisely(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {"focused_window": None, "windows": [], "monitors": []},
    )
    monkeypatch.setattr(SystemProbe, "_running_processes", lambda self: [])

    result = probe.app_control(action="force_quit", app_name="Snipping Tool")

    assert result["success"] is False
    assert result["reason"] == "app_not_running"


def test_app_control_reports_missing_window_when_discord_is_running_but_no_window_is_visible(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)

    monkeypatch.setattr(SystemProbe, "active_apps", lambda self: {"applications": []})
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {"focused_window": None, "windows": [], "monitors": []},
    )
    monkeypatch.setattr(
        SystemProbe,
        "_running_processes",
        lambda self: [
            {
                "process_name": "Discord",
                "pid": 9360,
                "path": "C:/Users/test/AppData/Local/Discord/app-1.0.9233/Discord.exe",
            },
            {
                "process_name": "Discord",
                "pid": 16364,
                "path": "C:/Users/test/AppData/Local/Discord/app-1.0.9233/Discord.exe",
            },
        ],
    )

    result = probe.app_control(action="close", app_name="Discord")

    assert result["success"] is False
    assert result["reason"] == "no_matching_window_found"


def test_window_status_reports_focused_window_and_monitors(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)

    monkeypatch.setattr(
        SystemProbe,
        "_run_powershell_json",
        lambda self, script: {
            "focused_window": {
                "process_name": "chrome",
                "window_title": "Chrome",
                "window_handle": 1001,
                "pid": 2001,
                "x": 100,
                "y": 100,
                "width": 1280,
                "height": 800,
                "monitor_index": 1,
            },
            "windows": [
                {
                    "process_name": "chrome",
                    "window_title": "Chrome",
                    "window_handle": 1001,
                    "pid": 2001,
                    "x": 100,
                    "y": 100,
                    "width": 1280,
                    "height": 800,
                    "monitor_index": 1,
                    "is_focused": True,
                }
            ],
            "monitors": [
                {"index": 1, "device_name": "DISPLAY1", "is_primary": True, "work_x": 0, "work_y": 0, "work_width": 1920, "work_height": 1040},
                {"index": 2, "device_name": "DISPLAY2", "is_primary": False, "work_x": 1920, "work_y": 0, "work_width": 1920, "work_height": 1040},
            ],
        },
    )

    result = probe.window_status()

    assert result["focused_window"]["process_name"] == "chrome"
    assert len(result["windows"]) == 1
    assert len(result["monitors"]) == 2


def test_window_control_moves_window_to_monitor(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {
            "focused_window": None,
            "windows": [
                {
                    "process_name": "chrome",
                    "window_title": "Chrome",
                    "window_handle": 1001,
                    "pid": 2001,
                    "x": 100,
                    "y": 100,
                    "width": 1200,
                    "height": 800,
                    "monitor_index": 1,
                }
            ],
            "monitors": [
                {"index": 1, "device_name": "DISPLAY1", "is_primary": True, "work_x": 0, "work_y": 0, "work_width": 1920, "work_height": 1040},
                {"index": 2, "device_name": "DISPLAY2", "is_primary": False, "work_x": 1920, "work_y": 0, "work_width": 1920, "work_height": 1040},
            ],
        },
    )

    def fake_run(self, script: str):
        scripts.append(script)
        return {
            "success": True,
            "action": "move_to_monitor",
            "process_name": "chrome",
            "window_title": "Chrome",
            "pid": 2001,
            "monitor_index": 2,
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.window_control(action="move_to_monitor", app_name="chrome", monitor_index=2)

    assert result["success"] is True
    assert result["monitor_index"] == 2
    assert any("SetWindowPos" in script for script in scripts)


def test_window_control_targets_focused_window_for_deictic_command(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {
            "focused_window": {
                "process_name": "Code",
                "window_title": "Visual Studio Code",
                "window_handle": 991,
                "pid": 4120,
                "x": 20,
                "y": 20,
                "width": 1400,
                "height": 900,
                "monitor_index": 1,
                "is_focused": True,
            },
            "windows": [],
            "monitors": [{"index": 1, "device_name": "DISPLAY1", "is_primary": True, "work_x": 0, "work_y": 0, "work_width": 1920, "work_height": 1040}],
        },
    )

    def fake_run(self, script: str):
        scripts.append(script)
        return {
            "success": True,
            "action": "maximize",
            "process_name": "Code",
            "window_title": "Visual Studio Code",
            "pid": 4120,
        }

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.window_control(action="maximize", target_mode="focused")

    assert result["success"] is True
    assert result["process_name"] == "Code"
    assert any("ShowWindowAsync" in script for script in scripts)


def test_system_control_opens_task_manager(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(SystemProbe, "control_capabilities", lambda self: {"system": {"task_manager": True}})

    def fake_run(self, script: str):
        scripts.append(script)
        return {"success": True, "action": "open_task_manager", "target": "taskmgr"}

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.system_control(action="open_task_manager")

    assert result["success"] is True
    assert any("Start-Process" in script and "taskmgr" in script for script in scripts)


def test_system_control_locks_workstation(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(SystemProbe, "control_capabilities", lambda self: {"system": {"lock": True}})

    def fake_run(self, script: str):
        scripts.append(script)
        return {"success": True, "action": "lock"}

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.system_control(action="lock")

    assert result["success"] is True
    assert any("LockWorkStation" in script for script in scripts)


def test_system_control_sets_volume_to_percent(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    scripts: list[str] = []

    monkeypatch.setattr(SystemProbe, "control_capabilities", lambda self: {"system": {"volume": True}})

    def fake_run(self, script: str):
        scripts.append(script)
        return {"success": True, "action": "set_volume", "value": 20}

    monkeypatch.setattr(SystemProbe, "_run_powershell_json", fake_run)

    result = probe.system_control(action="set_volume", value=20)

    assert result["success"] is True
    assert result["value"] == 20
    assert any("keybd_event" in script for script in scripts)


def test_system_control_reports_unsupported_bluetooth_toggle_honestly(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(
        SystemProbe,
        "control_capabilities",
        lambda self: {"system": {"bluetooth_toggle": False}},
    )

    result = probe.system_control(action="toggle_bluetooth", state="off")

    assert result["success"] is False
    assert result["reason"] == "unsupported"


def test_control_capabilities_reports_supported_control_groups(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SystemProbe(temp_config)
    monkeypatch.setattr(SystemProbe, "_brightness_control_supported", lambda self: True)
    monkeypatch.setattr(SystemProbe, "_wifi_toggle_supported", lambda self: True)
    monkeypatch.setattr(SystemProbe, "_bluetooth_toggle_supported", lambda self: False)
    monkeypatch.setattr(
        SystemProbe,
        "window_status",
        lambda self: {
            "focused_window": None,
            "windows": [],
            "monitors": [
                {"index": 1, "device_name": "DISPLAY1", "is_primary": True, "work_x": 0, "work_y": 0, "work_width": 1920, "work_height": 1040},
                {"index": 2, "device_name": "DISPLAY2", "is_primary": False, "work_x": 1920, "work_y": 0, "work_width": 1920, "work_height": 1040},
            ],
        },
    )

    result = probe.control_capabilities()

    assert result["app"]["launch"] is True
    assert result["window"]["move"] is True
    assert result["window"]["monitor_move"] is True
    assert result["system"]["brightness"] is True
    assert result["system"]["wifi_toggle"] is True
    assert result["system"]["bluetooth_toggle"] is False
