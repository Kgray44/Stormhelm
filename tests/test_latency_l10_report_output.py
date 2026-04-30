from __future__ import annotations

import json

from stormhelm.command_eval.run_latency_profile import main as run_latency_profile_main
from stormhelm.core.latency_gates import (
    build_latency_gate_report,
    format_latency_gate_report_markdown,
)


def test_l10_json_report_contains_required_sections() -> None:
    report = build_latency_gate_report(
        [{"test_id": "native", "actual_route_family": "calculations", "total_latency_ms": 45}],
        profile="focused_hot_path_profile",
    )

    for key in (
        "run_metadata",
        "lane_summary",
        "gate_summary",
        "release_posture",
        "known_baseline_gaps",
        "known_slow_lanes",
        "outlier_investigation",
        "route_family_histograms",
        "provider_fallback_metrics",
        "voice_first_audio_metrics",
        "ui_perceived_latency_metrics",
        "correctness_latency_summary",
        "recommended_next_actions",
    ):
        assert key in report


def test_l10_markdown_report_is_human_readable_and_mentions_known_baselines() -> None:
    report = build_latency_gate_report([], profile="ui_profile")
    markdown = format_latency_gate_report_markdown(report)

    assert "## Release Posture" in markdown
    assert "## Gate Summary" in markdown
    assert "Known Baseline / Non-Blocking Gaps" in markdown
    assert "web_retrieval_fetch" in markdown


def test_l10_report_does_not_expose_private_payloads() -> None:
    report = build_latency_gate_report(
        [
            {
                "test_id": "secret-row",
                "actual_route_family": "generic_provider",
                "total_latency_ms": 5000,
                "provider_called": True,
                "prompt": "sk-secret private prompt body",
                "raw_audio": "audio-bytes",
            }
        ],
        profile="provider_profile",
    )

    encoded = json.dumps(report).lower()
    assert "sk-secret" not in encoded
    assert "private prompt body" not in encoded
    assert "audio-bytes" not in encoded


def test_l10_latency_profile_runner_writes_json_and_markdown(tmp_path) -> None:
    exit_code = run_latency_profile_main(
        [
            "--profile",
            "provider_mock",
            "--output-dir",
            str(tmp_path),
            "--mock-provider-samples",
            "5",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "latency_profile_report.json").exists()
    assert (tmp_path / "latency_profile_report.md").exists()
    payload = json.loads((tmp_path / "latency_profile_report.json").read_text(encoding="utf-8"))
    assert payload["run_metadata"]["profile"] == "provider_mock"
    assert payload["provider_fallback_metrics"]["provider_timing_mode"] == "mock"
