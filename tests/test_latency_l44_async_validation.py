from __future__ import annotations

from stormhelm.core.latency import attach_latency_metadata
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import assess_l44_scheduler_pressure
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import build_l44_async_validation_report
from stormhelm.core.orchestrator.command_eval.report import classify_l44_tail_latency
from stormhelm.core.orchestrator.command_eval.report import validate_l44_truth_clamps


def _result(
    *,
    case_id: str,
    message: str,
    route_family: str,
    subsystem: str = "",
    latency_ms: float = 50.0,
    longest_stage: str = "",
    longest_stage_ms: float = 0.0,
    ui_response: str = "Queued.",
    result_state: str = "queued",
    latency_overrides: dict[str, object] | None = None,
    stage_timings_ms: dict[str, float] | None = None,
) -> CommandEvalResult:
    metadata = {
        "route_family": route_family,
        "subsystem": subsystem or route_family,
    }
    overrides = dict(latency_overrides or {})
    if overrides:
        metadata["subsystem_continuation"] = {
            key: value
            for key, value in overrides.items()
            if key.startswith("subsystem_continuation_")
            or key.startswith("continuation_")
            or key
            in {
                "direct_subsystem_async_converted",
                "inline_front_half_ms",
                "worker_back_half_ms",
                "returned_before_subsystem_completion",
                "async_conversion_expected",
                "async_conversion_missing_reason",
            }
        }
        metadata.update(overrides)
    timings = {
        "total_latency_ms": latency_ms,
        "planner_route_ms": 0.0,
        "route_handler_ms": 0.0,
        "response_serialization_ms": 0.0,
        **(stage_timings_ms or {}),
    }
    attach_latency_metadata(
        metadata,
        stage_timings_ms=timings,
        request_id=f"req-{case_id}",
        session_id="l44",
        surface_mode="ghost",
        active_module="chartroom",
    )
    summary = dict(metadata["latency_summary"])
    summary.update(overrides)
    if longest_stage:
        summary["longest_stage"] = longest_stage
        summary["longest_stage_ms"] = longest_stage_ms
    case = CommandEvalCase(
        case_id=case_id,
        message=message,
        expected=ExpectedBehavior(route_family=route_family, subsystem=subsystem or route_family),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=latency_ms,
        ui_response=ui_response,
        actual_route_family=route_family,
        actual_subsystem=subsystem or route_family,
        result_state=result_state,
        stage_timings_ms=timings,
        latency_summary=summary,
        budget_result=dict(metadata["budget_result"]),
    )
    return CommandEvalResult(case=case, observation=observation, assertions={})


def test_l44_async_coverage_audit_classifies_inline_implemented_and_missing_handlers() -> None:
    rows = [
        _result(case_id="calc", message="47k / 2.2u", route_family="calculations", result_state="verified"),
        _result(
            case_id="workspace",
            message="assemble my workspace",
            route_family="workspace_operations",
            subsystem="workspace",
            result_state="queued",
            latency_overrides={
                "subsystem_continuation_created": True,
                "subsystem_continuation_kind": "workspace.assemble_deep",
                "subsystem_continuation_handler": "workspace.assemble_deep",
                "subsystem_continuation_handler_implemented": True,
                "subsystem_continuation_total_ms": 32.0,
                "returned_before_subsystem_completion": True,
                "direct_subsystem_async_converted": True,
            },
        ),
        _result(
            case_id="screen",
            message="verify the screen changed",
            route_family="screen_awareness",
            subsystem="screen_awareness",
            result_state="verification_pending",
            latency_overrides={
                "async_conversion_expected": True,
                "subsystem_continuation_kind": "screen_awareness.verify_change",
                "subsystem_continuation_handler_missing_reason": "no_handler_registered",
            },
        ),
    ]

    report = build_l44_async_validation_report(rows)

    coverage = report["async_coverage_audit"]
    assert coverage["status_by_route"]["calculations"]["current_async_status"] == "inline_correct"
    assert coverage["status_by_handler"]["workspace.assemble_deep"]["current_async_status"] == "continuation_handler_implemented"
    assert coverage["status_by_handler"]["screen_awareness.verify_change"]["current_async_status"] == "continuation_handler_missing"
    assert coverage["missing_handler_count_by_reason"] == {"no_handler_registered": 1}


def test_l44_tail_classifier_separates_planner_queue_runtime_missing_handler_and_timeout() -> None:
    rows = [
        {"test_id": "planner", "latency_ms": 4000.0, "longest_stage": "planner_route_ms", "planner_route_ms": 3200.0},
        {"test_id": "queue", "latency_ms": 3000.0, "queue_wait_ms": 2100.0, "job_run_ms": 200.0},
        {
            "test_id": "continuation",
            "latency_ms": 4500.0,
            "subsystem_continuation_created": True,
            "continuation_total_ms": 3900.0,
        },
        {
            "test_id": "missing",
            "latency_ms": 3500.0,
            "async_conversion_expected": True,
            "async_continuation": False,
            "subsystem_continuation_handler_missing_reason": "no_clean_worker_seam",
        },
        {"test_id": "timeout", "latency_ms": 30000.0, "failure_category": "hard_timeout", "budget_exceeded": True},
    ]

    classifications = {item["test_id"]: item["tail_category"] for item in classify_l44_tail_latency(rows)}

    assert classifications["planner"] == "planner_route_slow"
    assert classifications["queue"] == "job_queue_wait_slow"
    assert classifications["continuation"] == "subsystem_continuation_runtime_slow"
    assert classifications["missing"] == "handler_missing"
    assert classifications["timeout"] == "harness_artifact"


def test_l44_tail_classifier_does_not_mark_normal_context_use_as_slow() -> None:
    rows = [
        {
            "test_id": "normal-context",
            "latency_ms": 600.0,
            "heavy_context_loaded": True,
            "heavy_context_ms": 80.0,
            "longest_stage": "memory_context_ms",
            "longest_stage_ms": 110.0,
        }
    ]

    classifications = classify_l44_tail_latency(rows)

    assert classifications[0]["tail_category"] == "within_expected_band"


def test_l44_tail_classifier_does_not_mark_normal_snapshot_miss_as_slow() -> None:
    rows = [
        {
            "test_id": "normal-miss",
            "latency_ms": 700.0,
            "snapshot_miss_reason": {"active_workspace": "expired"},
        }
    ]

    classifications = classify_l44_tail_latency(rows)

    assert classifications[0]["tail_category"] == "within_expected_band"


def test_l44_truth_clamp_validation_detects_unsafe_async_claims() -> None:
    rows = [
        {
            "test_id": "preview",
            "actual_route_family": "discord_relay",
            "result_state": "preview_ready",
            "ui_response": "Preview sent to Baby.",
        },
        {
            "test_id": "recovery",
            "actual_route_family": "software_recovery",
            "result_state": "completed_unverified",
            "ui_response": "Recovery fixed the install.",
        },
        {
            "test_id": "network",
            "actual_route_family": "network",
            "subsystem_continuation_handler": "network.run_live_diagnosis",
            "result_state": "completed_unverified",
            "ui_response": "Network diagnosis repaired the connection.",
        },
        {
            "test_id": "queued",
            "subsystem_continuation_created": True,
            "returned_before_subsystem_completion": True,
            "result_state": "verified",
            "ui_response": "Queued verification.",
        },
    ]

    report = validate_l44_truth_clamps(rows)

    assert report["unsafe_claim_count"] == 4
    assert report["unsafe_claim_count_by_type"]["preview_claimed_sent"] == 1
    assert report["unsafe_claim_count_by_type"]["recovery_attempted_claimed_fixed"] == 1
    assert report["unsafe_claim_count_by_type"]["diagnosis_claimed_repair"] == 1
    assert report["unsafe_claim_count_by_type"]["initial_response_claimed_completion"] == 1


def test_l44_scheduler_pressure_distinguishes_queue_pressure_from_runtime_pressure() -> None:
    low = assess_l44_scheduler_pressure(
        [{"queue_wait_ms": 0.0, "job_run_ms": 12.0, "worker_saturation_percent": 0.0}]
    )
    runtime = assess_l44_scheduler_pressure(
        [{"queue_wait_ms": 4.0, "job_run_ms": 6200.0, "worker_saturation_percent": 20.0}]
    )
    starvation = assess_l44_scheduler_pressure(
        [
            {
                "queue_wait_ms": 1800.0,
                "job_run_ms": 200.0,
                "worker_saturation_percent": 100.0,
                "interactive_jobs_waiting": 2,
                "background_jobs_running": 1,
                "starvation_detected": True,
            }
        ]
    )

    assert low["scheduler_pressure"] == "low"
    assert runtime["primary_pressure_source"] == "handler_runtime"
    assert starvation["scheduler_pressure"] == "high"
    assert starvation["primary_pressure_source"] == "background_starvation"


def test_l44_checkpoint_summary_includes_validation_report() -> None:
    result = _result(
        case_id="summary",
        message="run live network diagnosis",
        route_family="network",
        subsystem="network",
        latency_ms=800.0,
        result_state="completed_unverified",
        latency_overrides={
            "subsystem_continuation_created": True,
            "subsystem_continuation_kind": "network.run_live_diagnosis",
            "subsystem_continuation_handler": "network.run_live_diagnosis",
            "subsystem_continuation_handler_implemented": True,
            "continuation_total_ms": 300.0,
            "continuation_verification_required": True,
            "continuation_verification_attempted": True,
            "continuation_verification_evidence_count": 2,
            "continuation_truth_clamps_applied": ["diagnosis_is_not_repair"],
            "returned_before_subsystem_completion": True,
        },
    )

    summary = build_checkpoint_summary([result])
    kraken = summary["kraken_latency_report"]

    assert "l44_async_validation" in kraken
    assert kraken["l44_async_validation"]["async_coverage_audit"]["implemented_handler_count"] == 1
    assert kraken["l44_async_validation"]["truth_clamp_validation"]["unsafe_claim_count"] == 0


def test_l44_report_infers_known_registered_handler_when_older_rows_lack_implemented_flag() -> None:
    result = _result(
        case_id="workspace-old",
        message="assemble my workspace",
        route_family="workspace_operations",
        subsystem="workspace",
        latency_ms=700.0,
        result_state="queued",
        latency_overrides={
            "subsystem_continuation_created": True,
            "subsystem_continuation_kind": "workspace.assemble_deep",
            "subsystem_continuation_handler": "workspace.assemble_deep",
            "subsystem_continuation_worker_lane": "normal",
            "returned_before_subsystem_completion": True,
            "direct_subsystem_async_converted": True,
        },
    )

    kraken = build_checkpoint_summary([result])["kraken_latency_report"]
    coverage = kraken["l44_async_validation"]["async_coverage_audit"]

    assert kraken["implemented_handler_count"] == 1
    assert kraken["async_initial_response_count"] == 1
    assert kraken["by_async_strategy"]["create_job"]["count"] == 1
    assert coverage["implemented_handler_count"] == 1
