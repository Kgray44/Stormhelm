from __future__ import annotations

from typing import Any


class NetworkResponseFormatter:
    def format_diagnostic_response(self, analysis: dict[str, Any], telemetry: dict[str, Any]) -> str:
        quality = telemetry.get("quality", {}) if isinstance(telemetry.get("quality"), dict) else {}
        monitoring = telemetry.get("monitoring", {}) if isinstance(telemetry.get("monitoring"), dict) else {}
        fragments: list[str] = []
        headline = str(analysis.get("headline") or "").strip()
        if headline:
            fragments.append(headline + ".")

        gateway_latency = quality.get("gateway_latency_ms")
        external_latency = quality.get("external_latency_ms")
        jitter = quality.get("jitter_ms")
        loss = quality.get("packet_loss_pct")

        observed: list[str] = []
        if gateway_latency is not None:
            observed.append(f"gateway latency is around {self._metric(gateway_latency, 'ms')}")
        if external_latency is not None:
            observed.append(f"external latency is around {self._metric(external_latency, 'ms')}")
        if jitter is not None:
            observed.append(f"jitter is about {self._metric(jitter, 'ms')}")
        if loss is not None:
            observed.append(f"packet loss is near {self._metric(loss, '%')}")

        if observed:
            fragments.append("Stormhelm observed " + ", ".join(observed) + ".")
        fragments.append(str(analysis.get("summary") or ""))

        confidence = str(analysis.get("confidence") or "").strip()
        sufficiency = str(analysis.get("evidence_sufficiency") or "").strip()
        if confidence:
            confidence_text = confidence.title()
            if sufficiency and sufficiency != "recent":
                confidence_text = f"{confidence_text} confidence while {sufficiency.replace('_', ' ')} evidence builds"
            else:
                confidence_text = f"{confidence_text} confidence"
            fragments.append(confidence_text + ".")

        next_checks = [str(item).strip() for item in analysis.get("next_checks", []) if str(item).strip()]
        if next_checks:
            fragments.append("Best next move: " + next_checks[0])

        if bool(monitoring.get("diagnostic_burst_active")):
            fragments.append("A short diagnostic sample is active.")

        return " ".join(fragment for fragment in fragments if fragment).strip()

    def format_status_response(self, telemetry: dict[str, Any], *, focus: str = "overview") -> str:
        interfaces = telemetry.get("interfaces", []) if isinstance(telemetry.get("interfaces"), list) else []
        if not interfaces:
            return "Network bearings are limited right now. No active interface is being reported."
        primary = interfaces[0] if isinstance(interfaces[0], dict) else {}
        alias = str(primary.get("interface_alias") or "the active interface").strip()
        profile = str(primary.get("profile") or "").strip()
        ipv4 = primary.get("ipv4", [])
        address = ipv4[0] if isinstance(ipv4, list) and ipv4 else ""
        if focus == "ip":
            return f"Connected on {alias}. Local address {address}." if address else f"Connected on {alias}, but the local address is not exposed cleanly right now."
        assessment = telemetry.get("assessment", {}) if isinstance(telemetry.get("assessment"), dict) else {}
        health = str(assessment.get("headline") or "Connected").strip()
        detail = f"Connected on {alias}"
        if profile:
            detail = f"{detail} via {profile}"
        if address:
            detail = f"{detail}. Local address {address}"
        if health and health.lower() != "stable":
            detail = f"{health}. {detail}"
        return detail + "."

    def _metric(self, value: object, unit: str) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "unknown"
        if unit == "%":
            return f"{number:.1f}{unit}"
        return f"{int(round(number))} {unit}"
