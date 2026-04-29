from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from stormhelm.core.api.app import create_app
from stormhelm.core.latency import LatencyBudget
from stormhelm.core.latency import LatencyStage
from stormhelm.core.latency import LatencyTrace
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.voice.evaluation import VoiceLatencyBreakdown

from test_assistant_orchestrator import FakeSystemProbe
from test_assistant_orchestrator import _build_assistant_with_workspace


def test_latency_trace_serializes_budget_longest_stage_and_redacts_unsafe_metadata() -> None:
    trace = LatencyTrace(
        trace_id="trace-1",
        request_id="request-1",
        session_id="default",
        surface_mode="ghost",
        route_family="calculations",
        subsystem="calculations",
        request_kind="calculation",
        started_at="2026-04-28T10:00:00Z",
        completed_at="2026-04-28T10:00:01Z",
        total_ms=1800.0,
        budget=LatencyBudget.for_label("ghost_interactive"),
        stages=[
            LatencyStage(name="planner_route_ms", duration_ms=25.0),
            LatencyStage(
                name="route_handler_ms",
                duration_ms=1775.0,
                metadata={
                    "api_key": "sk-test-secret",
                    "authorization": "Bearer hidden",
                    "raw_audio": b"not-for-trace",
                    "safe_hint": "calculation path",
                },
            ),
        ],
        provider_called=False,
        voice_involved=False,
    )

    payload = trace.to_dict()
    encoded = json.dumps(payload)

    assert payload["longest_stage"] == "route_handler_ms"
    assert payload["longest_stage_ms"] == 1775.0
    assert payload["budget_result"]["budget_exceeded"] is False
    assert payload["budget_result"]["hard_ceiling_exceeded"] is False
    assert "sk-test-secret" not in encoded
    assert "Bearer hidden" not in encoded
    assert "not-for-trace" not in encoded
    assert payload["stages"][1]["metadata"]["safe_hint"] == "calculation path"


def test_assistant_response_includes_latency_trace_and_route_attribution(temp_config) -> None:
    assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "47k / 2.2u",
                surface_mode="ghost",
                active_module="chartroom",
                response_profile="command_eval_compact",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]

    assert "stage_timings_ms" in metadata
    assert metadata["stage_timings_ms"]["planner_route_ms"] >= 0
    assert metadata["latency_summary"]["total_ms"] >= 0
    assert metadata["latency_summary"]["route_family"] == "calculations"
    assert metadata["latency_summary"]["longest_stage"]
    assert metadata["latency_summary"]["provider_called"] is False
    assert metadata["budget_result"]["budget_label"] == "ghost_interactive"
    assert metadata["latency_trace"]["request_id"]
    assert metadata["latency_trace"]["longest_stage_ms"] >= 0


def test_chat_send_api_refreshes_latency_trace_with_endpoint_timings(temp_config) -> None:
    app = create_app(temp_config)

    with TestClient(app) as client:
        response = client.post(
            "/chat/send",
            json={
                "message": "47k / 2.2u",
                "session_id": "latency-api",
                "surface_mode": "ghost",
                "active_module": "chartroom",
                "response_profile": "command_eval_compact",
            },
        )

    assert response.status_code == 200
    metadata = response.json()["assistant_message"]["metadata"]
    stage_timings = metadata["stage_timings_ms"]
    assert "endpoint_dispatch_ms" in stage_timings
    assert "endpoint_return_to_asgi_ms" in stage_timings
    assert metadata["latency_trace"]["stage_timings_ms"]["endpoint_dispatch_ms"] >= 0
    assert metadata["latency_summary"]["longest_stage"]


def test_voice_latency_breakdown_maps_to_unified_summary_without_audio_payloads() -> None:
    breakdown = VoiceLatencyBreakdown.from_marks(
        {
            "wake": 0,
            "ghost": 20,
            "listen_window": 35,
            "capture_start": 50,
            "capture_complete": 950,
            "vad_speech_started": 160,
            "vad_speech_stopped": 900,
            "stt_complete": 1200,
            "core_bridge_complete": 1350,
            "spoken_render_complete": 1380,
            "tts_complete": 1600,
            "playback_requested": 1620,
            "playback_started": 1660,
            "playback_completed": 1780,
            "cleanup_completed": 1800,
        },
        latency_budget_ms=2000,
        budget_label="voice_hot_path",
    )

    summary = breakdown.to_latency_summary(
        request_id="voice-request-1",
        session_id="voice-session",
    )
    encoded = json.dumps(summary)

    assert summary["voice_involved"] is True
    assert summary["budget_result"]["budget_label"] == "voice_hot_path"
    assert summary["longest_stage"] in {"capture_ms", "listen_window_ms"}
    assert "raw_audio" not in encoded
    assert "generated_audio" not in encoded


def test_command_eval_rows_and_summary_include_kraken_latency_fields() -> None:
    case = CommandEvalCase(
        case_id="latency-row-1",
        message="open calculator",
        expected=ExpectedBehavior(route_family="software_control", subsystem="software"),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=6200.0,
        ui_response="Prepared the plan.",
        actual_route_family="software_control",
        actual_subsystem="software",
        result_state="prepared",
        stage_timings_ms={
            "planner_route_ms": 800.0,
            "route_handler_ms": 5100.0,
            "response_serialization_ms": 30.0,
        },
        job_count=1,
        event_count=2,
    )
    result = CommandEvalResult(
        case=case,
        observation=observation,
        assertions={},
        failure_category="latency_issue",
    )

    row = result.to_dict()
    summary = build_checkpoint_summary([result])

    assert row["longest_stage"] == "route_handler_ms"
    assert row["budget_label"] == "ghost_interactive"
    assert row["budget_exceeded"] is True
    assert row["hard_timeout"] is False
    assert summary["kraken_latency_report"]["total_latency_ms"]["p95"] == 6200.0
    assert summary["kraken_latency_report"]["budget_exceeded_count"] == 1
    assert summary["kraken_latency_report"]["top_10_slowest_rows"][0]["test_id"] == "latency-row-1"
