from __future__ import annotations

from stormhelm.core.latency import build_latency_trace
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import _kraken_latency_report


def test_latency_trace_exposes_l8_subsystem_hot_path_fields() -> None:
    trace = build_latency_trace(
        metadata={
            "route_family": "network",
            "subsystem": "network_hardware_system",
            "l8_operation": "status",
            "cache_hit": True,
            "cache_age_ms": 125.0,
        },
        stage_timings_ms={
            "route_triage_ms": 5.0,
            "route_handler_ms": 18.0,
            "first_feedback_ms": 30.0,
        },
        total_ms=35.0,
    )
    summary = trace.to_summary_dict()

    assert summary["subsystem_id"] == "network_hardware_system"
    assert summary["hot_path_name"] == "network_cached_status"
    assert summary["latency_mode"] == "cached_status"
    assert summary["cache_hit"] is True
    assert summary["cache_age_ms"] == 125.0
    assert summary["cache_policy_id"] == "network_status_snapshot_cache"
    assert summary["live_probe_started"] is False
    assert summary["provider_fallback_used"] is False
    assert summary["heavy_context_used"] is False
    assert summary["route_handler_ms"] == 18.0
    assert summary["first_feedback_ms"] == 30.0
    assert summary["longest_stage"] == "first_feedback_ms"


def test_command_eval_rows_include_l8_trace_fields_for_kraken_grouping() -> None:
    result = CommandEvalResult(
        case=CommandEvalCase(
            case_id="l8-network-status",
            message="how is my network?",
            expected=ExpectedBehavior(route_family="network", subsystem="network_hardware_system"),
        ),
        observation=CoreObservation(
            case_id="l8-network-status",
            input_boundary="core",
            latency_ms=44.0,
            ui_response="Cached network status from 0.1s ago.",
            actual_route_family="network",
            actual_subsystem="network_hardware_system",
            stage_timings_ms={"route_handler_ms": 20.0, "first_feedback_ms": 32.0},
            latency_summary={
                "subsystem_id": "network_hardware_system",
                "hot_path_name": "network_cached_status",
                "latency_mode": "cached_status",
                "cache_hit": True,
                "cache_age_ms": 100.0,
                "cache_policy_id": "network_status_snapshot_cache",
                "provider_fallback_used": False,
                "heavy_context_used": False,
                "route_handler_ms": 20.0,
                "first_feedback_ms": 32.0,
            },
        ),
        assertions={},
    )

    row = result.to_dict()

    assert row["l8_subsystem_id"] == "network_hardware_system"
    assert row["l8_hot_path_name"] == "network_cached_status"
    assert row["l8_latency_mode"] == "cached_status"
    assert row["l8_cache_hit"] is True
    assert row["l8_cache_policy_id"] == "network_status_snapshot_cache"
    assert row["l8_provider_fallback_used"] is False
    assert row["l8_heavy_context_used"] is False


def test_kraken_latency_report_groups_l8_hot_paths_and_cache_behavior() -> None:
    result = CommandEvalResult(
        case=CommandEvalCase(
            case_id="l8-network-status",
            message="how is my network?",
            expected=ExpectedBehavior(route_family="network", subsystem="network_hardware_system"),
        ),
        observation=CoreObservation(
            case_id="l8-network-status",
            input_boundary="core",
            latency_ms=44.0,
            ui_response="Cached network status from 0.1s ago.",
            actual_route_family="network",
            actual_subsystem="network_hardware_system",
            latency_summary={
                "subsystem_id": "network_hardware_system",
                "hot_path_name": "network_cached_status",
                "latency_mode": "cached_status",
                "cache_hit": True,
                "cache_age_ms": 100.0,
                "cache_policy_id": "network_status_snapshot_cache",
                "live_probe_started": False,
                "provider_fallback_used": False,
                "heavy_context_used": False,
            },
        ),
        assertions={},
    )

    report = _kraken_latency_report([result])

    assert report["l8_latency_by_hot_path"]["network_cached_status"]["count"] == 1
    assert report["l8_latency_by_subsystem"]["network_hardware_system"]["count"] == 1
    assert report["l8_cache_hit_count"] == 1
    assert report["l8_cache_miss_count"] == 0
    assert report["l8_live_probe_started_count"] == 0
    assert report["l8_provider_fallback_used_count"] == 0
