from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.screen_awareness import BrowserSemanticControl
from stormhelm.core.screen_awareness import BrowserSemanticObservation
from stormhelm.core.screen_awareness import BrowserSemanticVerificationRequest
from stormhelm.core.screen_awareness import PlaywrightBrowserSemanticAdapter
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.ui.command_surface_v2 import build_command_surface_model


def _enabled_config() -> ScreenAwarenessConfig:
    config = ScreenAwarenessConfig()
    playwright = config.browser_adapters.playwright
    playwright.enabled = True
    playwright.allow_dev_adapter = True
    return config


def _adapter(*, events: EventBuffer | None = None) -> PlaywrightBrowserSemanticAdapter:
    return PlaywrightBrowserSemanticAdapter(_enabled_config().browser_adapters.playwright, events=events)


def _control(
    control_id: str,
    role: str,
    name: str,
    *,
    label: str = "",
    text: str = "",
    enabled: bool | None = True,
    visible: bool | None = True,
    required: bool | None = None,
    readonly: bool | None = None,
    checked: bool | None = None,
    expanded: bool | None = None,
    value_summary: str = "",
    risk_hint: str = "",
) -> BrowserSemanticControl:
    return BrowserSemanticControl(
        control_id=control_id,
        role=role,
        name=name,
        label=label or name,
        text=text or name,
        enabled=enabled,
        visible=visible,
        required=required,
        readonly=readonly,
        checked=checked,
        expanded=expanded,
        value_summary=value_summary,
        risk_hint=risk_hint,
        confidence=0.82,
    )


def _observation(
    *,
    page_url: str = "https://example.test/checkout",
    page_title: str = "Checkout",
    controls: list[BrowserSemanticControl] | None = None,
    dialogs: list[dict] | None = None,
    forms: list[dict] | None = None,
    limitations: list[str] | None = None,
    observed_at: str | None = None,
) -> BrowserSemanticObservation:
    dialogs = dialogs or []
    return BrowserSemanticObservation(
        provider="playwright_live_semantic",
        adapter_id="screen_awareness.browser.playwright",
        session_id="verification-fixture",
        page_url=page_url,
        page_title=page_title,
        browser_context_kind="isolated_playwright_context",
        observed_at=observed_at or datetime.now(UTC).isoformat(),
        controls=controls or [],
        dialogs=dialogs,
        alerts=[item for item in dialogs if item.get("role") == "alert"],
        forms=forms or [],
        limitations=limitations
        or [
            "live_semantic_observation_only",
            "isolated_temporary_browser_context",
            "no_actions",
            "not_visible_screen_verification",
        ],
        confidence=0.82,
    )


def _before_observation(**overrides) -> BrowserSemanticObservation:
    return _observation(
        controls=[
            _control("button-continue", "button", "Continue", enabled=False),
            _control("textbox-email", "textbox", "Email", required=False),
            _control("checkbox-agree", "checkbox", "I agree", checked=False, required=True),
            _control("reference", "textbox", "Reference", readonly=True),
            _control("password", "textbox", "Password", value_summary="alpha-secret", risk_hint="sensitive_input"),
            _control("link-privacy", "link", "Privacy Policy"),
        ],
        dialogs=[{"dialog_id": "warning-session", "role": "alert", "name": "Session expired", "text": "Session expired"}],
        forms=[{"form_id": "checkout", "name": "Checkout", "field_count": 4, "summary": "Checkout form"}],
        **overrides,
    )


def _after_observation(**overrides) -> BrowserSemanticObservation:
    payload = {
        "page_url": "https://example.test/done",
        "page_title": "Done",
        "controls": [
            _control("button-continue", "button", "Continue", enabled=True),
            _control("textbox-email", "textbox", "Email", required=True),
            _control("checkbox-agree", "checkbox", "I agree", checked=True, required=True),
            _control("reference", "textbox", "Reference", readonly=False),
            _control("password", "textbox", "Password", value_summary="beta-secret", risk_hint="sensitive_input"),
            _control("link-privacy", "link", "Privacy Policy"),
            _control("link-terms", "link", "Terms of Service"),
        ],
        "dialogs": [],
        "forms": [{"form_id": "checkout", "name": "Checkout", "field_count": 5, "summary": "Checkout form"}],
    }
    payload.update(overrides)
    return _observation(
        **payload,
    )


def test_semantic_verification_models_serialize_with_comparison_claim_ceiling() -> None:
    request = BrowserSemanticVerificationRequest(
        before_observation_id="before-1",
        after_observation_id="after-1",
        expected_change_kind="enabled_state_changed",
        target_phrase="Continue button",
        expected_state=True,
    )

    payload = request.to_dict()

    assert payload["expected_change_kind"] == "enabled_state_changed"
    assert payload["target_phrase"] == "Continue button"
    assert payload["route_family"] == "screen_awareness"
    assert payload["created_at"]


def test_comparison_detects_page_control_warning_link_form_and_redacted_value_changes() -> None:
    adapter = _adapter()

    result = adapter.compare_semantic_observations(_before_observation(), _after_observation())
    change_types = {change.change_type for change in result.changes}
    text = str(result.to_dict()).lower()

    assert result.status == "supported"
    assert result.claim_ceiling == "browser_semantic_observation_comparison"
    assert {
        "page_url_changed",
        "page_title_changed",
        "enabled_state_changed",
        "required_state_changed",
        "checked_state_changed",
        "readonly_state_changed",
        "warning_removed",
        "link_added",
        "form_summary_changed",
        "value_summary_changed",
    }.issubset(change_types)
    assert result.expected_change_supported is False
    assert result.confidence >= 0.7
    assert "alpha-secret" not in text
    assert "beta-secret" not in text
    assert "clicked" not in text
    assert "completed" not in text


def test_expected_warning_removed_and_button_enabled_are_supported() -> None:
    adapter = _adapter()
    before = _before_observation()
    after = _after_observation()

    warning = adapter.verify_semantic_change(
        BrowserSemanticVerificationRequest(
            before_observation_id=before.observation_id,
            after_observation_id=after.observation_id,
            expected_change_kind="warning_removed",
            target_phrase="Session expired warning",
        ),
        before=before,
        after=after,
    )
    enabled = adapter.verify_semantic_change(
        BrowserSemanticVerificationRequest(
            before_observation_id=before.observation_id,
            after_observation_id=after.observation_id,
            expected_change_kind="enabled_state_changed",
            target_phrase="Continue button",
            expected_state=True,
        ),
        before=before,
        after=after,
    )

    assert warning.status == "supported"
    assert warning.expected_change_supported is True
    assert "warning disappeared" in warning.user_message
    assert enabled.status == "supported"
    assert enabled.expected_change_supported is True
    assert "Continue button appears to have become enabled" in enabled.user_message


def test_expected_outcome_handles_missing_ambiguous_stale_and_partial_basis() -> None:
    adapter = _adapter()
    before = _before_observation()
    after = _after_observation()

    missing = adapter.verify_semantic_change(
        BrowserSemanticVerificationRequest(
            before_observation_id=before.observation_id,
            after_observation_id=after.observation_id,
            expected_change_kind="control_added",
            target_phrase="Delete account button",
        ),
        before=before,
        after=after,
    )
    ambiguous_after = _after_observation(
        controls=[
            _control("button-continue-a", "button", "Continue", enabled=True),
            _control("button-continue-b", "button", "Continue", enabled=True),
        ]
    )
    ambiguous = adapter.verify_semantic_change(
        BrowserSemanticVerificationRequest(
            before_observation_id=before.observation_id,
            after_observation_id=ambiguous_after.observation_id,
            expected_change_kind="enabled_state_changed",
            target_phrase="Continue button",
            expected_state=True,
        ),
        before=before,
        after=ambiguous_after,
    )
    stale_before = _before_observation(observed_at=(datetime.now(UTC) - timedelta(minutes=8)).isoformat())
    stale = adapter.verify_semantic_change(
        BrowserSemanticVerificationRequest(
            before_observation_id=stale_before.observation_id,
            after_observation_id=after.observation_id,
            expected_change_kind="warning_removed",
            target_phrase="warning",
        ),
        before=stale_before,
        after=after,
    )
    partial_after = _after_observation(limitations=["partial_semantic_observation", "iframe_context_limited", "no_actions"])
    partial = adapter.verify_semantic_change(
        BrowserSemanticVerificationRequest(
            before_observation_id=before.observation_id,
            after_observation_id=partial_after.observation_id,
            expected_change_kind="warning_removed",
            target_phrase="warning",
        ),
        before=before,
        after=partial_after,
    )

    assert missing.status == "unsupported"
    assert missing.expected_change_supported is False
    assert ambiguous.status == "ambiguous"
    assert ambiguous.expected_change_supported is False
    assert stale.status == "stale_basis"
    assert "stale" in stale.limitations
    assert partial.status == "partial"
    assert partial.expected_change_supported is True
    assert "partial_semantic_observation" in partial.limitations


def test_insufficient_basis_and_action_preview_remain_unsupported() -> None:
    adapter = _adapter()
    after = _after_observation()

    result = adapter.compare_semantic_observations(None, after)  # type: ignore[arg-type]
    preview = adapter.build_action_preview(
        adapter.ground_target("Continue button", after)[0]
    )

    assert result.status == "insufficient_basis"
    assert result.changes == []
    assert result.expected_change_supported is False
    assert preview["status"] == "unsupported"
    assert preview["action_supported"] is False


def test_service_emits_bounded_semantic_comparison_events_and_status() -> None:
    events = EventBuffer(capacity=32)
    subsystem = build_screen_awareness_subsystem(_enabled_config(), events=events)
    before = _before_observation()
    after = _after_observation()

    result = subsystem.verify_playwright_semantic_change(
        BrowserSemanticVerificationRequest(
            before_observation_id=before.observation_id,
            after_observation_id=after.observation_id,
            expected_change_kind="warning_removed",
            target_phrase="Session expired warning",
        ),
        before=before,
        after=after,
    )
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]
    event_text = str(events.recent(limit=32)).lower()

    assert result.status == "supported"
    assert status["last_verification_summary"]["status"] == "supported"
    assert status["last_verification_summary"]["change_count"] >= 1
    assert "screen_awareness.playwright_semantic_comparison_started" in event_text
    assert "screen_awareness.playwright_semantic_comparison_completed" in event_text
    assert "screen_awareness.playwright_semantic_verification_supported" in event_text
    assert "alpha-secret" not in event_text
    assert "beta-secret" not in event_text
    assert "clicked" not in event_text


def test_deck_payload_surfaces_semantic_comparison_without_action_controls() -> None:
    before = _before_observation()
    after = _after_observation()
    result = _adapter().verify_semantic_change(
        BrowserSemanticVerificationRequest(
            before_observation_id=before.observation_id,
            after_observation_id=after.observation_id,
            expected_change_kind="warning_removed",
            target_phrase="Session expired warning",
        ),
        before=before,
        after=after,
    )
    status = {
        "screen_awareness": {
            "enabled": True,
            "phase": "phase12",
            "policy_state": {"summary": "Screen Awareness owns browser semantics."},
            "hardening": {"latest_trace": {"total_duration_ms": 4.0}},
            "browser_adapters": {
                "playwright": {
                    "status": "runtime_ready",
                    "playwright_runtime_ready": True,
                    "live_actions_enabled": False,
                    "claim_ceiling": "browser_semantic_observation",
                    "last_verification_summary": result.to_dict(),
                }
            },
        }
    }

    surface = build_command_surface_model(
        active_request_state={"family": "screen_awareness", "subject": "browser comparison", "parameters": {"result_state": "attempted"}},
        active_task=None,
        recent_context_resolutions=[],
        latest_message={"content": result.user_message, "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}}},
        status=status,
        workspace_focus={},
    )
    station = next(item for item in surface["deckStations"] if item["stationFamily"] == "screen_awareness")
    station_text = str(station).lower()

    assert "semantic comparison" in station_text
    assert "supported" in station_text
    assert "browser semantic observation comparison" in station_text
    assert "warning" in station_text
    assert "click" not in station_text
    assert "typed" not in station_text
    assert "completed" not in station_text
    assert "verified" not in station_text
