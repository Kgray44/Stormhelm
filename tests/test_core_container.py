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


def test_core_container_status_snapshot_includes_operational_surface_state(temp_config) -> None:
    container = build_container(temp_config)
    container.system_probe = FakeOperationalProbe()  # type: ignore[assignment]

    snapshot = container.status_snapshot()

    assert snapshot["systems_interpretation"]["headline"] == "Local Wi-Fi instability likely"
    assert snapshot["watch_state"]["tasks"] == []
    assert any(signal["title"] == "Battery drain elevated" for signal in snapshot["signal_state"]["signals"])
    assert snapshot["system_state"]["network"]["throughput"]["download_mbps"] == 84.25
