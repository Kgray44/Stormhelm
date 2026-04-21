from __future__ import annotations

from typing import Any


class NetworkAnalyzer:
    def analyze(self, telemetry: dict[str, Any]) -> dict[str, Any]:
        monitoring = telemetry.get("monitoring", {}) if isinstance(telemetry.get("monitoring"), dict) else {}
        quality = telemetry.get("quality", {}) if isinstance(telemetry.get("quality"), dict) else {}
        dns = telemetry.get("dns", {}) if isinstance(telemetry.get("dns"), dict) else {}
        events = telemetry.get("events", []) if isinstance(telemetry.get("events"), list) else []

        history_ready = bool(monitoring.get("history_ready"))
        gateway_latency = _float_or_none(quality.get("gateway_latency_ms"))
        external_latency = _float_or_none(quality.get("external_latency_ms"))
        gateway_jitter = _float_or_none(quality.get("gateway_jitter_ms"))
        external_jitter = _float_or_none(quality.get("external_jitter_ms"))
        gateway_loss = _float_or_none(quality.get("gateway_packet_loss_pct"))
        external_loss = _float_or_none(quality.get("external_packet_loss_pct"))
        signal_dbm = _float_or_none(quality.get("signal_strength_dbm"))
        signal_pct = _float_or_none(quality.get("signal_quality_pct"))
        dns_latency = _float_or_none(dns.get("latency_ms"))
        dns_failures = int(dns.get("failures") or 0)

        event_kinds = {str(event.get("kind", "")).strip().lower() for event in events if isinstance(event, dict)}
        weak_signal = (signal_dbm is not None and signal_dbm <= -70) or (signal_pct is not None and signal_pct <= 45)
        local_evidence = (
            _meets(gateway_loss, 2.0)
            or _meets(gateway_latency, 80.0)
            or _meets(gateway_jitter, 18.0)
            or bool(event_kinds & {"gateway_packet_loss_burst", "gateway_latency_spike", "gateway_unreachable", "reconnect", "roam"})
        )
        external_evidence = (
            _meets(external_loss, 2.0)
            or _meets(external_latency, 120.0)
            or _meets(external_jitter, 22.0)
            or bool(event_kinds & {"external_packet_loss_burst", "external_latency_spike", "external_unreachable"})
        )
        dns_evidence = dns_failures >= 2 or _meets(dns_latency, 400.0) or "dns_failure_burst" in event_kinds
        roam_evidence = bool(event_kinds & {"roam", "ssid_change", "bssid_change", "reconnect", "roam_linked_outage"})

        if dns_evidence and not local_evidence and not external_evidence:
            return self._result(
                kind="dns_issue",
                headline="DNS issue suspected",
                summary="Transport looks steady, but DNS resolution is slow or failing.",
                confidence="moderate" if history_ready else "low",
                attribution="dns",
                evidence_sufficiency="recent" if history_ready else "gathering",
                next_checks=["Switch DNS servers or compare a direct IP test against normal host lookups."],
            )

        if local_evidence and (
            weak_signal
            or not external_evidence
            or _meets(gateway_loss, 2.0)
            or _meets(gateway_jitter, 18.0)
            or bool(event_kinds & {"gateway_packet_loss_burst", "gateway_latency_spike", "gateway_unreachable"})
            or _coalesce(gateway_loss, 0.0) >= _coalesce(external_loss, 0.0)
        ):
            return self._result(
                kind="local_link_issue",
                headline="Local Wi-Fi instability likely",
                summary="Recent gateway jitter and packet-loss bursts suggest the problem starts on the local link.",
                confidence="high" if history_ready and _meets(gateway_loss, 5.0) else "moderate",
                attribution="local_link",
                evidence_sufficiency="recent" if history_ready else "gathering",
                next_checks=["Stay on the current access point and compare again closer to the router.", "Check adapter power saving or interference."],
            )

        if external_evidence and not local_evidence:
            return self._result(
                kind="upstream_issue",
                headline="Upstream congestion likely",
                summary="The gateway looks steady, but external latency, jitter, or loss is degrading farther upstream.",
                confidence="high" if history_ready else "moderate",
                attribution="upstream",
                evidence_sufficiency="recent" if history_ready else "gathering",
                next_checks=["Compare another device on the same Wi-Fi and check whether the ISP path is degrading beyond the router."],
            )

        if roam_evidence:
            return self._result(
                kind="roam_or_ap_handoff",
                headline="Access point handoff likely",
                summary="Recent access-point or reconnect events line up with the interruption pattern.",
                confidence="moderate",
                attribution="local_link",
                evidence_sufficiency="recent" if history_ready else "gathering",
                next_checks=["Hold position near one access point and see whether the skips stop after roaming settles."],
            )

        if weak_signal:
            return self._result(
                kind="weak_signal_possible",
                headline="Weak signal possible",
                summary="Signal quality is running low enough to make local instability more likely.",
                confidence="moderate",
                attribution="local_link",
                evidence_sufficiency="recent" if history_ready else "gathering",
                next_checks=["Move closer to the access point or reduce interference and compare the gateway latency again."],
            )

        if history_ready and not local_evidence and not external_evidence and not dns_evidence:
            return self._result(
                kind="stable",
                headline="Stable",
                summary="Recent telemetry looks steady with no strong evidence of loss, jitter, or dropouts.",
                confidence="moderate",
                attribution="none",
                evidence_sufficiency="recent",
                next_checks=[],
            )

        return self._result(
            kind="insufficient_evidence",
            headline="Not enough evidence yet",
            summary="Stormhelm does not have enough recent quality history to explain the trouble confidently.",
            confidence="low",
            attribution="unclear",
            evidence_sufficiency="gathering",
            next_checks=["Let the network monitor run for a few minutes or trigger a short diagnostic burst."],
        )

    def _result(
        self,
        *,
        kind: str,
        headline: str,
        summary: str,
        confidence: str,
        attribution: str,
        evidence_sufficiency: str,
        next_checks: list[str],
    ) -> dict[str, Any]:
        return {
            "kind": kind,
            "headline": headline,
            "summary": summary,
            "confidence": confidence,
            "attribution": attribution,
            "evidence_sufficiency": evidence_sufficiency,
            "next_checks": next_checks[:2],
        }


def _float_or_none(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _meets(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _coalesce(value: float | None, fallback: float) -> float:
    return fallback if value is None else value
