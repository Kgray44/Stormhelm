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
        fragments.append(str(analysis.get("summary") or "").strip())

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
        primary = self._primary_interface(telemetry)
        monitoring = telemetry.get("monitoring", {}) if isinstance(telemetry.get("monitoring"), dict) else {}
        if not primary:
            return "No active network interface is up right now."

        alias = str(primary.get("interface_alias") or "the active interface").strip()
        profile = str(primary.get("ssid") or primary.get("profile") or "").strip()
        connected = str(primary.get("status", "")).strip().lower() == "up"
        ipv4 = self._first_text(primary.get("ipv4"))
        gateway = self._first_text(primary.get("gateway"))
        dns_servers = self._string_list(primary.get("dns_servers"))
        signal = self._signal_label(telemetry, primary)
        refresh = self._age_label(monitoring.get("last_sample_age_seconds"))

        if focus == "ip":
            if not connected:
                return f"{alias} is not connected right now, so there is no current local IP to report."
            parts = [f"Local IP is {ipv4}." if ipv4 else f"{alias} is connected, but the local IP is not exposed cleanly right now."]
            if gateway:
                parts.append(f"Gateway is {gateway}.")
            if dns_servers:
                parts.append("DNS is " + ", ".join(dns_servers[:2]) + ".")
            if refresh:
                parts.append(f"Status refreshed {refresh}.")
            return " ".join(parts).strip()

        if focus == "signal":
            if signal:
                return f"{alias} signal is {signal}."
            return f"{alias} is connected, but the current signal reading is not exposed on this interface."

        parts: list[str] = []
        if connected:
            connection = f"Connected on {alias}"
            if profile:
                connection += f" via {profile}"
            parts.append(connection + ".")
        else:
            parts.append(f"{alias} is currently disconnected.")

        if ipv4:
            parts.append(f"Local IP is {ipv4}.")
        if gateway:
            parts.append(f"Gateway is {gateway}.")
        if dns_servers:
            parts.append("DNS is " + ", ".join(dns_servers[:2]) + ".")
        if signal:
            parts.append(f"Signal is {signal}.")
        if refresh:
            parts.append(f"Status refreshed {refresh}.")
        return " ".join(parts).strip()

    def format_throughput_response(self, measurement: dict[str, Any]) -> str:
        metric = str(measurement.get("metric") or "internet_speed").strip().lower() or "internet_speed"
        if not measurement.get("available"):
            detail = str(measurement.get("unsupported_reason") or measurement.get("detail") or "Current throughput is unavailable.").strip()
            return detail

        interface = self._primary_interface(measurement)
        alias = str((interface or {}).get("interface_alias") or measurement.get("interface_alias") or "the active interface").strip()
        profile = str((interface or {}).get("ssid") or (interface or {}).get("profile") or measurement.get("profile") or "").strip()
        window_seconds = measurement.get("sample_window_seconds")
        freshness = self._age_label(measurement.get("last_sample_age_seconds"))
        stale = bool(measurement.get("stale"))

        if metric == "download_speed":
            speed = self._rate(measurement.get("download_mbps"))
            if speed:
                summary = f"Current download speed is {speed}"
            else:
                summary = str(measurement.get("unsupported_reason") or "Current download speed is unavailable.").strip()
                return summary
        elif metric == "upload_speed":
            speed = self._rate(measurement.get("upload_mbps"))
            if speed:
                summary = f"Current upload speed is {speed}"
            else:
                summary = str(measurement.get("unsupported_reason") or "Current upload speed is unavailable.").strip()
                return summary
        else:
            download = self._rate(measurement.get("download_mbps"))
            upload = self._rate(measurement.get("upload_mbps"))
            if download and upload:
                summary = f"Current observed throughput is {download} down and {upload} up"
            elif download:
                summary = f"Current observed download speed is {download}"
            elif upload:
                summary = f"Current observed upload speed is {upload}"
            else:
                summary = str(measurement.get("unsupported_reason") or "Current throughput is unavailable.").strip()
                return summary

        suffix_parts: list[str] = []
        if profile:
            suffix_parts.append(f"on {alias} via {profile}")
        elif alias:
            suffix_parts.append(f"on {alias}")
        if isinstance(window_seconds, (int, float)) and float(window_seconds) > 0:
            suffix_parts.append(f"over the last {float(window_seconds):.1f} seconds")
        if freshness:
            suffix_parts.append(f"sampled {freshness}")
        if stale:
            suffix_parts.append("so it may already be stale")
        detail = ". " + ", ".join(suffix_parts) if suffix_parts else "."
        return summary + detail

    def _primary_interface(self, telemetry: dict[str, Any]) -> dict[str, Any]:
        interfaces = telemetry.get("interfaces", []) if isinstance(telemetry.get("interfaces"), list) else []
        return interfaces[0] if interfaces and isinstance(interfaces[0], dict) else {}

    def _signal_label(self, telemetry: dict[str, Any], primary: dict[str, Any]) -> str | None:
        quality = telemetry.get("quality", {}) if isinstance(telemetry.get("quality"), dict) else {}
        if isinstance(quality.get("signal_strength_dbm"), (int, float)):
            return f"{int(round(float(quality['signal_strength_dbm'])))} dBm"
        if isinstance(quality.get("signal_quality_pct"), (int, float)):
            return f"{int(round(float(quality['signal_quality_pct'])))}%"
        if isinstance(primary.get("signal_quality_pct"), (int, float)):
            return f"{int(round(float(primary['signal_quality_pct'])))}%"
        return None

    def _age_label(self, seconds: object) -> str | None:
        try:
            if seconds in {None, ""}:
                return None
            value = int(round(float(seconds)))
        except (TypeError, ValueError):
            return None
        if value <= 5:
            return "just now"
        if value < 60:
            return f"{value} seconds ago"
        minutes = max(int(round(value / 60.0)), 1)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"

    def _first_text(self, value: object) -> str:
        if isinstance(value, list):
            for item in value:
                text = str(item or "").strip()
                if text:
                    return text
            return ""
        return str(value or "").strip()

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _rate(self, value: object) -> str | None:
        try:
            if value in {None, ""}:
                return None
            return f"{float(value):.2f} Mbps"
        except (TypeError, ValueError):
            return None

    def _metric(self, value: object, unit: str) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "unknown"
        if unit == "%":
            return f"{number:.1f}{unit}"
        return f"{int(round(number))} {unit}"
