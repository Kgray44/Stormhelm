from __future__ import annotations

from collections import deque
from datetime import datetime
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, TYPE_CHECKING

from stormhelm.core.network.analyzer import NetworkAnalyzer
from stormhelm.core.network.providers import CloudflareQualityProvider, ObservedThroughputProvider

if TYPE_CHECKING:
    from stormhelm.core.events import EventBuffer
    from stormhelm.core.system.probe import SystemProbe


logger = logging.getLogger(__name__)


class NetworkMonitor:
    def __init__(
        self,
        *,
        probe: SystemProbe,
        events: EventBuffer | None = None,
        analyzer: NetworkAnalyzer | None = None,
        cloudflare_provider: CloudflareQualityProvider | None = None,
        throughput_provider: ObservedThroughputProvider | None = None,
        history_path: Path | None = None,
        history_limit: int = 120,
        event_limit: int = 48,
        idle_interval_seconds: float = 20.0,
        normal_interval_seconds: float = 8.0,
        diagnostic_interval_seconds: float = 2.5,
        diagnostic_burst_seconds: float = 30.0,
    ) -> None:
        self._probe = probe
        self._events = events
        self._analyzer = analyzer or NetworkAnalyzer()
        self._cloudflare_provider = cloudflare_provider or CloudflareQualityProvider(enabled=True)
        self._throughput_provider = throughput_provider or ObservedThroughputProvider(probe)
        self._history = deque(maxlen=max(history_limit, 24))
        self._event_log = deque(maxlen=max(event_limit, 12))
        self._history_path = Path(history_path) if history_path is not None else None
        self._idle_interval_seconds = idle_interval_seconds
        self._normal_interval_seconds = normal_interval_seconds
        self._diagnostic_interval_seconds = diagnostic_interval_seconds
        self._diagnostic_burst_seconds = diagnostic_burst_seconds
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._diagnostic_until = 0.0
        self._last_sample_at = 0.0
        self._load_persisted_history()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="StormhelmNetworkMonitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def request_diagnostic_burst(self, reason: str = "manual") -> None:
        with self._lock:
            self._diagnostic_until = max(self._diagnostic_until, time.monotonic() + self._diagnostic_burst_seconds)
        self._append_event(
            {
                "kind": "diagnostic_burst",
                "title": "Diagnostic sample active",
                "detail": f"Stormhelm raised network sampling for {reason.replace('_', ' ')}.",
                "severity": "attention",
                "recorded_at": datetime.now().astimezone().isoformat(),
            }
        )

    def snapshot(self, *, diagnostic_burst: bool = False) -> dict[str, Any]:
        if diagnostic_burst:
            self.request_diagnostic_burst("operator request")
        if self._needs_sample():
            self._sample_once(mode="normal")
        with self._lock:
            samples = list(self._history)
            events = list(self._event_log)
            diagnostic_until = self._diagnostic_until
            last_sample_at = self._last_sample_at
        telemetry = self._summarize(samples, events, diagnostic_until=diagnostic_until, last_sample_at=last_sample_at)
        telemetry["assessment"] = self._analyzer.analyze(telemetry)
        return telemetry

    def snapshot_cached(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self._history)
            events = list(self._event_log)
            diagnostic_until = self._diagnostic_until
            last_sample_at = self._last_sample_at
        telemetry = self._summarize(samples, events, diagnostic_until=diagnostic_until, last_sample_at=last_sample_at)
        telemetry["assessment"] = self._analyzer.analyze(telemetry)
        age_ms = round(max(time.monotonic() - last_sample_at, 0.0) * 1000, 3) if last_sample_at else None
        if age_ms is None:
            freshness_state = "missing"
        elif age_ms <= self._normal_interval_seconds * 1000:
            freshness_state = "fresh"
        else:
            freshness_state = "stale"
        telemetry["system_resource_cache_hit"] = last_sample_at > 0
        telemetry["system_resource_cache_age_ms"] = age_ms
        telemetry["system_resource_freshness_state"] = freshness_state
        telemetry["system_probe_deferred"] = False
        telemetry["system_live_refresh_job_id"] = ""
        telemetry.setdefault("monitoring", {})["system_resource_freshness_state"] = freshness_state
        telemetry["monitoring"]["system_probe_deferred"] = False
        return telemetry

    def _run(self) -> None:
        while not self._stop_event.is_set():
            mode = "diagnostic" if self._diagnostic_active() else "idle"
            try:
                self._sample_once(mode=mode)
            except Exception:
                logger.exception("Network monitor sample failed.")
            interval = self._diagnostic_interval_seconds if mode == "diagnostic" else self._idle_interval_seconds
            self._stop_event.wait(interval)

    def _needs_sample(self) -> bool:
        with self._lock:
            last = self._last_sample_at
        return not last or (time.monotonic() - last) > self._normal_interval_seconds

    def _diagnostic_active(self) -> bool:
        with self._lock:
            return self._diagnostic_until > time.monotonic()

    def _sample_once(self, *, mode: str) -> None:
        interfaces_payload = self._probe._network_interface_status()
        interfaces = interfaces_payload.get("interfaces", []) if isinstance(interfaces_payload.get("interfaces"), list) else []
        primary = interfaces[0] if interfaces and isinstance(interfaces[0], dict) else {}
        gateway = ""
        gateways = primary.get("gateway", [])
        if isinstance(gateways, list) and gateways:
            gateway = str(gateways[0]).strip()
        gateway_probe = self._probe._network_probe(gateway, timeout_ms=900) if gateway else {"reachable": False, "latency_ms": None, "timed_out": True}
        external_targets = ["1.1.1.1", "8.8.8.8"]
        external_probes = [self._probe._network_probe(target, timeout_ms=1100) for target in external_targets]
        dns = self._probe._dns_health(hostname="cloudflare.com")
        provider_state = self._cloudflare_provider.sample() if mode == "diagnostic" else self._cloudflare_provider.capability_state()
        captured_at = datetime.now().astimezone().isoformat()
        throughput_sample = self._throughput_provider.capture_sample(primary_interface=primary, captured_at=captured_at)
        sample = {
            "captured_at": captured_at,
            "mode": mode,
            "hostname": interfaces_payload.get("hostname"),
            "fqdn": interfaces_payload.get("fqdn"),
            "interfaces": interfaces,
            "primary_interface": primary,
            "gateway_probe": gateway_probe,
            "external_probes": external_probes,
            "dns": dns,
            "throughput_sample": throughput_sample,
            "providers": {"cloudflare_quality": provider_state},
        }
        with self._lock:
            previous = self._history[-1] if self._history else None
            self._history.append(sample)
            self._last_sample_at = time.monotonic()
            self._persist_history_locked()
        self._detect_events(previous, sample)

    def _detect_events(self, previous: dict[str, Any] | None, current: dict[str, Any]) -> None:
        primary = current.get("primary_interface", {}) if isinstance(current.get("primary_interface"), dict) else {}
        previous_primary = previous.get("primary_interface", {}) if isinstance(previous, dict) and isinstance(previous.get("primary_interface"), dict) else {}
        current_up = str(primary.get("status", "")).strip().lower() == "up"
        previous_up = str(previous_primary.get("status", "")).strip().lower() == "up"
        if previous is not None and previous_up and not current_up:
            self._append_event({"kind": "disconnect", "title": "Connection dropped", "detail": "The active interface went down.", "severity": "warning"})
        if previous is not None and not previous_up and current_up:
            self._append_event({"kind": "reconnect", "title": "Connection restored", "detail": "The active interface came back up.", "severity": "steady"})
        current_bssid = str(primary.get("bssid") or "").strip().lower()
        previous_bssid = str(previous_primary.get("bssid") or "").strip().lower()
        if previous_bssid and current_bssid and previous_bssid != current_bssid:
            self._append_event({"kind": "bssid_change", "title": "Access point changed", "detail": "Stormhelm detected a BSSID handoff.", "severity": "attention"})
        gateway_probe = current.get("gateway_probe", {}) if isinstance(current.get("gateway_probe"), dict) else {}
        if gateway_probe.get("timed_out"):
            self._append_event({"kind": "gateway_unreachable", "title": "Gateway timeout", "detail": "The local gateway missed a recent probe.", "severity": "warning"})
            self._append_event({"kind": "gateway_packet_loss_burst", "title": "Gateway packet-loss burst", "detail": "The local gateway dropped the latest probe.", "severity": "warning"})
        gateway_latency = gateway_probe.get("latency_ms")
        previous_gateway_probe = previous.get("gateway_probe", {}) if isinstance(previous, dict) and isinstance(previous.get("gateway_probe"), dict) else {}
        previous_gateway_latency = previous_gateway_probe.get("latency_ms")
        if gateway_latency is not None and (
            float(gateway_latency) >= 120.0
            or (
                previous_gateway_latency is not None
                and float(previous_gateway_latency) < 100.0
                and (float(gateway_latency) - float(previous_gateway_latency)) >= 45.0
            )
        ):
            self._append_event(
                {
                    "kind": "gateway_latency_spike",
                    "title": "Gateway latency spike",
                    "detail": f"Gateway latency climbed to about {int(round(float(gateway_latency)))} ms.",
                    "severity": "attention",
                }
            )
        external_probes = current.get("external_probes", []) if isinstance(current.get("external_probes"), list) else []
        if external_probes and all(isinstance(item, dict) and item.get("timed_out") for item in external_probes):
            self._append_event({"kind": "external_unreachable", "title": "External path stalled", "detail": "Every recent external probe timed out.", "severity": "warning"})
        if external_probes:
            timeout_count = sum(1 for item in external_probes if isinstance(item, dict) and item.get("timed_out"))
            if timeout_count:
                self._append_event(
                    {
                        "kind": "external_packet_loss_burst",
                        "title": "Packet-loss burst",
                        "detail": f"External probes lost {timeout_count} of {len(external_probes)} recent samples.",
                        "severity": "warning",
                    }
                )
            latencies = [float(item.get("latency_ms")) for item in external_probes if isinstance(item, dict) and item.get("latency_ms") is not None]
            previous_probes = previous.get("external_probes", []) if isinstance(previous, dict) and isinstance(previous.get("external_probes"), list) else []
            previous_latencies = [float(item.get("latency_ms")) for item in previous_probes if isinstance(item, dict) and item.get("latency_ms") is not None]
            if latencies:
                current_external_latency = sum(latencies) / len(latencies)
                previous_external_latency = sum(previous_latencies) / len(previous_latencies) if previous_latencies else None
                if current_external_latency >= 160.0 or (
                    previous_external_latency is not None and previous_external_latency < 130.0 and (current_external_latency - previous_external_latency) >= 45.0
                ):
                    self._append_event(
                        {
                            "kind": "external_latency_spike",
                            "title": "External latency spike",
                            "detail": f"External latency jumped to about {int(round(current_external_latency))} ms.",
                            "severity": "attention",
                        }
                    )
        dns = current.get("dns", {}) if isinstance(current.get("dns"), dict) else {}
        if dns.get("failed"):
            self._append_event({"kind": "dns_failure_burst", "title": "DNS failure burst", "detail": "Recent DNS resolution did not complete cleanly.", "severity": "warning"})
        if previous_bssid and current_bssid and previous_bssid != current_bssid and (
            gateway_probe.get("timed_out")
            or (external_probes and all(isinstance(item, dict) and item.get("timed_out") for item in external_probes))
            or not current_up
        ):
            self._append_event(
                {
                    "kind": "roam_linked_outage",
                    "title": "Roam-linked outage",
                    "detail": "The interruption lines up with an access-point handoff.",
                    "severity": "attention",
                }
            )

    def _append_event(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("recorded_at", datetime.now().astimezone().isoformat())
        with self._lock:
            if self._event_log and self._event_log[-1].get("kind") == payload.get("kind"):
                return
            self._event_log.append(payload)
            self._persist_history_locked()
        if self._events is not None:
            self._events.publish(
                event_family="network",
                event_type=f"network.{str(payload.get('kind') or 'signal').strip().lower()}",
                severity="warning" if str(payload.get("severity", "")).lower() == "warning" else "info",
                subsystem="network",
                subject=str(payload.get("kind") or "network_signal"),
                visibility_scope="systems_surface",
                retention_class="operator_relevant",
                provenance={
                    "channel": "network_monitor",
                    "kind": "subsystem_interpretation",
                    "detail": "Derived from local probe history and bounded network monitoring.",
                },
                message=str(payload.get("title") or "Network event"),
                payload=payload,
            )

    def _summarize(
        self,
        samples: list[dict[str, Any]],
        events: list[dict[str, Any]],
        *,
        diagnostic_until: float,
        last_sample_at: float,
    ) -> dict[str, Any]:
        latest = samples[-1] if samples else {}
        interfaces = latest.get("interfaces", []) if isinstance(latest.get("interfaces"), list) else []
        primary = latest.get("primary_interface", {}) if isinstance(latest.get("primary_interface"), dict) else {}
        last_sample_age_seconds = int(max(time.monotonic() - last_sample_at, 0)) if last_sample_at else None
        gateway_latencies = [float(item["gateway_probe"]["latency_ms"]) for item in samples if isinstance(item.get("gateway_probe"), dict) and item["gateway_probe"].get("latency_ms") is not None]
        gateway_losses = [1.0 for item in samples if isinstance(item.get("gateway_probe"), dict) and item["gateway_probe"].get("timed_out")]
        external_latencies: list[float] = []
        external_losses = 0
        trend_points: list[dict[str, Any]] = []
        for item in samples[-18:]:
            probes = item.get("external_probes", []) if isinstance(item.get("external_probes"), list) else []
            latencies = [float(probe["latency_ms"]) for probe in probes if isinstance(probe, dict) and probe.get("latency_ms") is not None]
            timeout_count = sum(1 for probe in probes if isinstance(probe, dict) and probe.get("timed_out"))
            if latencies:
                external_latencies.append(sum(latencies) / len(latencies))
            external_losses += timeout_count
            gateway_probe = item.get("gateway_probe", {}) if isinstance(item.get("gateway_probe"), dict) else {}
            trend_points.append(
                {
                    "latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
                    "gateway_latency_ms": gateway_probe.get("latency_ms"),
                    "packet_loss_pct": round((timeout_count / max(len(probes), 1)) * 100.0, 1) if probes else None,
                    "jitter_ms": None,
                }
            )

        dns_items = [item.get("dns", {}) for item in samples if isinstance(item.get("dns"), dict)]
        dns_latencies = [float(item["latency_ms"]) for item in dns_items if item.get("latency_ms") is not None]
        dns_failures = sum(1 for item in dns_items if item.get("failed"))

        gateway_latency = round(sum(gateway_latencies) / len(gateway_latencies), 1) if gateway_latencies else None
        external_latency = round(sum(external_latencies) / len(external_latencies), 1) if external_latencies else None
        gateway_jitter = round(_mean_abs_delta(gateway_latencies), 1) if len(gateway_latencies) > 1 else None
        external_jitter = round(_mean_abs_delta(external_latencies), 1) if len(external_latencies) > 1 else None
        gateway_loss_pct = round((sum(gateway_losses) / max(len(samples), 1)) * 100.0, 1) if samples else None
        external_probe_count = sum(len(item.get("external_probes", [])) for item in samples if isinstance(item.get("external_probes"), list))
        external_loss_pct = round((external_losses / max(external_probe_count, 1)) * 100.0, 1) if external_probe_count else None
        latest_provider = latest.get("providers", {}) if isinstance(latest.get("providers"), dict) else {}
        provider_state = latest_provider.get("cloudflare_quality") if isinstance(latest_provider, dict) else self._cloudflare_provider.capability_state()
        if not isinstance(provider_state, dict):
            provider_state = self._cloudflare_provider.capability_state()
        provider_state = self._provider_with_comparison(
            provider_state,
            external_latency_ms=external_latency,
            external_jitter_ms=external_jitter,
            external_loss_pct=external_loss_pct,
        )
        throughput = self._throughput_provider.summarize(samples, last_sample_age_seconds=last_sample_age_seconds)
        local_provider = self._local_provider_state(primary, last_sample_age_seconds=last_sample_age_seconds)
        upstream_provider = self._upstream_provider_state(
            latest=latest,
            external_latency_ms=external_latency,
            external_jitter_ms=external_jitter,
            external_loss_pct=external_loss_pct,
            last_sample_age_seconds=last_sample_age_seconds,
        )

        quality = {
            "latency_ms": external_latency if external_latency is not None else gateway_latency,
            "gateway_latency_ms": gateway_latency,
            "external_latency_ms": external_latency,
            "jitter_ms": external_jitter if external_jitter is not None else gateway_jitter,
            "gateway_jitter_ms": gateway_jitter,
            "external_jitter_ms": external_jitter,
            "packet_loss_pct": external_loss_pct if external_loss_pct is not None else gateway_loss_pct,
            "gateway_packet_loss_pct": gateway_loss_pct,
            "external_packet_loss_pct": external_loss_pct,
            "signal_strength_dbm": primary.get("signal_strength_dbm"),
            "signal_quality_pct": primary.get("signal_quality_pct"),
            "connected": str(primary.get("status", "")).strip().lower() == "up",
            "source_precedence": ["local_link", "upstream_external", "cloudflare_quality_enrichment"],
            "source_status": {
                "local_link_available": bool(local_provider.get("available")),
                "upstream_available": bool(upstream_provider.get("available")),
                "cloudflare_available": bool(provider_state.get("available")),
            },
        }

        return {
            "hostname": latest.get("hostname") or "",
            "fqdn": latest.get("fqdn") or "",
            "interfaces": interfaces,
            "monitoring": {
                "history_ready": len(samples) >= 3,
                "sample_count": len(samples),
                "diagnostic_burst_active": diagnostic_until > time.monotonic(),
                "last_sample_age_seconds": last_sample_age_seconds,
            },
            "quality": quality,
            "throughput": throughput,
            "dns": {
                "latency_ms": round(sum(dns_latencies) / len(dns_latencies), 1) if dns_latencies else None,
                "failures": dns_failures,
            },
            "events": [_with_age(event) for event in events][-6:],
            "trend_points": trend_points,
            "providers": {
                "local_status": local_provider,
                "upstream_path": upstream_provider,
                "observed_throughput": {
                    "state": throughput.get("state"),
                    "label": throughput.get("label"),
                    "detail": throughput.get("detail"),
                "available": throughput.get("available"),
                "source": throughput.get("source"),
                "sampled_at": throughput.get("sampled_at"),
                "last_sample_age_seconds": throughput.get("last_sample_age_seconds"),
                "unsupported_code": throughput.get("unsupported_code"),
                "unsupported_reason": throughput.get("unsupported_reason"),
            },
                "cloudflare_quality": provider_state,
            },
            "source_debug": {
                "status_primary": "local_status",
                "diagnosis_inputs": ["local_status", "upstream_path", "cloudflare_quality"],
                "throughput_primary": str(throughput.get("source") or "net_adapter_statistics"),
            },
        }

    def _provider_with_comparison(
        self,
        provider_state: dict[str, Any],
        *,
        external_latency_ms: float | None,
        external_jitter_ms: float | None,
        external_loss_pct: float | None,
    ) -> dict[str, Any]:
        enriched = dict(provider_state)
        latency = _float_or_none(enriched.get("latency_ms"))
        jitter = _float_or_none(enriched.get("jitter_ms"))
        loss = _float_or_none(enriched.get("packet_loss_pct"))
        comparison_parts: list[str] = []
        if latency is not None and external_latency_ms is not None:
            delta = round(latency - external_latency_ms, 1)
            comparison_parts.append(
                "Cloudflare latency aligns with Stormhelm's external probes."
                if abs(delta) <= 15
                else f"Cloudflare latency is about {abs(int(round(delta)))} ms {'higher' if delta > 0 else 'lower'} than Stormhelm's external probes."
            )
        if jitter is not None and external_jitter_ms is not None:
            comparison_parts.append(f"Cloudflare jitter is about {int(round(jitter))} ms versus {int(round(external_jitter_ms))} ms on Stormhelm's external probes.")
        if loss is not None and external_loss_pct is not None:
            comparison_parts.append(f"Cloudflare loss is {loss:.1f}% versus {external_loss_pct:.1f}% on Stormhelm's external probes.")
        if comparison_parts:
            enriched["comparison_summary"] = " ".join(comparison_parts)
        else:
            enriched.setdefault("comparison_summary", "Stormhelm does not have enough external quality evidence to compare yet.")
        enriched["comparison_ready"] = bool(comparison_parts) or bool(enriched.get("comparison_ready"))
        return enriched

    def _local_provider_state(self, primary: dict[str, Any], *, last_sample_age_seconds: int | None) -> dict[str, Any]:
        if not primary:
            return {
                "state": "no_active_interface",
                "label": "Local link telemetry",
                "detail": "No active interface is being reported right now.",
                "available": False,
                "source": "net_ip_configuration",
                "last_sample_age_seconds": last_sample_age_seconds,
            }
        gateway = primary.get("gateway", []) if isinstance(primary.get("gateway"), list) else []
        dns_servers = primary.get("dns_servers", []) if isinstance(primary.get("dns_servers"), list) else []
        detail_parts = [str(primary.get("profile") or primary.get("ssid") or primary.get("interface_alias") or "Active interface").strip()]
        if gateway:
            detail_parts.append(f"gateway {gateway[0]}")
        if dns_servers:
            detail_parts.append(f"DNS {', '.join(str(item) for item in dns_servers[:2])}")
        signal_quality = primary.get("signal_quality_pct")
        if signal_quality is not None:
            detail_parts.append(f"signal {int(round(float(signal_quality)))}%")
        return {
            "state": "ready",
            "label": "Local link telemetry",
            "detail": " · ".join(part for part in detail_parts if part),
            "available": True,
            "source": "net_ip_configuration",
            "interface_alias": primary.get("interface_alias"),
            "profile": primary.get("ssid") or primary.get("profile"),
            "gateway": gateway,
            "dns_servers": dns_servers,
            "signal_quality_pct": signal_quality,
            "last_sample_age_seconds": last_sample_age_seconds,
        }

    def _upstream_provider_state(
        self,
        *,
        latest: dict[str, Any],
        external_latency_ms: float | None,
        external_jitter_ms: float | None,
        external_loss_pct: float | None,
        last_sample_age_seconds: int | None,
    ) -> dict[str, Any]:
        probes = latest.get("external_probes", []) if isinstance(latest.get("external_probes"), list) else []
        targets = [str(probe.get("target") or "").strip() for probe in probes if isinstance(probe, dict) and str(probe.get("target") or "").strip()]
        if not probes:
            return {
                "state": "no_external_probe_data",
                "label": "Upstream path probes",
                "detail": "Stormhelm does not have current external probe data yet.",
                "available": False,
                "source": "icmp_external_probes",
                "last_sample_age_seconds": last_sample_age_seconds,
            }
        detail_parts: list[str] = []
        if external_latency_ms is not None:
            detail_parts.append(f"latency {int(round(external_latency_ms))} ms")
        if external_jitter_ms is not None:
            detail_parts.append(f"jitter {int(round(external_jitter_ms))} ms")
        if external_loss_pct is not None:
            detail_parts.append(f"loss {external_loss_pct:.1f}%")
        if targets:
            detail_parts.append("targets " + ", ".join(targets[:2]))
        return {
            "state": "ready",
            "label": "Upstream path probes",
            "detail": " · ".join(detail_parts) if detail_parts else "External targets responded to the latest probes.",
            "available": True,
            "source": "icmp_external_probes",
            "latency_ms": external_latency_ms,
            "jitter_ms": external_jitter_ms,
            "packet_loss_pct": external_loss_pct,
            "targets": targets,
            "last_sample_age_seconds": last_sample_age_seconds,
        }

    def _load_persisted_history(self) -> None:
        if self._history_path is None or not self._history_path.exists():
            return
        try:
            payload = json.loads(self._history_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        history = payload.get("history", [])
        events = payload.get("events", [])
        if isinstance(history, list):
            for item in history[-self._history.maxlen :]:
                if isinstance(item, dict):
                    self._history.append(item)
        if isinstance(events, list):
            for item in events[-self._event_log.maxlen :]:
                if isinstance(item, dict):
                    self._event_log.append(item)

    def _persist_history_locked(self) -> None:
        if self._history_path is None:
            return
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "history": list(self._history),
                "events": list(self._event_log),
            }
            self._history_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Could not persist network monitor history.")


def _mean_abs_delta(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    deltas = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
    return sum(deltas) / len(deltas)


def _with_age(event: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(event)
    recorded_at = str(enriched.get("recorded_at") or "").strip()
    if not recorded_at:
        return enriched
    try:
        moment = datetime.fromisoformat(recorded_at)
        enriched["seconds_ago"] = max(int((datetime.now(moment.tzinfo or datetime.now().astimezone().tzinfo) - moment).total_seconds()), 0)
    except ValueError:
        pass
    return enriched


def _float_or_none(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
