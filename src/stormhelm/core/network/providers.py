from __future__ import annotations

import time
import urllib.request
from typing import Any


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
