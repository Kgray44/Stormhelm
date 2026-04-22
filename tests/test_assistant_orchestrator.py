from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.discord_relay import DiscordDispatchAttempt
from stormhelm.core.discord_relay import DiscordDispatchState
from stormhelm.core.discord_relay import DiscordRouteMode
from stormhelm.core.discord_relay import DiscordRelaySubsystem
from stormhelm.core.discord_relay import build_discord_relay_subsystem
from stormhelm.core.orchestrator.assistant import AssistantOrchestrator
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.providers.base import AssistantProvider, ProviderToolCall, ProviderTurnResult
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.calculations import build_calculations_subsystem
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.builtins import workspace_actions
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService


class FakeProvider(AssistantProvider):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        instructions: str,
        input_items: str | list[dict[str, object]],
        previous_response_id: str | None,
        tools: list[dict[str, object]],
        model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderTurnResult:
        self.calls.append(
            {
                "instructions": instructions,
                "input_items": input_items,
                "previous_response_id": previous_response_id,
                "tool_names": [tool["name"] for tool in tools],
                "model": model,
                "max_output_tokens": max_output_tokens,
            }
        )
        if model and (model.endswith("mini") or model.endswith("nano")) and previous_response_id is None:
            return ProviderTurnResult(
                response_id="resp_1",
                output_text="",
                tool_calls=[
                    ProviderToolCall(call_id="call_clock", name="clock", arguments={}),
                    ProviderToolCall(call_id="call_system", name="system_info", arguments={}),
                ],
            )
        if model and (model.endswith("mini") or model.endswith("nano")):
            return ProviderTurnResult(
                response_id="resp_planner_final",
                output_text="Planner bearings gathered.",
                tool_calls=[],
            )
        return ProviderTurnResult(
            response_id="resp_2",
            output_text="Current system bearings assembled.",
            tool_calls=[],
        )


class InputContextProvider(AssistantProvider):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        instructions: str,
        input_items: str | list[dict[str, object]],
        previous_response_id: str | None,
        tools: list[dict[str, object]],
        model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderTurnResult:
        self.calls.append(
            {
                "instructions": instructions,
                "input_items": input_items,
                "previous_response_id": previous_response_id,
                "tool_names": [tool["name"] for tool in tools],
                "model": model,
                "max_output_tokens": max_output_tokens,
            }
        )
        return ProviderTurnResult(response_id="resp_ctx", output_text="Summarized the selection.", tool_calls=[])


class BrowserSearchFallbackProvider(AssistantProvider):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        instructions: str,
        input_items: str | list[dict[str, object]],
        previous_response_id: str | None,
        tools: list[dict[str, object]],
        model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderTurnResult:
        self.calls.append(
            {
                "instructions": instructions,
                "input_items": input_items,
                "previous_response_id": previous_response_id,
                "tool_names": [tool["name"] for tool in tools],
                "model": model,
                "max_output_tokens": max_output_tokens,
            }
        )
        return ProviderTurnResult(
            response_id="resp_browser_search_fallback",
            output_text="",
            tool_calls=[
                ProviderToolCall(
                    call_id="call_browser_search_fallback",
                    name="browser_search_fallback_resolve",
                    arguments={
                        "resolved_url": "https://www.google.com/search?q=site%3Aorbitz.com+flights",
                        "title": "Orbitz search",
                        "resolution_kind": "site_search",
                        "provider_phrase": "orbitz",
                        "reason": "Resolved the provider to orbitz.com and built a site search URL.",
                    },
                )
            ],
        )


class FakeDiscordRelayAdapter:
    def __init__(self, *, state: DiscordDispatchState = DiscordDispatchState.STARTED) -> None:
        self.state = state
        self.calls: list[dict[str, object]] = []

    def send(self, *, destination, preview) -> DiscordDispatchAttempt:
        self.calls.append({"destination": destination.to_dict(), "preview": preview.to_dict()})
        return DiscordDispatchAttempt(
            state=self.state,
            route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
            route_basis="fake_adapter",
            verification_evidence=["Fake Discord adapter executed the send route."],
            send_summary="Fake Discord adapter completed the send path.",
        )


class FakeConversationRecord:
    def __init__(self, *, role: str, content: str, metadata: dict[str, object] | None = None) -> None:
        self.role = role
        self.content = content
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
        }


class FakeConversationRepository:
    def __init__(self) -> None:
        self.messages: list[FakeConversationRecord] = []

    def ensure_session(self, session_id: str = "default", title: str = "Primary Session") -> None:
        del session_id, title

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> FakeConversationRecord:
        del session_id
        record = FakeConversationRecord(role=role, content=content, metadata=metadata)
        self.messages.append(record)
        return record

    def list_messages(self, session_id: str = "default", limit: int = 100) -> list[FakeConversationRecord]:
        del session_id
        return list(self.messages[-limit:])


class FakeNotesRepository:
    def create_note(self, title: str, content: str) -> dict[str, str]:
        return {"title": title, "content": content}


class FakePreferencesRepository:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def set_preference(self, key: str, value: object) -> None:
        self.values[key] = value

    def get_all(self) -> dict[str, object]:
        return dict(self.values)


class FakeToolRunRepository:
    def upsert_run(self, **_: object) -> None:
        return None


class FakeSystemProbe:
    def machine_status(self) -> dict[str, object]:
        return {
            "machine_name": "Stormhelm-Test",
            "platform": "Windows-Test",
            "timezone": "America/New_York",
        }

    def power_status(self) -> dict[str, object]:
        return {
            "available": True,
            "ac_line_status": "online",
            "battery_percent": 72,
            "battery_flag": 8,
            "battery_saver": False,
            "seconds_remaining": None,
            "power_source": "ac",
            "charge_rate_watts": 18.5,
            "discharge_rate_watts": None,
            "instant_power_draw_watts": 18.5,
            "telemetry_capabilities": {
                "helper_installed": True,
                "helper_reachable": True,
                "power_current_available": True,
            },
            "telemetry_sources": {
                "helper": {"provider": "stormhelm_helper", "state": "reachable"},
                "power": {"provider": "stormhelm_helper", "confidence": "measured"},
            },
            "telemetry_freshness": {"sampling_tier": "active", "sample_age_seconds": 2.0},
        }

    def power_projection(
        self,
        *,
        metric: str = "time_to_percent",
        target_percent: int | None = None,
        assume_unplugged: bool = False,
    ) -> dict[str, object]:
        return {
            "available": True,
            "metric": metric,
            "target_percent": target_percent,
            "assume_unplugged": assume_unplugged,
            "battery_percent": 72,
            "ac_line_status": "offline" if assume_unplugged else "online",
            "power_draw_watts": 13.2 if assume_unplugged else 18.5,
            "rate_source": "system_estimate",
            "projection_minutes": 95 if metric == "time_to_percent" and target_percent == 100 else 128,
            "reliable": True,
            "notes": [],
        }

    def resource_status(self) -> dict[str, object]:
        return {
            "cpu": {
                "name": "Test CPU",
                "logical_processors": 16,
                "max_clock_mhz": 4000,
                "utilization_percent": 37.0,
                "package_temperature_c": 71.0,
                "effective_clock_mhz": 3985,
            },
            "memory": {"total_bytes": 32 * 1024**3, "free_bytes": 20 * 1024**3, "used_bytes": 12 * 1024**3},
            "gpu": [
                {
                    "name": "Test GPU",
                    "adapter_ram": 8 * 1024**3,
                    "driver_version": "1.0",
                    "utilization_percent": 58.0,
                    "temperature_c": 66.0,
                    "vram_total_bytes": 8 * 1024**3,
                    "vram_used_bytes": 2 * 1024**3,
                    "power_w": 118.5,
                }
            ],
            "capabilities": {
                "helper_installed": True,
                "helper_reachable": True,
                "cpu_deep_telemetry_available": True,
                "gpu_deep_telemetry_available": True,
                "thermal_sensor_availability": True,
            },
            "sources": {
                "helper": {"provider": "stormhelm_helper", "state": "reachable"},
                "cpu": {"provider": "stormhelm_helper", "confidence": "best_effort"},
                "gpu": {"provider": "stormhelm_helper", "confidence": "best_effort"},
            },
            "freshness": {"sampling_tier": "active", "sample_age_seconds": 2.0},
        }

    def storage_status(self) -> dict[str, object]:
        return {"drives": [{"drive": "C:\\", "total_bytes": 500 * 1024**3, "free_bytes": 200 * 1024**3}]}

    def network_status(self) -> dict[str, object]:
        return {
            "hostname": "stormhelm-test",
            "fqdn": "stormhelm-test.local",
            "interfaces": [
                {
                    "interface_alias": "Wi-Fi",
                    "profile": "Home",
                    "ssid": "Home",
                    "status": "Up",
                    "ipv4": ["192.168.1.20"],
                    "gateway": ["192.168.1.1"],
                    "dns_servers": ["1.1.1.1", "8.8.8.8"],
                    "signal_quality_pct": 82,
                }
            ],
            "monitoring": {"history_ready": True, "sample_count": 8, "last_sample_age_seconds": 4},
            "quality": {
                "connected": True,
                "signal_quality_pct": 82,
                "latency_ms": 28,
                "jitter_ms": 4,
                "packet_loss_pct": 0.0,
            },
            "throughput": {
                "available": True,
                "metric": "internet_speed",
                "state": "ready",
                "source": "net_adapter_statistics",
                "download_mbps": 126.4,
                "upload_mbps": 18.7,
                "sample_window_seconds": 1.0,
                "last_sample_age_seconds": 0.0,
            },
            "providers": {
                "local_status": {"state": "ready", "detail": "Home | gateway 192.168.1.1 | DNS 1.1.1.1, 8.8.8.8 | signal 82%", "available": True},
                "upstream_path": {"state": "ready", "detail": "latency 28 ms | jitter 4 ms | loss 0.0%", "available": True},
                "observed_throughput": {"state": "ready", "detail": "Observed over the last 1.0 seconds on Wi-Fi.", "available": True},
                "cloudflare_quality": {"state": "ready", "label": "Cloudflare quality", "detail": "Cloudflare-quality sample refreshed around 29 ms.", "available": True},
            },
            "source_debug": {
                "status_primary": "local_status",
                "diagnosis_inputs": ["local_status", "upstream_path", "cloudflare_quality"],
                "throughput_primary": "net_adapter_statistics",
            },
        }

    def network_throughput(self, *, metric: str = "internet_speed") -> dict[str, object]:
        payload = dict(self.network_status().get("throughput", {}))
        payload.update(
            {
                "metric": metric,
                "interfaces": self.network_status().get("interfaces", []),
                "quality": self.network_status().get("quality", {}),
                "monitoring": self.network_status().get("monitoring", {}),
                "providers": self.network_status().get("providers", {}),
                "source_debug": self.network_status().get("source_debug", {}),
            }
        )
        if metric == "download_speed":
            payload["metric_value_mbps"] = payload.get("download_mbps")
        elif metric == "upload_speed":
            payload["metric_value_mbps"] = payload.get("upload_mbps")
        else:
            payload["metric_value_mbps"] = payload.get("download_mbps")
        return payload

    def network_diagnosis(
        self,
        *,
        focus: str = "overview",
        diagnostic_burst: bool = False,
    ) -> dict[str, object]:
        return {
            "hostname": "stormhelm-test",
            "interfaces": [{"interface_alias": "Wi-Fi", "profile": "Home", "status": "Up", "ipv4": ["192.168.1.20"]}],
            "monitoring": {
                "history_ready": True,
                "diagnostic_burst_active": diagnostic_burst,
                "last_sample_age_seconds": 12,
            },
            "assessment": {
                "kind": "local_link_issue",
                "headline": "Local Wi-Fi instability likely",
                "summary": "Recent gateway jitter and packet-loss bursts suggest the problem starts on the local link.",
                "confidence": "moderate",
                "attribution": "local_link",
            },
            "quality": {
                "latency_ms": 46,
                "gateway_latency_ms": 31,
                "external_latency_ms": 46,
                "jitter_ms": 19,
                "packet_loss_pct": 3.4,
                "signal_strength_dbm": -63,
            },
            "throughput": {
                "available": True,
                "metric": "internet_speed",
                "state": "ready",
                "source": "net_adapter_statistics",
                "download_mbps": 126.4,
                "upload_mbps": 18.7,
                "sample_window_seconds": 1.0,
                "last_sample_age_seconds": 0.0,
            },
            "events": [
                {"kind": "packet_loss_burst", "title": "Packet-loss burst", "detail": "External loss reached 3.4%.", "seconds_ago": 34}
            ],
            "providers": {
                "local_status": {"state": "ready", "detail": "Home | gateway 192.168.1.1 | DNS 1.1.1.1, 8.8.8.8 | signal 82%", "available": True},
                "upstream_path": {"state": "ready", "detail": "latency 46 ms | jitter 19 ms | loss 3.4%", "available": True},
                "observed_throughput": {"state": "ready", "detail": "Observed over the last 1.0 seconds on Wi-Fi.", "available": True},
                "cloudflare_quality": {
                    "state": "partial",
                    "label": "Cloudflare quality",
                    "detail": "Waiting for richer quality samples.",
                }
            },
            "source_debug": {
                "status_primary": "local_status",
                "diagnosis_inputs": ["local_status", "upstream_path", "cloudflare_quality"],
                "throughput_primary": "net_adapter_statistics",
            },
            "focus": focus,
        }

    def power_diagnosis(self) -> dict[str, object]:
        return {
            "kind": "drain_elevated",
            "headline": "Battery drain elevated",
            "summary": "Recent discharge rate is elevated compared with the current operating posture.",
            "severity": "warning",
            "confidence": "moderate",
        }

    def resource_diagnosis(self) -> dict[str, object]:
        return {
            "kind": "memory_pressure",
            "headline": "Memory pressure elevated",
            "summary": "RAM usage is high enough that it may explain sluggishness.",
            "severity": "warning",
            "confidence": "moderate",
        }

    def active_apps(self) -> dict[str, object]:
        return {"applications": [{"process_name": "code", "window_title": "Stormhelm", "pid": 1200}]}

    def recent_files(self, limit: int = 12) -> dict[str, object]:
        del limit
        return {"files": [{"path": "C:\\Stormhelm\\README.md", "name": "README.md", "modified_at": "2026-04-19T00:00:00+00:00"}]}

    def resolve_location(self, *, mode: str = "auto", allow_home_fallback: bool = True) -> dict[str, object]:
        if mode == "home":
            return {
                "resolved": True,
                "source": "saved_home",
                "label": "Brooklyn, New York",
                "latitude": 40.6782,
                "longitude": -73.9442,
                "timezone": "America/New_York",
                "approximate": False,
            }
        return {
            "resolved": True,
            "source": "approximate",
            "label": "Queens, New York",
            "latitude": 40.7282,
            "longitude": -73.7949,
            "timezone": "America/New_York",
            "approximate": True,
            "allow_home_fallback": allow_home_fallback,
        }

    def resolve_best_location_for_request(
        self,
        *,
        mode: str = "auto",
        allow_home_fallback: bool = True,
        named_location: str | None = None,
        named_location_type: str = "auto",
    ) -> dict[str, object]:
        if named_location:
            return {
                "resolved": True,
                "source": "queried_place" if named_location_type == "place_query" else "saved_named",
                "name": named_location,
                "label": named_location.title(),
                "latitude": 40.71,
                "longitude": -73.91,
                "timezone": "America/New_York",
                "approximate": False,
            }
        return self.resolve_location(mode=mode, allow_home_fallback=allow_home_fallback)

    def weather_status(
        self,
        *,
        location_mode: str = "auto",
        named_location: str | None = None,
        named_location_type: str = "auto",
        allow_home_fallback: bool = True,
        forecast_target: str = "current",
        units: str = "imperial",
    ) -> dict[str, object]:
        del units
        location = self.resolve_best_location_for_request(
            mode=location_mode,
            named_location=named_location,
            named_location_type=named_location_type,
            allow_home_fallback=allow_home_fallback,
        )
        forecast = {
            "current": {
                "summary": "Light rain",
                "temperature": 61.0,
                "apparent": 59.0,
                "high": 66.0,
                "low": 52.0,
            },
            "tomorrow": {
                "summary": "Partly cloudy",
                "temperature": 64.0,
                "apparent": 63.0,
                "high": 68.0,
                "low": 50.0,
            },
            "tonight": {
                "summary": "Cool and mostly clear",
                "temperature": 48.0,
                "apparent": 46.0,
                "high": 52.0,
                "low": 45.0,
            },
            "weekend": {
                "summary": "Mixed rain and sun",
                "temperature": 62.0,
                "apparent": 61.0,
                "high": 69.0,
                "low": 49.0,
            },
        }[forecast_target]
        return {
            "available": True,
            "location": location,
            "forecast_target": forecast_target,
            "temperature": {
                "current": forecast["temperature"],
                "apparent": forecast["apparent"],
                "high": forecast["high"],
                "low": forecast["low"],
                "unit": "F",
            },
            "condition": {"summary": forecast["summary"], "code": 61},
            "wind": {"speed": 7.0, "unit": "mph"},
            "humidity_percent": 74,
            "deck_url": "https://weather.com/weather/today/l/40.7282,-73.7949",
        }


class PermissionFallbackSystemProbe(FakeSystemProbe):
    def resolve_location(self, *, mode: str = "auto", allow_home_fallback: bool = True) -> dict[str, object]:
        del allow_home_fallback
        if mode == "home":
            return {
                "resolved": True,
                "source": "saved_home",
                "label": "Brooklyn, New York",
                "latitude": 40.6782,
                "longitude": -73.9442,
                "timezone": "America/New_York",
                "approximate": False,
            }
        return {
            "resolved": True,
            "source": "ip_estimate",
            "label": "Queens, New York",
            "latitude": 40.7282,
            "longitude": -73.7949,
            "timezone": "America/New_York",
            "approximate": True,
            "used_home_fallback": False,
            "fallback_reason": "permission_denied",
        }

    def resolve_best_location_for_request(
        self,
        *,
        mode: str = "auto",
        allow_home_fallback: bool = True,
        named_location: str | None = None,
        named_location_type: str = "auto",
    ) -> dict[str, object]:
        del named_location, named_location_type
        return self.resolve_location(mode=mode, allow_home_fallback=allow_home_fallback)


class ForceQuitSuggestionProbe(FakeSystemProbe):
    def app_control(self, *, action: str, app_name: str | None = None, app_path: str | None = None) -> dict[str, object]:
        del app_path
        return {
            "success": True,
            "action": action,
            "process_name": str(app_name or "chrome"),
            "pid": 9912,
        }


class PartialNetworkRepairProbe(FakeSystemProbe):
    def flush_dns_cache(self) -> dict[str, object]:
        return {"success": True}

    def restart_network_adapter(self) -> dict[str, object]:
        return {"success": False, "reason": "unsupported"}


class StatusLeakageSystemProbe(FakeSystemProbe):
    def network_status(self) -> dict[str, object]:
        payload = dict(super().network_status())
        payload["assessment"] = {
            "headline": "Local Wi-Fi instability likely",
            "summary": "This should never leak into current-status formatting.",
        }
        return payload


class BrowserAwareSystemProbe(FakeSystemProbe):
    def __init__(self) -> None:
        self.focus_requests: list[str] = []

    def control_capabilities(self) -> dict[str, object]:
        return {
            "search": {
                "browser_tabs": False,
                "windows": True,
                "recent_files": True,
                "workspace_files": True,
            },
            "window": {
                "focus": True,
            },
        }

    def window_status(self) -> dict[str, object]:
        focused = {
            "process_name": "chrome",
            "window_title": "PyInstaller Docs - Google Chrome",
            "window_handle": 401,
            "pid": 1440,
            "monitor_index": 1,
            "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "is_focused": True,
            "minimized": False,
        }
        return {
            "focused_window": focused,
            "windows": [
                focused,
                {
                    "process_name": "msedge",
                    "window_title": "Packet Loss Guide - Microsoft Edge",
                    "window_handle": 402,
                    "pid": 1550,
                    "monitor_index": 1,
                    "path": "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
                    "is_focused": False,
                    "minimized": False,
                },
                {
                    "process_name": "code",
                    "window_title": "Stormhelm - Visual Studio Code",
                    "window_handle": 403,
                    "pid": 1660,
                    "monitor_index": 1,
                    "path": "C:\\Program Files\\Microsoft VS Code\\Code.exe",
                    "is_focused": False,
                    "minimized": False,
                },
            ],
            "monitors": [{"index": 1, "device_name": "\\\\.\\DISPLAY1", "is_primary": True}],
        }

    def window_control(
        self,
        *,
        action: str,
        app_name: str | None = None,
        target_mode: str | None = None,
        **_: object,
    ) -> dict[str, object]:
        self.focus_requests.append(str(app_name or ""))
        return {
            "success": True,
            "action": action,
            "process_name": "msedge",
            "window_title": str(app_name or ""),
            "target_mode": target_mode,
        }


def _build_assistant(
    temp_config,
    *,
    system_probe=None,
    discord_relay: DiscordRelaySubsystem | None = None,
) -> tuple[AssistantOrchestrator, JobManager, ToolExecutor, ConversationStateStore]:
    events = EventBuffer()
    notes = FakeNotesRepository()
    preferences = FakePreferencesRepository()
    session_state = ConversationStateStore(preferences)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry, max_sync_workers=temp_config.concurrency.max_workers)
    jobs = JobManager(
        config=temp_config,
        executor=executor,
        context_factory=lambda job_id: ToolContext(
            job_id=job_id,
            config=temp_config,
            events=events,
            notes=notes,
            preferences=preferences,
            safety_policy=SafetyPolicy(temp_config),
            system_probe=system_probe,
        ),
        tool_runs=FakeToolRunRepository(),
        events=events,
    )
    calculations = build_calculations_subsystem(temp_config.calculations)
    screen_awareness = build_screen_awareness_subsystem(
        temp_config.screen_awareness,
        system_probe=system_probe,
        calculations=calculations,
    )
    relay = discord_relay or build_discord_relay_subsystem(
        temp_config.discord_relay,
        session_state=session_state,
        system_probe=system_probe,
        observation_source=screen_awareness.native_observer,
    )
    assistant = AssistantOrchestrator(
        config=temp_config,
        conversations=FakeConversationRepository(),
        jobs=jobs,
        router=IntentRouter(),
        events=events,
        tool_registry=registry,
        session_state=session_state,
        planner=DeterministicPlanner(
            calculations_config=temp_config.calculations,
            screen_awareness_config=temp_config.screen_awareness,
            discord_relay_config=temp_config.discord_relay,
        ),
        persona=PersonaContract(temp_config),
        workspace_service=None,
        provider=None,
        calculations=calculations,
        screen_awareness=screen_awareness,
        discord_relay=relay,
    )
    return assistant, jobs, executor, session_state


def _planner_debug(payload: dict[str, object]) -> dict[str, object]:
    assistant_message = payload.get("assistant_message") if isinstance(payload.get("assistant_message"), dict) else {}
    metadata = assistant_message.get("metadata") if isinstance(assistant_message.get("metadata"), dict) else {}
    return dict(metadata.get("planner_debug") or {})


def _planner_obedience(payload: dict[str, object]) -> dict[str, object]:
    assistant_message = payload.get("assistant_message") if isinstance(payload.get("assistant_message"), dict) else {}
    metadata = assistant_message.get("metadata") if isinstance(assistant_message.get("metadata"), dict) else {}
    return dict(metadata.get("planner_obedience") or {})


def _build_assistant_with_workspace(
    temp_config,
    *,
    system_probe=None,
    discord_relay: DiscordRelaySubsystem | None = None,
) -> tuple[AssistantOrchestrator, JobManager, ToolExecutor, ConversationStateStore, WorkspaceService]:
    events = EventBuffer()
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    session_state = ConversationStateStore(preferences)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry, max_sync_workers=temp_config.concurrency.max_workers)
    workspace_service = WorkspaceService(
        config=temp_config,
        repository=WorkspaceRepository(database),
        notes=notes,
        conversations=conversations,
        preferences=preferences,
        session_state=session_state,
        indexer=WorkspaceIndexer(temp_config),
        events=events,
        persona=PersonaContract(temp_config),
    )
    jobs = JobManager(
        config=temp_config,
        executor=executor,
        context_factory=lambda job_id: ToolContext(
            job_id=job_id,
            config=temp_config,
            events=events,
            notes=notes,
            preferences=preferences,
            safety_policy=SafetyPolicy(temp_config),
            system_probe=system_probe,
            workspace_service=workspace_service,
        ),
        tool_runs=FakeToolRunRepository(),
        events=events,
    )
    calculations = build_calculations_subsystem(temp_config.calculations)
    screen_awareness = build_screen_awareness_subsystem(
        temp_config.screen_awareness,
        system_probe=system_probe,
        calculations=calculations,
    )
    relay = discord_relay or build_discord_relay_subsystem(
        temp_config.discord_relay,
        session_state=session_state,
        system_probe=system_probe,
        observation_source=screen_awareness.native_observer,
    )
    assistant = AssistantOrchestrator(
        config=temp_config,
        conversations=conversations,
        jobs=jobs,
        router=IntentRouter(),
        events=events,
        tool_registry=registry,
        session_state=session_state,
        planner=DeterministicPlanner(
            calculations_config=temp_config.calculations,
            screen_awareness_config=temp_config.screen_awareness,
            discord_relay_config=temp_config.discord_relay,
        ),
        persona=PersonaContract(temp_config),
        workspace_service=workspace_service,
        provider=None,
        calculations=calculations,
        screen_awareness=screen_awareness,
        discord_relay=relay,
    )
    return assistant, jobs, executor, session_state, workspace_service


def _run_assistant_once(
    assistant: AssistantOrchestrator,
    jobs: JobManager,
    executor: ToolExecutor,
    *,
    message: str,
    surface_mode: str = "ghost",
    active_module: str = "systems",
    workspace_context: dict[str, object] | None = None,
    input_context: dict[str, object] | None = None,
) -> dict[str, object]:
    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                message,
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=workspace_context,
                input_context=input_context,
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    return asyncio.run(runner())


def test_assistant_routes_direct_arithmetic_to_local_calculation_lane_without_provider(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="2+2",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert payload["jobs"] == []
    assert payload["assistant_message"]["content"] in {"4", "4."}
    planner_debug = _planner_debug(payload)
    assert planner_debug["calculations"]["candidate"] is True
    assert planner_debug["calculations"]["trace"]["normalized_expression"] == "2+2"
    assert planner_debug["calculations"]["trace"]["parse_success"] is True


def test_assistant_reports_honest_parse_failure_for_malformed_calculation(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="calculate 2+*",
        surface_mode="ghost",
        active_module="chartroom",
    )

    planner_debug = _planner_debug(payload)
    assert planner_debug["calculations"]["candidate"] is True
    assert planner_debug["calculations"]["trace"]["parse_success"] is False
    assert "parse" in payload["assistant_message"]["content"].lower()


def test_assistant_routes_engineering_style_expression_to_local_calculation_lane(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="3.3k * 2.2mA",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert payload["jobs"] == []
    assert payload["assistant_message"]["content"] == "7.26"
    planner_debug = _planner_debug(payload)
    assert planner_debug["calculations"]["candidate"] is True
    assert planner_debug["calculations"]["trace"]["normalized_expression"] == "3300*0.0022"
    assert planner_debug["calculations"]["trace"]["parse_success"] is True


def test_assistant_routes_supported_helper_request_to_local_calculation_lane(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="power at 12V and 1.5A",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert payload["jobs"] == []
    assert payload["assistant_message"]["content"] == "Power = 18 W"
    planner_debug = _planner_debug(payload)
    assert planner_debug["calculations"]["candidate"] is True
    assert planner_debug["calculations"]["helper_name"] == "power_from_voltage_current"
    assert planner_debug["calculations"]["trace"]["helper_used"] == "power_from_voltage_current"


def test_assistant_reports_brief_under_specified_helper_failure_locally(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="power at 12V",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert payload["jobs"] == []
    planner_debug = _planner_debug(payload)
    assert planner_debug["calculations"]["candidate"] is True
    assert planner_debug["calculations"]["trace"]["failure_stage"] == "helper_match"
    assert "current or resistance" in payload["assistant_message"]["content"].lower()


def test_assistant_reuses_prior_direct_calculation_for_show_the_steps_follow_up(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            first = await assistant.handle_message(
                "3.3k * 2.2mA",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
            )
            second = await assistant.handle_message(
                "show the steps",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
            )
            return first, second
        finally:
            await jobs.stop()
            executor.shutdown()

    _, payload = asyncio.run(runner())

    planner_debug = _planner_debug(payload)
    assert planner_debug["calculations"]["candidate"] is True
    assert planner_debug["calculations"]["follow_up_reuse"] is True
    assert planner_debug["calculations"]["trace"]["explanation_follow_up_reuse"] is True
    assert payload["assistant_message"]["content"] == "3.3k -> 3300\n2.2mA -> 0.0022\n3300 * 0.0022 = 7.26"


def test_assistant_reuses_prior_helper_calculation_for_show_the_formula_follow_up(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            first = await assistant.handle_message(
                "power at 12V and 1.5A",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
            )
            second = await assistant.handle_message(
                "show the formula",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
            )
            return first, second
        finally:
            await jobs.stop()
            executor.shutdown()

    _, payload = asyncio.run(runner())

    planner_debug = _planner_debug(payload)
    assert planner_debug["calculations"]["candidate"] is True
    assert planner_debug["calculations"]["follow_up_reuse"] is True
    assert planner_debug["calculations"]["trace"]["helper_used"] == "power_from_voltage_current"
    assert planner_debug["calculations"]["trace"]["explanation_follow_up_reuse"] is True
    assert payload["assistant_message"]["content"] == "P = V * I\nP = 12 * 1.5\nP = 18 W"


def test_assistant_reuses_prior_screen_calculation_for_show_the_steps_follow_up(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase4"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            first = await assistant.handle_message(
                "can you solve this",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
                input_context={
                    "selection": {
                        "kind": "text",
                        "value": "(48/3)+7^2",
                        "preview": "(48/3)+7^2",
                    }
                },
            )
            second = await assistant.handle_message(
                "show the steps",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
            )
            return first, second
        finally:
            await jobs.stop()
            executor.shutdown()

    first_payload, payload = asyncio.run(runner())

    first_debug = _planner_debug(first_payload)
    planner_debug = _planner_debug(payload)

    assert first_debug["screen_awareness"]["analysis_result"]["calculation_activity"]["status"] == "resolved"
    assert first_debug["screen_awareness"]["analysis_result"]["calculation_activity"]["calculation_trace"]["caller_subsystem"] == "screen_awareness"
    assert planner_debug["calculations"]["candidate"] is True
    assert planner_debug["calculations"]["follow_up_reuse"] is True
    assert planner_debug["calculations"]["trace"]["explanation_follow_up_reuse"] is True
    assert payload["assistant_message"]["content"] == "48 / 3 = 16\n7 ^ 2 = 49\n16 + 49 = 65"


def test_assistant_orchestrator_handles_phase1_screen_awareness_analysis_and_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase1"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="what am I looking at",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-1", "title": "PyInstaller Research"},
            "module": "browser",
            "section": "open-pages",
            "opened_items": [
                {
                    "itemId": "page-1",
                    "title": "PyInstaller Docs",
                    "url": "https://pyinstaller.org/en/stable/",
                    "kind": "browser-tab",
                }
            ],
            "active_item": {
                "itemId": "page-1",
                "title": "PyInstaller Docs",
                "url": "https://pyinstaller.org/en/stable/",
                "kind": "browser-tab",
            },
        },
        input_context={
            "selection": {
                "kind": "text",
                "value": "PyInstaller bundles a Python application into a single package.",
                "preview": "PyInstaller bundles a Python application into a single package.",
            }
        },
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=50) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_analyze"
    assert planner_debug["screen_awareness"]["disposition"] == "phase1_analyze"
    assert planner_obedience["actual_result_mode"] == "summary_result"
    assert planner_obedience["authority_enforced"] is True
    assert "pyinstaller" in payload["assistant_message"]["content"].lower()
    assert "clicked" not in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase1_analyze"
    assert screen_events[-1]["payload"]["analysis_result"]["current_screen_context"]["summary"]


def test_assistant_orchestrator_handles_phase2_grounding_and_emits_grounding_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase2"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="what does this warning mean",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-1", "title": "Deployment Troubleshooting"},
            "module": "browser",
            "section": "open-pages",
            "opened_items": [
                {
                    "itemId": "warning-1",
                    "title": "Warning: Token expired",
                    "kind": "warning-banner",
                    "color": "red",
                },
                {
                    "itemId": "button-1",
                    "title": "Save",
                    "kind": "button",
                },
            ],
            "active_item": {
                "itemId": "settings-page",
                "title": "Deploy Settings",
                "url": "https://example.test/settings/deploy",
                "kind": "settings-page",
            },
        },
        input_context={
            "selection": {
                "kind": "text",
                "value": "Warning: Token expired",
                "preview": "Warning: Token expired",
            }
        },
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=50) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_analyze"
    assert planner_debug["screen_awareness"]["disposition"] == "phase2_ground"
    assert planner_debug["screen_awareness"]["analysis_result"]["grounding_result"]["winning_target"]["role"] == "warning"
    assert planner_debug["screen_awareness"]["telemetry"]["grounding"]["candidate_count"] >= 2
    assert planner_debug["screen_awareness"]["telemetry"]["grounding"]["outcome"] == "resolved"
    assert planner_obedience["actual_result_mode"] == "summary_result"
    assert planner_obedience["authority_enforced"] is True
    assert "warning" in payload["assistant_message"]["content"].lower()
    assert "clicked" not in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase2_ground"
    assert screen_events[-1]["payload"]["telemetry"]["grounding"]["winning_candidate_id"]


def test_assistant_orchestrator_handles_phase3_guided_navigation_and_emits_navigation_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase3"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="what should I click next?",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-1", "title": "Release Form"},
            "module": "browser",
            "section": "form",
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                },
                {
                    "itemId": "button-cancel",
                    "title": "Cancel",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                },
            ],
            "active_item": {
                "itemId": "field-email",
                "title": "Release email",
                "kind": "text-field",
                "focused": True,
                "selected": True,
            },
        },
        input_context={"selection": {}, "clipboard": {}},
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=50) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_analyze"
    assert planner_debug["screen_awareness"]["disposition"] == "phase3_guide"
    assert planner_debug["screen_awareness"]["analysis_result"]["navigation_result"]["winning_candidate"]["label"] == "Continue"
    assert planner_debug["screen_awareness"]["telemetry"]["navigation"]["outcome"] == "ready"
    assert planner_debug["screen_awareness"]["telemetry"]["navigation"]["candidate_count"] >= 2
    assert planner_obedience["actual_result_mode"] == "summary_result"
    assert planner_obedience["authority_enforced"] is True
    assert "continue" in payload["assistant_message"]["content"].lower()
    assert "clicked" not in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase3_guide"
    assert screen_events[-1]["payload"]["telemetry"]["navigation"]["winning_candidate_id"] == "button-continue"


def test_assistant_orchestrator_handles_phase4_verification_and_emits_verification_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase4"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    first_payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="what should I click next?",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-event", "title": "Deploy Settings"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "field-token",
                "title": "API token",
                "kind": "text-field",
                "focused": True,
                "selected": True,
            },
            "opened_items": [
                {
                    "itemId": "button-save",
                    "title": "Save",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        input_context={"selection": {}, "clipboard": {}},
    )
    assert first_payload["assistant_message"]["content"]

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="did that work?",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-verify-event", "title": "Deploy Settings"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "save-success",
                "title": "Saved successfully",
                "kind": "status-banner",
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        input_context={"selection": {}, "clipboard": {}},
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=50) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_analyze"
    assert planner_debug["screen_awareness"]["disposition"] == "phase4_verify"
    assert planner_debug["screen_awareness"]["analysis_result"]["verification_result"]["completion_status"] == "completed"
    assert planner_debug["screen_awareness"]["telemetry"]["verification"]["outcome"] == "completed"
    assert planner_obedience["actual_result_mode"] == "summary_result"
    assert planner_obedience["authority_enforced"] is True
    assert "completed" in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase4_verify"
    assert screen_events[-1]["payload"]["telemetry"]["verification"]["requested"] is True


def test_assistant_orchestrator_handles_phase5_action_preview_and_emits_action_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase5"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="click the Save button",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-act-preview", "title": "Deploy Settings"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "settings-page",
                "title": "Deploy Settings",
                "kind": "settings-page",
            },
            "opened_items": [
                {
                    "itemId": "button-save",
                    "title": "Save",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                    "bounds": {"left": 120, "top": 220, "width": 90, "height": 32},
                }
            ],
        },
        input_context={"selection": {}, "clipboard": {}},
    )

    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=50) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_act"
    assert planner_debug["screen_awareness"]["disposition"] == "phase5_act"
    assert planner_debug["screen_awareness"]["analysis_result"]["action_result"]["status"] == "planned"
    assert planner_debug["screen_awareness"]["telemetry"]["action"]["outcome"] == "planned"
    assert planner_obedience["actual_result_mode"] == "action_result"
    assert planner_obedience["authority_enforced"] is True
    assert "go ahead" in payload["assistant_message"]["content"].lower() or "confirm" in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase5_act"
    assert screen_events[-1]["payload"]["telemetry"]["action"]["confirmation_required"] is True


def test_assistant_orchestrator_handles_phase6_continuity_and_emits_continuity_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase6"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    first_payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="what should I click next?",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-cont-event", "title": "Release Form"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "field-email",
                "title": "Release email",
                "kind": "text-field",
                "focused": True,
                "selected": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        input_context={"selection": {}, "clipboard": {}},
    )
    assert first_payload["assistant_message"]["content"]

    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="continue where we left off",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-cont-event", "title": "Release Form"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "field-email",
                "title": "Release email",
                "kind": "text-field",
                "focused": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        input_context={"selection": {}, "clipboard": {}},
    )

    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=50) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_continue"
    assert planner_debug["screen_awareness"]["disposition"] == "phase6_continue"
    assert planner_debug["screen_awareness"]["analysis_result"]["continuity_result"]["status"] == "resume_ready"
    assert planner_debug["screen_awareness"]["telemetry"]["continuity"]["outcome"] == "resume_ready"
    assert planner_obedience["actual_result_mode"] == "summary_result"
    assert planner_obedience["authority_enforced"] is True
    assert "continue" in payload["assistant_message"]["content"].lower() or "resume" in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase6_continue"
    assert screen_events[-1]["payload"]["telemetry"]["continuity"]["resume_candidate_id"] == "button-continue"


def test_assistant_orchestrator_handles_phase8_problem_solving_and_emits_problem_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase8"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    temp_config.screen_awareness.adapters_enabled = True
    temp_config.screen_awareness.problem_solving_enabled = True

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="explain this like i'm stressed",
        surface_mode="ghost",
        active_module="chartroom",
        input_context={
            "selection": {
                "kind": "text",
                "value": "NameError: name 'foo' is not defined",
                "preview": "NameError: name 'foo' is not defined",
            }
        },
    )

    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=50) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_analyze"
    assert planner_debug["screen_awareness"]["disposition"] == "phase8_problem_solve"
    assert planner_debug["screen_awareness"]["analysis_result"]["problem_solving_result"]["explanation_mode"] == "stressed_user"
    assert planner_debug["screen_awareness"]["telemetry"]["problem_solving"]["requested"] is True
    assert planner_debug["screen_awareness"]["telemetry"]["problem_solving"]["selected_mode"] == "stressed_user"
    assert planner_obedience["actual_result_mode"] == "summary_result"
    assert planner_obedience["authority_enforced"] is True
    assert "important part" in payload["assistant_message"]["content"].lower() or "start with" in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase8_problem_solve"
    assert screen_events[-1]["payload"]["telemetry"]["problem_solving"]["requested"] is True


def test_assistant_orchestrator_handles_phase9_workflow_learning_and_emits_workflow_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase9"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    temp_config.screen_awareness.adapters_enabled = True
    temp_config.screen_awareness.problem_solving_enabled = True
    temp_config.screen_awareness.workflow_learning_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="watch me do this and remember the workflow",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase9-event", "title": "Release Form"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "release-form",
                "title": "Release Form",
                "kind": "form",
                "focused": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        input_context={"selection": {}, "clipboard": {}},
    )
    _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="click the Continue button",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase9-event", "title": "Release Form"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "release-form",
                "title": "Release Form",
                "kind": "form",
                "focused": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        input_context={"selection": {}, "clipboard": {}},
    )
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="save this process",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase9-event", "title": "Release Form"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "release-form",
                "title": "Release Form",
                "kind": "form",
                "focused": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        input_context={"selection": {}, "clipboard": {}},
    )

    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=75) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_workflow"
    assert planner_debug["screen_awareness"]["disposition"] == "phase9_workflow_reuse"
    assert planner_debug["screen_awareness"]["analysis_result"]["workflow_learning_result"]["status"] == "reusable_accepted"
    assert planner_debug["screen_awareness"]["telemetry"]["workflow_learning"]["requested"] is True
    assert planner_obedience["actual_result_mode"] == "summary_result"
    assert planner_obedience["authority_enforced"] is True
    assert "workflow" in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase9_workflow_reuse"
    assert screen_events[-1]["payload"]["telemetry"]["workflow_learning"]["requested"] is True


def test_assistant_orchestrator_handles_phase10_brain_integration_and_emits_memory_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase10"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    temp_config.screen_awareness.adapters_enabled = True
    temp_config.screen_awareness.problem_solving_enabled = True
    temp_config.screen_awareness.workflow_learning_enabled = True
    temp_config.screen_awareness.brain_integration_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="you should remember that I prefer step-by-step guidance here",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase10-event", "title": "Release Form"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "release-form",
                "title": "Release Form",
                "kind": "form",
                "focused": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        input_context={"selection": {}, "clipboard": {}},
    )

    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=75) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_brain"
    assert planner_debug["screen_awareness"]["disposition"] == "phase10_brain_integration"
    assert planner_debug["screen_awareness"]["analysis_result"]["brain_integration_result"]["status"] == "preference_learned"
    assert planner_debug["screen_awareness"]["telemetry"]["brain_integration"]["requested"] is True
    assert planner_obedience["actual_result_mode"] == "summary_result"
    assert planner_obedience["authority_enforced"] is True
    assert "preference" in payload["assistant_message"]["content"].lower() or "remember" in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase10_brain_integration"
    assert screen_events[-1]["payload"]["telemetry"]["brain_integration"]["requested"] is True


def test_assistant_orchestrator_handles_phase11_power_features_and_emits_power_debug_event(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase11"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    temp_config.screen_awareness.adapters_enabled = True
    temp_config.screen_awareness.problem_solving_enabled = True
    temp_config.screen_awareness.workflow_learning_enabled = True
    temp_config.screen_awareness.brain_integration_enabled = True
    temp_config.screen_awareness.power_features_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="which display is that on",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase11-event", "title": "Release Form"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "release-form",
                "title": "Release Form",
                "kind": "form",
                "focused": True,
            },
        },
        input_context={
            "selection": {},
            "clipboard": {},
            "accessibility": {
                "focused_label": "Continue",
                "focused_role": "button",
                "enabled": True,
                "focus_path": ["Release Form", "Footer", "Continue"],
                "keyboard_hint": "Press Tab until Continue, then Enter.",
            },
        },
    )

    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    screen_events = [event for event in assistant.events.recent(limit=75) if event.get("source") == "screen_awareness"]

    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert planner_debug["structured_query"]["query_shape"] == "screen_awareness_request"
    assert planner_debug["execution_plan"]["plan_type"] == "screen_awareness_power"
    assert planner_debug["screen_awareness"]["disposition"] == "phase11_power"
    assert planner_debug["screen_awareness"]["telemetry"]["power_features"]["requested"] is True
    assert planner_obedience["actual_result_mode"] == "summary_result"
    assert planner_obedience["authority_enforced"] is True
    assert "display" in payload["assistant_message"]["content"].lower() or "monitor" in payload["assistant_message"]["content"].lower()
    assert screen_events
    assert screen_events[-1]["payload"]["disposition"] == "phase11_power"
    assert screen_events[-1]["payload"]["telemetry"]["power_features"]["requested"] is True


def test_assistant_orchestrator_phase12_debug_event_exposes_trace_and_truthfulness_audit(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase12"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    temp_config.screen_awareness.adapters_enabled = True
    temp_config.screen_awareness.problem_solving_enabled = True
    temp_config.screen_awareness.workflow_learning_enabled = True
    temp_config.screen_awareness.brain_integration_enabled = True
    temp_config.screen_awareness.power_features_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="did anything change?",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase12-event", "title": "Deploy Dashboard"},
            "module": "browser",
            "section": "dashboard",
        },
        input_context={
            "selection": {
                "kind": "text",
                "value": "Deployment failed. Try again.",
                "preview": "Deployment failed. Try again.",
            },
            "clipboard": {},
        },
    )

    planner_debug = _planner_debug(payload)
    screen_events = [event for event in assistant.events.recent(limit=75) if event.get("source") == "screen_awareness"]

    assert planner_debug["screen_awareness"]["analysis_result"]["trace_id"]
    assert planner_debug["screen_awareness"]["telemetry"]["trace"]["trace_id"]
    assert planner_debug["screen_awareness"]["telemetry"]["truthfulness_audit"]["passed"] is True
    assert planner_debug["screen_awareness"]["telemetry"]["policy"]["phase"] == "phase12"
    assert planner_debug["screen_awareness"]["telemetry"]["recovery"]["status"] == "unresolved"
    assert screen_events
    assert screen_events[-1]["payload"]["telemetry"]["trace"]["trace_id"]
    assert screen_events[-1]["payload"]["telemetry"]["truthfulness_audit"]["passed"] is True


def test_assistant_orchestrator_routes_deck_open_url_without_provider(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config)
    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "/open deck https://platform.openai.com/docs",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["actions"][0]["type"] == "workspace_open"
    assert payload["actions"][0]["module"] == "browser"
    assert payload["jobs"][0]["tool_name"] == "deck_open_url"
    assert "Deck browser" in payload["assistant_message"]["content"]


def test_assistant_orchestrator_uses_provider_and_keeps_previous_response_state(temp_config) -> None:
    provider = FakeProvider()
    temp_config.openai.enabled = True
    temp_config.openai.planner_model = "gpt-5.4-mini"
    temp_config.openai.reasoning_model = "gpt-5.4"
    assistant, jobs, executor, session_state = _build_assistant(temp_config)
    assistant.provider = provider
    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "Give me current system bearings.",
                surface_mode="deck",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["assistant_message"]["content"] == "Current system bearings assembled."
    assert len(payload["jobs"]) == 2
    assert {job["tool_name"] for job in payload["jobs"]} == {"clock", "system_info"}
    assert provider.calls[0]["previous_response_id"] is None
    assert provider.calls[0]["model"] == "gpt-5.4-mini"
    assert provider.calls[1]["model"] == "gpt-5.4-mini"
    assert provider.calls[2]["model"] == "gpt-5.4"
    assert session_state.get_previous_response_id("default", role="planner") == "resp_planner_final"
    assert session_state.get_previous_response_id("default", role="reasoner") == "resp_2"


def test_assistant_orchestrator_provider_includes_previous_user_message_and_concise_instructions(temp_config) -> None:
    provider = FakeProvider()
    temp_config.openai.enabled = True
    temp_config.openai.planner_model = "gpt-5.4-nano"
    temp_config.openai.reasoning_model = "gpt-5.4"
    assistant, jobs, executor, _ = _build_assistant(temp_config)
    assistant.provider = provider

    async def runner() -> None:
        await jobs.start()
        try:
            await assistant.handle_message(
                "Summarize current bearings.",
                surface_mode="ghost",
                active_module="chartroom",
            )
            await assistant.handle_message(
                "Be more specific.",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    asyncio.run(runner())

    assert any("Keep visible replies concise" in str(call["instructions"]) for call in provider.calls)
    contextual_calls = [call for call in provider.calls if isinstance(call["input_items"], list)]
    assert contextual_calls
    latest = contextual_calls[-1]
    texts: list[str] = []
    for item in latest["input_items"]:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                texts.append(content["text"])
    joined = " ".join(texts)
    assert "Summarize current bearings." in joined
    assert "Be more specific." in joined


def test_assistant_orchestrator_prefers_deterministic_system_tools_before_provider(temp_config) -> None:
    provider = FakeProvider()
    temp_config.openai.enabled = True
    assistant, jobs, executor, _ = _build_assistant(temp_config)
    assistant.provider = provider

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "How much storage do I have left on this machine?",
                surface_mode="ghost",
                active_module="systems",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert provider.calls == []
    assert payload["jobs"][0]["tool_name"] == "storage_status"
    assert "storage" in payload["assistant_message"]["content"].lower()


def test_assistant_orchestrator_grounds_workspace_follow_ups_in_structured_state(temp_config) -> None:
    assistant, jobs, executor, _, workspace_service = _build_assistant_with_workspace(temp_config)

    workspace = workspace_service.repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Portable packaging and release prep.",
    )
    workspace_service.capture_workspace_context(
        session_id="default",
        prompt="Verify the portable archive and confirm the first-run boot path.",
        surface_mode="deck",
        active_module="files",
        workspace_context={
            "workspace": {
                **workspace.to_dict(),
                "activeGoal": "Verify the portable packaging output.",
                "pendingNextSteps": [
                    "Verify the portable archive contents.",
                    "Check the first-run boot behavior.",
                ],
            },
            "module": "files",
            "section": "opened-items",
            "opened_items": [
                {
                    "itemId": "item-readme",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "README.md",
                    "path": str(Path(temp_config.project_root) / "README.md"),
                }
            ],
            "active_item": {
                "itemId": "item-readme",
                "kind": "markdown",
                "viewer": "markdown",
                "title": "README.md",
                "path": str(Path(temp_config.project_root) / "README.md"),
            },
        },
    )
    workspace_service.save_workspace(session_id="default")

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "what were we doing?",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["jobs"][0]["tool_name"] == "workspace_where_left_off"
    assert "packaging" in payload["assistant_message"]["content"].lower()
    assert "portable archive" in payload["assistant_message"]["content"].lower()


def test_assistant_orchestrator_handles_workspace_archive_without_provider(temp_config) -> None:
    assistant, jobs, executor, _, workspace_service = _build_assistant_with_workspace(temp_config)

    workspace = workspace_service.repository.upsert_workspace(
        name="Minecraft Workspace",
        topic="minecraft",
        summary="Modding and server setup work.",
    )
    workspace_service.session_state.set_active_workspace_id("default", workspace.workspace_id)
    workspace_service.session_state.set_active_posture(
        "default",
        {
            "workspace": workspace.to_dict(),
            "active_goal": "Finish the server setup.",
            "pending_next_steps": ["Reopen the server config files."],
        },
    )

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "archive this workspace",
                surface_mode="deck",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())
    archived = workspace_service.repository.get_workspace(workspace.workspace_id)

    assert payload["jobs"][0]["tool_name"] == "workspace_archive"
    assert archived is not None
    assert archived.archived is True
    assert "archived" in payload["assistant_message"]["content"].lower()


def test_assistant_orchestrator_clears_active_workspace_directly_without_provider(temp_config) -> None:
    assistant, jobs, executor, _, workspace_service = _build_assistant_with_workspace(temp_config)

    workspace = workspace_service.repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Portable packaging and release prep.",
    )
    workspace_service.session_state.set_active_workspace_id("default", workspace.workspace_id)
    workspace_service.session_state.set_active_posture(
        "default",
        {
            "workspace": workspace.to_dict(),
            "opened_items": [
                {
                    "itemId": "item-a",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "packaging-notes.md",
                    "path": str(Path(temp_config.project_root) / "packaging-notes.md"),
                }
            ],
            "active_item": {
                "itemId": "item-a",
                "kind": "markdown",
                "viewer": "markdown",
                "title": "packaging-notes.md",
                "path": str(Path(temp_config.project_root) / "packaging-notes.md"),
            },
        },
    )

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "clear workspace",
                surface_mode="deck",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["jobs"][0]["tool_name"] == "workspace_clear"
    assert payload["actions"][0]["type"] == "workspace_clear"
    assert payload["assistant_message"]["content"] == "Cleared active workspace."
    assert workspace_service.session_state.get_active_workspace_id("default") is None


def test_assistant_orchestrator_answers_weather_directly_without_provider_or_browser_open(temp_config) -> None:
    provider = FakeProvider()
    temp_config.openai.enabled = True
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    assistant.provider = provider

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "just get me the current weather",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert provider.calls == []
    assert payload["jobs"][0]["tool_name"] == "weather_current"
    assert payload["jobs"][0]["arguments"]["forecast_target"] == "current"
    assert payload["actions"] == []
    assert "weather" in payload["assistant_message"]["content"].lower()


def test_assistant_orchestrator_shapes_visible_response_tiers_for_concise_surfaces(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "what is my battery level?",
                surface_mode="ghost",
                active_module="systems",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]

    assert metadata["bearing_title"] == "Power"
    assert metadata["full_response"] == payload["assistant_message"]["content"]
    assert metadata["micro_response"]
    assert len(metadata["micro_response"]) <= len(metadata["full_response"])


def test_assistant_orchestrator_uses_workspace_bearing_title_and_concise_workspace_copy(
    temp_project_root,
    temp_config,
) -> None:
    docs_dir = temp_project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "motor-torque-notes.md").write_text("Motor torque notes", encoding="utf-8")

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "create a research workspace for motor torque",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]

    assert metadata["bearing_title"] == "Research workspace created"
    assert metadata["micro_response"] == "Created the research workspace."
    assert "motor torque" in metadata["full_response"].lower()


def test_assistant_orchestrator_routes_browser_find_request_with_compact_response_contract(temp_config) -> None:
    probe = BrowserAwareSystemProbe()
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=probe)

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "bring up the page about packet loss",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]

    assert payload["jobs"][0]["tool_name"] == "browser_context"
    assert probe.focus_requests
    assert "packet loss guide" in probe.focus_requests[-1].lower()
    assert metadata["bearing_title"] == "Packet Loss Guide found"
    assert metadata["micro_response"] == "Found the matching browser page."
    assert "brought it forward" in metadata["full_response"].lower()


def test_assistant_orchestrator_adds_current_browser_page_to_workspace_references_end_to_end(temp_config) -> None:
    probe = BrowserAwareSystemProbe()
    assistant, jobs, executor, _, workspace_service = _build_assistant_with_workspace(
        temp_config,
        system_probe=probe,
    )
    workspace = workspace_service.repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Portable packaging and release work.",
        active_goal="Finish the packaging pass.",
    )

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "add this page to the workspace",
                surface_mode="deck",
                active_module="browser",
                workspace_context={
                    "workspace": workspace.to_dict(),
                    "module": "browser",
                    "section": "references",
                    "opened_items": [],
                    "active_item": {},
                },
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]
    active_workspace = workspace_service.active_workspace_summary("default")
    references = active_workspace["workspace"]["surfaceContent"]["references"]["items"]
    added = next(item for item in references if item.get("title") == "PyInstaller Docs")

    assert payload["jobs"][0]["tool_name"] == "browser_context"
    assert metadata["bearing_title"] == "Page added to workspace"
    assert metadata["micro_response"] == "Added the page to References."
    assert "supports the active topic" in metadata["full_response"].lower()
    assert any(reason.get("code") == "active_browser_context" for reason in added.get("inclusionReasons", []))


def test_assistant_orchestrator_summarizes_recent_activity_without_dumping_noise(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    assistant.events.publish(
        level="WARNING",
        source="job_manager",
        message="Job repair-1 finished with status 'failed'.",
        payload={"job_id": "repair-1", "status": "failed", "tool_name": "repair_action", "error": "adapter_not_found"},
    )
    assistant.events.publish(
        level="INFO",
        source="job_manager",
        message="Job workflow-1 finished with status 'completed'.",
        payload={
            "job_id": "workflow-1",
            "status": "completed",
            "tool_name": "workflow_execute",
            "result_summary": "Diagnostics setup completed.",
        },
    )
    assistant.events.publish(
        level="INFO",
        source="job_manager",
        message="Queued job clock-1 for tool 'clock'.",
        payload={"job_id": "clock-1", "tool_name": "clock"},
    )

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "what did I miss?",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]

    assert payload["jobs"][0]["tool_name"] == "activity_summary"
    assert metadata["bearing_title"] == "Recent activity summarized"
    assert metadata["micro_response"] == "Summarized the recent important changes."
    assert "failed" in metadata["full_response"].lower()


def test_assistant_orchestrator_surfaces_compact_next_step_after_force_quit(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=ForceQuitSuggestionProbe())

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "force quit Chrome",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]

    assert metadata["bearing_title"] == "Applications"
    assert metadata["next_suggestion"]["title"] == "Relaunch Chrome"
    assert metadata["next_suggestion"]["command"] == "relaunch chrome"
    assert metadata["judgment"]["risk_tier"] == "high"


def test_assistant_orchestrator_uses_partial_repair_recovery_suggestion(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=PartialNetworkRepairProbe())

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "try fixing my wi-fi",
                surface_mode="ghost",
                active_module="systems",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]

    assert metadata["judgment"]["risk_tier"] == "caution"
    assert metadata["next_suggestion"]["title"] == "Open Device Manager"
    assert metadata["next_suggestion"]["command"] == "open device manager"


def test_assistant_orchestrator_prompts_for_location_permission_guidance_when_precise_fix_is_blocked(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=PermissionFallbackSystemProbe())

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            location = await assistant.handle_message(
                "what is my current location",
                surface_mode="ghost",
                active_module="chartroom",
            )
            weather = await assistant.handle_message(
                "what's the weather right now",
                surface_mode="ghost",
                active_module="chartroom",
            )
            return location, weather
        finally:
            await jobs.stop()
            executor.shutdown()

    location_payload, weather_payload = asyncio.run(runner())

    assert "privacy & security > location" in location_payload["assistant_message"]["content"].lower()
    assert "privacy & security > location" in weather_payload["assistant_message"]["content"].lower()


def test_assistant_orchestrator_uses_recent_power_context_for_eta_follow_up(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            first = await assistant.handle_message(
                "what is my battery level?",
                surface_mode="ghost",
                active_module="systems",
            )
            second = await assistant.handle_message(
                "how long until 100%?",
                surface_mode="ghost",
                active_module="systems",
            )
            return first, second
        finally:
            await jobs.stop()
            executor.shutdown()

    first_payload, second_payload = asyncio.run(runner())

    assert first_payload["jobs"][0]["tool_name"] == "power_status"
    assert second_payload["jobs"][0]["tool_name"] == "power_projection"
    assert second_payload["jobs"][0]["arguments"]["metric"] == "time_to_percent"
    assert second_payload["jobs"][0]["arguments"]["target_percent"] == 100
    assert second_payload["assistant_message"]["content"] != first_payload["assistant_message"]["content"]


def test_assistant_orchestrator_translates_network_state_into_useful_human_meaning(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=StatusLeakageSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="what network am i on?",
        surface_mode="ghost",
        active_module="systems",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)

    assert payload["jobs"][0]["tool_name"] == "network_status"
    assert "connected" in payload["assistant_message"]["content"].lower()
    assert "wi-fi" in payload["assistant_message"]["content"].lower()
    assert "local wi-fi instability likely" not in payload["assistant_message"]["content"].lower()
    assert planner_debug["structured_query"]["query_shape"] == "current_status"
    assert planner_debug["execution_plan"]["plan_type"] == "retrieve_current_status"
    assert planner_debug["response_mode"] == "status_summary"
    assert planner_obedience["actual_tool_names"] == ["network_status"]
    assert planner_obedience["actual_result_mode"] == "status_summary"
    assert planner_obedience["authority_enforced"] is True


def test_assistant_orchestrator_routes_network_diagnostic_questions_to_evidence_based_answer(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "why does my internet keep skipping?",
                surface_mode="ghost",
                active_module="systems",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["jobs"][0]["tool_name"] == "network_diagnosis"
    assert "local wi-fi instability" in payload["assistant_message"]["content"].lower()
    assert "gateway jitter" in payload["assistant_message"]["content"].lower()


@pytest.mark.parametrize(
    ("query", "expected_shape", "expected_plan", "expected_response_mode", "expected_tool", "required_text", "forbidden_text"),
    [
        (
            "what is my current internet speed",
            "current_metric",
            "run_measurement",
            "numeric_metric",
            "network_throughput",
            "mbps",
            "local wi-fi instability likely",
        ),
        (
            "what is my download speed right now",
            "current_metric",
            "run_measurement",
            "numeric_metric",
            "network_throughput",
            "download speed",
            "local wi-fi instability likely",
        ),
        (
            "am i connected",
            "current_status",
            "retrieve_current_status",
            "status_summary",
            "network_status",
            "connected",
            "local wi-fi instability likely",
        ),
        (
            "what network am i on",
            "current_status",
            "retrieve_current_status",
            "status_summary",
            "network_status",
            "connected",
            "local wi-fi instability likely",
        ),
        (
            "what is my wi-fi signal",
            "current_status",
            "retrieve_current_status",
            "status_summary",
            "network_status",
            "signal",
            "local wi-fi instability likely",
        ),
        (
            "why does my internet keep skipping",
            "diagnostic_causal",
            "diagnose_from_telemetry",
            "diagnostic_summary",
            "network_diagnosis",
            "local wi-fi instability likely",
            "",
        ),
        (
            "has my wi-fi been unstable today",
            "history_trend",
            "analyze_history",
            "history_summary",
            "network_diagnosis",
            "local wi-fi instability likely",
            "",
        ),
    ],
)
def test_assistant_orchestrator_enforces_network_planner_contract_end_to_end(
    temp_config,
    query: str,
    expected_shape: str,
    expected_plan: str,
    expected_response_mode: str,
    expected_tool: str | None,
    required_text: str,
    forbidden_text: str,
) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=StatusLeakageSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message=query,
        surface_mode="ghost",
        active_module="systems",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    content = payload["assistant_message"]["content"].lower()

    assert planner_debug["structured_query"]["query_shape"] == expected_shape
    assert planner_debug["execution_plan"]["plan_type"] == expected_plan
    assert payload["assistant_message"]["metadata"]["planner_obedience"]["expected_response_mode"] == expected_response_mode
    assert planner_obedience["actual_result_mode"] == expected_response_mode
    assert planner_obedience["authority_enforced"] is True

    if expected_tool is None:
        assert payload["jobs"] == []
        assert planner_obedience["actual_tool_names"] == []
    else:
        assert payload["jobs"][0]["tool_name"] == expected_tool
        assert planner_obedience["actual_tool_names"] == [expected_tool]

    assert required_text in content
    if forbidden_text:
        assert forbidden_text not in content


def test_assistant_orchestrator_enforces_fix_wifi_as_repair_request(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=PartialNetworkRepairProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="fix Wi-Fi",
        surface_mode="ghost",
        active_module="systems",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)

    assert planner_debug["structured_query"]["query_shape"] == "repair_request"
    assert planner_debug["execution_plan"]["plan_type"] == "execute_repair"
    assert planner_debug["response_mode"] == "action_result"
    assert payload["jobs"][0]["tool_name"] == "repair_action"
    assert planner_obedience["actual_tool_names"] == ["repair_action"]
    assert planner_obedience["actual_result_mode"] == "action_result"
    assert planner_obedience["authority_enforced"] is True
    assert "network repair" in payload["assistant_message"]["content"].lower() or "dns" in payload["assistant_message"]["content"].lower()


def test_assistant_orchestrator_routes_battery_drain_question_to_power_diagnosis(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "Is my battery draining unusually fast?",
                surface_mode="ghost",
                active_module="systems",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["jobs"][0]["tool_name"] == "power_diagnosis"
    assert "battery drain elevated" in payload["assistant_message"]["content"].lower()


def test_assistant_orchestrator_routes_machine_slowdown_question_to_resource_diagnosis(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "What's slowing this machine down?",
                surface_mode="ghost",
                active_module="systems",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["jobs"][0]["tool_name"] == "resource_diagnosis"
    assert "memory pressure" in payload["assistant_message"]["content"].lower()


@pytest.mark.parametrize(
    ("query", "expected_shape", "expected_plan", "expected_response_mode", "expected_tool", "required_text", "forbidden_text"),
    [
        (
            "what GPU do I have",
            "identity_lookup",
            "retrieve_identity",
            "identity_summary",
            "resource_status",
            "gpu is test gpu",
            "gpu usage is",
        ),
        (
            "what is my GPU usage right now",
            "current_metric",
            "retrieve_live_metric",
            "numeric_metric",
            "resource_status",
            "gpu usage is",
            "gpu is test gpu",
        ),
        (
            "is my GPU under load",
            "diagnostic_causal",
            "diagnose_from_telemetry",
            "diagnostic_summary",
            "resource_status",
            "gpu load is",
            "gpu is test gpu",
        ),
        (
            "CPU temp",
            "current_metric",
            "retrieve_live_metric",
            "numeric_metric",
            "resource_status",
            "cpu temperature",
            "cpu is test cpu",
        ),
        (
            "what CPU do I have",
            "identity_lookup",
            "retrieve_identity",
            "identity_summary",
            "resource_status",
            "cpu is test cpu",
            "cpu temperature",
        ),
        (
            "current RAM usage",
            "current_metric",
            "retrieve_live_metric",
            "numeric_metric",
            "resource_status",
            "memory usage is",
            "installed memory is",
        ),
        (
            "what is slowing this machine down",
            "diagnostic_causal",
            "diagnose_from_telemetry",
            "diagnostic_summary",
            "resource_diagnosis",
            "memory pressure",
            "gpu is test gpu",
        ),
    ],
)
def test_assistant_orchestrator_enforces_resource_planner_contract_end_to_end(
    temp_config,
    query: str,
    expected_shape: str,
    expected_plan: str,
    expected_response_mode: str,
    expected_tool: str,
    required_text: str,
    forbidden_text: str,
) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message=query,
        surface_mode="ghost",
        active_module="systems",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    content = payload["assistant_message"]["content"].lower()

    assert planner_debug["structured_query"]["query_shape"] == expected_shape
    assert planner_debug["execution_plan"]["plan_type"] == expected_plan
    assert planner_debug["response_mode"] == expected_response_mode
    assert payload["jobs"][0]["tool_name"] == expected_tool
    assert planner_obedience["actual_tool_names"] == [expected_tool]
    assert planner_obedience["actual_result_mode"] == expected_response_mode
    assert planner_obedience["authority_enforced"] is True
    assert required_text in content
    assert forbidden_text not in content


def test_assistant_orchestrator_mutates_weather_follow_up_horizon(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            first = await assistant.handle_message(
                "what is the weather right now",
                surface_mode="ghost",
                active_module="chartroom",
            )
            second = await assistant.handle_message(
                "what about tomorrow?",
                surface_mode="ghost",
                active_module="chartroom",
            )
            return first, second
        finally:
            await jobs.stop()
            executor.shutdown()

    first_payload, second_payload = asyncio.run(runner())

    assert first_payload["jobs"][0]["tool_name"] == "weather_current"
    assert first_payload["jobs"][0]["arguments"]["forecast_target"] == "current"
    assert second_payload["jobs"][0]["tool_name"] == "weather_current"
    assert second_payload["jobs"][0]["arguments"]["forecast_target"] == "tomorrow"
    assert second_payload["assistant_message"]["content"] != first_payload["assistant_message"]["content"]


def test_assistant_orchestrator_mutates_weather_route_from_external_to_deck(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            first = await assistant.handle_message(
                "open the weather externally",
                surface_mode="ghost",
                active_module="chartroom",
            )
            second = await assistant.handle_message(
                "show it in the Deck instead",
                surface_mode="ghost",
                active_module="chartroom",
            )
            return first, second
        finally:
            await jobs.stop()
            executor.shutdown()

    first_payload, second_payload = asyncio.run(runner())

    assert first_payload["jobs"][0]["tool_name"] == "weather_current"
    assert first_payload["jobs"][0]["arguments"]["open_target"] == "external"
    assert first_payload["actions"][0]["type"] == "open_external"
    assert second_payload["jobs"][0]["tool_name"] == "weather_current"
    assert second_payload["jobs"][0]["arguments"]["open_target"] == "deck"
    assert second_payload["actions"][0]["type"] == "workspace_open"


def test_assistant_orchestrator_treats_unplug_now_follow_up_as_projection_change(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            first = await assistant.handle_message(
                "what is my battery level?",
                surface_mode="ghost",
                active_module="systems",
            )
            second = await assistant.handle_message(
                "what if I unplug now?",
                surface_mode="ghost",
                active_module="systems",
            )
            return first, second
        finally:
            await jobs.stop()
            executor.shutdown()

    first_payload, second_payload = asyncio.run(runner())

    assert first_payload["jobs"][0]["tool_name"] == "power_status"
    assert second_payload["jobs"][0]["tool_name"] == "power_projection"
    assert second_payload["jobs"][0]["arguments"]["assume_unplugged"] is True
    assert second_payload["jobs"][0]["arguments"]["metric"] == "time_to_empty"
    assert second_payload["assistant_message"]["content"] != first_payload["assistant_message"]["content"]


def test_assistant_orchestrator_uses_nano_planner_and_full_reasoner_models(temp_config) -> None:
    provider = FakeProvider()
    temp_config.openai.enabled = True
    temp_config.openai.planner_model = "gpt-5.4-nano"
    temp_config.openai.reasoning_model = "gpt-5.4"
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    assistant.provider = provider

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            direct_provider = await assistant.handle_message(
                "summarize the current bearings",
                surface_mode="ghost",
                active_module="chartroom",
            )
            reasoned = await assistant.handle_message(
                "show me my current system state and tell me if anything looks wrong",
                surface_mode="deck",
                active_module="systems",
            )
            return direct_provider, reasoned
        finally:
            await jobs.stop()
            executor.shutdown()

    asyncio.run(runner())

    assert any(call["model"] == "gpt-5.4-nano" for call in provider.calls)
    assert any(call["model"] == "gpt-5.4" for call in provider.calls)


def test_assistant_orchestrator_learns_weather_deck_preference_after_repeated_explicit_requests(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    async def runner() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            first = await assistant.handle_message(
                "show me the weather in the Deck",
                surface_mode="ghost",
                active_module="chartroom",
            )
            second = await assistant.handle_message(
                "show me the weather in the Deck again",
                surface_mode="ghost",
                active_module="chartroom",
            )
            third = await assistant.handle_message(
                "what's the weather right now",
                surface_mode="ghost",
                active_module="chartroom",
            )
            return first, second, third
        finally:
            await jobs.stop()
            executor.shutdown()

    first_payload, second_payload, third_payload = asyncio.run(runner())

    assert first_payload["jobs"][0]["arguments"]["open_target"] == "deck"
    assert second_payload["jobs"][0]["arguments"]["open_target"] == "deck"
    assert third_payload["jobs"][0]["tool_name"] == "weather_current"
    assert third_payload["jobs"][0]["arguments"]["open_target"] == "deck"
    assert third_payload["actions"][0]["type"] == "workspace_open"


def test_assistant_orchestrator_supports_active_item_shorthand_follow_up(temp_config) -> None:
    assistant, jobs, executor, _, workspace_service = _build_assistant_with_workspace(temp_config)

    workspace = workspace_service.repository.upsert_workspace(
        name="PDF Review",
        topic="pdf review",
        summary="Hold the active PDF for review.",
    )
    workspace_service.capture_workspace_context(
        session_id="default",
        prompt="Review the active PDF.",
        surface_mode="deck",
        active_module="files",
        workspace_context={
            "workspace": workspace.to_dict(),
            "module": "files",
            "section": "opened-items",
            "opened_items": [
                {
                    "itemId": "item-pdf",
                    "kind": "pdf",
                    "viewer": "pdf",
                    "title": "spec.pdf",
                    "path": "C:/Stormhelm/spec.pdf",
                    "summary": "Current active PDF.",
                }
            ],
            "active_item": {
                "itemId": "item-pdf",
                "kind": "pdf",
                "viewer": "pdf",
                "title": "spec.pdf",
                "path": "C:/Stormhelm/spec.pdf",
                "summary": "Current active PDF.",
            },
        },
    )

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "show the pdf in deck",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["jobs"][0]["tool_name"] == "deck_open_file"
    assert payload["jobs"][0]["arguments"]["path"] == "C:/Stormhelm/spec.pdf"


def test_assistant_orchestrator_enforces_search_and_open_contract_for_documents_lookup(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="open the Stormhelm docs in Documents",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    content = payload["assistant_message"]["content"].lower()

    assert planner_debug["structured_query"]["query_shape"] == "search_and_open"
    assert planner_debug["execution_plan"]["plan_type"] == "search_then_open"
    assert planner_debug["response_mode"] == "search_result"
    assert payload["jobs"][0]["tool_name"] == "desktop_search"
    assert planner_obedience["actual_tool_names"] == ["desktop_search"]
    assert planner_obedience["actual_result_mode"] == "search_result"
    assert planner_obedience["authority_enforced"] is True
    assert "documents" in content
    assert "accessible" in content
    assert "local wi-fi instability likely" not in content


def test_assistant_orchestrator_enforces_search_and_open_contract_for_latest_cad_lookup(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="find the latest CAD file and open it",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    content = payload["assistant_message"]["content"].lower()

    assert planner_debug["structured_query"]["query_shape"] == "search_and_open"
    assert planner_debug["execution_plan"]["plan_type"] == "search_then_open"
    assert planner_debug["response_mode"] == "search_result"
    assert payload["jobs"][0]["tool_name"] == "desktop_search"
    assert planner_obedience["actual_tool_names"] == ["desktop_search"]
    assert planner_obedience["actual_result_mode"] == "search_result"
    assert planner_obedience["authority_enforced"] is True
    assert "match" in content
    assert "connected on" not in content


def test_assistant_orchestrator_enforces_comparison_requests_as_clarifications(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="compare these two files",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)

    assert payload["jobs"] == []
    assert planner_debug["structured_query"]["query_shape"] == "comparison_request"
    assert planner_debug["response_mode"] == "clarification"
    assert planner_obedience["actual_result_mode"] == "clarification"
    assert planner_obedience["authority_enforced"] is True
    assert payload["assistant_message"]["content"] == "Which two files should I compare?"


def test_assistant_orchestrator_handles_discord_relay_preview_then_confirmation(temp_config) -> None:
    adapter = FakeDiscordRelayAdapter(state=DiscordDispatchState.STARTED)
    assistant, jobs, executor, session_state = _build_assistant(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    assistant.discord_relay = build_discord_relay_subsystem(
        temp_config.discord_relay,
        session_state=session_state,
        local_adapter=adapter,
    )

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await jobs.start()
        try:
            preview_payload = await assistant.handle_message(
                "send this to Baby",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
                workspace_context={
                    "module": "browser",
                    "active_item": {
                        "title": "Stormhelm Dispatch Spec",
                        "url": "https://example.com/dispatch",
                        "kind": "browser-tab",
                    },
                },
            )
            dispatch_payload = await assistant.handle_message(
                "send it",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
                workspace_context={
                    "module": "browser",
                    "active_item": {
                        "title": "Stormhelm Dispatch Spec",
                        "url": "https://example.com/dispatch",
                        "kind": "browser-tab",
                    },
                },
            )
            return preview_payload, dispatch_payload
        finally:
            await jobs.stop()
            executor.shutdown()

    preview_payload, dispatch_payload = asyncio.run(runner())
    preview_debug = _planner_debug(preview_payload)
    dispatch_debug = _planner_debug(dispatch_payload)

    assert preview_payload["jobs"] == []
    assert preview_payload["assistant_message"]["metadata"]["bearing_title"] == "Discord Preview"
    assert "haven't sent anything yet" in preview_payload["assistant_message"]["content"]
    assert preview_debug["structured_query"]["query_shape"] == "discord_relay_request"
    assert preview_debug["execution_plan"]["plan_type"] == "discord_relay_preview"

    assert dispatch_payload["jobs"] == []
    assert dispatch_payload["assistant_message"]["metadata"]["bearing_title"] == "Discord Dispatch"
    assert "Started the Discord dispatch to Baby" in dispatch_payload["assistant_message"]["content"]
    assert dispatch_debug["structured_query"]["query_shape"] == "discord_relay_request"
    assert dispatch_debug["execution_plan"]["plan_type"] == "discord_relay_dispatch"
    assert adapter.calls
    assert session_state.get_active_request_state("default") == {}


def test_assistant_orchestrator_enforces_workspace_restore_contract(temp_config) -> None:
    assistant, jobs, executor, _, workspace_service = _build_assistant_with_workspace(temp_config)
    workspace_service.repository.upsert_workspace(
        name="Troubleshooting Workspace",
        topic="troubleshooting",
        summary="Network diagnostics and repair notes.",
    )

    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="open my troubleshooting workspace",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)

    assert payload["jobs"][0]["tool_name"] == "workspace_restore"
    assert planner_debug["structured_query"]["query_shape"] == "workspace_request"
    assert planner_debug["execution_plan"]["plan_type"] == "restore_workspace"
    assert planner_debug["response_mode"] == "workspace_result"
    assert planner_obedience["actual_tool_names"] == ["workspace_restore"]
    assert planner_obedience["actual_result_mode"] == "workspace_result"
    assert planner_obedience["authority_enforced"] is True


def test_assistant_orchestrator_enforces_workspace_continuity_contract(temp_config) -> None:
    assistant, jobs, executor, _, workspace_service = _build_assistant_with_workspace(temp_config)
    workspace = workspace_service.repository.upsert_workspace(
        name="Troubleshooting Workspace",
        topic="troubleshooting",
        summary="Network diagnostics and repair notes.",
        active_goal="Finish the network repair pass.",
    )
    workspace_service.capture_workspace_context(
        session_id="default",
        prompt="Carry the troubleshooting workspace forward.",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={
            "workspace": workspace.to_dict(),
            "module": "chartroom",
            "section": "working-set",
            "opened_items": [],
            "active_item": {},
        },
    )

    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="continue where I left off",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)

    assert payload["jobs"][0]["tool_name"] == "workspace_where_left_off"
    assert planner_debug["structured_query"]["query_shape"] == "workspace_request"
    assert planner_debug["execution_plan"]["plan_type"] == "summarize_workspace"
    assert planner_debug["response_mode"] == "workspace_result"
    assert planner_obedience["actual_tool_names"] == ["workspace_where_left_off"]
    assert planner_obedience["actual_result_mode"] == "workspace_result"
    assert planner_obedience["authority_enforced"] is True


def test_assistant_orchestrator_enforces_workspace_assembly_contract(temp_project_root, temp_config) -> None:
    docs_dir = temp_project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "motor-torque-notes.md").write_text("Motor torque notes", encoding="utf-8")

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="create a research workspace for motor torque",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)

    assert payload["jobs"][0]["tool_name"] == "workspace_assemble"
    assert planner_debug["structured_query"]["query_shape"] == "workspace_request"
    assert planner_debug["execution_plan"]["plan_type"] == "assemble_workspace"
    assert planner_debug["response_mode"] == "workspace_result"
    assert planner_obedience["actual_tool_names"] == ["workspace_assemble"]
    assert planner_obedience["actual_result_mode"] == "workspace_result"
    assert planner_obedience["authority_enforced"] is True


def test_assistant_orchestrator_includes_input_context_for_reasoner_backed_selection_request(temp_config) -> None:
    provider = InputContextProvider()
    temp_config.openai.enabled = True
    temp_config.openai.planner_model = "gpt-5.4"
    temp_config.openai.reasoning_model = "gpt-5.4"
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    assistant.provider = provider

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "summarize this",
                session_id="default",
                surface_mode="deck",
                active_module="chartroom",
                workspace_context={"workspace": {"workspaceId": "ws-1", "name": "Packaging Workspace"}},
                input_context={
                    "selection": {
                        "kind": "text",
                        "value": "Selected packaging notes.",
                        "preview": "Selected packaging notes.",
                    }
                },
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["assistant_message"]["content"] == "Summarized the selection."
    assert provider.calls
    serialized = str(provider.calls[0]["input_items"])
    assert "Selected packaging notes." in serialized


def test_assistant_orchestrator_opens_personal_youtube_history_in_browser_with_compact_contract(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="open my personal youtube history in a browser",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    metadata = payload["assistant_message"]["metadata"]

    assert planner_debug["structured_query"]["query_shape"] == "open_browser_destination"
    assert planner_debug["execution_plan"]["plan_type"] == "resolve_url_then_open_in_browser"
    assert payload["jobs"][0]["tool_name"] == "external_open_url"
    assert payload["jobs"][0]["arguments"]["url"] == "https://www.youtube.com/feed/history"
    assert payload["actions"][0]["type"] == "open_external"
    assert payload["actions"][0]["url"] == "https://www.youtube.com/feed/history"
    assert metadata["bearing_title"] == "YouTube history requested"
    assert metadata["micro_response"] == "Requested that YouTube history open externally."
    assert metadata["full_response"] == "Requested that YouTube history open externally."


def test_assistant_orchestrator_reports_unresolved_browser_destination_without_launch_category_error(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="open the nebula portal in a browser",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    metadata = payload["assistant_message"]["metadata"]

    assert planner_debug["structured_query"]["query_shape"] == "open_browser_destination"
    assert payload["jobs"] == []
    assert payload["actions"] == []
    assert metadata["bearing_title"] == "Browser destination unresolved"
    assert metadata["micro_response"] == "I couldn't resolve that site."
    assert metadata["full_response"] == "I couldn't resolve a browser destination for that request."
    assert "launch" not in payload["assistant_message"]["content"].lower()


@pytest.mark.parametrize(
    ("message", "expected_url", "expected_destination_name", "expected_scope", "expected_title"),
    [
        ("open youtube in a browser", "https://www.youtube.com/", "youtube", "general", "YouTube"),
        ("open gmail in a browser", "https://mail.google.com/mail/u/0/#inbox", "gmail", "general", "Gmail"),
        ("open chatgpt in a browser", "https://chatgpt.com/", "chatgpt", "general", "ChatGPT"),
        ("open github in a browser", "https://github.com/", "github", "general", "GitHub"),
        ("open openai in a browser", "https://openai.com/", "openai", "general", "OpenAI"),
        ("open youtube history in a browser", "https://www.youtube.com/feed/history", "youtube_history", "general", "YouTube history"),
        ("open my email in a browser", "https://mail.google.com/mail/u/0/#inbox", "gmail", "personal", "Gmail"),
        ("open my gmail in a browser", "https://mail.google.com/mail/u/0/#inbox", "gmail", "personal", "Gmail"),
    ],
)
def test_assistant_orchestrator_routes_known_browser_destinations_end_to_end(
    temp_config,
    message: str,
    expected_url: str,
    expected_destination_name: str,
    expected_scope: str,
    expected_title: str,
) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message=message,
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    metadata = payload["assistant_message"]["metadata"]
    structured_slots = planner_debug["structured_query"]["slots"]

    assert planner_debug["structured_query"]["query_shape"] == "open_browser_destination"
    assert planner_debug["execution_plan"]["plan_type"] == "resolve_url_then_open_in_browser"
    assert structured_slots["destination_name"] == expected_destination_name
    assert structured_slots["destination_scope"] == expected_scope
    assert payload["jobs"][0]["tool_name"] == "external_open_url"
    assert payload["jobs"][0]["arguments"]["url"] == expected_url
    assert payload["actions"][0]["type"] == "open_external"
    assert payload["actions"][0]["url"] == expected_url
    assert metadata["bearing_title"] == f"{expected_title} requested"
    assert planner_obedience["actual_tool_names"] == ["external_open_url"]
    assert planner_obedience["actual_result_mode"] == "action_result"
    assert planner_obedience["authority_enforced"] is True


def test_assistant_orchestrator_keeps_app_launch_and_web_search_distinct_from_browser_destinations(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())

    chrome_payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="open Chrome",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(chrome_payload)

    assert planner_debug["structured_query"]["query_shape"] == "control_command"
    assert chrome_payload["jobs"][0]["tool_name"] == "app_control"
    assert chrome_payload["jobs"][0]["arguments"]["action"] == "launch"
    assert chrome_payload["jobs"][0]["arguments"]["app_name"] == "chrome"

    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    search_payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="search YouTube for cats",
        surface_mode="ghost",
        active_module="chartroom",
    )
    search_debug = _planner_debug(search_payload)
    search_obedience = _planner_obedience(search_payload)

    assert search_debug["structured_query"]["query_shape"] == "search_browser_destination"
    assert search_debug["execution_plan"]["plan_type"] == "resolve_search_url_then_open_in_browser"
    assert search_payload["jobs"][0]["tool_name"] == "external_open_url"
    assert search_payload["jobs"][0]["arguments"]["url"] == "https://www.youtube.com/results?search_query=cats"
    assert search_payload["actions"][0]["type"] == "open_external"
    assert search_payload["actions"][0]["url"] == "https://www.youtube.com/results?search_query=cats"
    assert search_obedience["authority_enforced"] is True


def test_assistant_orchestrator_uses_nano_browser_search_fallback_for_unresolved_provider(monkeypatch, temp_config) -> None:
    monkeypatch.setattr(
        workspace_actions,
        "probe_browser_target",
        lambda browser_target: workspace_actions.BrowserTargetProbeResult(
            requested_target=browser_target,
            resolved_target=browser_target,
            browser_title="Chrome",
            available=True,
            launch_command="C:/Program Files/Google/Chrome/Application/chrome.exe",
            fallback_to_default=False,
            reason="launcher_found_in_common_install_path",
        ),
    )
    provider = BrowserSearchFallbackProvider()
    temp_config.openai.enabled = True
    temp_config.openai.planner_model = "gpt-5.4-nano"
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    assistant.provider = provider

    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="search orbitz for flights in chrome",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    planner_obedience = _planner_obedience(payload)
    metadata = payload["assistant_message"]["metadata"]

    assert planner_debug["structured_query"]["query_shape"] == "search_browser_destination"
    assert planner_debug["execution_plan"]["plan_type"] == "resolve_search_url_then_open_in_browser"
    assert planner_debug["structured_query"]["slots"]["browser_search_failure_reason"] == "search_provider_unresolved"
    assert planner_debug["structured_query"]["slots"]["browser_search_fallback"]["used"] is True
    assert planner_debug["structured_query"]["slots"]["browser_search_fallback"]["resolution_kind"] == "site_search"
    assert payload["jobs"][0]["tool_name"] == "external_open_url"
    assert payload["jobs"][0]["arguments"]["url"] == "https://www.google.com/search?q=site%3Aorbitz.com+flights"
    assert payload["jobs"][0]["arguments"]["browser_target"] == "chrome"
    assert payload["actions"][0]["type"] == "open_external"
    assert payload["actions"][0]["url"] == "https://www.google.com/search?q=site%3Aorbitz.com+flights"
    assert payload["actions"][0]["browser_target"] == "chrome"
    assert payload["actions"][0]["browser_command"] == "C:/Program Files/Google/Chrome/Application/chrome.exe"
    assert metadata["bearing_title"] == "Orbitz search requested"
    assert metadata["micro_response"] == "Requested that Orbitz search open externally."
    assert metadata["full_response"] == "Requested that Orbitz search open externally."
    assert planner_obedience["actual_tool_names"] == ["external_open_url"]
    assert planner_obedience["authority_enforced"] is True
    assert provider.calls
    assert provider.calls[0]["model"] == "gpt-5.4-nano"
    assert provider.calls[0]["previous_response_id"] is None
    assert provider.calls[0]["tool_names"] == ["browser_search_fallback_resolve"]


def test_assistant_orchestrator_opens_direct_domain_in_explicit_browser(monkeypatch, temp_config) -> None:
    monkeypatch.setattr(
        workspace_actions,
        "probe_browser_target",
        lambda browser_target: workspace_actions.BrowserTargetProbeResult(
            requested_target=browser_target,
            resolved_target=browser_target,
            browser_title="Firefox",
            available=True,
            launch_command="C:/Program Files/Mozilla Firefox/firefox.exe",
            fallback_to_default=False,
            reason="launcher_found_in_common_install_path",
        ),
    )
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="open docs.python.org in firefox",
        surface_mode="ghost",
        active_module="chartroom",
    )
    planner_debug = _planner_debug(payload)
    metadata = payload["assistant_message"]["metadata"]
    structured_slots = planner_debug["structured_query"]["slots"]

    assert planner_debug["structured_query"]["query_shape"] == "open_browser_destination"
    assert planner_debug["execution_plan"]["plan_type"] == "resolve_url_then_open_in_browser"
    assert structured_slots["destination_type"] == "direct_domain"
    assert structured_slots["destination_resolution_kind"] == "direct_domain"
    assert structured_slots["destination_site_domain"] == "docs.python.org"
    assert payload["jobs"][0]["tool_name"] == "external_open_url"
    assert payload["jobs"][0]["arguments"]["url"] == "https://docs.python.org/"
    assert payload["jobs"][0]["arguments"]["browser_target"] == "firefox"
    assert payload["actions"][0]["type"] == "open_external"
    assert payload["actions"][0]["url"] == "https://docs.python.org/"
    assert payload["actions"][0]["browser_target"] == "firefox"
    assert payload["actions"][0]["browser_command"] == "C:/Program Files/Mozilla Firefox/firefox.exe"
    assert metadata["bearing_title"] == "docs.python.org requested"
    assert metadata["micro_response"] == "Requested that docs.python.org open externally."
    assert metadata["full_response"] == "Requested that docs.python.org open externally."


def test_assistant_orchestrator_falls_back_to_default_browser_when_explicit_target_is_unavailable(
    monkeypatch,
    temp_config,
) -> None:
    monkeypatch.setattr(
        workspace_actions,
        "probe_browser_target",
        lambda browser_target: workspace_actions.BrowserTargetProbeResult(
            requested_target=browser_target,
            resolved_target=browser_target,
            browser_title="Firefox",
            available=False,
            launch_command=None,
            fallback_to_default=True,
            reason="browser_not_available",
        ),
    )
    assistant, jobs, executor, _ = _build_assistant(temp_config, system_probe=FakeSystemProbe())
    payload = _run_assistant_once(
        assistant,
        jobs,
        executor,
        message="open docs.python.org in firefox",
        surface_mode="ghost",
        active_module="chartroom",
    )
    metadata = payload["assistant_message"]["metadata"]
    action = payload["actions"][0]

    assert payload["jobs"][0]["tool_name"] == "external_open_url"
    assert payload["jobs"][0]["arguments"]["browser_target"] == "firefox"
    assert action["type"] == "open_external"
    assert action["url"] == "https://docs.python.org/"
    assert "browser_target" not in action
    assert action["browser_target_requested"] == "firefox"
    assert action["browser_fallback_to_default"] is True
    assert action["browser_target_probe"]["available"] is False
    assert action["browser_target_probe"]["reason"] == "browser_not_available"
    assert metadata["bearing_title"] == "docs.python.org requested"
    assert metadata["micro_response"] == (
        "Requested that docs.python.org open in the default browser because Firefox wasn't available here."
    )
    assert metadata["full_response"] == (
        "Requested that docs.python.org open in the default browser because Firefox wasn't available here."
    )
