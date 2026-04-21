from __future__ import annotations

from stormhelm.core.container import build_container


class FakeOperationalProbe:
    def machine_status(self) -> dict[str, object]:
        return {
            "machine_name": "Stormhelm-Test",
            "system": "Windows",
            "release": "11",
            "timezone": "America/New_York",
        }

    def power_status(self) -> dict[str, object]:
        return {
            "available": True,
            "ac_line_status": "offline",
            "battery_percent": 74,
            "rolling_power_draw_watts": 27.5,
            "time_to_empty_seconds": 6400,
        }

    def resource_status(self) -> dict[str, object]:
        return {
            "cpu": {"name": "AMD Ryzen", "utilization_percent": 34.0},
            "memory": {
                "total_bytes": 32 * 1024**3,
                "used_bytes": 29 * 1024**3,
                "free_bytes": 3 * 1024**3,
            },
            "gpu": [{"name": "NVIDIA RTX", "temperature_c": 60.0}],
        }

    def hardware_telemetry_snapshot(self, sampling_tier: str = "active") -> dict[str, object]:
        return {
            "capabilities": {"helper_reachable": True},
            "freshness": {"sampling_tier": sampling_tier, "sample_age_seconds": 1.0},
        }

    def storage_status(self) -> dict[str, object]:
        return {
            "drives": [
                {
                    "drive": "C:\\",
                    "total_bytes": 512 * 1024**3,
                    "used_bytes": 420 * 1024**3,
                    "free_bytes": 92 * 1024**3,
                }
            ]
        }

    def network_status(self) -> dict[str, object]:
        return {
            "interfaces": [{"interface_alias": "Wi-Fi", "ipv4": ["192.168.1.20"]}],
            "assessment": {
                "kind": "local_link_issue",
                "headline": "Local Wi-Fi instability likely",
                "summary": "Gateway and external probes degraded together, which points to the local link.",
                "confidence": "moderate",
            },
            "throughput": {
                "available": True,
                "state": "ready",
                "download_mbps": 84.25,
                "upload_mbps": 12.5,
                "source": "net_adapter_statistics",
            },
            "providers": {
                "local_status": {"state": "ready", "detail": "Wi-Fi | gateway 192.168.1.1", "available": True},
                "upstream_path": {"state": "ready", "detail": "latency 26 ms | jitter 3 ms", "available": True},
                "observed_throughput": {"state": "ready", "detail": "Observed over the last 1.0 seconds on Wi-Fi.", "available": True},
                "cloudflare_quality": {"state": "ready", "label": "Cloudflare quality", "detail": "Aligned with probes.", "available": True},
            },
            "source_debug": {"throughput_primary": "net_adapter_statistics"},
        }

    def resolve_location(self) -> dict[str, object]:
        return {"resolved": True, "label": "Queens, New York", "source": "approximate"}


class CountingOperationalProbe(FakeOperationalProbe):
    def __init__(self) -> None:
        self.power_calls = 0
        self.resource_calls = 0
        self.hardware_calls = 0
        self.network_calls = 0
        self.location_calls = 0

    def power_status(self) -> dict[str, object]:
        self.power_calls += 1
        return super().power_status()

    def resource_status(self) -> dict[str, object]:
        self.resource_calls += 1
        return super().resource_status()

    def hardware_telemetry_snapshot(self, sampling_tier: str = "active") -> dict[str, object]:
        self.hardware_calls += 1
        return super().hardware_telemetry_snapshot(sampling_tier=sampling_tier)

    def network_status(self) -> dict[str, object]:
        self.network_calls += 1
        return super().network_status()

    def resolve_location(self) -> dict[str, object]:
        self.location_calls += 1
        return super().resolve_location()


def test_core_container_status_snapshot_includes_operational_surface_state(temp_config) -> None:
    container = build_container(temp_config)
    container.system_probe = FakeOperationalProbe()  # type: ignore[assignment]

    snapshot = container.status_snapshot()

    assert snapshot["systems_interpretation"]["headline"] == "Local Wi-Fi instability likely"
    assert snapshot["watch_state"]["tasks"] == []
    assert any(signal["title"] == "Battery drain elevated" for signal in snapshot["signal_state"]["signals"])
    assert snapshot["system_state"]["network"]["throughput"]["download_mbps"] == 84.25


def test_core_container_status_snapshot_includes_screen_awareness_phase1_state(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase1"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True

    container = build_container(temp_config)
    container.system_probe = FakeOperationalProbe()  # type: ignore[assignment]

    snapshot = container.status_snapshot()

    assert snapshot["screen_awareness"]["phase"] == "phase1"
    assert snapshot["screen_awareness"]["enabled"] is True
    assert snapshot["screen_awareness"]["planner_routing_enabled"] is True
    assert snapshot["screen_awareness"]["capabilities"]["observation_enabled"] is True
    assert snapshot["screen_awareness"]["capabilities"]["interpretation_enabled"] is True
    assert snapshot["screen_awareness"]["capabilities"]["action_enabled"] is False
    assert snapshot["screen_awareness"]["truthfulness_contract"]["observation_vs_inference"] == "separate"
    assert snapshot["screen_awareness"]["extension_points"]["verification"] is True


def test_core_container_status_snapshot_includes_phase2_grounding_runtime_hooks(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase2"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True

    container = build_container(temp_config)
    container.system_probe = FakeOperationalProbe()  # type: ignore[assignment]

    snapshot = container.status_snapshot()

    assert snapshot["screen_awareness"]["phase"] == "phase2"
    assert snapshot["screen_awareness"]["capabilities"]["grounding_enabled"] is True
    assert snapshot["screen_awareness"]["runtime_hooks"]["grounding_engine_ready"] is True


def test_core_container_system_state_cache_uses_completed_snapshot_time(temp_config, monkeypatch) -> None:
    container = build_container(temp_config)
    probe = CountingOperationalProbe()
    container.system_probe = probe  # type: ignore[assignment]
    monotonic_values = iter([100.0, 116.0, 117.0])
    monkeypatch.setattr("stormhelm.core.container.monotonic", lambda: next(monotonic_values))

    first = container._system_state_snapshot()
    second = container._system_state_snapshot()

    assert first["network"]["throughput"]["download_mbps"] == 84.25
    assert second["network"]["throughput"]["download_mbps"] == 84.25
    assert probe.power_calls == 1
    assert probe.resource_calls == 1
    assert probe.hardware_calls == 1
    assert probe.location_calls == 1
    assert probe.network_calls == 1
