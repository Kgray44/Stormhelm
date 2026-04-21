from __future__ import annotations

from stormhelm.core.network.analyzer import NetworkAnalyzer


def test_network_analyzer_flags_local_link_instability_when_gateway_and_external_degrade_together() -> None:
    analyzer = NetworkAnalyzer()

    analysis = analyzer.analyze(
        {
            "monitoring": {"history_ready": True},
            "quality": {
                "gateway_latency_ms": 78,
                "external_latency_ms": 91,
                "gateway_jitter_ms": 26,
                "external_jitter_ms": 29,
                "gateway_packet_loss_pct": 8.5,
                "external_packet_loss_pct": 9.2,
                "signal_strength_dbm": -69,
            },
            "dns": {"latency_ms": 28, "failures": 0},
            "events": [{"kind": "gateway_packet_loss_burst"}],
        }
    )

    assert analysis["kind"] == "local_link_issue"
    assert analysis["attribution"] == "local_link"
    assert analysis["confidence"] in {"moderate", "high"}


def test_network_analyzer_flags_upstream_instability_when_gateway_is_stable_but_external_path_degrades() -> None:
    analyzer = NetworkAnalyzer()

    analysis = analyzer.analyze(
        {
            "monitoring": {"history_ready": True},
            "quality": {
                "gateway_latency_ms": 8,
                "external_latency_ms": 142,
                "gateway_jitter_ms": 2,
                "external_jitter_ms": 33,
                "gateway_packet_loss_pct": 0.0,
                "external_packet_loss_pct": 4.8,
                "signal_strength_dbm": -55,
            },
            "dns": {"latency_ms": 18, "failures": 0},
            "events": [{"kind": "external_latency_spike"}],
        }
    )

    assert analysis["kind"] == "upstream_issue"
    assert analysis["attribution"] == "upstream"


def test_network_analyzer_flags_dns_issue_when_transport_is_stable_but_dns_is_failing() -> None:
    analyzer = NetworkAnalyzer()

    analysis = analyzer.analyze(
        {
            "monitoring": {"history_ready": True},
            "quality": {
                "gateway_latency_ms": 7,
                "external_latency_ms": 18,
                "gateway_jitter_ms": 1,
                "external_jitter_ms": 3,
                "gateway_packet_loss_pct": 0.0,
                "external_packet_loss_pct": 0.0,
                "signal_strength_dbm": -52,
            },
            "dns": {"latency_ms": 640, "failures": 4},
            "events": [{"kind": "dns_failure_burst"}],
        }
    )

    assert analysis["kind"] == "dns_issue"
    assert analysis["attribution"] == "dns"


def test_network_analyzer_reports_insufficient_evidence_when_history_is_thin() -> None:
    analyzer = NetworkAnalyzer()

    analysis = analyzer.analyze(
        {
            "monitoring": {"history_ready": False},
            "quality": {
                "gateway_latency_ms": None,
                "external_latency_ms": None,
                "gateway_jitter_ms": None,
                "external_jitter_ms": None,
                "gateway_packet_loss_pct": None,
                "external_packet_loss_pct": None,
                "signal_strength_dbm": None,
            },
            "dns": {"latency_ms": None, "failures": 0},
            "events": [],
        }
    )

    assert analysis["kind"] == "insufficient_evidence"
    assert analysis["confidence"] == "low"
