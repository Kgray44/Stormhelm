from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from stormhelm.core.api.app import create_app
from stormhelm.core.latency import RouteExecutionMode
from stormhelm.core.latency import build_partial_response_posture
from stormhelm.core.latency import classify_route_latency_policy
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.voice.evaluation import VoiceLatencyBreakdown

from test_assistant_orchestrator import FakeSystemProbe
from test_assistant_orchestrator import _build_assistant_with_workspace


def _run_assistant(
    assistant,
    jobs,
    executor,
    *,
    message: str,
    workspace_context: dict[str, object] | None = None,
) -> dict[str, object]:
    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                message,
                surface_mode="ghost",
                active_module="chartroom",
                workspace_context=workspace_context,
                response_profile="command_eval_compact",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    return asyncio.run(runner())


def test_route_budget_policy_maps_family_to_budget_and_execution_mode() -> None:
    calculation = classify_route_latency_policy(route_family="calculations")
    software_plan = classify_route_latency_policy(
        route_family="software_control",
        execution_plan_type="software_control_execute",
        result_state="approval_required",
    )
    software_execute = classify_route_latency_policy(
        route_family="software_control",
        execution_plan_type="software_control_execute",
        request_kind="software_execution",
    )
    discord_preview = classify_route_latency_policy(
        route_family="discord_relay",
        execution_plan_type="discord_relay_preview",
    )
    provider = classify_route_latency_policy(route_family="generic_provider")
    unsupported = classify_route_latency_policy(route_family="unsupported")

    assert calculation.budget.label == "ghost_interactive"
    assert calculation.execution_mode == RouteExecutionMode.INSTANT
    assert calculation.budget.target_first_feedback_ms == 250
    assert software_plan.execution_mode == RouteExecutionMode.PLAN_FIRST
    assert software_plan.budget.label == "ghost_interactive"
    assert software_execute.execution_mode == RouteExecutionMode.ASYNC_FIRST
    assert software_execute.budget.label == "long_task"
    assert software_execute.async_expected is True
    assert discord_preview.execution_mode == RouteExecutionMode.PLAN_FIRST
    assert provider.execution_mode == RouteExecutionMode.PROVIDER_WAIT
    assert provider.budget.label == "provider_fallback"
    assert unsupported.execution_mode == RouteExecutionMode.UNSUPPORTED


def test_partial_response_posture_never_claims_completion_or_verification() -> None:
    policy = classify_route_latency_policy(
        route_family="software_control",
        request_kind="software_execution",
    )

    posture = build_partial_response_posture(
        route_family="software_control",
        subsystem="software",
        assistant_message="Queued the approved software action.",
        result_state="budget_exceeded_continuing",
        verification_state="verification_pending",
        latency_trace_id="trace-123",
        policy=policy,
        budget_exceeded=True,
        async_continuation=True,
        continue_reason="budget_exceeded_continuing",
        job_id="job-1",
    )

    assert posture["result_state"] == "budget_exceeded_continuing"
    assert posture["route_family"] == "software_control"
    assert posture["async_continuation"] is True
    assert posture["events_expected"] is True
    assert posture["completion_claimed"] is False
    assert posture["verification_claimed"] is False
    assert posture["budget_exceeded"] is True
    assert posture["failed"] is False
    assert posture["job_id"] == "job-1"


def test_assistant_calculation_stays_instant_with_no_partial_success_claim(temp_config) -> None:
    assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )

    payload = _run_assistant(assistant, jobs, executor, message="47k / 2.2u")
    metadata = payload["assistant_message"]["metadata"]

    assert metadata["execution_mode"] == "instant"
    assert metadata["latency_summary"]["execution_mode"] == "instant"
    assert metadata["partial_response"]["partial_response_returned"] is False
    assert metadata["partial_response"]["completion_claimed"] is True
    assert metadata["partial_response"]["verification_claimed"] is False


def test_provider_disabled_fails_fast_without_provider_call_or_completion_claim(temp_config) -> None:
    app = create_app(temp_config)

    with TestClient(app) as client:
        response = client.post(
            "/chat/send",
            json={
                "message": "write a two sentence pep talk for finals",
                "session_id": "latency-provider-disabled",
                "surface_mode": "ghost",
                "active_module": "chartroom",
                "response_profile": "command_eval_compact",
            },
        )

    assert response.status_code == 200
    metadata = response.json()["assistant_message"]["metadata"]
    assert metadata["fail_fast_reason"] == "provider_disabled"
    assert metadata["execution_mode"] == "unsupported"
    assert metadata["latency_summary"]["fail_fast_reason"] == "provider_disabled"
    assert metadata["latency_summary"]["provider_called"] is False
    assert metadata["partial_response"]["completion_claimed"] is False
    assert metadata["partial_response"]["verification_claimed"] is False


def test_voice_disabled_action_reports_fail_fast_posture(temp_config) -> None:
    app = create_app(temp_config)

    with TestClient(app) as client:
        response = client.post(
            "/voice/capture/start",
            json={"session_id": "latency-voice-disabled"},
        )

    payload = response.json()

    assert response.status_code == 200
    assert payload["execution_mode"] == "unsupported"
    assert payload["latency_policy"]["budget_label"] == "voice_hot_path"
    assert payload["fail_fast_reason"] == "voice_disabled"
    assert payload["partial_response"]["completion_claimed"] is False
    assert payload["partial_response"]["verification_claimed"] is False


def test_playback_disabled_action_reports_fail_fast_posture(temp_config) -> None:
    app = create_app(temp_config)

    with TestClient(app) as client:
        response = client.post(
            "/voice/output/stop-speaking",
            json={"session_id": "latency-playback-disabled"},
        )

    payload = response.json()

    assert response.status_code == 200
    assert payload["execution_mode"] == "unsupported"
    assert payload["latency_policy"]["budget_label"] == "voice_hot_path"
    assert payload["fail_fast_reason"] == "playback_disabled"
    assert payload["partial_response"]["completion_claimed"] is False
    assert payload["partial_response"]["verification_claimed"] is False


def test_plan_first_routes_emit_first_feedback_metadata_and_event(temp_config) -> None:
    assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )

    payload = _run_assistant(
        assistant,
        jobs,
        executor,
        message="send this to Baby",
        workspace_context={
            "module": "browser",
            "active_item": {
                "title": "Stormhelm Dispatch Spec",
                "url": "https://example.com/dispatch",
                "kind": "browser-tab",
            },
        },
    )
    metadata = payload["assistant_message"]["metadata"]
    events = assistant.events.replay(cursor=0, session_id="default").events
    event_types = {event.event_type for event in events}

    assert metadata["execution_mode"] == "plan_first"
    assert metadata["first_feedback"]["result_state"] in {"planning", "plan_ready", "approval_required"}
    assert metadata["first_feedback"]["completion_claimed"] is False
    assert metadata["partial_response"]["partial_response_returned"] is True
    assert "latency.first_feedback_ready" in event_types


def test_kraken_l1_report_groups_execution_modes_and_partial_rows() -> None:
    case = CommandEvalCase(
        case_id="l1-row-1",
        message="install calculator",
        expected=ExpectedBehavior(route_family="software_control", subsystem="software"),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=3200.0,
        ui_response="Prepared the plan.",
        actual_route_family="software_control",
        actual_subsystem="software",
        result_state="budget_exceeded_continuing",
        stage_timings_ms={
            "planner_route_ms": 300.0,
            "route_handler_ms": 2800.0,
        },
        latency_summary={
            "execution_mode": "async_first",
            "async_expected": True,
            "partial_response_returned": True,
            "budget_exceeded_continuing": True,
            "first_feedback_ms": 250.0,
        },
        budget_result={
            "budget_label": "long_task",
            "target_ms": 500.0,
            "soft_ceiling_ms": 1500.0,
            "hard_ceiling_ms": 10000.0,
            "budget_exceeded": True,
            "hard_ceiling_exceeded": False,
            "async_continuation_expected": True,
        },
    )
    result = CommandEvalResult(case=case, observation=observation, assertions={})

    row = result.to_dict()
    report = build_checkpoint_summary([result])["kraken_latency_report"]

    assert row["execution_mode"] == "async_first"
    assert row["partial_response_returned"] is True
    assert row["async_expected"] is True
    assert report["by_execution_mode"]["async_first"]["p95"] == 3200.0
    assert report["partial_response_count"] == 1
    assert report["budget_exceeded_continuing_count"] == 1


def test_voice_l1_summary_exposes_hot_path_budget_without_playback_claim() -> None:
    breakdown = VoiceLatencyBreakdown.from_marks(
        {
            "wake": 0,
            "ghost": 20,
            "listen_window": 40,
            "capture_start": 60,
            "capture_complete": 500,
            "stt_complete": 700,
            "core_bridge_complete": 900,
        },
        budget_label="voice_hot_path",
    )

    summary = breakdown.to_latency_summary(
        request_id="voice-l1",
        session_id="voice-session",
    )

    assert summary["budget_label"] == "voice_hot_path"
    assert summary["execution_mode"] == "instant"
    assert summary["first_visual_feedback_ms"] == 20
    assert summary["first_audio_available"] is False
    assert summary["playback_user_heard_claimed"] is False
