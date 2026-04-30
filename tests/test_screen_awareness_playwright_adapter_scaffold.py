from __future__ import annotations

from pathlib import Path

from stormhelm.config.loader import load_config
from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import TrustTier
from stormhelm.core.adapters import default_adapter_contract_registry
from stormhelm.core.events import EventBuffer
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.screen_awareness import (
    BrowserGroundingCandidate,
    BrowserSemanticControl,
    BrowserSemanticObservation,
    PlaywrightAdapterReadiness,
    PlaywrightBrowserSemanticAdapter,
    build_screen_awareness_subsystem,
)
from stormhelm.ui.command_surface_v2 import build_command_surface_model


def test_playwright_browser_adapter_config_defaults_disabled(temp_project_root: Path) -> None:
    config = load_config(project_root=temp_project_root, env={})
    playwright = config.screen_awareness.browser_adapters.playwright

    assert playwright.enabled is False
    assert playwright.provider == "playwright"
    assert playwright.mode == "semantic_observation"
    assert playwright.allow_browser_launch is False
    assert playwright.allow_connect_existing is False
    assert playwright.allow_actions is False
    assert playwright.allow_form_fill is False
    assert playwright.allow_login is False
    assert playwright.allow_cookies is False
    assert playwright.allow_screenshots is False
    assert playwright.allow_dev_adapter is False
    assert playwright.max_session_seconds == 120
    assert playwright.navigation_timeout_seconds == 12000
    assert playwright.observation_timeout_seconds == 8000
    assert playwright.debug_events_enabled is True


def test_playwright_adapter_readiness_is_disabled_without_importing_dependency() -> None:
    checks: list[str] = []
    config = ScreenAwarenessConfig()
    adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: checks.append("called") or True,
    )

    readiness = adapter.get_readiness()

    assert readiness.enabled is False
    assert readiness.available is False
    assert readiness.dependency_installed is False
    assert readiness.actions_enabled is False
    assert readiness.launch_allowed is False
    assert readiness.connect_existing_allowed is False
    assert "playwright_adapter_disabled" in readiness.blocking_reasons
    assert checks == []


def test_playwright_adapter_models_are_observation_only() -> None:
    control = BrowserSemanticControl(
        control_id="ctrl-search",
        role="textbox",
        name="Search",
        label="Search docs",
        text="",
        selector_hint="role=textbox[name='Search']",
        visible=True,
        enabled=True,
        confidence=0.82,
    )
    observation = BrowserSemanticObservation(
        provider="playwright",
        adapter_id="screen_awareness.browser.playwright",
        session_id="semantic-session",
        page_url="https://example.com/docs",
        page_title="Docs",
        controls=[control],
        confidence=0.74,
    )
    candidate = BrowserGroundingCandidate(
        target_phrase="search field",
        control_id=control.control_id,
        role=control.role,
        name=control.name,
        label=control.label,
        match_reason="role/name semantic match",
        confidence=0.79,
    )

    assert observation.claim_ceiling == "browser_semantic_observation"
    assert observation.controls[0].to_dict()["selector_hint"] == "role=textbox[name='Search']"
    assert candidate.action_supported is False
    assert candidate.verification_supported is False


def test_playwright_browser_adapter_contract_is_observation_only() -> None:
    registry = default_adapter_contract_registry()
    contract = registry.get_contract("screen_awareness.browser.playwright")

    assert contract.family == "screen_awareness"
    assert contract.trust_tier == TrustTier.LOCAL_BROWSER_SEMANTIC_ADAPTER
    assert contract.verification.max_claimable_outcome == ClaimOutcome.OBSERVED
    assert "browser.semantic_observe" in contract.observation_modes
    assert "browser.extract_accessibility_snapshot" in contract.observation_modes
    assert "browser.report_visible_controls" in contract.observation_modes
    assert "browser_semantic_observation" in contract.artifact_modes
    assert "browser.input.click" not in contract.action_modes
    assert "browser.input.type" not in contract.action_modes
    assert "browser.form.fill" not in contract.action_modes
    assert "browser.form.submit" not in contract.action_modes
    assert "browser.login" not in contract.action_modes
    assert "browser.cookies.read" not in contract.action_modes
    assert "browser.visible_screen_verify" not in contract.artifact_modes
    assert "browser.truth_verify" not in contract.artifact_modes


def test_screen_awareness_status_lists_playwright_adapter_disabled() -> None:
    subsystem = build_screen_awareness_subsystem(ScreenAwarenessConfig())

    snapshot = subsystem.status_snapshot()
    playwright = snapshot["browser_adapters"]["playwright"]

    assert playwright["enabled"] is False
    assert playwright["available"] is False
    assert playwright["claim_ceiling"] == "browser_semantic_observation"
    assert "playwright_adapter_disabled" in playwright["blocking_reasons"]
    assert "playwright" not in snapshot["runtime_hooks"]["supported_adapters"]


def test_planner_does_not_route_browser_actions_to_playwright_scaffold(temp_config) -> None:
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    def plan(text: str):
        return planner.plan(
            text,
            session_id="playwright-scaffold-test",
            surface_mode="ghost",
            active_module="chartroom",
            workspace_context={},
            active_posture={},
            active_request_state={},
            active_context={},
            recent_tool_results=[],
        )

    click = plan("click the search button on this page")
    login = plan("log into this site with my account")
    inspect = plan("what am I looking at?")
    click_winner = click.route_state.to_dict()["winner"]["route_family"]
    login_winner = login.route_state.to_dict()["winner"]["route_family"]
    inspect_winner = inspect.route_state.to_dict()["winner"]["route_family"]

    assert click_winner != "web_retrieval"
    assert login_winner != "web_retrieval"
    assert inspect_winner == "screen_awareness"
    assert "playwright" not in str(click.tool_requests).lower()
    assert "playwright" not in str(login.tool_requests).lower()


def _enabled_playwright_config(
    *,
    allow_dev_adapter: bool = True,
    allow_browser_launch: bool = False,
    allow_connect_existing: bool = False,
) -> ScreenAwarenessConfig:
    config = ScreenAwarenessConfig()
    playwright = config.browser_adapters.playwright
    playwright.enabled = True
    playwright.allow_dev_adapter = allow_dev_adapter
    playwright.allow_browser_launch = allow_browser_launch
    playwright.allow_connect_existing = allow_connect_existing
    return config


def _checkout_fixture(*, extra_controls: list[dict[str, object]] | None = None) -> dict[str, object]:
    controls: list[dict[str, object]] = [
        {"control_id": "button-continue", "role": "button", "name": "Continue", "visible": True, "enabled": True},
        {"control_id": "textbox-email", "role": "textbox", "label": "Email", "visible": True, "enabled": True},
        {"control_id": "checkbox-agree", "role": "checkbox", "label": "I agree", "checked": False, "visible": True, "enabled": True},
        {"control_id": "link-privacy", "role": "link", "name": "Privacy Policy", "visible": True, "enabled": True},
    ]
    if extra_controls:
        controls.extend(extra_controls)
    return {
        "session_id": "mock-checkout-session",
        "page_url": "https://example.test/checkout",
        "page_title": "Example Checkout",
        "controls": controls,
        "text_regions": [{"text": "Example checkout"}],
        "forms": [{"name": "checkout", "field_count": 1}],
        "dialogs": [{"dialog_id": "dialog-session-expired", "role": "alert", "text": "Session expired"}],
        "alerts": [{"alert_id": "alert-session-expired", "text": "Session expired"}],
    }


def test_playwright_readiness_reports_dev_gate_required() -> None:
    config = _enabled_playwright_config(allow_dev_adapter=False)
    adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: True,
    )

    readiness = adapter.get_readiness()

    assert readiness.status == "dev_gate_required"
    assert readiness.enabled is True
    assert readiness.available is False
    assert readiness.mock_ready is False
    assert readiness.runtime_ready is False
    assert "playwright_dev_adapter_gate_required" in readiness.blocking_reasons


def test_playwright_readiness_handles_missing_dependency_for_live_runtime() -> None:
    config = _enabled_playwright_config(allow_browser_launch=True)
    adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: False,
    )

    readiness = adapter.get_readiness()

    assert readiness.status == "dependency_missing"
    assert readiness.dependency_installed is False
    assert readiness.live_runtime_allowed is True
    assert readiness.mock_ready is True
    assert readiness.runtime_ready is False
    assert "playwright_dependency_missing" in readiness.blocking_reasons


def test_playwright_mock_readiness_available_without_playwright_dependency() -> None:
    config = _enabled_playwright_config()
    adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: False,
    )

    readiness = adapter.get_readiness()

    assert readiness.status == "mock_ready"
    assert readiness.available is True
    assert readiness.dependency_installed is False
    assert readiness.mock_ready is True
    assert readiness.mock_provider_active is True
    assert readiness.runtime_ready is False
    assert readiness.actions_enabled is False
    assert readiness.launch_allowed is False
    assert readiness.connect_existing_allowed is False


def test_playwright_runtime_readiness_detects_browser_engines_when_safely_checkable() -> None:
    config = _enabled_playwright_config(allow_connect_existing=True)
    adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: True,
        browser_engine_checker=lambda: True,
    )

    readiness = adapter.get_readiness()

    assert readiness.status == "runtime_ready"
    assert readiness.available is True
    assert readiness.dependency_installed is True
    assert readiness.browser_engines_available is True
    assert readiness.browser_engines_checkable is True
    assert readiness.runtime_ready is True
    assert readiness.mock_ready is True


def test_playwright_mock_observation_creation_serializes_bounded_controls() -> None:
    config = _enabled_playwright_config()
    adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: False,
    )

    observation = adapter.observe_mock_browser_page(_checkout_fixture())
    payload = observation.to_dict()

    assert observation.provider == "playwright_mock"
    assert observation.browser_context_kind == "mock"
    assert observation.page_url == "https://example.test/checkout"
    assert observation.page_title == "Example Checkout"
    assert observation.claim_ceiling == "browser_semantic_observation"
    assert len(payload["controls"]) == 4
    assert payload["controls"][0]["control_id"] == "button-continue"
    assert payload["dialogs"][0]["text"] == "Session expired"
    assert "mock_semantic_observation" in observation.limitations
    assert "not_visible_screen_verification" in observation.limitations


def test_playwright_mock_grounding_exact_role_label_and_text_matches() -> None:
    config = _enabled_playwright_config()
    adapter = PlaywrightBrowserSemanticAdapter(config.browser_adapters.playwright)
    observation = adapter.observe_mock_browser_page(_checkout_fixture())

    continue_candidates = adapter.ground_target("the Continue button", observation)
    email_candidates = adapter.ground_target("email field", observation)
    privacy_candidates = adapter.ground_target("privacy policy link", observation)
    dialog_candidates = adapter.ground_target("session expired", observation)

    assert [candidate.control_id for candidate in continue_candidates] == ["button-continue"]
    assert continue_candidates[0].match_reason == "role_name_match"
    assert [candidate.control_id for candidate in email_candidates] == ["textbox-email"]
    assert email_candidates[0].match_reason == "label_match"
    assert [candidate.control_id for candidate in privacy_candidates] == ["link-privacy"]
    assert privacy_candidates[0].match_reason == "role_name_match"
    assert [candidate.control_id for candidate in dialog_candidates] == ["dialog-session-expired"]
    assert dialog_candidates[0].role == "alert"


def test_playwright_mock_grounding_preserves_ambiguity_and_no_match() -> None:
    config = _enabled_playwright_config()
    adapter = PlaywrightBrowserSemanticAdapter(config.browser_adapters.playwright)
    observation = adapter.observe_mock_browser_page(
        _checkout_fixture(
            extra_controls=[
                {"control_id": "button-back", "role": "button", "name": "Back", "visible": True, "enabled": True}
            ]
        )
    )

    ambiguous = adapter.ground_target("the button", observation)
    no_match = adapter.ground_target("delete account", observation)

    assert {candidate.control_id for candidate in ambiguous} == {"button-continue", "button-back"}
    assert all(candidate.ambiguity_reason == "multiple_semantic_controls_matched" for candidate in ambiguous)
    assert all(candidate.action_supported is False for candidate in ambiguous)
    assert no_match == []
    assert adapter.last_grounding_summary["status"] == "no_match"


def test_playwright_mock_guidance_for_found_ambiguous_and_mock_limitations() -> None:
    config = _enabled_playwright_config()
    adapter = PlaywrightBrowserSemanticAdapter(config.browser_adapters.playwright)
    observation = adapter.observe_mock_browser_page(
        _checkout_fixture(
            extra_controls=[
                {"control_id": "button-back", "role": "button", "name": "Back", "visible": True, "enabled": True}
            ]
        )
    )

    found = adapter.produce_guidance_step(adapter.ground_target("email field", observation)[0], observation=observation)
    ambiguous = adapter.produce_guidance_step(adapter.ground_target("the button", observation), observation=observation)

    assert found["message"] == "I found the Email field."
    assert found["action_supported"] is False
    assert found["verification_supported"] is False
    assert "mock_semantic_observation" in found["limitations"]
    assert ambiguous["message"] == "I found two matching buttons: Continue and Back. Which one do you mean?"
    assert "clicked" not in str(found).lower()
    assert "submitted" not in str(found).lower()
    assert "verified" not in str(found).lower()


def test_playwright_status_snapshot_contains_bounded_latest_mock_summaries() -> None:
    config = _enabled_playwright_config()
    subsystem = build_screen_awareness_subsystem(config)

    observation = subsystem.observe_playwright_mock_browser_page(_checkout_fixture())
    subsystem.ground_playwright_mock_target("email field", observation)

    snapshot = subsystem.status_snapshot()
    playwright = snapshot["browser_adapters"]["playwright"]

    assert playwright["status"] == "mock_ready"
    assert playwright["playwright_adapter_enabled"] is True
    assert playwright["playwright_mock_ready"] is True
    assert playwright["live_actions_enabled"] is False
    assert playwright["last_observation_summary"] == {
        "provider": "playwright_mock",
        "page_url": "https://example.test/checkout",
        "page_title": "Example Checkout",
        "control_count": 4,
        "dialog_count": 1,
        "alert_count": 1,
        "claim_ceiling": "browser_semantic_observation",
    }
    assert playwright["last_grounding_summary"]["candidate_count"] == 1
    assert "controls" not in playwright["last_observation_summary"]
    assert "raw_dom" not in str(playwright).lower()


def test_playwright_adapter_publishes_bounded_mock_events() -> None:
    config = _enabled_playwright_config()
    events = EventBuffer(capacity=16)
    adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        events=events,
        dependency_checker=lambda: False,
    )

    adapter.get_readiness(emit_event=True)
    observation = adapter.observe_mock_browser_page(_checkout_fixture())
    candidates = adapter.ground_target("email field", observation)
    adapter.produce_guidance_step(candidates[0], observation=observation)
    recent = events.recent(limit=10)

    event_types = [event["event_type"] for event in recent]
    assert "screen_awareness.playwright_readiness_checked" in event_types
    assert "screen_awareness.playwright_mock_observation_created" in event_types
    assert "screen_awareness.playwright_grounding_completed" in event_types
    assert "screen_awareness.playwright_guidance_created" in event_types
    assert all("Session expired" not in str(event["payload"]) for event in recent)
    assert all("cookie" not in str(event["payload"]).lower() for event in recent)


def test_playwright_contract_still_exposes_no_action_capabilities() -> None:
    contract = default_adapter_contract_registry().get_contract("screen_awareness.browser.playwright")
    forbidden = {
        "browser.input.click",
        "browser.input.type",
        "browser.input.scroll",
        "browser.form.fill",
        "browser.form.submit",
        "browser.login",
        "browser.cookies.read",
        "browser.cookies.write",
        "browser.download",
        "browser.visible_screen_verify",
        "browser.truth_verify",
        "browser.workflow_replay",
    }

    declared = set(contract.observation_modes) | set(contract.action_modes) | set(contract.artifact_modes)

    assert forbidden.isdisjoint(declared)
    assert contract.verification.max_claimable_outcome == ClaimOutcome.OBSERVED


def test_command_deck_model_surfaces_playwright_mock_readiness_without_action_controls() -> None:
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "checkout page",
            "request_type": "screen_guided_request",
            "parameters": {"request_stage": "prepare_plan", "result_state": "attempted"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": "I found the Email field. This is a mock browser observation.",
            "metadata": {
                "bearing_title": "Mock Browser Grounding",
                "micro_response": "I found the Email field.",
                "route_state": {
                    "winner": {"route_family": "screen_awareness", "status": "attempted"},
                    "decomposition": {"subject": "checkout page"},
                },
            },
        },
        status={
            "screen_awareness": {
                "enabled": True,
                "phase": "phase12",
                "policy_state": {"action_policy_mode": "confirm_before_act", "summary": "Screen Awareness owns browser semantics."},
                "hardening": {"latest_trace": {"total_duration_ms": 4.2}},
                "browser_adapters": {
                    "playwright": {
                        "status": "mock_ready",
                        "playwright_mock_ready": True,
                        "playwright_runtime_ready": False,
                        "live_actions_enabled": False,
                        "claim_ceiling": "browser_semantic_observation",
                        "last_observation_summary": {
                            "provider": "playwright_mock",
                            "page_url": "https://example.test/checkout",
                            "page_title": "Example Checkout",
                            "control_count": 4,
                            "dialog_count": 1,
                            "alert_count": 1,
                            "claim_ceiling": "browser_semantic_observation",
                        },
                        "last_grounding_summary": {
                            "status": "completed",
                            "candidate_count": 1,
                            "roles": ["textbox"],
                            "claim_ceiling": "browser_semantic_observation",
                        },
                    }
                },
            }
        },
        workspace_focus={},
    )

    station = next(item for item in surface["deckStations"] if item["stationFamily"] == "screen_awareness")
    entries = {
        entry["primary"]: entry
        for section in station["sections"]
        for entry in section["entries"]
    }

    assert entries["Browser Adapter"]["secondary"] == "Mock Ready"
    assert entries["Mock Observation"]["secondary"] == "4 controls"
    assert entries["Grounding"]["secondary"] == "1 candidate"
    assert entries["Claim Ceiling"]["secondary"] == "Browser Semantic Observation"
    action_labels = {str(action.get("label", "")).lower() for action in station["actions"]}
    assert {"click", "type", "submit", "fill form"}.isdisjoint(action_labels)
    assert "clicked" not in str(station).lower()
    assert "verified" not in str(station).lower()
