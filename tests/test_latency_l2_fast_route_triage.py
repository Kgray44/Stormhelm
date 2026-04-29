from __future__ import annotations

from fastapi.testclient import TestClient

from stormhelm.core.api.app import create_app
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.route_triage import FastRouteClassifier


def _post_chat(client: TestClient, message: str, *, session_id: str = "latency-l2") -> dict[str, object]:
    response = client.post(
        "/chat/send",
        json={
            "message": message,
            "session_id": session_id,
            "surface_mode": "ghost",
            "active_module": "chartroom",
            "response_profile": "command_eval_compact",
        },
    )
    assert response.status_code == 200
    return response.json()["assistant_message"]["metadata"]


def test_fast_route_classifier_detects_required_obvious_shapes() -> None:
    classifier = FastRouteClassifier()

    calculation = classifier.classify("47k / 2.2u")
    engineering = classifier.classify("calculate 10k + 4.7u")
    helper = classifier.classify("power at 12V and 1.5A")
    browser = classifier.classify("open github.com")
    install = classifier.classify("download and install Minecraft")
    relay = classifier.classify("send this to Baby")
    trust_pending = classifier.classify(
        "confirm",
        active_request_state={"family": "software_control", "trust_prompt_id": "trust-1"},
    )
    trust_without_pending = classifier.classify("confirm")
    voice = classifier.classify("stop talking")
    screen = classifier.classify("what changed on screen")
    continuity = classifier.classify("where did we leave off")
    network = classifier.classify("network speed diagnostics")

    assert calculation.likely_route_families == ("calculations",)
    assert "calculation_expression" in calculation.reason_codes
    assert calculation.provider_fallback_eligible is False
    assert engineering.likely_route_families == ("calculations",)
    assert helper.likely_route_families == ("calculations",)
    assert "calculation_helper_phrase" in helper.reason_codes
    assert browser.likely_route_families == ("browser_destination",)
    assert "software_control" not in browser.likely_route_families
    assert install.likely_route_families == ("software_control",)
    assert relay.likely_route_families == ("discord_relay",)
    assert relay.needs_deictic_context is True
    assert trust_pending.likely_route_families == ("trust_approvals",)
    assert trust_without_pending.likely_route_families != ("trust_approvals",)
    assert trust_without_pending.clarification_likely is True
    assert voice.likely_route_families == ("voice_control",)
    assert screen.likely_route_families == ("screen_awareness",)
    assert screen.needs_screen_context is True
    assert continuity.likely_route_families == ("task_continuity",)
    assert network.likely_route_families == ("watch_runtime",)
    assert network.route_hints["system_lane"] == "network"


def test_chat_send_calculation_records_fast_triage_and_skips_heavy_context(temp_config) -> None:
    app = create_app(temp_config)

    with TestClient(app) as client:
        metadata = _post_chat(client, "47k / 2.2u", session_id="latency-l2-calc")

    triage = metadata["route_triage_result"]
    summary = metadata["latency_summary"]
    trace = metadata["latency_trace"]
    planner_debug = metadata["planner_debug"]

    assert triage["likely_route_families"] == ["calculations"]
    assert triage["provider_fallback_eligible"] is False
    assert summary["route_triage_ms"] >= 0
    assert trace["route_triage_ms"] >= 0
    assert summary["fast_path_used"] is True
    assert summary["heavy_context_loaded"] is False
    assert summary["provider_fallback_suppressed_reason"] == "native_route_triage"
    assert planner_debug["route_triage"]["likely_route_families"] == ["calculations"]
    assert "software_control" in summary["route_family_seams_skipped"]


def test_chat_send_browser_destination_does_not_enter_software_triage(temp_config) -> None:
    app = create_app(temp_config)

    with TestClient(app) as client:
        metadata = _post_chat(client, "open github.com", session_id="latency-l2-browser")

    triage = metadata["route_triage_result"]
    summary = metadata["latency_summary"]

    assert triage["likely_route_families"] == ["browser_destination"]
    assert "software_control" not in triage["likely_route_families"]
    assert summary["provider_fallback_suppressed_reason"] == "native_route_triage"
    assert "software_control" in summary["route_family_seams_skipped"]


def test_chat_send_deictic_relay_loads_heavy_context_without_claiming_completion(temp_config) -> None:
    app = create_app(temp_config)

    with TestClient(app) as client:
        metadata = _post_chat(client, "send this to Baby", session_id="latency-l2-relay")

    triage = metadata["route_triage_result"]
    summary = metadata["latency_summary"]
    partial = metadata["partial_response"]

    assert triage["likely_route_families"] == ["discord_relay"]
    assert triage["needs_deictic_context"] is True
    assert summary["heavy_context_loaded"] is True
    assert summary["heavy_context_reason"] in {"deictic_context", "planner_context_required"}
    assert partial["completion_claimed"] is False
    assert partial["verification_claimed"] is False


def test_latency_l2_fields_flow_into_kraken_rows_and_aggregates() -> None:
    case = CommandEvalCase(
        case_id="l2-row-1",
        message="47k / 2.2u",
        expected=ExpectedBehavior(route_family="calculations", subsystem="calculator"),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=120.0,
        ui_response="47k / 2.2u = 21363636363.63636",
        actual_route_family="calculations",
        actual_subsystem="calculator",
        result_state="verified",
        stage_timings_ms={
            "route_triage_ms": 1.2,
            "planner_route_ms": 8.0,
            "route_handler_ms": 20.0,
        },
        latency_summary={
            "execution_mode": "instant",
            "fast_path_used": True,
            "route_triage_ms": 1.2,
            "triage_confidence": 0.97,
            "triage_reason_codes": ["calculation_expression"],
            "likely_route_families": ["calculations"],
            "skipped_route_families": ["software_control", "screen_awareness"],
            "heavy_context_loaded": False,
            "provider_fallback_suppressed_reason": "native_route_triage",
            "planner_candidates_pruned_count": 2,
            "route_family_seams_evaluated": ["calculations"],
            "route_family_seams_skipped": ["software_control", "screen_awareness"],
            "longest_stage": "route_handler_ms",
            "longest_stage_ms": 20.0,
        },
        budget_result={
            "budget_label": "ghost_interactive",
            "target_ms": 1500.0,
            "soft_ceiling_ms": 2500.0,
            "hard_ceiling_ms": 5000.0,
            "budget_exceeded": False,
            "hard_ceiling_exceeded": False,
            "async_continuation_expected": False,
        },
    )
    result = CommandEvalResult(case=case, observation=observation, assertions={})

    row = result.to_dict()
    report = build_checkpoint_summary([result])["kraken_latency_report"]

    assert row["fast_path_used"] is True
    assert row["route_triage_ms"] == 1.2
    assert row["likely_route_families"] == ["calculations"]
    assert row["provider_fallback_suppressed_reason"] == "native_route_triage"
    assert report["route_triage_ms"]["p95"] == 1.2
    assert report["fast_path_hit_rate"] == 1.0
    assert report["fast_path_correctness_rate"] == 1.0
    assert report["provider_fallback_suppressed_count"] == 1
    assert report["native_route_protection_count"] == 1
