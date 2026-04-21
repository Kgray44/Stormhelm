from __future__ import annotations

from datetime import datetime
import time
import urllib.request
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from stormhelm.core.system.probe import SystemProbe


class CloudflareQualityProvider:
    def __init__(self, *, enabled: bool = True, timeout_seconds: float = 2.5, sample_count: int = 3) -> None:
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.sample_count = max(int(sample_count), 1)
        self._last_sample: dict[str, Any] | None = None

    def capability_state(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "state": "not_configured",
                "label": "Cloudflare quality",
                "detail": "Cloudflare-quality enrichment is disabled.",
                "available": False,
            }
        if self._last_sample is None:
            return {
                "state": "waiting_for_sample",
                "label": "Cloudflare quality",
                "detail": "Waiting for an external quality sample.",
                "available": True,
            }
        sample = dict(self._last_sample)
        sample.setdefault("label", "Cloudflare quality")
        sample.setdefault("available", True)
        return sample

    def sample(self) -> dict[str, Any]:
        if not self.enabled:
            return self.capability_state()
        measurements = [self._request_latency_sample() for _ in range(self.sample_count)]
        successful = [value for value in measurements if isinstance(value, (int, float))]
        sampled_at = time.time()
        if not successful:
            self._last_sample = {
                "state": "partial",
                "label": "Cloudflare quality",
                "detail": "Cloudflare-quality enrichment is available in principle, but the latest quality sample did not complete.",
                "available": True,
                "sample_count": self.sample_count,
                "successful_samples": 0,
                "packet_loss_pct": 100.0,
                "comparison_ready": False,
                "sampled_at": sampled_at,
            }
            return dict(self._last_sample)

        latency_ms = round(sum(float(value) for value in successful) / len(successful), 1)
        jitter_ms = 0.0
        if len(successful) > 1:
            deltas = [abs(float(successful[index]) - float(successful[index - 1])) for index in range(1, len(successful))]
            jitter_ms = round(sum(deltas) / len(deltas), 1)
        packet_loss_pct = round(((self.sample_count - len(successful)) / max(self.sample_count, 1)) * 100.0, 1)
        min_latency = round(min(float(value) for value in successful), 1)
        max_latency = round(max(float(value) for value in successful), 1)
        state = "ready" if len(successful) >= max(2, min(self.sample_count, 3)) else "partial"
        detail = (
            f"Cloudflare-quality sample refreshed around {int(round(latency_ms))} ms with about {int(round(jitter_ms))} ms jitter."
            if state == "ready"
            else f"Cloudflare-quality sample refreshed around {int(round(latency_ms))} ms, but evidence is still partial."
        )
        self._last_sample = {
            "state": state,
            "label": "Cloudflare quality",
            "detail": detail,
            "available": True,
            "latency_ms": latency_ms,
            "idle_latency_ms": latency_ms,
            "jitter_ms": jitter_ms,
            "packet_loss_pct": packet_loss_pct,
            "min_latency_ms": min_latency,
            "max_latency_ms": max_latency,
            "sample_count": self.sample_count,
            "successful_samples": len(successful),
            "comparison_ready": len(successful) >= 2,
            "sampled_at": sampled_at,
        }
        return dict(self._last_sample)

    def _request_latency_sample(self) -> float | None:
        started = time.monotonic()
        try:
            with urllib.request.urlopen("https://www.cloudflare.com/cdn-cgi/trace", timeout=self.timeout_seconds) as response:
                response.read(512)
            return round((time.monotonic() - started) * 1000, 1)
        except Exception:
            return None


class ObservedThroughputProvider:
    def __init__(self, probe: SystemProbe) -> None:
        self._probe = probe

    def capture_sample(self, *, primary_interface: dict[str, Any], captured_at: str) -> dict[str, Any]:
        alias = str(primary_interface.get("interface_alias") or "").strip()
        profile = str(primary_interface.get("ssid") or primary_interface.get("profile") or "").strip() or None
        if not alias:
            return self._unsupported(
                code="no_active_interface",
                detail="No active interface is up right now, so Stormhelm cannot sample throughput.",
                captured_at=captured_at,
                interface_alias=None,
                profile=profile,
            )

        counter = self._matching_counter(alias)
        if not isinstance(counter, dict):
            return self._unsupported(
                code="counters_unavailable",
                detail="Windows did not expose adapter byte counters for the active interface.",
                captured_at=captured_at,
                interface_alias=alias,
                profile=profile,
            )

        received_bytes = _int_or_none(counter.get("received_bytes"))
        sent_bytes = _int_or_none(counter.get("sent_bytes"))
        if received_bytes is None or sent_bytes is None:
            return self._unsupported(
                code="counter_values_missing",
                detail="The active adapter exposed statistics, but the byte counters were incomplete.",
                captured_at=captured_at,
                interface_alias=alias,
                profile=profile,
            )

        return {
            "state": "sampled",
            "label": "Observed throughput",
            "detail": "Captured adapter byte counters on the active interface.",
            "available": True,
            "source": "net_adapter_statistics",
            "interface_alias": alias,
            "profile": profile,
            "received_bytes": received_bytes,
            "sent_bytes": sent_bytes,
            "receive_link_mbps": _float_or_none(primary_interface.get("receive_rate_mbps")),
            "transmit_link_mbps": _float_or_none(primary_interface.get("transmit_rate_mbps")),
            "sampled_at": captured_at,
            "unsupported_reason": None,
        }

    def measure_current(
        self,
        *,
        primary_interface: dict[str, Any],
        sample_window_seconds: float = 1.0,
    ) -> dict[str, Any]:
        captured_at = datetime.now().astimezone().isoformat()
        baseline = self.capture_sample(primary_interface=primary_interface, captured_at=captured_at)
        if not baseline.get("available"):
            return self._unsupported_summary(
                sample=baseline,
                last_sample_age_seconds=0.0,
            )

        wait_seconds = max(float(sample_window_seconds), 0.5)
        time.sleep(wait_seconds)
        follow_up = self.capture_sample(
            primary_interface=primary_interface,
            captured_at=datetime.now().astimezone().isoformat(),
        )
        if not follow_up.get("available"):
            return self._unsupported_summary(
                sample=follow_up,
                last_sample_age_seconds=0.0,
            )

        return self._rate_from_samples(
            previous=baseline,
            latest=follow_up,
            last_sample_age_seconds=0.0,
        )

    def summarize(self, samples: list[dict[str, Any]], *, last_sample_age_seconds: float | None) -> dict[str, Any]:
        throughput_samples = [
            item.get("throughput_sample")
            for item in samples
            if isinstance(item, dict) and isinstance(item.get("throughput_sample"), dict)
        ]
        latest = throughput_samples[-1] if throughput_samples else None
        if not isinstance(latest, dict):
            return {
                "state": "provider_unavailable",
                "available": False,
                "label": "Observed throughput",
                "detail": "Stormhelm does not have a throughput sample yet.",
                "source": "net_adapter_statistics",
                "unsupported_code": "provider_unavailable",
                "unsupported_reason": "Stormhelm does not have a throughput sample yet.",
            }

        if not latest.get("available"):
            return self._unsupported_summary(
                sample=latest,
                last_sample_age_seconds=last_sample_age_seconds,
            )

        previous: dict[str, Any] | None = None
        latest_alias = str(latest.get("interface_alias") or "").strip().lower()
        for candidate in reversed(throughput_samples[:-1]):
            if not isinstance(candidate, dict) or not candidate.get("available"):
                continue
            candidate_alias = str(candidate.get("interface_alias") or "").strip().lower()
            if candidate_alias == latest_alias:
                previous = candidate
                break

        if previous is None:
            return {
                "state": "waiting_for_baseline",
                "available": False,
                "label": "Observed throughput",
                "detail": "Stormhelm needs one more adapter-counter sample before it can calculate a current transfer rate.",
                "source": "net_adapter_statistics",
                "interface_alias": latest.get("interface_alias"),
                "profile": latest.get("profile"),
                "sampled_at": latest.get("sampled_at"),
                "last_sample_age_seconds": last_sample_age_seconds,
                "receive_link_mbps": latest.get("receive_link_mbps"),
                "transmit_link_mbps": latest.get("transmit_link_mbps"),
                "unsupported_code": "waiting_for_baseline",
                "unsupported_reason": "Stormhelm needs one more adapter-counter sample before it can calculate a current transfer rate.",
            }

        return self._rate_from_samples(
            previous=previous,
            latest=latest,
            last_sample_age_seconds=last_sample_age_seconds,
        )

    def _rate_from_samples(
        self,
        *,
        previous: dict[str, Any],
        latest: dict[str, Any],
        last_sample_age_seconds: float | None,
    ) -> dict[str, Any]:
        latest_moment = _parse_iso_timestamp(latest.get("sampled_at"))
        previous_moment = _parse_iso_timestamp(previous.get("sampled_at"))
        elapsed_seconds = (
            (latest_moment - previous_moment).total_seconds()
            if latest_moment is not None and previous_moment is not None
            else None
        )
        if elapsed_seconds is None or elapsed_seconds <= 0.5:
            return {
                "state": "interval_too_short",
                "available": False,
                "label": "Observed throughput",
                "detail": "The throughput sample window was too short to calculate a stable rate.",
                "source": "net_adapter_statistics",
                "interface_alias": latest.get("interface_alias"),
                "profile": latest.get("profile"),
                "sampled_at": latest.get("sampled_at"),
                "last_sample_age_seconds": last_sample_age_seconds,
                "receive_link_mbps": latest.get("receive_link_mbps"),
                "transmit_link_mbps": latest.get("transmit_link_mbps"),
                "unsupported_code": "interval_too_short",
                "unsupported_reason": "The throughput sample window was too short to calculate a stable rate.",
            }

        received_delta = _int_or_none(latest.get("received_bytes"))
        previous_received = _int_or_none(previous.get("received_bytes"))
        sent_delta = _int_or_none(latest.get("sent_bytes"))
        previous_sent = _int_or_none(previous.get("sent_bytes"))
        if (
            received_delta is None
            or previous_received is None
            or sent_delta is None
            or previous_sent is None
            or received_delta < previous_received
            or sent_delta < previous_sent
        ):
            return {
                "state": "counter_reset",
                "available": False,
                "label": "Observed throughput",
                "detail": "Adapter byte counters reset before Stormhelm could form a stable throughput sample.",
                "source": "net_adapter_statistics",
                "interface_alias": latest.get("interface_alias"),
                "profile": latest.get("profile"),
                "sampled_at": latest.get("sampled_at"),
                "last_sample_age_seconds": last_sample_age_seconds,
                "receive_link_mbps": latest.get("receive_link_mbps"),
                "transmit_link_mbps": latest.get("transmit_link_mbps"),
                "unsupported_code": "counter_reset",
                "unsupported_reason": "Adapter byte counters reset before Stormhelm could form a stable throughput sample.",
            }

        download_mbps = round(((received_delta - previous_received) * 8.0) / (elapsed_seconds * 1_000_000.0), 2)
        upload_mbps = round(((sent_delta - previous_sent) * 8.0) / (elapsed_seconds * 1_000_000.0), 2)
        stale = last_sample_age_seconds is not None and float(last_sample_age_seconds) > 30.0
        state = "stale" if stale else "ready"
        detail = (
            f"Observed over the last {int(round(elapsed_seconds))} seconds on {latest.get('interface_alias') or 'the active interface'}."
        )
        return {
            "state": state,
            "available": True,
            "current": not stale,
            "stale": stale,
            "label": "Observed throughput",
            "detail": detail,
            "sample_kind": "observed_transfer",
            "source": "net_adapter_statistics",
            "interface_alias": latest.get("interface_alias"),
            "profile": latest.get("profile"),
            "download_mbps": download_mbps,
            "upload_mbps": upload_mbps,
            "sample_window_seconds": round(elapsed_seconds, 1),
            "sampled_at": latest.get("sampled_at"),
            "last_sample_age_seconds": last_sample_age_seconds,
            "receive_link_mbps": latest.get("receive_link_mbps"),
            "transmit_link_mbps": latest.get("transmit_link_mbps"),
            "unsupported_code": None,
            "unsupported_reason": None,
        }

    def _matching_counter(self, alias: str) -> dict[str, Any] | None:
        normalized_alias = alias.strip().lower()
        counters = self._probe._network_interface_counters()
        for counter in counters:
            if not isinstance(counter, dict):
                continue
            counter_alias = str(counter.get("interface_alias") or "").strip().lower()
            if counter_alias == normalized_alias:
                return dict(counter)
        return None

    def _unsupported(
        self,
        *,
        code: str,
        detail: str,
        captured_at: str,
        interface_alias: str | None,
        profile: str | None,
    ) -> dict[str, Any]:
        return {
            "state": code,
            "label": "Observed throughput",
            "detail": detail,
            "available": False,
            "source": "net_adapter_statistics",
            "interface_alias": interface_alias,
            "profile": profile,
            "sampled_at": captured_at,
            "unsupported_code": code,
            "unsupported_reason": detail,
        }

    def _unsupported_summary(
        self,
        *,
        sample: dict[str, Any],
        last_sample_age_seconds: float | None,
    ) -> dict[str, Any]:
        detail = str(sample.get("detail") or "Observed throughput is unavailable.").strip()
        return {
            "state": str(sample.get("state") or "unavailable").strip() or "unavailable",
            "available": False,
            "label": str(sample.get("label") or "Observed throughput").strip() or "Observed throughput",
            "detail": detail,
            "source": str(sample.get("source") or "net_adapter_statistics").strip() or "net_adapter_statistics",
            "interface_alias": sample.get("interface_alias"),
            "profile": sample.get("profile"),
            "sampled_at": sample.get("sampled_at"),
            "last_sample_age_seconds": last_sample_age_seconds,
            "receive_link_mbps": sample.get("receive_link_mbps"),
            "transmit_link_mbps": sample.get("transmit_link_mbps"),
            "unsupported_code": str(sample.get("unsupported_code") or sample.get("state") or "unavailable").strip() or "unavailable",
            "unsupported_reason": detail,
        }


def _parse_iso_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _float_or_none(value: object) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        if value in {None, ""}:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
