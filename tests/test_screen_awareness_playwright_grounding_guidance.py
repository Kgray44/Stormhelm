from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.screen_awareness import BrowserSemanticControl
from stormhelm.core.screen_awareness import BrowserSemanticObservation
from stormhelm.core.screen_awareness import PlaywrightBrowserSemanticAdapter
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.ui.command_surface_v2 import build_command_surface_model


def _enabled_config() -> ScreenAwarenessConfig:
    config = ScreenAwarenessConfig()
    config.browser_adapters.playwright.enabled = True
    config.browser_adapters.playwright.allow_dev_adapter = True
    return config


def _adapter(*, events: EventBuffer | None = None) -> PlaywrightBrowserSemanticAdapter:
    config = _enabled_config()
    return PlaywrightBrowserSemanticAdapter(config.browser_adapters.playwright, events=events)


def _observation(*, observed_at: str | None = None) -> BrowserSemanticObservation:
    return BrowserSemanticObservation(
        provider="playwright_live_semantic",
        adapter_id="screen_awareness.browser.playwright",
        session_id="semantic-guidance-test",
        page_url="http://127.0.0.1:60123/semantic.html",
        page_title="Stormhelm Semantic Fixture",
        browser_context_kind="isolated_playwright_context",
        observed_at=observed_at or datetime.now(UTC).isoformat(),
        controls=[
            BrowserSemanticControl(
                control_id="textbox-email",
                role="textbox",
                name="Email",
                label="Email",
                selector_hint="#email",
                enabled=True,
                visible=True,
                required=True,
                confidence=0.86,
            ),
            BrowserSemanticControl(
                control_id="button-continue",
                role="button",
                name="Continue",
                text="Continue",
                selector_hint="#continue",
                enabled=True,
                visible=True,
                confidence=0.84,
            ),
            BrowserSemanticControl(
                control_id="button-cancel",
                role="button",
                name="Cancel",
                text="Cancel",
                selector_hint="#cancel",
                enabled=True,
                visible=True,
                confidence=0.82,
            ),
            BrowserSemanticControl(
                control_id="button-submit-disabled",
                role="button",
                name="Submit",
                text="Submit",
                selector_hint="#submit",
                enabled=False,
                visible=True,
                confidence=0.8,
            ),
            BrowserSemanticControl(
                control_id="checkbox-agree",
                role="checkbox",
                name="I agree",
                label="I agree",
                selector_hint="#agree",
                enabled=True,
                visible=True,
                checked=False,
                confidence=0.78,
            ),
            BrowserSemanticControl(
                control_id="select-plan",
                role="combobox",
                name="Plan",
                label="Plan",
                selector_hint="#plan",
                enabled=True,
                visible=True,
                value_summary="selected value present",
                confidence=0.76,
            ),
            BrowserSemanticControl(
                control_id="link-privacy",
                role="link",
                name="Privacy Policy",
                text="Privacy Policy",
                selector_hint="a[href='/privacy']",
                enabled=True,
                visible=True,
                confidence=0.8,
            ),
            BrowserSemanticControl(
                control_id="link-terms",
                role="link",
                name="Terms of Service",
                text="Terms of Service",
                selector_hint="a[href='/terms']",
                enabled=True,
                visible=True,
                confidence=0.78,
            ),
            BrowserSemanticControl(
                control_id="password-current",
                role="textbox",
                name="Password",
                label="Password",
                selector_hint="#password",
                enabled=True,
                visible=True,
                required=True,
                value_summary="[redacted sensitive field]",
                risk_hint="sensitive_input",
                confidence=0.76,
            ),
            BrowserSemanticControl(
                control_id="hidden-token",
                role="textbox",
                name="Hidden token",
                label="Hidden token",
                visible=False,
                value_summary="secret-token",
            ),
        ],
        text_regions=[
            {"text": "Example checkout form"},
            {"text": "Session expired"},
        ],
        forms=[
            {
                "form_id": "checkout-form",
                "name": "Checkout",
                "field_count": 5,
                "summary": "Checkout form",
            }
        ],
        dialogs=[
            {
                "dialog_id": "session-expired-alert",
                "role": "alert",
                "name": "Session expired",
                "text": "Session expired",
            }
        ],
        alerts=[
            {
                "alert_id": "session-expired-alert",
                "role": "alert",
                "text": "Session expired",
            }
        ],
        limitations=[
            "live_semantic_observation_only",
            "isolated_temporary_browser_context",
            "no_actions",
            "not_visible_screen_verification",
        ],
        confidence=0.8,
    )


def test_semantic_grounding_ranks_state_ordinal_dialog_and_nearby_matches() -> None:
    adapter = _adapter()
    observation = _observation()

    required = adapter.ground_target("the required field", observation)
    disabled_submit = adapter.ground_target("the disabled submit button", observation)
    second_link = adapter.ground_target("the second link", observation)
    nearby = adapter.ground_target("the button near the email field", observation)
    dialog = adapter.ground_target("the thing that says Session expired", observation)

    assert required[0].control_id == "textbox-email"
    assert "required_state_match" in required[0].evidence_terms
    assert disabled_submit[0].control_id == "button-submit-disabled"
    assert {"disabled_state_match", "role_match"}.issubset(set(disabled_submit[0].evidence_terms))
    assert second_link == [candidate for candidate in second_link if candidate.control_id == "link-terms"]
    assert second_link[0].match_reason == "ordinal_match"
    assert nearby[0].control_id == "button-continue"
    assert "nearby_context_match" in nearby[0].evidence_terms
    assert dialog[0].control_id == "session-expired-alert"
    assert dialog[0].role == "alert"
    assert dialog[0].source_provider == "playwright_live_semantic"
    assert dialog[0].source_observation_id == observation.observation_id
    assert dialog[0].claim_ceiling == "browser_semantic_observation"
    assert all(candidate.action_supported is False for candidate in required + disabled_submit + second_link + nearby + dialog)


def test_ambiguity_closest_match_and_stale_confidence_are_truthful() -> None:
    adapter = _adapter()
    stale_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    observation = _observation(observed_at=stale_at)

    buttons = adapter.ground_target("the button", observation)
    closest = adapter.ground_target("find the search box", observation)
    no_match = adapter.ground_target("delete account", observation)
    ambiguous_guidance = adapter.produce_guidance_step(buttons, observation=observation)
    closest_guidance = adapter.produce_guidance_step(closest, observation=observation)
    no_match_guidance = adapter.produce_guidance_step(no_match, observation=observation)
    combined = str([ambiguous_guidance, closest_guidance, no_match_guidance]).lower()

    assert len(buttons) == 3
    assert buttons[0].ambiguity_reason == "multiple_semantic_controls_matched"
    assert buttons[0].confidence < 0.52
    assert "stale_observation" in buttons[0].mismatch_terms
    assert ambiguous_guidance["message"] == "I found three matching buttons: Continue, Cancel, and Submit. Which one do you mean?"
    assert closest[0].match_reason == "closest_match"
    assert closest[0].confidence < 0.55
    assert closest_guidance["message"] == "I did not find a Search field. The closest match is Email."
    assert no_match == []
    assert no_match_guidance["message"] == "I could not ground that target in the latest isolated browser semantic snapshot."
    assert "observation_may_be_stale" in closest_guidance["limitations"]
    assert "clicked" not in combined
    assert "typed" not in combined
    assert "submitted" not in combined
    assert "verified" not in combined


def test_form_summary_is_bounded_redacted_and_evented() -> None:
    events = EventBuffer(capacity=16)
    adapter = _adapter(events=events)
    observation = _observation()

    summary = adapter.summarize_observation(observation)
    event_text = str(events.recent(limit=16)).lower()

    assert summary["provider"] == "playwright_live_semantic"
    assert summary["field_count"] == 4
    assert summary["required_fields"] == ["Email", "Password"]
    assert summary["disabled_controls"] == ["Submit"]
    assert summary["warnings"] == ["Session expired"]
    assert summary["links"] == ["Privacy Policy", "Terms of Service"]
    assert summary["sensitive_fields"] == ["Password"]
    assert summary["claim_ceiling"] == "browser_semantic_observation"
    assert "secret-token" not in str(summary)
    assert "screen_awareness.playwright_form_summary_created" in event_text
    assert "secret-token" not in event_text


def test_service_status_and_deck_include_ranked_candidate_details() -> None:
    config = _enabled_config()
    subsystem = build_screen_awareness_subsystem(config)
    observation = _observation()

    candidates = subsystem.ground_playwright_live_target("the disabled submit button", observation)
    subsystem.guide_playwright_live_target(candidates[0], observation=observation)
    subsystem.summarize_playwright_browser_observation(observation)
    status = {"screen_awareness": subsystem.status_snapshot()}

    grounding = status["screen_awareness"]["browser_adapters"]["playwright"]["last_grounding_summary"]
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "semantic fixture",
            "parameters": {"request_stage": "guide", "result_state": "attempted"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": "I found the Submit button. The button appears disabled.",
            "metadata": {
                "route_state": {
                    "winner": {"route_family": "screen_awareness", "status": "attempted"},
                    "decomposition": {"subject": "semantic fixture"},
                }
            },
        },
        status=status,
        workspace_focus={},
    )
    station = next(item for item in surface["deckStations"] if item["stationFamily"] == "screen_awareness")
    station_text = str(station).lower()

    assert grounding["top_candidates"][0]["control_id"] == "button-submit-disabled"
    assert grounding["top_candidates"][0]["confidence"] >= 0.75
    assert "disabled_state_match" in grounding["top_candidates"][0]["evidence_terms"]
    assert grounding["source_provider"] == "playwright_live_semantic"
    assert "Candidate" in station_text or "candidate" in station_text
    assert "submit" in station_text
    assert "disabled" in station_text
    assert "browser semantic observation" in station_text
    assert "secret-token" not in station_text
    assert "clicked" not in station_text
    assert "typed" not in station_text
