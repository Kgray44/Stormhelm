from __future__ import annotations

from pathlib import Path

import pytest

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.screen_awareness import ActionExecutionStatus
from stormhelm.core.screen_awareness import BrowserSemanticActionExecutionResult
from stormhelm.core.screen_awareness import BrowserSemanticControl
from stormhelm.core.screen_awareness import BrowserSemanticObservation
from stormhelm.core.screen_awareness import GroundingEvidenceChannel
from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenInterpretation
from stormhelm.core.screen_awareness import ScreenSourceType
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.ui.command_surface_v2 import build_command_surface_model


def _enabled_screen_config() -> ScreenAwarenessConfig:
    config = ScreenAwarenessConfig()
    config.browser_adapters.playwright.enabled = True
    config.browser_adapters.playwright.allow_dev_adapter = True
    return config


def _observation() -> BrowserSemanticObservation:
    return BrowserSemanticObservation(
        provider="playwright_live_semantic",
        adapter_id="screen_awareness.browser.playwright",
        session_id="canonical-kraken",
        page_url="https://example.test/checkout",
        page_title="Example Checkout",
        browser_context_kind="isolated_playwright_context",
        controls=[
            BrowserSemanticControl(
                control_id="button-continue",
                role="button",
                name="Continue",
                label="Continue",
                text="Continue",
                selector_hint="#continue",
                visible=True,
                enabled=True,
                confidence=0.92,
            ),
            BrowserSemanticControl(
                control_id="textbox-email",
                role="textbox",
                name="Email",
                label="Email",
                text="Email",
                selector_hint="#email",
                visible=True,
                enabled=True,
                required=True,
                confidence=0.9,
            ),
            BrowserSemanticControl(
                control_id="link-privacy",
                role="link",
                name="Privacy Policy",
                label="Privacy Policy",
                text="Privacy Policy",
                selector_hint="#privacy",
                visible=True,
                enabled=True,
                confidence=0.88,
            ),
        ],
        dialogs=[{"dialog_id": "warning", "role": "alert", "text": "Session expired"}],
        limitations=["isolated_temporary_browser_context"],
        confidence=0.91,
    )


def _plan(message: str, *, active_context: dict[str, object] | None = None):
    return DeterministicPlanner().plan(
        message,
        session_id="playwright-canonical-kraken",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context=active_context or {},
        recent_tool_results=[],
    )


def _winner_family(decision) -> str:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    return str(winner.get("route_family") or "")


def _tool_names(decision) -> list[str]:
    return [request.tool_name for request in decision.tool_requests]


def test_playwright_observation_is_canonical_browser_semantics_not_parallel_authority() -> None:
    subsystem = build_screen_awareness_subsystem(_enabled_screen_config())
    observation = _observation()

    resolution = subsystem.resolve_playwright_browser_semantics(observation)
    context = subsystem.build_playwright_canonical_context(observation)
    screen_observation = subsystem.screen_observation_from_playwright_browser_observation(observation)
    grounding = subsystem.grounding_engine.resolve(
        operator_text="where is the Continue button",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        observation=screen_observation,
        interpretation=ScreenInterpretation(likely_environment="browser"),
        current_context=context,
    )

    assert resolution.adapter_id.value == "browser"
    assert resolution.used_for_context is True
    assert {target.label for target in resolution.semantic_targets} >= {"Continue", "Email", "Privacy Policy"}
    assert all(target.source_type == ScreenSourceType.APP_ADAPTER for target in resolution.semantic_targets)
    assert all(target.semantic_metadata["source_provider"] == "playwright_live_semantic" for target in resolution.semantic_targets)
    assert context.adapter_resolution is not None
    assert context.adapter_resolution.adapter_id == resolution.adapter_id
    assert {target.label for target in context.adapter_resolution.semantic_targets} >= {"Continue", "Email", "Privacy Policy"}
    assert context.active_environment == "browser"
    assert grounding is not None
    assert grounding.winning_target is not None
    assert grounding.winning_target.label == "Continue"
    assert grounding.winning_target.source_channel == GroundingEvidenceChannel.ADAPTER_SEMANTICS
    assert grounding.winning_target.semantic_metadata["claim_ceiling"] == "browser_semantic_observation"


@pytest.mark.parametrize(
    ("provider_status", "verification_status", "expected_status"),
    [
        ("verified_supported", "supported", ActionExecutionStatus.VERIFIED_SUCCESS),
        ("completed_unverified", "unverifiable", ActionExecutionStatus.ATTEMPTED_UNVERIFIED),
        ("verified_unsupported", "unsupported", ActionExecutionStatus.ATTEMPTED_UNVERIFIED),
        ("partial", "partial", ActionExecutionStatus.ATTEMPTED_UNVERIFIED),
        ("failed", "failed", ActionExecutionStatus.FAILED),
        ("blocked_stale_plan", "", ActionExecutionStatus.BLOCKED),
        ("approval_invalid", "", ActionExecutionStatus.BLOCKED),
    ],
)
def test_provider_action_statuses_map_to_canonical_action_language(
    provider_status: str,
    verification_status: str,
    expected_status: ActionExecutionStatus,
) -> None:
    subsystem = build_screen_awareness_subsystem(_enabled_screen_config())

    canonical = subsystem.map_playwright_browser_action_execution_result(
        BrowserSemanticActionExecutionResult(
            request_id="exec-kraken",
            plan_id="plan-kraken",
            preview_id="preview-kraken",
            action_kind="focus" if provider_status == "completed_unverified" else "click",
            status=provider_status,
            action_attempted=provider_status in {"verified_supported", "completed_unverified", "verified_unsupported", "partial", "failed"},
            action_completed=provider_status in {"verified_supported", "completed_unverified", "verified_unsupported", "partial"},
            verification_attempted=bool(verification_status),
            verification_status=verification_status,
            target_summary={"candidate_id": "button-continue", "role": "button", "name": "Continue"},
            risk_level="low",
            provider="playwright_live_semantic",
            error_code=provider_status if provider_status.startswith("blocked_") or provider_status.startswith("approval_") else "",
            user_message=f"Provider returned {provider_status}.",
        )
    )

    assert canonical.status == expected_status
    assert canonical.plan.target is not None
    assert canonical.plan.target.source_channel == GroundingEvidenceChannel.ADAPTER_SEMANTICS
    assert canonical.plan.target.semantic_metadata["provider"] == "playwright_live_semantic"
    if expected_status == ActionExecutionStatus.VERIFIED_SUCCESS:
        assert canonical.gate.verification_ready is True
    if expected_status == ActionExecutionStatus.BLOCKED:
        assert canonical.gate.blocker_present is True
        assert canonical.attempt is None


def test_status_and_deck_show_canonical_state_before_playwright_provenance() -> None:
    subsystem = build_screen_awareness_subsystem(_enabled_screen_config())
    subsystem.map_playwright_browser_action_execution_result(
        BrowserSemanticActionExecutionResult(
            request_id="exec-kraken",
            plan_id="plan-kraken",
            preview_id="preview-kraken",
            action_kind="click",
            status="completed_unverified",
            action_attempted=True,
            action_completed=True,
            verification_attempted=True,
            verification_status="unverifiable",
            target_summary={"candidate_id": "button-continue", "role": "button", "name": "Continue"},
            risk_level="low",
            provider="playwright_live_semantic",
            cleanup_status="closed",
        )
    )

    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "checkout page",
            "parameters": {"request_stage": "execute", "result_state": "attempted"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={"content": "Click attempted; semantic verification was not conclusive.", "metadata": {}},
        status={"screen_awareness": subsystem.status_snapshot()},
        workspace_focus={},
    )
    station = next(item for item in surface["deckStations"] if item["stationFamily"] == "screen_awareness")
    station_text = str(station).lower()

    assert status["latest_canonical_action_summary"]["status"] == "attempted_unverified"
    assert status["last_action_execution_summary"]["canonical_status"] == "attempted_unverified"
    assert "canonical: attempted unverified" in station_text
    assert "completed unverified" in station_text
    assert "execute now" not in station_text
    assert "raw dom" not in station_text
    assert "cookie" not in station_text
    assert "password" not in station_text


def test_planner_and_ui_have_no_direct_playwright_execution_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    planner_paths = [
        repo_root / "src" / "stormhelm" / "core" / "orchestrator" / "planner.py",
        repo_root / "src" / "stormhelm" / "core" / "orchestrator" / "planner_v2.py",
        repo_root / "src" / "stormhelm" / "core" / "orchestrator" / "assistant.py",
    ]
    ui_paths = list((repo_root / "src" / "stormhelm" / "ui").rglob("*.py"))
    planner_text = "\n".join(path.read_text(encoding="utf-8") for path in planner_paths if path.exists())
    ui_text = "\n".join(path.read_text(encoding="utf-8") for path in ui_paths if path.exists())

    forbidden = [
        "execute_playwright_browser_action",
        "request_playwright_browser_action_execution",
        "execute_semantic_action",
        "request_semantic_action_execution",
        "PlaywrightBrowserSemanticAdapter",
        "browser_playwright",
    ]
    assert all(token not in planner_text for token in forbidden)
    assert all(token not in ui_text for token in forbidden)


def test_playwright_provider_uses_injected_trust_service_and_provider_local_cleanup_only() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "src" / "stormhelm" / "core" / "screen_awareness" / "browser_playwright.py").read_text(
        encoding="utf-8"
    )

    assert "TrustService(" not in source
    assert "build_trust_service" not in source
    assert ".respond_to_request(" not in source
    assert "trust_service.evaluate_action(" in source
    assert "trust_service.mark_action_executed(" in source
    assert "_cleanup_isolated_browser_resources" in source


@pytest.mark.parametrize(
    ("prompt", "expected_family", "expected_tools"),
    [
        ("what fields are on this page?", "screen_awareness", []),
        ("where is the continue button?", "screen_awareness", []),
        ("click the continue button", "screen_awareness", []),
        ("type into the email field", "screen_awareness", []),
        ("submit the form", "screen_awareness", []),
        ("summarize this URL https://example.com", "web_retrieval", ["web_retrieval_fetch"]),
        ("open YouTube", "browser_destination", ["external_open_url"]),
        ("send this page to Baby", "discord_relay", []),
    ],
)
def test_route_boundaries_keep_playwright_inside_screen_awareness(
    prompt: str,
    expected_family: str,
    expected_tools: list[str],
) -> None:
    decision = _plan(
        prompt,
        active_context={
            "selection": {"kind": "text", "value": "Selected page excerpt.", "preview": "Selected page excerpt."},
            "browser": {"url": "https://example.com", "title": "Example"},
        },
    )

    assert _winner_family(decision) == expected_family
    assert _tool_names(decision) == expected_tools
    assert "playwright" not in str(decision.route_state.to_dict()).lower()
