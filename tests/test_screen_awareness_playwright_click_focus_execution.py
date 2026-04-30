from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.screen_awareness import BrowserSemanticActionExecutionResult
from stormhelm.core.screen_awareness import BrowserSemanticControl
from stormhelm.core.screen_awareness import BrowserSemanticObservation
from stormhelm.core.screen_awareness import PlaywrightBrowserSemanticAdapter
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.core.trust import PermissionScope
from stormhelm.ui.command_surface_v2 import build_command_surface_model


def _execution_config(*, click: bool = True, focus: bool = True) -> ScreenAwarenessConfig:
    config = ScreenAwarenessConfig()
    playwright = config.browser_adapters.playwright
    playwright.enabled = True
    playwright.allow_dev_adapter = True
    playwright.allow_browser_launch = True
    playwright.allow_actions = True
    playwright.allow_dev_actions = True
    playwright.allow_click = click
    playwright.allow_focus = focus
    return config


def _safe_control(
    control_id: str,
    role: str,
    name: str,
    *,
    selector_hint: str = "",
    enabled: bool = True,
    visible: bool = True,
    value_summary: str = "",
    risk_hint: str = "",
) -> BrowserSemanticControl:
    return BrowserSemanticControl(
        control_id=control_id,
        role=role,
        name=name,
        label=name,
        text=name,
        selector_hint=selector_hint,
        enabled=enabled,
        visible=visible,
        value_summary=value_summary,
        risk_hint=risk_hint,
        confidence=0.9,
    )


def _plan_observation() -> BrowserSemanticObservation:
    return BrowserSemanticObservation(
        provider="playwright_live_semantic",
        adapter_id="screen_awareness.browser.playwright",
        session_id="execution-plan",
        page_url="http://127.0.0.1:60231/click.html",
        page_title="Action Fixture",
        browser_context_kind="isolated_playwright_context",
        observed_at=datetime.now(UTC).isoformat(),
        controls=[
            _safe_control("button-continue", "button", "Continue", selector_hint="#continue"),
            _safe_control("textbox-email", "textbox", "Email", selector_hint="#email"),
            _safe_control(
                "password-current",
                "textbox",
                "Password",
                selector_hint="#password",
                value_summary="[redacted sensitive field]",
                risk_hint="sensitive_input",
            ),
        ],
        dialogs=[{"dialog_id": "warning", "role": "alert", "text": "Warning still present"}],
        alerts=[{"alert_id": "warning", "role": "alert", "text": "Warning still present"}],
        limitations=["live_semantic_observation_only", "isolated_temporary_browser_context"],
        confidence=0.9,
    )


def _payload_control(
    control_id: str,
    role: str,
    name: str,
    *,
    selector_hint: str,
    enabled: bool = True,
    visible: bool = True,
    value_summary: str = "",
    risk_hint: str = "",
) -> dict[str, Any]:
    return {
        "control_id": control_id,
        "role": role,
        "name": name,
        "label": name,
        "text": name,
        "selector_hint": selector_hint,
        "enabled": enabled,
        "visible": visible,
        "checked": False,
        "expanded": None,
        "required": False,
        "readonly": False,
        "value_summary": value_summary,
        "risk_hint": risk_hint,
        "confidence": 0.9,
    }


class _FakeActionLocator:
    def __init__(self, page: "_FakeActionPage", *, selector: str = "", role: str = "", name: str = "") -> None:
        self.page = page
        self.selector = selector
        self.role = role
        self.name = name

    def evaluate_all(self, _script: str) -> list[dict[str, Any]]:
        if self.page.scenario == "after_snapshot_failure" and self.page.state == "after_click":
            raise RuntimeError("after snapshot failed")
        if self.selector == "button, input, textarea, select, a, [role]":
            return self.page.controls()
        if self.selector == "form, [role='form'], [data-form], .form":
            return []
        if self.selector == "dialog, [role='dialog'], [role='alert'], [aria-modal='true']":
            return self.page.dialogs()
        if self.selector == "h1, h2, h3, p, li, [role='heading']":
            return [{"text": "Action fixture", "role": "h1", "name": "heading"}]
        return []

    def count(self) -> int:
        return len(self._matches())

    def click(self, *, timeout: int | None = None) -> None:
        del timeout
        matches = self._matches()
        if len(matches) != 1:
            raise RuntimeError("locator is ambiguous")
        self.page.actions.append(("click", matches[0]["name"]))
        self.page.state = "after_click"

    def focus(self, *, timeout: int | None = None) -> None:
        del timeout
        matches = self._matches()
        if len(matches) != 1:
            raise RuntimeError("locator is ambiguous")
        self.page.actions.append(("focus", matches[0]["name"]))
        self.page.focused_name = matches[0]["name"]
        self.page.state = "after_focus"

    def _matches(self) -> list[dict[str, Any]]:
        controls = self.page.controls()
        if self.role:
            if self.page.scenario == "role_locator_duplicate" and self.role == "button" and self.name == "Continue":
                return [
                    _payload_control("button-continue", "button", "Continue", selector_hint="#continue"),
                    _payload_control("button-continue-duplicate", "button", "Continue", selector_hint="#continue-duplicate"),
                ]
            return [
                control
                for control in controls
                if str(control.get("role")).lower() == self.role.lower()
                and (not self.name or str(control.get("name")).lower() == self.name.lower())
            ]
        if self.selector.startswith("#"):
            if self.page.scenario == "selector_disagrees" and self.selector == "#continue":
                return []
            return [control for control in controls if control.get("selector_hint") == self.selector]
        return []


class _FakeActionPage:
    def __init__(self, *, scenario: str = "normal") -> None:
        self.scenario = scenario
        self.url = ""
        self.state = "before"
        self.actions: list[tuple[str, str]] = []
        self.focused_name = ""

    def goto(self, url: str, *, wait_until: str = "", timeout: int = 0) -> None:
        del wait_until, timeout
        self.url = url
        self.state = "before"

    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    def locator(self, selector: str) -> _FakeActionLocator:
        return _FakeActionLocator(self, selector=selector)

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool | None = None) -> _FakeActionLocator:
        del exact
        return _FakeActionLocator(self, role=role, name=name or "")

    def title(self) -> str:
        if self.scenario == "after_snapshot_failure" and self.state == "after_click":
            return ""
        if self.state == "after_click":
            return "Action Fixture Updated"
        return "Action Fixture"

    def evaluate(self, _script: str) -> dict[str, Any]:
        return {
            "ready_state": "complete",
            "control_count": len(self.controls()),
            "iframe_count": 0,
            "cross_origin_iframe_count": 0,
            "shadow_host_count": 0,
            "form_like_count": 0,
        }

    def controls(self) -> list[dict[str, Any]]:
        return [
            _payload_control("button-continue", "button", "Continue", selector_hint="#continue"),
            _payload_control("textbox-email", "textbox", "Email", selector_hint="#email"),
            _payload_control(
                "password-current",
                "textbox",
                "Password",
                selector_hint="#password",
                value_summary="[redacted sensitive field]",
                risk_hint="sensitive_input",
            ),
        ]

    def dialogs(self) -> list[dict[str, Any]]:
        if self.state == "after_click":
            return []
        return [{"dialog_id": "warning", "alert_id": "warning", "role": "alert", "name": "Warning", "text": "Warning still present"}]


class _FakeActionContext:
    def __init__(self, page: _FakeActionPage, *, scenario: str = "normal") -> None:
        self.page = page
        self.scenario = scenario
        self.clear_cookies_called = False
        self.closed = False
        self.playwright_manager_stopped = False

    def new_page(self) -> _FakeActionPage:
        return self.page

    def clear_cookies(self) -> None:
        if self.playwright_manager_stopped and self.scenario == "manager_stopped_before_cleanup":
            raise RuntimeError("Event loop is closed! Is Playwright already stopped?")
        self.clear_cookies_called = True

    def close(self) -> None:
        if self.playwright_manager_stopped and self.scenario == "manager_stopped_before_cleanup":
            raise RuntimeError("Event loop is closed! Is Playwright already stopped?")
        self.closed = True


class _FakeActionBrowser:
    def __init__(self, context: _FakeActionContext, *, scenario: str = "normal") -> None:
        self.context = context
        self.scenario = scenario
        self.closed = False
        self.playwright_manager_stopped = False

    def new_context(self, **kwargs: Any) -> _FakeActionContext:
        assert kwargs.get("storage_state") is None
        assert "user_data_dir" not in kwargs
        return self.context

    def close(self) -> None:
        if self.playwright_manager_stopped and self.scenario == "manager_stopped_before_cleanup":
            raise RuntimeError("Event loop is closed! Is Playwright already stopped?")
        self.closed = True


class _FakeActionChromium:
    def __init__(self, browser: _FakeActionBrowser) -> None:
        self.browser = browser

    def launch(self, *, headless: bool = True) -> _FakeActionBrowser:
        assert headless is True
        return self.browser


class _FakeActionPlaywright:
    def __init__(self, *, scenario: str = "normal") -> None:
        self.page = _FakeActionPage(scenario=scenario)
        self.context = _FakeActionContext(self.page, scenario=scenario)
        self.browser = _FakeActionBrowser(self.context, scenario=scenario)
        self.chromium = _FakeActionChromium(self.browser)

    def __enter__(self) -> "_FakeActionPlaywright":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.context.playwright_manager_stopped = True
        self.browser.playwright_manager_stopped = True
        return None


def _subsystem_with_fake(
    config: ScreenAwarenessConfig,
    fake: _FakeActionPlaywright,
    *,
    events: EventBuffer | None = None,
):
    subsystem = build_screen_awareness_subsystem(config, events=events)
    subsystem.playwright_browser_adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: True,
        browser_engine_checker=lambda: True,
        sync_playwright_factory=lambda: fake,
        events=events,
    )
    return subsystem


def _approved_click_plan(subsystem) -> Any:
    observation = _plan_observation()
    preview = subsystem.preview_playwright_browser_action(
        observation,
        target_phrase="Continue button",
        action_phrase="click Continue",
    )
    return subsystem.build_playwright_browser_action_plan(preview)


def test_action_execution_models_serialize_precise_non_truthful_status() -> None:
    result = BrowserSemanticActionExecutionResult(
        request_id="exec-1",
        action_kind="click",
        status="completed_unverified",
        action_attempted=True,
        action_completed=True,
        verification_attempted=True,
        verification_status="unsupported",
        target_summary={"role": "button", "name": "Continue"},
        provider="playwright_live_semantic",
    )
    payload = result.to_dict()

    assert payload["claim_ceiling"] == "browser_semantic_action_execution"
    assert payload["action_attempted"] is True
    assert payload["action_completed"] is True
    assert payload["status"] == "completed_unverified"
    assert "visible" not in payload["claim_ceiling"]
    assert "truth" not in payload["claim_ceiling"]


def test_click_execution_requires_approval_before_playwright_action(trust_harness) -> None:
    events = EventBuffer(capacity=64)
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake, events=events)
    plan = _approved_click_plan(subsystem)

    result = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    event_text = str(events.recent(limit=64)).lower()

    assert result.status == "approval_required"
    assert result.action_attempted is False
    assert result.action_completed is False
    assert result.trust_scope == "once"
    assert result.approval_request_id
    assert fake.page.actions == []
    assert "screen_awareness.playwright_action_approval_required" in event_text
    assert "screen_awareness.playwright_action_execution_started" not in event_text


def test_approved_click_executes_in_isolated_context_and_verifies_warning_removed(trust_harness) -> None:
    events = EventBuffer(capacity=96)
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake, events=events)
    plan = _approved_click_plan(subsystem)

    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]
    event_text = str(events.recent(limit=96)).lower()

    assert result.status == "verified_supported"
    assert result.action_attempted is True
    assert result.action_completed is True
    assert result.verification_attempted is True
    assert result.verification_status == "supported"
    assert result.comparison_result_id
    assert result.before_observation_id
    assert result.after_observation_id
    assert ("click", "Continue") in fake.page.actions
    assert fake.context.clear_cookies_called is True
    assert fake.context.closed is True
    assert fake.browser.closed is True
    assert status["last_action_execution_summary"]["status"] == "verified_supported"
    assert status["last_action_execution_summary"]["action_kind"] == "click"
    assert "browser_semantic_action_execution" in status["last_action_execution_summary"]["claim_ceiling"]
    assert "screen_awareness.playwright_action_execution_attempted" in event_text
    assert "screen_awareness.playwright_action_verification_completed" in event_text
    assert "typed" not in event_text
    assert "submitted" not in event_text


def test_stale_plan_blocks_before_approval_or_browser_launch(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake)
    plan = _approved_click_plan(subsystem)
    plan.created_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()

    result = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "blocked"
    assert result.error_code == "blocked_stale_plan"
    assert result.action_attempted is False
    assert result.approval_request_id == ""
    assert result.cleanup_status == "not_started"
    assert fake.page.url == ""
    assert fake.page.actions == []


def test_approval_for_one_target_cannot_execute_mutated_target(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake)
    plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    mutated_target = dict(plan.target_candidate)
    mutated_target["name"] = "Cancel"
    mutated_target["label"] = "Cancel"
    mutated_target["target_fingerprint"] = "tampered"
    mutated_plan = replace(plan, target_candidate=mutated_target)

    result = subsystem.execute_playwright_browser_action(
        mutated_plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "blocked"
    assert result.error_code == "approval_invalid"
    assert result.action_attempted is False
    assert result.cleanup_status == "not_started"
    assert fake.page.url == ""
    assert fake.page.actions == []


def test_role_locator_and_selector_hint_disagreement_blocks_click(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="selector_disagrees")
    subsystem = _subsystem_with_fake(_execution_config(), fake)
    plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "blocked"
    assert result.error_code == "locator_selector_disagrees"
    assert result.action_attempted is False
    assert result.before_observation_id
    assert result.cleanup_status == "closed"
    assert fake.page.actions == []


def test_multiple_role_locator_matches_block_click_without_using_first_match(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="role_locator_duplicate")
    subsystem = _subsystem_with_fake(_execution_config(), fake)
    plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "blocked"
    assert result.error_code == "locator_ambiguous"
    assert result.action_attempted is False
    assert result.cleanup_status == "closed"
    assert fake.page.actions == []


def test_after_observation_failure_returns_completed_unverified_and_cleans_up(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="after_snapshot_failure")
    events = EventBuffer(capacity=128)
    subsystem = _subsystem_with_fake(_execution_config(), fake, events=events)
    plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    event_text = str(events.recent(limit=128)).lower()

    assert result.status == "completed_unverified"
    assert result.error_code == "after_observation_failed"
    assert result.action_attempted is True
    assert result.action_completed is True
    assert result.verification_attempted is False
    assert result.cleanup_status == "closed"
    assert fake.context.clear_cookies_called is True
    assert fake.context.closed is True
    assert fake.browser.closed is True
    assert "screen_awareness.playwright_action_command_returned" in event_text
    assert "screen_awareness.playwright_action_after_observation_started" in event_text
    assert "screen_awareness.playwright_action_execution_failed" not in event_text


def test_live_observation_cleanup_runs_before_playwright_manager_stops() -> None:
    fake = _FakeActionPlaywright(scenario="manager_stopped_before_cleanup")
    subsystem = _subsystem_with_fake(_execution_config(), fake)

    observation = subsystem.observe_playwright_live_browser_page(
        "http://127.0.0.1:60231/click.html",
        fixture_mode=True,
    )

    assert observation.provider == "playwright_live_semantic"
    assert fake.context.clear_cookies_called is True
    assert fake.context.closed is True
    assert fake.browser.closed is True
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]
    assert status["last_observation_summary"]["provider"] == "playwright_live_semantic"
    assert "cleanup_failed" not in str(status).lower()


def test_action_cleanup_runs_before_playwright_manager_stops(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="manager_stopped_before_cleanup")
    events = EventBuffer(capacity=128)
    subsystem = _subsystem_with_fake(_execution_config(), fake, events=events)
    plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    event_text = str(events.recent(limit=128)).lower()

    assert result.status == "verified_supported"
    assert result.cleanup_status == "closed"
    assert result.error_code == ""
    assert "cleanup_failed" not in result.limitations
    assert fake.context.clear_cookies_called is True
    assert fake.context.closed is True
    assert fake.browser.closed is True
    assert "playwright_cleanup_failed" not in event_text


def test_focus_execution_is_low_risk_and_does_not_type_or_overclaim_verification(trust_harness) -> None:
    events = EventBuffer(capacity=96)
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake, events=events)
    observation = _plan_observation()
    preview = subsystem.preview_playwright_browser_action(observation, "Email field", "focus email field")
    plan = subsystem.build_playwright_browser_action_plan(preview)

    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert preview.action_kind == "focus"
    assert preview.risk_level == "low"
    assert result.action_attempted is True
    assert result.action_completed is True
    assert result.status == "completed_unverified"
    assert result.verification_attempted is True
    assert result.user_message == "Focus was attempted, but semantic comparison did not support the expected change."
    assert ("focus", "Email") in fake.page.actions
    assert all(action[0] != "type" for action in fake.page.actions)


def test_consumed_once_grant_cannot_be_reused_for_second_click(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake)
    plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    first = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    second = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert first.action_attempted is True
    assert second.status == "approval_required"
    assert second.action_attempted is False
    assert fake.page.actions.count(("click", "Continue")) == 1


def test_denied_approval_blocks_without_launching_playwright(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake)
    plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="deny",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "blocked"
    assert result.error_code == "approval_denied"
    assert result.action_attempted is False
    assert result.cleanup_status == "not_started"
    assert fake.page.url == ""
    assert fake.page.actions == []


def test_expired_grant_requires_fresh_approval_before_click(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake)
    plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_service = trust_harness["trust_service"]
    trust_service.respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    grant = trust_service.repository.list_grants(session_id="default")[0]
    grant.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    trust_service.repository.save_grant(grant)

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_service,
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "approval_required"
    assert result.action_attempted is False
    assert result.cleanup_status == "not_started"
    assert fake.page.actions == []


def test_click_grant_cannot_authorize_focus_action(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake)
    click_plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        click_plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    focus_plan = subsystem.build_playwright_browser_action_plan(
        subsystem.preview_playwright_browser_action(_plan_observation(), "Email field", "focus email field")
    )
    focus_plan = replace(focus_plan, plan_id=click_plan.plan_id)

    result = subsystem.execute_playwright_browser_action(
        focus_plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "approval_required"
    assert result.action_attempted is False
    assert result.cleanup_status == "not_started"
    assert fake.page.actions == []


def test_unsupported_type_scroll_submit_and_sensitive_focus_stay_blocked(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(), fake)
    observation = _plan_observation()

    type_plan = subsystem.build_playwright_browser_action_plan(
        subsystem.preview_playwright_browser_action(
            observation,
            target_phrase="Email field",
            action_phrase="type hello@example.test into Email",
            action_arguments={"text": "hello@example.test"},
        ),
        action_arguments={"text": "hello@example.test"},
    )
    password_plan = subsystem.build_playwright_browser_action_plan(
        subsystem.preview_playwright_browser_action(observation, "Password field", "focus password field")
    )
    type_result = subsystem.execute_playwright_browser_action(
        type_plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    password_result = subsystem.execute_playwright_browser_action(
        password_plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]

    assert type_result.status == "unsupported"
    assert type_result.error_code == "unsupported_action_kind"
    assert type_result.action_attempted is False
    assert password_result.status == "blocked"
    assert password_result.error_code == "restricted_context_deferred"
    assert password_result.action_attempted is False
    assert "browser.input.click" in status["declared_action_capabilities"]
    assert "browser.input.focus" in status["declared_action_capabilities"]
    assert "browser.input.type" not in status["declared_action_capabilities"]
    assert "browser.form.submit" not in status["declared_action_capabilities"]
    assert fake.page.actions == []


def test_deck_payload_surfaces_execution_state_without_active_execute_control(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    events = EventBuffer(capacity=96)
    subsystem = _subsystem_with_fake(_execution_config(), fake, events=events)
    plan = _approved_click_plan(subsystem)
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/click.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "browser action execution",
            "parameters": {"result_state": "attempted", "request_stage": "execution"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": "The expected semantic change is supported.",
            "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}},
        },
        status={"screen_awareness": subsystem.status_snapshot()},
        workspace_focus={},
    )
    station = next(item for item in surface["deckStations"] if item["stationFamily"] == "screen_awareness")
    station_text = str(station).lower()

    assert "action execution" in station_text
    assert "verified supported" in station_text
    assert "cleanup: closed" in station_text
    assert "browser semantic action execution" in station_text
    assert "execute now" not in station_text
    assert "typed" not in station_text
    assert "submitted" not in station_text
