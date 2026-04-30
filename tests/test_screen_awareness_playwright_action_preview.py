from __future__ import annotations

from datetime import UTC
from datetime import datetime

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.adapters import default_adapter_contract_registry
from stormhelm.core.events import EventBuffer
from stormhelm.core.screen_awareness import BrowserSemanticActionPlan
from stormhelm.core.screen_awareness import BrowserSemanticActionPreview
from stormhelm.core.screen_awareness import BrowserSemanticControl
from stormhelm.core.screen_awareness import BrowserSemanticObservation
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
    checked: bool | None = None,
    required: bool | None = None,
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
        checked=checked,
        required=required,
        value_summary=value_summary,
        risk_hint=risk_hint,
        confidence=0.86,
    )


def _observation(*, extra_controls: list[BrowserSemanticControl] | None = None) -> BrowserSemanticObservation:
    controls = [
        _control("button-continue", "button", "Continue"),
        _control("textbox-email", "textbox", "Email", required=True),
        _control("checkbox-agree", "checkbox", "I agree", checked=False, required=True),
        _control("select-country", "combobox", "Country"),
        _control("button-submit", "button", "Submit"),
        _control(
            "password-current",
            "textbox",
            "Password",
            required=True,
            value_summary="[redacted sensitive field]",
            risk_hint="sensitive_input",
        ),
        _control("link-billing", "link", "Billing Portal", risk_hint="payment_context"),
    ]
    if extra_controls:
        controls.extend(extra_controls)
    return BrowserSemanticObservation(
        provider="playwright_live_semantic",
        adapter_id="screen_awareness.browser.playwright",
        session_id="action-preview-fixture",
        page_url="https://example.test/checkout",
        page_title="Example Checkout",
        browser_context_kind="isolated_playwright_context",
        observed_at=datetime.now(UTC).isoformat(),
        controls=controls,
        forms=[{"form_id": "checkout", "name": "Checkout", "field_count": 5}],
        limitations=[
            "live_semantic_observation_only",
            "isolated_temporary_browser_context",
            "no_actions",
            "not_visible_screen_verification",
        ],
        confidence=0.84,
    )


def test_action_preview_models_serialize_as_preview_only() -> None:
    preview = BrowserSemanticActionPreview(
        observation_id="obs-1",
        source_provider="playwright_live_semantic",
        target_phrase="Continue button",
        target_candidate_id="candidate-1",
        target_role="button",
        target_name="Continue",
        action_kind="click",
        confidence=0.82,
        risk_level="medium",
        approval_required=True,
        required_trust_scope="browser_action_once_future",
        expected_outcome=["page_url_changed"],
        verification_strategy="semantic_before_after_comparison_required",
    )
    plan = BrowserSemanticActionPlan(
        preview_id=preview.preview_id,
        observation_id=preview.observation_id,
        target_candidate={"candidate_id": "candidate-1", "name": "Continue"},
        action_kind=preview.action_kind,
        adapter_capability_required="browser.input.click",
        verification_request_template={"expected_change_kind": "page_url_changed"},
    )

    payload = preview.to_dict()
    plan_payload = plan.to_dict()

    assert payload["claim_ceiling"] == "browser_semantic_action_preview"
    assert payload["action_supported_now"] is False
    assert payload["executable_now"] is False
    assert payload["reason_not_executable"] == "action_execution_deferred"
    assert payload["approval_required"] is True
    assert plan_payload["result_state"] == "preview_only"
    assert plan_payload["adapter_capability_declared"] is False
    assert plan_payload["executable_now"] is False


def test_click_preview_clear_target_is_non_executable_and_evented() -> None:
    events = EventBuffer(capacity=16)
    adapter = _adapter(events=events)
    observation = _observation()

    preview = adapter.preview_semantic_action(
        observation,
        target_phrase="Continue button",
        action_phrase="click Continue",
    )
    plan = adapter.build_semantic_action_plan(preview)
    action_events = [event for event in events.recent(limit=16) if "action_preview" in str(event.get("event_type") or "") or "action_plan" in str(event.get("event_type") or "")]
    event_text = str(action_events).lower()

    assert preview.action_kind == "click"
    assert preview.target_name == "Continue"
    assert preview.preview_state == "preview_only"
    assert preview.action_supported_now is False
    assert preview.executable_now is False
    assert preview.risk_level == "medium"
    assert preview.approval_required is True
    assert preview.required_trust_scope == "browser_action_once_future"
    assert "page_url_changed" in preview.expected_outcome
    assert plan.result_state == "preview_only"
    assert plan.adapter_capability_required == "browser.input.click"
    assert plan.adapter_capability_declared is False
    assert "screen_awareness.playwright_action_preview_created" in event_text
    assert "screen_awareness.playwright_action_plan_created" in event_text
    assert "clicked" not in event_text
    assert "completed" not in event_text


def test_type_select_check_submit_and_sensitive_previews_are_bounded() -> None:
    adapter = _adapter()
    observation = _observation()

    type_preview = adapter.preview_semantic_action(
        observation,
        target_phrase="Email field",
        action_phrase="type super-secret@example.test into Email",
        action_arguments={"text": "super-secret@example.test"},
    )
    check_preview = adapter.preview_semantic_action(observation, "I agree checkbox", "check the box")
    uncheck_preview = adapter.preview_semantic_action(observation, "I agree checkbox", "uncheck the box")
    select_preview = adapter.preview_semantic_action(
        observation,
        "Country dropdown",
        "select Canada",
        action_arguments={"option": "Canada"},
    )
    submit_preview = adapter.preview_semantic_action(observation, "last button", "submit the form")
    password_preview = adapter.preview_semantic_action(
        observation,
        "Password field",
        "type hunter2 into Password",
        action_arguments={"text": "hunter2"},
    )
    billing_preview = adapter.preview_semantic_action(observation, "Billing Portal link", "click billing")
    plan_text = str(adapter.build_semantic_action_plan(type_preview).to_dict()).lower()

    assert type_preview.action_kind == "type_text"
    assert type_preview.risk_level == "high"
    assert type_preview.required_trust_scope == "browser_action_strong_confirmation_future"
    assert "value_summary_changed" in type_preview.expected_outcome
    assert "super-secret" not in str(type_preview.to_dict()).lower()
    assert "super-secret" not in plan_text
    assert check_preview.action_kind == "check"
    assert uncheck_preview.action_kind == "uncheck"
    assert check_preview.expected_outcome == ["checked_state_changed"]
    assert select_preview.action_kind == "select_option"
    assert submit_preview.action_kind == "submit_form"
    assert submit_preview.risk_level == "high"
    assert password_preview.preview_state == "blocked"
    assert password_preview.risk_level == "blocked"
    assert password_preview.required_trust_scope == "blocked_until_future_policy"
    assert "sensitive_or_restricted_context" in password_preview.limitations
    assert billing_preview.preview_state == "blocked"
    assert "payment_or_restricted_context" in billing_preview.limitations


def test_ambiguous_and_unsupported_action_previews_do_not_fake_capability() -> None:
    adapter = _adapter()
    observation = _observation(extra_controls=[_control("button-continue-secondary", "button", "Continue")])

    ambiguous = adapter.preview_semantic_action(observation, "Continue button", "click Continue")
    unsupported = adapter.preview_semantic_action(observation, "Email field", "teleport the email field")
    no_target = adapter.preview_semantic_action(observation, "Delete account button", "click delete")

    assert ambiguous.preview_state == "ambiguous"
    assert ambiguous.executable_now is False
    assert ambiguous.action_kind == "click"
    assert "ambiguous_target" in ambiguous.limitations
    assert unsupported.preview_state == "unsupported"
    assert unsupported.action_kind == "unsupported"
    assert unsupported.reason_not_executable == "unsupported_action_preview"
    assert no_target.preview_state == "unsupported"
    assert "target_not_grounded" in no_target.limitations


def test_service_status_deck_and_events_surface_preview_without_execute_controls() -> None:
    events = EventBuffer(capacity=32)
    subsystem = build_screen_awareness_subsystem(_enabled_config(), events=events)
    observation = _observation()

    preview = subsystem.preview_playwright_browser_action(
        observation,
        target_phrase="Continue button",
        action_phrase="click Continue",
    )
    plan = subsystem.build_playwright_browser_action_plan(preview)
    status = {"screen_awareness": subsystem.status_snapshot()}
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "browser action preview",
            "parameters": {"result_state": "attempted", "request_stage": "preview"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": "Action preview ready. Execution is not enabled yet.",
            "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}},
        },
        status=status,
        workspace_focus={},
    )
    station = next(item for item in surface["deckStations"] if item["stationFamily"] == "screen_awareness")
    station_text = str(station).lower()
    event_text = str(events.recent(limit=32)).lower()
    latest = status["screen_awareness"]["browser_adapters"]["playwright"]["last_action_preview_summary"]

    assert preview.preview_state == "preview_only"
    assert plan.result_state == "preview_only"
    assert latest["action_kind"] == "click"
    assert latest["executable_now"] is False
    assert "action preview" in station_text
    assert "execution is not enabled" in station_text
    assert "future check" in station_text
    assert "screen_awareness.playwright_action_preview_created" in event_text
    assert "screen_awareness.playwright_action_plan_created" in event_text
    assert "clicked" not in station_text
    assert "typed" not in station_text
    assert "submitted" not in station_text
    assert "approved" not in station_text
    assert "verified" not in station_text
    assert "action_executed" not in event_text


def test_adapter_contract_declares_preview_only_and_no_action_capabilities() -> None:
    contract = default_adapter_contract_registry().get_contract("screen_awareness.browser.playwright")
    declared = set(contract.observation_modes) | set(contract.preview_modes) | set(contract.action_modes) | set(contract.artifact_modes)

    assert "browser.action.preview" in contract.preview_modes
    assert "browser.action.plan_preview" in contract.preview_modes
    assert "browser_semantic_action_preview" in contract.artifact_modes
    assert "browser.input.click" not in declared
    assert "browser.input.type" not in declared
    assert "browser.input.scroll" not in declared
    assert "browser.form.fill" not in declared
    assert "browser.form.submit" not in declared
    assert "browser.login" not in declared
    assert "browser.cookies.read" not in declared
    assert "browser.download" not in declared
    assert "browser.payment" not in declared
    assert "browser.workflow_replay" not in declared
