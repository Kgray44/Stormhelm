from __future__ import annotations

import asyncio

from stormhelm.core.events import EventBuffer
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.builtins.system_state import (
    LocationStatusTool,
    NetworkThroughputTool,
    PowerStatusTool,
    ResourceStatusTool,
    WeatherCurrentTool,
)
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry


class DummyNotesRepository:
    def create_note(self, title: str, content: str):  # pragma: no cover - not used in this test
        raise NotImplementedError


class DummyPreferencesRepository:
    def set_preference(self, key: str, value: object) -> None:  # pragma: no cover - not used in this test
        return None


class FakeTelemetryProbe:
    def __init__(
        self,
        *,
        cpu: dict[str, object] | None = None,
        memory: dict[str, object] | None = None,
        gpu: list[dict[str, object]] | None = None,
        thermal: dict[str, object] | None = None,
        sources: dict[str, object] | None = None,
        freshness: dict[str, object] | None = None,
    ) -> None:
        self._cpu = cpu or {}
        self._memory = memory or {}
        self._gpu = gpu or []
        self._thermal = thermal or {}
        self._sources = sources or {}
        self._freshness = freshness or {"sampling_tier": "active", "sample_age_seconds": 2.0}

    def resource_status(self) -> dict[str, object]:
        return {
            "cpu": dict(self._cpu),
            "memory": dict(self._memory),
            "gpu": [dict(adapter) for adapter in self._gpu],
            "thermal": dict(self._thermal),
            "capabilities": {
                "helper_reachable": True,
                "cpu_deep_telemetry_available": isinstance(self._cpu.get("utilization_percent"), (int, float))
                or isinstance(self._cpu.get("package_temperature_c"), (int, float)),
                "gpu_deep_telemetry_available": any(
                    isinstance(adapter.get("utilization_percent"), (int, float))
                    or isinstance(adapter.get("temperature_c"), (int, float))
                    for adapter in self._gpu
                ),
                "thermal_sensor_availability": isinstance(self._cpu.get("package_temperature_c"), (int, float))
                or any(isinstance(adapter.get("temperature_c"), (int, float)) for adapter in self._gpu),
            },
            "sources": dict(self._sources),
            "freshness": dict(self._freshness),
        }


class FakeNetworkProbe:
    def network_throughput(self, *, metric: str = "internet_speed") -> dict[str, object]:
        payload = {
            "available": True,
            "metric": metric,
            "state": "ready",
            "source": "net_adapter_statistics",
            "download_mbps": 84.25,
            "upload_mbps": 12.5,
            "sample_window_seconds": 1.0,
            "last_sample_age_seconds": 0.0,
            "interfaces": [{"interface_alias": "Wi-Fi", "profile": "Home", "status": "Up", "ipv4": ["192.168.1.20"]}],
            "quality": {"connected": True},
            "monitoring": {"history_ready": True, "sample_count": 6, "last_sample_age_seconds": 0.0},
            "providers": {"observed_throughput": {"state": "ready", "detail": "Observed over the last 1.0 seconds on Wi-Fi.", "available": True}},
            "source_debug": {"throughput_primary": "net_adapter_statistics"},
        }
        if metric == "download_speed":
            payload["metric_value_mbps"] = payload["download_mbps"]
        elif metric == "upload_speed":
            payload["metric_value_mbps"] = payload["upload_mbps"]
        else:
            payload["metric_value_mbps"] = payload["download_mbps"]
        return payload


class FakePowerProbe:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def power_status(self) -> dict[str, object]:
        return dict(self._payload)


def test_tool_registry_executes_echo_tool(temp_config) -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
    )

    result = asyncio.run(executor.execute("echo", {"text": "hello"}, context))

    assert any(tool["name"] == "clock" for tool in registry.metadata())
    assert any(tool["name"] == "deck_open_url" and tool["category"] == "browser" for tool in registry.metadata())
    assert any(tool["name"] == "workspace_restore" and tool["category"] == "workspace" for tool in registry.metadata())
    assert any(tool["name"] == "machine_status" and tool["category"] == "system" for tool in registry.metadata())
    assert any(tool["name"] == "context_action" and tool["category"] == "context" for tool in registry.metadata())
    assert result.success is True
    assert result.data["text"] == "hello"


def test_location_and_weather_tools_preserve_none_named_location() -> None:
    location_args = LocationStatusTool().validate({"mode": "current", "named_location": None, "allow_home_fallback": False})
    weather_args = WeatherCurrentTool().validate(
        {"location_mode": "auto", "named_location": None, "allow_home_fallback": True, "forecast_target": "current", "open_target": "none"}
    )

    assert location_args["named_location"] is None
    assert weather_args["named_location"] is None


def test_resource_status_tool_reports_live_gpu_usage_before_identity(temp_config) -> None:
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=FakeTelemetryProbe(
            cpu={"name": "Test CPU", "logical_processors": 16, "utilization_percent": 24.0},
            memory={"total_bytes": 32 * 1024**3, "free_bytes": 20 * 1024**3, "used_bytes": 12 * 1024**3},
            gpu=[
                {
                    "name": "Test GPU",
                    "driver_version": "1.0",
                    "utilization_percent": 58.0,
                    "temperature_c": 66.0,
                    "vram_total_bytes": 8 * 1024**3,
                    "vram_used_bytes": 2 * 1024**3,
                }
            ],
        ),
    )

    result = ResourceStatusTool().execute_sync(
        context,
        {"focus": "gpu", "query_kind": "telemetry", "metric": "usage", "present_in": "none"},
    )

    assert result.success is True
    assert result.summary.startswith("GPU usage is 58%")
    assert "Test GPU" not in result.summary


def test_resource_status_tool_prefers_most_active_gpu_when_multiple_adapters_exist(temp_config) -> None:
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=FakeTelemetryProbe(
            gpu=[
                {"name": "Integrated GPU", "utilization_percent": 3.0, "temperature_c": 48.0},
                {
                    "name": "RTX Laptop GPU",
                    "utilization_percent": 67.0,
                    "temperature_c": 72.0,
                    "power_w": 38.4,
                    "vram_total_bytes": 8 * 1024**3,
                    "vram_used_bytes": 3 * 1024**3,
                },
            ],
        ),
    )

    result = ResourceStatusTool().execute_sync(
        context,
        {"focus": "gpu", "query_kind": "telemetry", "metric": "usage", "present_in": "none"},
    )

    assert result.success is True
    assert result.summary.startswith("GPU usage is 67%")
    assert "3%" not in result.summary


def test_resource_status_tool_reports_precise_temperature_unavailable_reason(temp_config) -> None:
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=FakeTelemetryProbe(
            cpu={"name": "Test CPU", "logical_processors": 16, "utilization_percent": 31.0},
            memory={"total_bytes": 32 * 1024**3, "free_bytes": 20 * 1024**3, "used_bytes": 12 * 1024**3},
        ),
    )

    result = ResourceStatusTool().execute_sync(
        context,
        {"focus": "cpu", "query_kind": "telemetry", "metric": "temperature", "present_in": "none"},
    )

    assert result.success is True
    assert "CPU temperature" in result.summary
    assert "Test CPU" not in result.summary
    assert "isn't" in result.summary or "not available" in result.summary


def test_resource_status_tool_uses_metric_level_provider_and_reason_contract(temp_config) -> None:
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=FakeTelemetryProbe(
            cpu={"name": "Test CPU", "logical_processors": 16, "utilization_percent": 31.0},
            sources={
                "helper": {"provider": "stormhelm_hardware_helper", "state": "reachable"},
                "cpu": {"provider": "windows_native"},
                "metrics": {
                    "cpu.package_temperature_c": {
                        "provider": "libre_hardware_monitor",
                        "available": False,
                        "unsupported_reason": "No valid CPU package temperature sensor is exposed by the available non-HWiNFO providers on this machine.",
                    }
                },
            },
        ),
    )

    result = ResourceStatusTool().execute_sync(
        context,
        {"focus": "cpu", "query_kind": "telemetry", "metric": "temperature", "present_in": "none"},
    )

    assert result.success is True
    assert "non-HWiNFO providers" in result.summary
    assert result.data["metric_contract"]["provider"] == "libre_hardware_monitor"


def test_resource_status_tool_reports_cpu_fan_telemetry_from_gigabyte_provider(temp_config) -> None:
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=FakeTelemetryProbe(
            cpu={"name": "AMD Ryzen AI 7 350", "logical_processors": 16, "utilization_percent": 31.0},
            thermal={
                "fans": [
                    {"label": "CPU Fan", "rpm": 3125, "duty_percent": 58, "source": "gigabyte_control_center"},
                    {"label": "GPU Fan", "rpm": 2980, "duty_percent": 55, "source": "gigabyte_control_center"},
                ]
            },
            sources={
                "helper": {"provider": "stormhelm_hardware_helper", "state": "reachable"},
                "thermal": {"provider": "gigabyte_control_center"},
                "metrics": {
                    "thermal.cpu_fan_rpm": {
                        "provider": "gigabyte_control_center",
                        "available": True,
                        "source": "GccWmiTool.GetFanSpeed(1)",
                    },
                    "thermal.cpu_fan_duty_percent": {
                        "provider": "gigabyte_control_center",
                        "available": True,
                        "source": "CWMI.getCPUFanDuty",
                    },
                },
            },
        ),
    )

    result = ResourceStatusTool().execute_sync(
        context,
        {"focus": "cpu", "query_kind": "telemetry", "metric": "fan", "present_in": "none"},
    )

    assert result.success is True
    assert "fan" in result.summary.lower()
    assert "3125" in result.summary or "58%" in result.summary
    assert result.data["metric_contract"]["provider"] == "gigabyte_control_center"


def test_resource_status_tool_reports_precise_cpu_fan_access_denied_reason(temp_config) -> None:
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=FakeTelemetryProbe(
            cpu={"name": "AMD Ryzen AI 7 350", "logical_processors": 16, "utilization_percent": 29.0},
            thermal={"fans": []},
            sources={
                "helper": {"provider": "stormhelm_hardware_helper", "state": "reachable"},
                "thermal": {"provider": "gigabyte_control_center"},
                "metrics": {
                    "thermal.cpu_fan_rpm": {
                        "provider": "gigabyte_control_center",
                        "available": False,
                        "unsupported_reason": "Gigabyte Control Center notebook WMI returned Access denied for CPU fan telemetry from the current helper context.",
                    }
                },
            },
        ),
    )

    result = ResourceStatusTool().execute_sync(
        context,
        {"focus": "cpu", "query_kind": "telemetry", "metric": "fan", "present_in": "none"},
    )

    assert result.success is True
    assert "access denied" in result.summary.lower()
    assert result.data["metric_contract"]["provider"] == "gigabyte_control_center"


def test_power_status_tool_overview_surfaces_detailed_battery_fields(temp_config) -> None:
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=FakePowerProbe(
            {
                "available": True,
                "battery_percent": 99,
                "ac_line_status": "online",
                "charge_rate_watts": 2.09,
                "time_to_full_seconds": 1017,
                "health_percent": 83.37,
                "wear_percent": 16.63,
                "telemetry_capabilities": {"helper_reachable": True, "helper_installed": True, "power_current_available": True},
                "telemetry_sources": {"helper": {"provider": "stormhelm_hardware_helper", "state": "reachable"}, "power": {"provider": "windows_native"}},
                "telemetry_freshness": {"sampling_tier": "active", "sample_age_seconds": 0.8},
            }
        ),
    )

    result = PowerStatusTool().execute_sync(
        context,
        {"focus": "overview", "present_in": "none"},
    )

    assert result.success is True
    assert "99%" in result.summary
    assert "2.1 w" in result.summary.lower()
    assert "83%" in result.summary


def test_network_throughput_tool_reports_observed_download_speed(temp_config) -> None:
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=FakeNetworkProbe(),
    )

    result = NetworkThroughputTool().execute_sync(
        context,
        {"metric": "download_speed", "present_in": "none"},
    )

    assert result.success is True
    assert "download speed" in result.summary.lower()
    assert "mbps" in result.summary.lower()
    assert result.data["metric_contract"]["provider"] == "net_adapter_statistics"
