from __future__ import annotations

from pathlib import Path

from stormhelm.config.loader import load_config
from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import default_adapter_contract_registry
from stormhelm.core.container import build_container
from stormhelm.core.events import EventBuffer
from stormhelm.core.screen_awareness import BrowserGroundingCandidate
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.ui.command_surface_v2 import build_command_surface_model


def _enabled_screen_config() -> ScreenAwarenessConfig:
    config = ScreenAwarenessConfig()
    config.browser_adapters.playwright.enabled = True
    config.browser_adapters.playwright.allow_dev_adapter = True
    return config


def _checkout_fixture(
    *,
    page_url: str = "https://example.test/checkout",
    extra_controls: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    controls: list[dict[str, object]] = [
        {"control_id": "button-continue", "role": "button", "name": "Continue", "visible": True, "enabled": True},
        {"control_id": "textbox-email", "role": "textbox", "label": "Email", "visible": True, "enabled": True},
        {"control_id": "checkbox-agree", "role": "checkbox", "label": "I agree", "visible": True, "enabled": True},
        {"control_id": "link-privacy", "role": "link", "name": "Privacy Policy", "visible": True, "enabled": True},
    ]
    if extra_controls:
        controls.extend(extra_controls)
    return {
        "session_id": "mock-checkout-session",
        "page_url": page_url,
        "page_title": "Example Checkout",
        "controls": controls,
        "text_regions": [{"text": "Example checkout"}],
        "forms": [{"name": "checkout", "field_count": 1}],
        "dialogs": [{"dialog_id": "dialog-session-expired", "role": "alert", "text": "Session expired"}],
        "alerts": [{"alert_id": "alert-session-expired", "text": "Session expired"}],
    }


def test_playwright_env_dev_mock_config_reaches_container_status(
    temp_project_root: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("stormhelm.core.screen_awareness.browser_playwright.find_spec", lambda _name: None)
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ENABLED": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_ADAPTER": "true",
        },
    )

    container = build_container(config)
    status = container.status_snapshot_fast()
    playwright = status["screen_awareness"]["browser_adapters"]["playwright"]

    assert config.screen_awareness.browser_adapters.playwright.enabled is True
    assert config.screen_awareness.browser_adapters.playwright.allow_dev_adapter is True
    assert config.calculations.enabled is True
    assert playwright["status"] == "mock_ready"
    assert playwright["playwright_adapter_enabled"] is True
    assert playwright["playwright_mock_ready"] is True
    assert playwright["playwright_runtime_ready"] is False
    assert playwright["live_actions_enabled"] is False


def test_playwright_user_config_override_reaches_screen_awareness_service(
    temp_project_root: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("stormhelm.core.screen_awareness.browser_playwright.find_spec", lambda _name: None)
    user_config = temp_project_root / ".runtime" / "config" / "user.toml"
    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_text(
        "\n".join(
            [
                "[screen_awareness.browser_adapters.playwright]",
                "enabled = true",
                "allow_dev_adapter = true",
                "debug_events_enabled = true",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(project_root=temp_project_root, env={})
    subsystem = build_screen_awareness_subsystem(config.screen_awareness)
    readiness = subsystem.check_playwright_browser_adapter_readiness()

    assert config.screen_awareness.browser_adapters.playwright.enabled is True
    assert config.screen_awareness.browser_adapters.playwright.allow_dev_adapter is True
    assert readiness["status"] == "mock_ready"
    assert readiness["mock_ready"] is True


def test_disabled_playwright_config_blocks_service_mock_observation() -> None:
    events = EventBuffer(capacity=16)
    subsystem = build_screen_awareness_subsystem(ScreenAwarenessConfig(), events=events)

    observation = subsystem.observe_playwright_mock_browser_page(_checkout_fixture())
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]

    assert observation.provider == "playwright_mock_unavailable"
    assert observation.browser_context_kind == "unavailable"
    assert observation.controls == []
    assert observation.confidence == 0.0
    assert "playwright_adapter_disabled" in observation.limitations
    assert status["last_observation_summary"]["status"] == "disabled"
    assert status["last_observation_summary"]["control_count"] == 0
    assert "screen_awareness.playwright_mock_observation_created" not in [
        event["event_type"] for event in events.recent(limit=10)
    ]


def test_service_emits_bounded_readiness_observation_grounding_and_guidance_events() -> None:
    events = EventBuffer(capacity=32)
    subsystem = build_screen_awareness_subsystem(_enabled_screen_config(), events=events)

    readiness = subsystem.check_playwright_browser_adapter_readiness()
    observation = subsystem.observe_playwright_mock_browser_page(
        _checkout_fixture(
            page_url="https://user:secret@example.test/checkout?token=abc",
            extra_controls=[
                {"control_id": "button-back", "role": "button", "name": "Back", "visible": True, "enabled": True}
            ],
        )
    )
    found = subsystem.ground_playwright_mock_target("email field", observation)
    ambiguous = subsystem.ground_playwright_mock_target("the button", observation)
    no_match = subsystem.ground_playwright_mock_target("delete account", observation)
    guidance = subsystem.guide_playwright_mock_target(found[0], observation=observation)

    recent = events.recent(limit=20)
    event_types = [event["event_type"] for event in recent]
    event_text = str(recent).lower()

    assert readiness["status"] == "mock_ready"
    assert observation.page_url == "https://example.test/checkout"
    assert found[0].control_id == "textbox-email"
    assert len(ambiguous) == 2
    assert no_match == []
    assert guidance["message"] == "I found the Email field."
    assert "screen_awareness.playwright_readiness_checked" in event_types
    assert "screen_awareness.playwright_mock_observation_created" in event_types
    assert "screen_awareness.playwright_grounding_completed" in event_types
    assert "screen_awareness.playwright_grounding_ambiguous" in event_types
    assert "screen_awareness.playwright_grounding_no_match" in event_types
    assert "screen_awareness.playwright_guidance_created" in event_types
    assert all("action" not in event_type and "verification" not in event_type for event_type in event_types)
    assert "secret" not in event_text
    assert "token=abc" not in event_text
    assert "session expired" not in event_text
    assert "button-continue" not in event_text
    assert "privacy policy" not in event_text


def test_service_grounding_covers_supported_match_modes_without_actions() -> None:
    subsystem = build_screen_awareness_subsystem(_enabled_screen_config())
    observation = subsystem.observe_playwright_mock_browser_page(
        _checkout_fixture(
            extra_controls=[
                {"control_id": "button-coupon", "role": "button", "text": "Apply coupon", "visible": True, "enabled": True}
            ]
        )
    )

    exact = subsystem.ground_playwright_mock_target("Continue", observation)
    role_name = subsystem.ground_playwright_mock_target("the Continue button", observation)
    label = subsystem.ground_playwright_mock_target("email field", observation)
    text = subsystem.ground_playwright_mock_target("Apply coupon", observation)
    fuzzy = subsystem.ground_playwright_mock_target("policy", observation)
    no_match = subsystem.ground_playwright_mock_target("delete account", observation)

    assert exact[0].match_reason == "exact_name_match"
    assert role_name[0].match_reason == "role_name_match"
    assert label[0].match_reason == "label_match"
    assert text[0].match_reason == "text_match"
    assert fuzzy[0].match_reason == "fuzzy_contains_match"
    assert no_match == []
    assert all(candidate.action_supported is False for candidate in exact + role_name + label + text + fuzzy)
    assert all(candidate.verification_supported is False for candidate in exact + role_name + label + text + fuzzy)


def test_service_guidance_handles_found_ambiguous_no_match_and_disabled_states() -> None:
    enabled = build_screen_awareness_subsystem(_enabled_screen_config())
    observation = enabled.observe_playwright_mock_browser_page(
        _checkout_fixture(
            extra_controls=[
                {"control_id": "button-back", "role": "button", "name": "Back", "visible": True, "enabled": True}
            ]
        )
    )

    found = enabled.guide_playwright_mock_target(
        enabled.ground_playwright_mock_target("email field", observation)[0],
        observation=observation,
    )
    ambiguous = enabled.guide_playwright_mock_target(
        enabled.ground_playwright_mock_target("the button", observation),
        observation=observation,
    )
    no_match = enabled.guide_playwright_mock_target(
        enabled.ground_playwright_mock_target("delete account", observation),
        observation=observation,
    )
    disabled = build_screen_awareness_subsystem(ScreenAwarenessConfig())
    disabled_observation = disabled.observe_playwright_mock_browser_page(_checkout_fixture())
    disabled_guidance = disabled.guide_playwright_mock_target([], observation=disabled_observation)
    combined_text = str([found, ambiguous, no_match, disabled_guidance]).lower()

    assert found["message"] == "I found the Email field."
    assert ambiguous["message"] == "I found two matching buttons: Continue and Back. Which one do you mean?"
    assert no_match["message"] == "I could not ground that target in the mock browser observation."
    assert disabled_guidance["status"] == "unavailable"
    assert "mock_semantic_observation" in found["limitations"]
    assert "playwright_adapter_disabled" in disabled_guidance["limitations"]
    assert "clicked" not in combined_text
    assert "typed" not in combined_text
    assert "submitted" not in combined_text
    assert "verified" not in combined_text


def test_service_future_action_and_verification_paths_are_typed_unsupported() -> None:
    subsystem = build_screen_awareness_subsystem(_enabled_screen_config())
    candidate = BrowserGroundingCandidate(
        target_phrase="continue button",
        control_id="button-continue",
        role="button",
        name="Continue",
        match_reason="role_name_match",
        confidence=0.9,
    )
    observation = subsystem.observe_playwright_mock_browser_page(_checkout_fixture())

    preview = subsystem.preview_playwright_browser_action(candidate)
    verification = subsystem.verify_playwright_browser_action(
        before=observation,
        after=observation,
        expected_change="button clicked",
    )

    assert preview["status"] == "unsupported"
    assert preview["action_supported"] is False
    assert verification["status"] == "unsupported"
    assert verification["verification_supported"] is False
    assert "completed" not in str(preview).lower()
    assert "verified" not in str(verification).lower()


def test_deck_payload_uses_service_status_with_latest_playwright_summaries() -> None:
    subsystem = build_screen_awareness_subsystem(_enabled_screen_config())
    observation = subsystem.observe_playwright_mock_browser_page(_checkout_fixture())
    subsystem.ground_playwright_mock_target("email field", observation)
    status = {"screen_awareness": subsystem.status_snapshot()}

    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "checkout page",
            "parameters": {"request_stage": "prepare_plan", "result_state": "attempted"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": "I found the Email field. This is a mock browser observation.",
            "metadata": {
                "route_state": {
                    "winner": {"route_family": "screen_awareness", "status": "attempted"},
                    "decomposition": {"subject": "checkout page"},
                }
            },
        },
        status=status,
        workspace_focus={},
    )

    station = next(item for item in surface["deckStations"] if item["stationFamily"] == "screen_awareness")
    entries = {
        entry["primary"]: entry
        for section in station["sections"]
        for entry in section["entries"]
    }
    station_text = str(station).lower()

    assert entries["Browser Adapter"]["secondary"] == "Mock Ready"
    assert entries["Mock Observation"]["secondary"] == "4 controls"
    assert entries["Grounding"]["secondary"] == "1 candidate"
    assert entries["Claim Ceiling"]["secondary"] == "Browser Semantic Observation"
    assert "click" not in station_text
    assert "typed" not in station_text
    assert "submitted" not in station_text
    assert "verified" not in station_text


def test_adapter_contract_registry_keeps_playwright_observation_only() -> None:
    registry = default_adapter_contract_registry()
    contract = registry.get_contract("screen_awareness.browser.playwright")
    declared = set(contract.observation_modes) | set(contract.action_modes) | set(contract.artifact_modes)

    assert contract.verification.max_claimable_outcome == ClaimOutcome.OBSERVED
    assert "browser.semantic_observe" in contract.observation_modes
    assert "browser.locate_element_by_role" in contract.observation_modes
    assert "browser_semantic_observation" in contract.artifact_modes
    assert "browser.input.click" not in declared
    assert "browser.input.type" not in declared
    assert "browser.form.fill" not in declared
    assert "browser.form.submit" not in declared
    assert "browser.login" not in declared
    assert "browser.cookies.read" not in declared
    assert "browser.visible_screen_verify" not in declared
    assert "browser.truth_verify" not in declared
