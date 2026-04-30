from __future__ import annotations

from pathlib import Path

from stormhelm.core.network.monitor import NetworkMonitor
from stormhelm.core.network.providers import CloudflareQualityProvider


class ScriptedProbe:
    def __init__(self, steps: list[dict[str, object]]) -> None:
        self.steps = steps
        self.index = -1
        self.current: dict[str, object] | None = None
        self.external_index = 0

    def _network_interface_status(self) -> dict[str, object]:
        self.index = min(self.index + 1, len(self.steps) - 1)
        self.current = self.steps[self.index]
        self.external_index = 0
        return dict(self.current["interfaces_payload"])  # type: ignore[index]

    def _network_probe(self, target: str, *, timeout_ms: int = 1000) -> dict[str, object]:
        del timeout_ms
        assert self.current is not None
        if target == self.current["gateway_target"]:
            return dict(self.current["gateway_probe"])  # type: ignore[index]
        probes = self.current["external_probes"]  # type: ignore[index]
        result = dict(probes[self.external_index])  # type: ignore[index]
        self.external_index += 1
        return result

    def _dns_health(self, *, hostname: str = "cloudflare.com") -> dict[str, object]:
        del hostname
        assert self.current is not None
        return dict(self.current.get("dns", {"hostname": "cloudflare.com", "latency_ms": 18.0, "failed": False}))


class StubCloudflareProvider:
    def __init__(self, samples: list[dict[str, object]] | None = None) -> None:
        self.samples = samples or []
        self.calls = 0

    def capability_state(self) -> dict[str, object]:
        if self.calls <= 0 and self.samples:
            return {"state": "waiting_for_sample", "label": "Cloudflare quality", "detail": "Waiting for an external quality sample."}
        if self.samples:
            return dict(self.samples[min(max(self.calls - 1, 0), len(self.samples) - 1)])
        return {"state": "not_configured", "label": "Cloudflare quality", "detail": "Cloudflare-quality enrichment is disabled."}

    def sample(self) -> dict[str, object]:
        if not self.samples:
            self.calls += 1
            return self.capability_state()
        sample = dict(self.samples[min(self.calls, len(self.samples) - 1)])
        self.calls += 1
        return sample


def _step(
    *,
    status: str = "Up",
    bssid: str = "aa:bb:cc:dd:ee:01",
    gateway_latency_ms: int | None = 10,
    gateway_timed_out: bool = False,
    external_latencies: tuple[int | None, int | None] = (18, 21),
    external_timeouts: tuple[bool, bool] = (False, False),
    signal_strength_dbm: int = -58,
) -> dict[str, object]:
    return {
        "interfaces_payload": {
            "hostname": "stormhelm-test",
            "fqdn": "stormhelm-test.local",
            "interfaces": [
                {
                    "interface_alias": "Wi-Fi",
                    "status": status,
                    "gateway": ["192.168.1.1"],
                    "bssid": bssid,
                    "signal_strength_dbm": signal_strength_dbm,
                }
            ],
        },
        "gateway_target": "192.168.1.1",
        "gateway_probe": {
            "target": "192.168.1.1",
            "reachable": gateway_latency_ms is not None and not gateway_timed_out,
            "latency_ms": gateway_latency_ms,
            "timed_out": gateway_timed_out,
        },
        "external_probes": [
            {
                "target": "1.1.1.1",
                "reachable": external_latencies[0] is not None and not external_timeouts[0],
                "latency_ms": external_latencies[0],
                "timed_out": external_timeouts[0],
            },
            {
                "target": "8.8.8.8",
                "reachable": external_latencies[1] is not None and not external_timeouts[1],
                "latency_ms": external_latencies[1],
                "timed_out": external_timeouts[1],
            },
        ],
        "dns": {
            "hostname": "cloudflare.com",
            "latency_ms": 18.0,
            "failed": False,
        },
    }


def test_network_monitor_detects_packet_loss_burst_and_latency_spike_windows(workspace_temp_dir: Path) -> None:
    probe = ScriptedProbe(
        [
            _step(),
            _step(gateway_latency_ms=164, external_latencies=(188, 210), external_timeouts=(True, False)),
            _step(gateway_latency_ms=142, external_latencies=(176, 205), external_timeouts=(True, True)),
        ]
    )
    monitor = NetworkMonitor(
        probe=probe,
        cloudflare_provider=StubCloudflareProvider(),
        history_path=workspace_temp_dir / "network-history.json",
    )

    monitor._sample_once(mode="idle")
    monitor._sample_once(mode="diagnostic")
    monitor._sample_once(mode="diagnostic")

    snapshot = monitor.snapshot()
    event_kinds = {str(event.get("kind")) for event in snapshot["events"]}

    assert "gateway_latency_spike" in event_kinds
    assert "external_packet_loss_burst" in event_kinds


def test_network_monitor_cached_snapshot_does_not_force_live_sample(
    workspace_temp_dir: Path,
) -> None:
    probe = ScriptedProbe([_step(), _step(gateway_latency_ms=170)])
    monitor = NetworkMonitor(
        probe=probe,
        cloudflare_provider=StubCloudflareProvider(),
        history_path=workspace_temp_dir / "network-history.json",
    )

    monitor._sample_once(mode="idle")
    probe.index = 999

    snapshot = monitor.snapshot_cached()

    assert snapshot["monitoring"]["sample_count"] == 1
    assert probe.index == 999
    assert snapshot["system_resource_freshness_state"] in {"fresh", "stale"}
    assert snapshot["system_probe_deferred"] is False


def test_network_monitor_detects_roam_linked_outage_periods(workspace_temp_dir: Path) -> None:
    probe = ScriptedProbe(
        [
            _step(bssid="aa:bb:cc:dd:ee:01"),
            _step(
                bssid="aa:bb:cc:dd:ee:02",
                gateway_latency_ms=None,
                gateway_timed_out=True,
                external_latencies=(None, None),
                external_timeouts=(True, True),
            ),
        ]
    )
    monitor = NetworkMonitor(
        probe=probe,
        cloudflare_provider=StubCloudflareProvider(),
        history_path=workspace_temp_dir / "network-history.json",
    )

    monitor._sample_once(mode="idle")
    monitor._sample_once(mode="diagnostic")

    snapshot = monitor.snapshot()
    event_kinds = {str(event.get("kind")) for event in snapshot["events"]}

    assert "roam_linked_outage" in event_kinds


def test_network_monitor_restores_recent_history_across_restarts(workspace_temp_dir: Path) -> None:
    history_path = workspace_temp_dir / "network-history.json"
    probe = ScriptedProbe([_step(), _step(gateway_latency_ms=152, external_latencies=(180, 204), external_timeouts=(True, False))])
    monitor = NetworkMonitor(
        probe=probe,
        cloudflare_provider=StubCloudflareProvider(),
        history_path=history_path,
    )

    monitor._sample_once(mode="idle")
    monitor._sample_once(mode="diagnostic")

    assert history_path.exists()

    reloaded = NetworkMonitor(
        probe=ScriptedProbe([_step()]),
        cloudflare_provider=StubCloudflareProvider(),
        history_path=history_path,
    )

    assert len(reloaded._history) >= 2
    assert any(str(event.get("kind")) == "gateway_latency_spike" for event in reloaded._event_log)


def test_cloudflare_quality_provider_reports_comparison_ready_metrics(monkeypatch) -> None:
    samples = iter([24.0, 32.0, None, 28.0])

    def fake_request(self) -> float | None:
        return next(samples)

    monkeypatch.setattr(CloudflareQualityProvider, "_request_latency_sample", fake_request)

    provider = CloudflareQualityProvider(enabled=True, timeout_seconds=0.1, sample_count=4)
    sample = provider.sample()

    assert sample["state"] == "ready"
    assert sample["sample_count"] == 4
    assert sample["successful_samples"] == 3
    assert sample["packet_loss_pct"] == 25.0
    assert sample["jitter_ms"] > 0
    assert sample["comparison_ready"] is True
