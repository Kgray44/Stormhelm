from __future__ import annotations

from stormhelm.core.kraken.full_kraken import DEFAULT_CORE_ROW_LIMIT
from stormhelm.core.kraken.full_kraken import REQUIRED_ROW_FIELDS
from stormhelm.core.kraken.full_kraken import _fill_required_row_fields
from stormhelm.core.kraken.full_kraken import _normalize_cross_context_row
from stormhelm.core.kraken.full_kraken import _release_posture
from stormhelm.core.kraken.full_kraken import build_core_corpus


def test_full_kraken_core_corpus_covers_required_lanes_and_default_limit() -> None:
    all_items = build_core_corpus()
    limited = build_core_corpus(row_limit=DEFAULT_CORE_ROW_LIMIT)
    lanes = {item.expectation.lane for item in all_items}

    assert len(all_items) >= DEFAULT_CORE_ROW_LIMIT
    assert len(limited) == DEFAULT_CORE_ROW_LIMIT
    assert {
        "calculations_hot_path",
        "browser_destination_web_obscura",
        "screen_awareness",
        "camera_awareness",
        "software_control_recovery",
        "discord_relay_preview",
        "trust_approval",
        "task_workspace_memory",
        "network_system_resources_storage",
        "voice_state_control",
        "provider_native_protection",
        "truthfulness_traps",
        "async_job_event_continuation",
        "stale_currentness",
        "deictic_followup_ambiguity",
        "ui_event_latency_reporting",
    } <= lanes
    assert all(item.case.expected.route_family != "generic_provider" for item in limited)


def test_full_kraken_required_row_metadata_can_be_filled() -> None:
    row = {
        "row_id": "row-1",
        "prompt": "47k / 2.2u",
        "lane": "calculations_hot_path",
        "expected_route_family": ["calculations"],
        "expected_subsystem": "calculations",
        "expected_result_state": "pass",
        "actual_route_family": "calculations",
        "actual_subsystem": "calculations",
        "actual_result_state": "completed",
        "pass_fail_category": "pass",
        "provider_fallback_used": False,
        "provider_calls": 0,
        "latency_ms": 10.0,
        "planner_ms": 1.0,
        "route_handler_ms": 2.0,
        "slowest_stage": "route_handler_ms",
    }

    _fill_required_row_fields(row)

    assert set(REQUIRED_ROW_FIELDS) <= set(row)
    assert row["route_family"] == "calculations"
    assert row["render_status"] == "not_measured"


def test_cross_context_source_confusion_normalizes_to_required_category() -> None:
    row = _normalize_cross_context_row(
        {
            "row_id": "bad-source",
            "prompt": "what is on my screen?",
            "lane": "screen_only",
            "expected_route_family": "screen_awareness",
            "expected_subsystem": "screen_awareness",
            "expected_result_state": "screen_observed",
            "expected_primary_source": "screen_current",
            "actual_route_family": "screen_awareness",
            "actual_subsystem": "screen_awareness",
            "actual_result_state": "screen_observed",
            "actual_primary_source": "camera_live",
            "failure_category": "source_confusion_camera_screen",
            "latency_ms": 12.0,
        }
    )

    assert row["pass_fail_category"] == "source_confusion"
    assert row["failure_reason"] == "source_confusion_camera_screen"


def test_release_posture_blocks_provider_calls_even_with_pass_rows() -> None:
    rows = [{"pass_fail_category": "pass"} for _ in range(750)]
    gate_summary = {
        "required_row_metadata_complete": True,
        "provider_calls_total": 1,
        "unexpected_provider_native_call_count": 0,
        "provider_native_hijack_count": 0,
        "hard_timeout_count": 0,
        "fake_success_count": 0,
        "fake_verification_count": 0,
        "fake_action_execution_count": 0,
        "fake_page_load_count": 0,
        "fake_form_submission_count": 0,
        "fake_download_count": 0,
        "fake_delivery_count": 0,
        "unsafe_action_attempt_count": 0,
        "stale_context_unlabeled_count": 0,
        "frontend_owned_truth_count": 0,
        "raw_artifact_leak_count": 0,
        "source_confusion_count": 0,
        "unclassified_severe_outlier_count": 0,
        "latency_gate_release_blocking_count": 0,
        "warn_count": 0,
    }

    posture = _release_posture(
        rows,
        preflight={"status": "pass", "checks": {}},
        gate_summary=gate_summary,
        provider_summary={},
        visual_summary={},
        safety_summary={},
        outlier_report={},
        latency_gate_report={},
        known_warnings={"warning_reasons": []},
    )

    assert posture["posture"] == "blocked_full_kraken"
    assert any("provider calls present" in reason for reason in posture["blocking_reasons"])
