from __future__ import annotations

import asyncio

from stormhelm.core.events import EventBuffer
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.builtins.system_state import LocationStatusTool, ResourceStatusTool, WeatherCurrentTool
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry


class DummyNotesRepository:
    def create_note(self, title: str, content: str):  # pragma: no cover - not used in this test
        raise NotImplementedError


class DummyPreferencesRepository:
    def set_preference(self, key: str, value: object) -> None:  # pragma: no cover - not used in this test
        return None


class FakeTelemetryProbe:
    def __init__(self, *, cpu: dict[str, object] | None = None, memory: dict[str, object] | None = None, gpu: list[dict[str, object]] | None = None) -> None:
        self._cpu = cpu or {}
        self._memory = memory or {}
        self._gpu = gpu or []

    def resource_status(self) -> dict[str, object]:
        return {
            "cpu": dict(self._cpu),
            "memory": dict(self._memory),
            "gpu": [dict(adapter) for adapter in self._gpu],
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
            "freshness": {"sampling_tier": "active", "sample_age_seconds": 2.0},
        }


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
