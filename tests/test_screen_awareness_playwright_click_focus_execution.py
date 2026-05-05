from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.screen_awareness import BrowserSemanticActionExecutionResult
from stormhelm.core.screen_awareness import ActionExecutionStatus
from stormhelm.core.screen_awareness import BrowserSemanticControl
from stormhelm.core.screen_awareness import BrowserSemanticObservation
from stormhelm.core.screen_awareness import PlaywrightBrowserSemanticAdapter
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.core.trust import PermissionScope
from stormhelm.ui.command_surface_v2 import build_command_surface_model


def _execution_config(
    *,
    click: bool = True,
    focus: bool = True,
    type_text: bool = False,
    dev_type_text: bool = False,
    check: bool = False,
    uncheck: bool = False,
    select_option: bool = False,
    dev_choice_controls: bool = False,
    scroll: bool = False,
    scroll_to_target: bool = False,
    dev_scroll: bool = False,
) -> ScreenAwarenessConfig:
    config = ScreenAwarenessConfig()
    playwright = config.browser_adapters.playwright
    playwright.enabled = True
    playwright.allow_dev_adapter = True
    playwright.allow_browser_launch = True
    playwright.allow_actions = True
    playwright.allow_dev_actions = True
    playwright.allow_click = click
    playwright.allow_focus = focus
    playwright.allow_type_text = type_text
    playwright.allow_dev_type_text = dev_type_text
    playwright.allow_check = check
    playwright.allow_uncheck = uncheck
    playwright.allow_select_option = select_option
    playwright.allow_dev_choice_controls = dev_choice_controls
    playwright.allow_scroll = scroll
    playwright.allow_scroll_to_target = scroll_to_target
    playwright.allow_dev_scroll = dev_scroll
    playwright.max_scroll_attempts = 3
    playwright.scroll_step_pixels = 700
    playwright.max_scroll_distance_pixels = 2100
    return config


def _safe_control(
    control_id: str,
    role: str,
    name: str,
    *,
    selector_hint: str = "",
    enabled: bool = True,
    visible: bool = True,
    readonly: bool = False,
    checked: bool | None = None,
    value_summary: str = "",
    risk_hint: str = "",
    options: list[dict[str, Any]] | None = None,
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
        readonly=readonly,
        checked=checked,
        value_summary=value_summary,
        risk_hint=risk_hint,
        options=list(options or []),
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
            _safe_control("textbox-notes", "textbox", "Notes", selector_hint="#notes"),
            _safe_control(
                "password-current",
                "textbox",
                "Password",
                selector_hint="#password",
                value_summary="[redacted sensitive field]",
                risk_hint="sensitive_input",
            ),
            _safe_control("checkbox-newsletter", "checkbox", "Newsletter", selector_hint="#newsletter", checked=False),
            _safe_control("checkbox-subscribed", "checkbox", "Already subscribed", selector_hint="#subscribed", checked=True),
            _safe_control("radio-student", "radio", "Student", selector_hint="#student", checked=False),
            _safe_control("radio-teacher", "radio", "Teacher", selector_hint="#teacher", checked=False),
            _safe_control(
                "select-country",
                "combobox",
                "Country",
                selector_hint="#country",
                value_summary="selected option: United States",
                options=[
                    {"label": "United States", "value_summary": "us", "selected": True, "disabled": False, "ordinal": 1},
                    {"label": "Canada", "value_summary": "ca", "selected": False, "disabled": False, "ordinal": 2},
                    {"label": "Disabled Option", "value_summary": "disabled", "selected": False, "disabled": True, "ordinal": 3},
                ],
            ),
            _safe_control(
                "checkbox-terms",
                "checkbox",
                "I agree to terms",
                selector_hint="#terms",
                checked=False,
                risk_hint="legal_terms_consent",
            ),
            _safe_control(
                "checkbox-privacy",
                "checkbox",
                "Privacy consent",
                selector_hint="#privacy",
                checked=False,
                risk_hint="privacy consent legal",
            ),
            _safe_control(
                "checkbox-payment",
                "checkbox",
                "Authorize payment",
                selector_hint="#payment",
                checked=False,
                risk_hint="payment authorization",
            ),
            _safe_control(
                "checkbox-captcha",
                "checkbox",
                "CAPTCHA human verification",
                selector_hint="#captcha",
                checked=False,
                risk_hint="captcha human verification",
            ),
            _safe_control(
                "checkbox-delete",
                "checkbox",
                "Delete confirmation",
                selector_hint="#delete-confirm",
                checked=False,
                risk_hint="delete confirmation permanent",
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
    readonly: bool = False,
    checked: bool = False,
    value_summary: str = "",
    risk_hint: str = "",
    options: list[dict[str, Any]] | None = None,
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
        "checked": checked,
        "expanded": None,
        "required": False,
        "readonly": readonly,
        "value_summary": value_summary,
        "risk_hint": risk_hint,
        "options": list(options or []),
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

    def fill(self, text: str, *, timeout: int | None = None) -> None:
        del timeout
        matches = self._matches()
        if len(matches) != 1:
            raise RuntimeError("locator is ambiguous")
        if self.page.scenario == "type_no_value_change":
            self.page.actions.append(("type_text", matches[0]["name"], text))
            self.page.state = "after_type"
            return
        self.page.actions.append(("type_text", matches[0]["name"], text))
        self.page.filled_values[matches[0]["name"]] = text
        self.page.state = "after_type"

    def check(self, *, timeout: int | None = None) -> None:
        del timeout
        matches = self._matches()
        if len(matches) != 1:
            raise RuntimeError("locator is ambiguous")
        self.page.actions.append(("check", matches[0]["name"]))
        if matches[0].get("role") == "radio":
            self.page.selected_radio = matches[0]["name"]
        else:
            self.page.checked_values[matches[0]["name"]] = True
        if self.page.scenario == "choice_submit_on_change":
            self.page.submit_count += 1
        if self.page.scenario == "choice_unexpected_navigation":
            self.page.url = "http://127.0.0.1:60231/unexpected-choice-navigation.html"
        self.page.state = "after_choice"

    def uncheck(self, *, timeout: int | None = None) -> None:
        del timeout
        matches = self._matches()
        if len(matches) != 1:
            raise RuntimeError("locator is ambiguous")
        self.page.actions.append(("uncheck", matches[0]["name"]))
        self.page.checked_values[matches[0]["name"]] = False
        if self.page.scenario == "choice_submit_on_change":
            self.page.submit_count += 1
        if self.page.scenario == "choice_unexpected_navigation":
            self.page.url = "http://127.0.0.1:60231/unexpected-choice-navigation.html"
        self.page.state = "after_choice"

    def select_option(self, *args: Any, **kwargs: Any) -> list[str]:
        del args
        matches = self._matches()
        if len(matches) != 1:
            raise RuntimeError("locator is ambiguous")
        label = str(kwargs.get("label") or "")
        value = str(kwargs.get("value") or "")
        index = kwargs.get("index")
        control = next(item for item in self.page.controls() if item["control_id"] == matches[0]["control_id"])
        options = list(control.get("options") or [])
        selected = None
        if label:
            selected = next((option for option in options if option.get("label") == label), None)
        elif value:
            selected = next((option for option in options if option.get("value_summary") == value), None)
        elif index is not None:
            selected = next((option for option in options if option.get("ordinal") == int(index) + 1), None)
        if selected is None:
            raise RuntimeError("option missing")
        self.page.actions.append(("select_option", matches[0]["name"], selected["label"]))
        self.page.selected_options[matches[0]["name"]] = selected["label"]
        if self.page.scenario == "choice_submit_on_change":
            self.page.submit_count += 1
        if self.page.scenario == "choice_unexpected_navigation":
            self.page.url = "http://127.0.0.1:60231/unexpected-choice-navigation.html"
        self.page.state = "after_choice"
        return [str(selected.get("value_summary") or selected["label"])]

    def press(self, key: str, *, timeout: int | None = None) -> None:
        del timeout
        self.page.actions.append(("press", key))
        if str(key).lower() == "enter":
            self.page.enter_pressed = True
            self.page.submit_count += 1

    def dispatch_event(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.page.actions.append(("dispatch_event", event_name))
        if str(event_name).lower() == "submit":
            self.page.submit_count += 1

    def evaluate(self, script: str, *args: Any) -> bool:
        del args
        if "submit" in str(script).lower():
            self.page.actions.append(("evaluate_submit", "script"))
            self.page.submit_count += 1
        return True

    def _matches(self) -> list[dict[str, Any]]:
        controls = self.page.controls()
        if self.role:
            if self.page.scenario == "role_locator_duplicate" and self.role == "button" and self.name == "Continue":
                return [
                    _payload_control("button-continue", "button", "Continue", selector_hint="#continue"),
                    _payload_control("button-continue-duplicate", "button", "Continue", selector_hint="#continue-duplicate"),
                ]
            if self.page.scenario == "type_locator_duplicate" and self.role == "textbox" and self.name == "Email":
                return [
                    _payload_control("textbox-email", "textbox", "Email", selector_hint="#email"),
                    _payload_control("textbox-email-duplicate", "textbox", "Email", selector_hint="#email-duplicate"),
                ]
            if self.page.scenario == "type_role_locator_duplicate" and self.role == "textbox" and self.name == "Email":
                return [
                    _payload_control("textbox-email", "textbox", "Email", selector_hint="#email"),
                    _payload_control("textbox-email-locator-only", "textbox", "Email", selector_hint="#email-shadow"),
                ]
            if self.page.scenario == "choice_role_locator_duplicate" and self.role == "checkbox" and self.name == "Newsletter":
                return [
                    _payload_control("checkbox-newsletter", "checkbox", "Newsletter", selector_hint="#newsletter"),
                    _payload_control("checkbox-newsletter-copy", "checkbox", "Newsletter", selector_hint="#newsletter-copy"),
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


class _FakeMouse:
    def __init__(self, page: "_FakeActionPage") -> None:
        self.page = page

    def wheel(self, delta_x: int, delta_y: int) -> None:
        del delta_x
        self.page.scroll_by(delta_y)


class _FakeActionPage:
    def __init__(self, *, scenario: str = "normal") -> None:
        self.scenario = scenario
        self.url = ""
        self.state = "before"
        self.actions: list[tuple[str, str]] = []
        self.focused_name = ""
        self.filled_values: dict[str, str] = {}
        self.checked_values: dict[str, bool] = {}
        self.selected_radio = ""
        self.selected_options: dict[str, str] = {}
        self.enter_pressed = False
        self.submit_count = 0
        self.scroll_y = 1400 if scenario == "scroll_start_middle" else 0
        self.max_scroll_y = 2800
        self.mouse = _FakeMouse(self)

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
        if self.scenario == "sensitive_page_with_safe_controls":
            return "Account Security Login Payment"
        if self.scenario == "scroll_sensitive_page":
            return "Login Payment Security"
        if self.scenario == "scroll_warning_after" and self.state == "after_scroll":
            return "Action Fixture Scroll Warning"
        if self.scenario == "type_no_value_change" and self.state == "after_type":
            return "Action Fixture"
        if self.state == "after_type":
            return "Action Fixture Typed"
        if self.state == "after_click":
            return "Action Fixture Updated"
        if self.state == "after_choice":
            return "Action Fixture Choice Updated"
        if self.state == "after_scroll":
            return "Action Fixture Scrolled"
        return "Action Fixture"

    def evaluate(self, script: str) -> dict[str, Any] | int:
        if "__stormhelmSubmitCount" in str(script):
            return self.submit_count
        if "__stormhelmScrollState" in str(script) or "scrollY" in str(script):
            return {
                "x": 0,
                "y": self.scroll_y,
                "max_y": self.max_scroll_y,
                "at_top": self.scroll_y <= 0,
                "at_bottom": self.scroll_y >= self.max_scroll_y,
            }
        return {
            "ready_state": "complete",
            "control_count": len(self.controls()),
            "iframe_count": 0,
            "cross_origin_iframe_count": 0,
            "shadow_host_count": 0,
            "form_like_count": 0,
        }

    def scroll_by(self, delta_y: int) -> None:
        direction = "down" if delta_y >= 0 else "up"
        amount = abs(int(delta_y or 0))
        self.actions.append(("scroll", direction, str(amount)))
        self.scroll_y = max(0, min(self.max_scroll_y, self.scroll_y + int(delta_y or 0)))
        self.state = "after_scroll"

    def controls(self) -> list[dict[str, Any]]:
        email_value = self.filled_values.get("Email", "")
        email_summary = ""
        if self.state == "after_type" and email_value and self.scenario not in {"type_unverifiable", "type_no_value_change"}:
            email_summary = f"[redacted text, {len(email_value)} chars]"
        password_value_summary = "[redacted sensitive field]"
        if self.scenario == "redaction_sentinel_fields":
            password_value_summary = "PASSWORD-KRAKEN-RAW-SECRET-8-1"
        if self.scenario == "email_missing":
            return [
                _payload_control("button-continue", "button", "Continue", selector_hint="#continue"),
                _payload_control(
                    "password-current",
                    "textbox",
                    "Password",
                    selector_hint="#password",
                    value_summary=password_value_summary,
                    risk_hint="sensitive_input",
                ),
            ]
        if self.scenario == "email_drift_password":
            return [
                _payload_control("button-continue", "button", "Continue", selector_hint="#continue"),
                _payload_control(
                    "textbox-email",
                    "textbox",
                    "Password",
                    selector_hint="#password",
                    value_summary="[redacted sensitive field]",
                    risk_hint="sensitive_input password login credential",
                ),
            ]
        if self.scenario == "email_drift_file":
            return [
                _payload_control("button-continue", "button", "Continue", selector_hint="#continue"),
                _payload_control(
                    "textbox-email",
                    "textbox",
                    "Upload file",
                    selector_hint="#upload",
                    risk_hint="file input upload",
                ),
            ]
        newsletter_name = "Newsletter"
        newsletter_role = "checkbox"
        newsletter_selector = "#newsletter"
        newsletter_risk = ""
        if self.scenario == "checkbox_drift_label":
            newsletter_name = "Promotions"
        if self.scenario == "checkbox_drift_button":
            newsletter_role = "button"
            newsletter_selector = "#newsletter-button"
        if self.scenario == "checkbox_captcha":
            newsletter_name = "I am not a robot"
            newsletter_risk = "captcha human verification"
        if self.scenario == "checkbox_delete":
            newsletter_name = "I understand this is permanent"
            newsletter_risk = "delete confirmation permanent"
        if self.scenario == "checkbox_payment_authorization":
            newsletter_name = "Authorize payment"
            newsletter_risk = "payment authorization"
        newsletter_checked = self.checked_values.get(newsletter_name, self.scenario == "newsletter_already_checked")
        already_checked = self.checked_values.get("Already subscribed", True)
        radio_student_checked = self.selected_radio == "Student"
        radio_teacher_checked = self.selected_radio == "Teacher"
        country_options = [
            {"label": "United States", "value_summary": "us", "selected": False, "disabled": False, "ordinal": 1},
            {"label": "Canada", "value_summary": "ca", "selected": False, "disabled": False, "ordinal": 2},
            {"label": "Disabled Option", "value_summary": "disabled", "selected": False, "disabled": True, "ordinal": 3},
        ]
        if self.scenario == "redaction_sentinel_fields":
            country_options.append(
                {
                    "label": "Hidden token option",
                    "value_summary": "OPTION-KRAKEN-HIDDEN-SECRET-8-1",
                    "selected": False,
                    "disabled": True,
                    "ordinal": 4,
                }
            )
        if self.scenario == "option_removed":
            country_options = [option for option in country_options if option.get("label") != "Canada"]
        if self.scenario == "option_disabled_after_preview":
            for option in country_options:
                if option.get("label") == "Canada":
                    option["disabled"] = True
        if self.scenario in {"duplicate_option", "option_duplicate_after_preview"}:
            country_options.insert(2, {"label": "Canada", "value_summary": "ca-duplicate", "selected": False, "disabled": False, "ordinal": 3})
        if self.scenario == "option_value_drift":
            for option in country_options:
                if option.get("label") == "Canada":
                    option["value_summary"] = "ca-new"
        if self.scenario == "option_ordinal_drift":
            country_options = [
                {"label": "United States", "value_summary": "us", "selected": False, "disabled": False, "ordinal": 1},
                {"label": "Mexico", "value_summary": "mx", "selected": False, "disabled": False, "ordinal": 2},
                {"label": "Canada", "value_summary": "ca", "selected": False, "disabled": False, "ordinal": 3},
            ]
        if self.scenario == "many_options":
            country_options = [
                {"label": f"Option {index}", "value_summary": f"opt-{index}", "selected": False, "disabled": False, "ordinal": index}
                for index in range(1, 55)
            ]
        selected_country = self.selected_options.get("Country", "Canada" if self.scenario == "option_already_selected" else "United States")
        for option in country_options:
            option["selected"] = option.get("label") == selected_country
        country_summary = f"selected option: {selected_country}"
        controls = [
            _payload_control("button-continue", "button", "Continue", selector_hint="#continue"),
            _payload_control(
                "textbox-email",
                "textbox",
                "Email",
                selector_hint="#email",
                readonly=self.scenario == "readonly_email",
                enabled=self.scenario != "disabled_email",
                visible=self.scenario != "hidden_email",
                value_summary=email_summary,
                risk_hint="login credential" if self.scenario == "login_like_email" else "",
            ),
            _payload_control(
                "password-current",
                "textbox",
                "Password",
                selector_hint="#password",
                value_summary=password_value_summary,
                risk_hint="sensitive_input",
            ),
            _payload_control(
                "checkbox-newsletter",
                newsletter_role,
                newsletter_name,
                selector_hint=newsletter_selector,
                enabled=self.scenario != "disabled_checkbox",
                visible=self.scenario != "hidden_checkbox",
                checked=newsletter_checked,
                risk_hint=newsletter_risk,
            ),
            _payload_control("checkbox-subscribed", "checkbox", "Already subscribed", selector_hint="#subscribed", checked=already_checked),
            _payload_control("radio-student", "radio", "Student", selector_hint="#student", checked=radio_student_checked),
            _payload_control("radio-teacher", "radio", "Teacher", selector_hint="#teacher", checked=radio_teacher_checked),
            _payload_control(
                "select-country",
                "combobox",
                "Country",
                selector_hint="#country",
                value_summary=country_summary,
                options=country_options,
            ),
            _payload_control(
                "checkbox-terms",
                "checkbox",
                "I agree to terms",
                selector_hint="#terms",
                checked=False,
                risk_hint="legal terms consent",
            ),
            _payload_control(
                "checkbox-payment",
                "checkbox",
                "Authorize payment",
                selector_hint="#payment",
                checked=False,
                risk_hint="payment authorization",
            ),
            _payload_control(
                "checkbox-privacy",
                "checkbox",
                "Privacy consent",
                selector_hint="#privacy",
                checked=False,
                risk_hint="privacy consent legal",
            ),
            _payload_control(
                "checkbox-captcha",
                "checkbox",
                "CAPTCHA human verification",
                selector_hint="#captcha",
                checked=False,
                risk_hint="captcha human verification",
            ),
            _payload_control(
                "checkbox-delete",
                "checkbox",
                "Delete confirmation",
                selector_hint="#delete-confirm",
                checked=False,
                risk_hint="delete confirmation permanent",
            ),
        ]
        if self.scenario == "checkbox_missing":
            controls = [control for control in controls if control.get("control_id") != "checkbox-newsletter"]
        if self.scenario in {"duplicate_email", "type_locator_duplicate"}:
            controls.append(_payload_control("textbox-email-duplicate", "textbox", "Email", selector_hint="#email-duplicate"))
        if self.scenario == "scroll_sensitive_page":
            return [
                _payload_control(
                    "textbox-login-email",
                    "textbox",
                    "Login email",
                    selector_hint="#login-email",
                    risk_hint="login credential security profile",
                ),
                _payload_control(
                    "button-payment",
                    "button",
                    "Pay now",
                    selector_hint="#pay-now",
                    risk_hint="payment checkout",
                ),
            ]
        if self.scenario == "scroll_target_visible":
            controls.append(_payload_control("link-privacy", "link", "Privacy Policy", selector_hint="#privacy"))
        if self.scenario in {"scroll_target_below_fold", "scroll_duplicate_target"} and self.scroll_y >= 700:
            controls.append(_payload_control("link-privacy", "link", "Privacy Policy", selector_hint="#privacy"))
            if self.scenario == "scroll_duplicate_target":
                controls.append(_payload_control("link-privacy-copy", "link", "Privacy Policy", selector_hint="#privacy-copy"))
        if self.scenario == "scroll_long_page" and self.scroll_y >= 700:
            controls.append(_payload_control("button-more", "button", "More details", selector_hint="#more-details"))
        if self.scenario == "redaction_sentinel_fields":
            controls.append(
                _payload_control(
                    "hidden-token-field",
                    "textbox",
                    "Hidden token field",
                    selector_hint="#hidden-token",
                    visible=False,
                    value_summary="HIDDEN-KRAKEN-RAW-SECRET-8-1",
                    risk_hint="hidden token secret cookie-like COOKIE-KRAKEN-RAW-SECRET-8-1",
                )
            )
        return controls

    def dialogs(self) -> list[dict[str, Any]]:
        if self.state == "after_click":
            return []
        if self.scenario == "scroll_warning_after" and self.state == "after_scroll":
            return [{"dialog_id": "scroll-warning", "alert_id": "scroll-warning", "role": "alert", "name": "Scroll warning", "text": "Warning appeared while scrolling"}]
        if self.scenario == "choice_warning_on_change":
            if self.state == "after_choice":
                return [{"dialog_id": "choice-warning", "alert_id": "choice-warning", "role": "alert", "name": "Choice warning", "text": "Choice changed warning"}]
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


def _type_plan(subsystem, *, text: str = "hello example") -> Any:
    observation = _plan_observation()
    action_arguments = {"text": text}
    preview = subsystem.preview_playwright_browser_action(
        observation,
        target_phrase="Email field",
        action_phrase="type text into Email",
        action_arguments=action_arguments,
    )
    return subsystem.build_playwright_browser_action_plan(preview, action_arguments=action_arguments)


def _choice_config() -> ScreenAwarenessConfig:
    return _execution_config(check=True, uncheck=True, select_option=True, dev_choice_controls=True)


def _scroll_config() -> ScreenAwarenessConfig:
    return _execution_config(scroll=True, scroll_to_target=True, dev_scroll=True)


def _all_browser_actions_config() -> ScreenAwarenessConfig:
    return _execution_config(
        click=True,
        focus=True,
        type_text=True,
        dev_type_text=True,
        check=True,
        uncheck=True,
        select_option=True,
        dev_choice_controls=True,
        scroll=True,
        scroll_to_target=True,
        dev_scroll=True,
    )


def _choice_plan(
    subsystem,
    *,
    target_phrase: str,
    action_phrase: str,
    action_arguments: dict[str, Any] | None = None,
) -> Any:
    observation = _plan_observation()
    preview = subsystem.preview_playwright_browser_action(
        observation,
        target_phrase=target_phrase,
        action_phrase=action_phrase,
        action_arguments=action_arguments,
    )
    return subsystem.build_playwright_browser_action_plan(preview, action_arguments=action_arguments)


def _scroll_plan(
    subsystem,
    *,
    target_phrase: str = "page",
    action_phrase: str = "scroll down",
    action_arguments: dict[str, Any] | None = None,
) -> Any:
    observation = _plan_observation()
    preview = subsystem.preview_playwright_browser_action(
        observation,
        target_phrase=target_phrase,
        action_phrase=action_phrase,
        action_arguments=action_arguments,
    )
    return subsystem.build_playwright_browser_action_plan(preview, action_arguments=action_arguments)


def _plan_for_action_kind(subsystem, action_kind: str) -> Any:
    if action_kind == "click":
        return _approved_click_plan(subsystem)
    if action_kind == "focus":
        observation = _plan_observation()
        preview = subsystem.preview_playwright_browser_action(observation, "Email field", "focus email field")
        return subsystem.build_playwright_browser_action_plan(preview)
    if action_kind == "type_text":
        return _type_plan(subsystem, text="kraken safe text")
    if action_kind == "check":
        return _choice_plan(subsystem, target_phrase="Newsletter checkbox", action_phrase="check Newsletter")
    if action_kind == "uncheck":
        return _choice_plan(
            subsystem,
            target_phrase="Already subscribed checkbox",
            action_phrase="uncheck Already subscribed",
        )
    if action_kind == "select_option":
        return _choice_plan(
            subsystem,
            target_phrase="Country dropdown",
            action_phrase="select Canada from Country",
            action_arguments={"option": "Canada"},
        )
    if action_kind == "scroll":
        return _scroll_plan(
            subsystem,
            action_phrase="scroll down",
            action_arguments={"direction": "down", "amount_pixels": 700, "max_attempts": 1},
        )
    if action_kind == "scroll_to_target":
        return _scroll_plan(
            subsystem,
            target_phrase="Privacy Policy link",
            action_phrase="scroll to Privacy Policy link",
            action_arguments={
                "direction": "down",
                "amount_pixels": 700,
                "max_attempts": 2,
                "target_phrase": "Privacy Policy link",
            },
        )
    raise AssertionError(f"unsupported test action kind: {action_kind}")


def _approve_plan(subsystem, trust_service, plan: Any, *, url: str = "http://127.0.0.1:60231/type.html") -> Any:
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url=url,
        trust_service=trust_service,
        session_id="default",
        fixture_mode=True,
    )
    trust_service.respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    return pending


def _assert_no_submit_side_effects(fake: _FakeActionPlaywright, *, allowed_actions: set[str]) -> None:
    assert fake.page.submit_count == 0
    assert fake.page.enter_pressed is False
    forbidden = {"press", "dispatch_event", "evaluate_submit"}
    assert all(action[0] not in forbidden for action in fake.page.actions)
    assert all(action[0] in allowed_actions for action in fake.page.actions)


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
    assert result.error_code == "stale_plan"
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


def test_type_text_capability_requires_specific_type_gates() -> None:
    fake_without_dev_gate = _FakeActionPlaywright()
    config_without_dev_gate = _execution_config(type_text=True, dev_type_text=False)
    subsystem_without_dev_gate = _subsystem_with_fake(config_without_dev_gate, fake_without_dev_gate)
    status_without_dev_gate = subsystem_without_dev_gate.status_snapshot()["browser_adapters"]["playwright"]

    fake_with_dev_gate = _FakeActionPlaywright()
    config_with_dev_gate = _execution_config(type_text=True, dev_type_text=True)
    subsystem_with_dev_gate = _subsystem_with_fake(config_with_dev_gate, fake_with_dev_gate)
    status_with_dev_gate = subsystem_with_dev_gate.status_snapshot()["browser_adapters"]["playwright"]

    assert "browser.input.type_text" not in status_without_dev_gate["declared_action_capabilities"]
    assert "browser.input.type_text" in status_with_dev_gate["declared_action_capabilities"]
    assert "browser.form.submit" not in status_with_dev_gate["declared_action_capabilities"]
    assert "browser.login" not in status_with_dev_gate["declared_action_capabilities"]
    assert "browser.cookies.write" not in status_with_dev_gate["declared_action_capabilities"]


def test_type_text_requires_approval_and_redacts_text(trust_harness) -> None:
    events = EventBuffer(capacity=128)
    raw_text = "hello example"
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), fake, events=events)
    plan = _type_plan(subsystem, text=raw_text)

    result = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]
    rendered_state = str({"result": result.to_dict(), "status": status, "events": events.recent(limit=128)}).lower()

    assert result.status == "approval_required"
    assert result.action_attempted is False
    assert result.typed_text_redacted is True
    assert result.text_length == len(raw_text)
    assert result.text_redacted_summary == f"[redacted text, {len(raw_text)} chars]"
    assert plan.adapter_capability_required == "browser.input.type_text"
    assert plan.adapter_capability_declared is True
    assert plan.action_arguments_redacted["typed_text_redacted"] is True
    assert plan.action_arguments_redacted["text_length"] == len(raw_text)
    assert "hello example" not in rendered_state
    assert "[redacted text" in rendered_state
    assert fake.page.actions == []


def test_serialized_type_plan_drops_raw_text_and_cannot_execute(trust_harness) -> None:
    raw_text = "hello example"
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), fake)
    plan = _type_plan(subsystem, text=raw_text)
    serialized_plan = plan.to_dict()

    result = subsystem.execute_playwright_browser_action(
        serialized_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    rendered_state = str({"plan": serialized_plan, "result": result.to_dict()}).lower()

    assert "action_arguments_private" not in serialized_plan
    assert raw_text not in rendered_state
    assert result.status == "blocked"
    assert result.error_code == "typed_text_missing"
    assert result.action_attempted is False
    assert fake.page.actions == []


def test_approved_type_text_executes_safe_textbox_and_verifies_redacted_value_summary(trust_harness) -> None:
    events = EventBuffer(capacity=160)
    raw_text = "hello example"
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), fake, events=events)
    plan = _type_plan(subsystem, text=raw_text)

    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/type.html",
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
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]
    rendered_state = str({"result": result.to_dict(), "status": status, "events": events.recent(limit=160)}).lower()

    assert result.status == "verified_supported"
    assert result.action_attempted is True
    assert result.action_completed is True
    assert result.verification_attempted is True
    assert result.verification_status == "supported"
    assert result.typed_text_redacted is True
    assert result.text_length == len(raw_text)
    assert result.text_redacted_summary == f"[redacted text, {len(raw_text)} chars]"
    assert ("type_text", "Email", raw_text) in fake.page.actions
    assert all(action[0] != "click" for action in fake.page.actions)
    assert fake.context.clear_cookies_called is True
    assert fake.context.closed is True
    assert fake.browser.closed is True
    assert "screen_awareness.playwright_type_attempted" in rendered_state
    assert "screen_awareness.playwright_type_verification_completed" in rendered_state
    assert "hello example" not in rendered_state
    assert "submitted" not in rendered_state


def test_type_text_blocks_changed_text_after_approval(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), fake)
    plan = _type_plan(subsystem, text="hello example")
    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/type.html",
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
    changed_text_plan = replace(plan, action_arguments_private={"text": "changed text", "mode": "replace_value"})

    result = subsystem.execute_playwright_browser_action(
        changed_text_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "blocked"
    assert result.error_code == "approval_invalid"
    assert result.action_attempted is False
    assert fake.page.actions == []


def test_type_text_blocks_readonly_disabled_hidden_ambiguous_and_sensitive_targets(trust_harness) -> None:
    readonly_fake = _FakeActionPlaywright(scenario="readonly_email")
    readonly_subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), readonly_fake)
    readonly_plan = _type_plan(readonly_subsystem, text="hello example")
    pending = readonly_subsystem.request_playwright_browser_action_execution(
        readonly_plan,
        url="http://127.0.0.1:60231/type.html",
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
    readonly_result = readonly_subsystem.execute_playwright_browser_action(
        readonly_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    sensitive_fake = _FakeActionPlaywright()
    sensitive_subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), sensitive_fake)
    observation = _plan_observation()
    sensitive_args = {"text": "secret-token-value"}
    sensitive_plan = sensitive_subsystem.build_playwright_browser_action_plan(
        sensitive_subsystem.preview_playwright_browser_action(
            observation,
            target_phrase="Password field",
            action_phrase="type text into Password",
            action_arguments=sensitive_args,
        ),
        action_arguments=sensitive_args,
    )
    sensitive_result = sensitive_subsystem.execute_playwright_browser_action(
        sensitive_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    disabled_fake = _FakeActionPlaywright(scenario="disabled_email")
    disabled_subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), disabled_fake)
    disabled_plan = _type_plan(disabled_subsystem, text="hello example")
    disabled_pending = disabled_subsystem.request_playwright_browser_action_execution(
        disabled_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=disabled_pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    disabled_result = disabled_subsystem.execute_playwright_browser_action(
        disabled_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    hidden_fake = _FakeActionPlaywright(scenario="hidden_email")
    hidden_subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), hidden_fake)
    hidden_plan = _type_plan(hidden_subsystem, text="hello example")
    hidden_pending = hidden_subsystem.request_playwright_browser_action_execution(
        hidden_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=hidden_pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    hidden_result = hidden_subsystem.execute_playwright_browser_action(
        hidden_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    duplicate_fake = _FakeActionPlaywright(scenario="duplicate_email")
    duplicate_subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), duplicate_fake)
    duplicate_plan = _type_plan(duplicate_subsystem, text="hello example")
    duplicate_pending = duplicate_subsystem.request_playwright_browser_action_execution(
        duplicate_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=duplicate_pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )
    duplicate_result = duplicate_subsystem.execute_playwright_browser_action(
        duplicate_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert readonly_result.status == "blocked"
    assert readonly_result.error_code == "target_readonly"
    assert readonly_result.action_attempted is False
    assert readonly_fake.page.actions == []
    assert disabled_result.status == "blocked"
    assert disabled_result.error_code == "target_disabled"
    assert disabled_result.action_attempted is False
    assert disabled_fake.page.actions == []
    assert hidden_result.status == "blocked"
    assert hidden_result.error_code == "target_hidden"
    assert hidden_result.action_attempted is False
    assert hidden_fake.page.actions == []
    assert duplicate_result.status == "blocked"
    assert duplicate_result.error_code == "target_ambiguous"
    assert duplicate_result.action_attempted is False
    assert duplicate_fake.page.actions == []
    assert sensitive_result.status == "blocked"
    assert sensitive_result.error_code in {"target_sensitive", "sensitive_text_blocked"}
    assert sensitive_result.action_attempted is False
    assert sensitive_fake.page.actions == []


def test_type_text_blocks_target_drift_missing_and_locator_ambiguity_with_precise_codes(trust_harness) -> None:
    cases = [
        ("email_missing", "target_missing"),
        ("email_drift_password", "target_sensitive"),
        ("email_drift_file", "target_uneditable"),
        ("readonly_email", "target_readonly"),
        ("disabled_email", "target_disabled"),
        ("hidden_email", "target_hidden"),
        ("duplicate_email", "target_ambiguous"),
        ("type_role_locator_duplicate", "locator_ambiguous"),
    ]
    for scenario, error_code in cases:
        fake = _FakeActionPlaywright(scenario=scenario)
        subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), fake)
        plan = _type_plan(subsystem, text="hello example")
        _approve_plan(subsystem, trust_harness["trust_service"], plan)

        result = subsystem.execute_playwright_browser_action(
            plan,
            url="http://127.0.0.1:60231/type.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status == "blocked", scenario
        assert result.error_code == error_code, scenario
        assert result.action_attempted is False
        assert fake.page.actions == []


def test_type_text_approval_binds_exact_text_target_and_action(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), fake)
    plan = _type_plan(subsystem, text="hello value")
    _approve_plan(subsystem, trust_harness["trust_service"], plan)

    same_length_changed_text = replace(plan, action_arguments_private={"text": "HELLO VALUE", "mode": "replace_value"})
    changed_text_result = subsystem.execute_playwright_browser_action(
        same_length_changed_text,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    notes_args = {"text": "hello value"}
    notes_preview = subsystem.preview_playwright_browser_action(
        _plan_observation(),
        target_phrase="Notes field",
        action_phrase="type text into Notes",
        action_arguments=notes_args,
    )
    notes_plan = subsystem.build_playwright_browser_action_plan(notes_preview, action_arguments=notes_args)
    notes_plan = replace(notes_plan, plan_id=plan.plan_id)
    changed_target_result = subsystem.execute_playwright_browser_action(
        notes_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    focus_preview = subsystem.preview_playwright_browser_action(_plan_observation(), "Email field", "focus email field")
    focus_plan = subsystem.build_playwright_browser_action_plan(focus_preview)
    focus_plan = replace(focus_plan, plan_id=plan.plan_id)
    changed_action_result = subsystem.execute_playwright_browser_action(
        focus_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert changed_text_result.status == "blocked"
    assert changed_text_result.error_code == "approval_invalid"
    assert changed_target_result.status in {"approval_required", "blocked"}
    assert changed_target_result.action_attempted is False
    assert changed_action_result.status == "approval_required"
    assert changed_action_result.action_attempted is False
    assert fake.page.actions == []


def test_type_text_raw_sentinel_is_absent_from_serialized_surfaces_and_audit(trust_harness) -> None:
    sentinel = "SENTINEL-RAW-TYPE-6-1"
    events = EventBuffer(capacity=160)
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), fake, events=events)
    plan = _type_plan(subsystem, text=sentinel)
    _approve_plan(subsystem, trust_harness["trust_service"], plan)

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    canonical_result = subsystem.action_engine.result_from_browser_semantic_execution(result)
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "browser typing execution",
            "parameters": {"result_state": "attempted", "request_stage": "execution"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": result.user_message,
            "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}},
        },
        status={"screen_awareness": subsystem.status_snapshot()},
        workspace_focus={},
    )
    audit = trust_harness["trust_service"].repository.list_recent_audit(session_id="default", limit=24)
    rendered_surfaces = str(
        {
            "plan": plan.to_dict(),
            "result": result.to_dict(),
            "canonical": canonical_result.to_dict(),
            "status": subsystem.status_snapshot(),
            "events": events.recent(limit=160),
            "surface": surface,
            "audit": [record.to_dict() for record in audit],
        }
    )

    assert result.status == "verified_supported"
    assert sentinel not in rendered_surfaces
    assert f"[redacted text, {len(sentinel)} chars]" in rendered_surfaces
    assert ("type_text", "Email", sentinel) in fake.page.actions


def test_type_text_never_submits_form_or_presses_enter(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), fake)
    plan = _type_plan(subsystem, text="safe field text")
    _approve_plan(subsystem, trust_harness["trust_service"], plan)

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.action_attempted is True
    assert result.status == "verified_supported"
    assert fake.page.enter_pressed is False
    assert fake.page.submit_count == 0
    assert all(action[0] not in {"press", "dispatch_event", "evaluate_submit", "click"} for action in fake.page.actions)


def test_type_text_append_mode_and_sensitive_categories_are_blocked(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), fake)
    append_args = {"text": "extra text", "mode": "append_text"}
    append_preview = subsystem.preview_playwright_browser_action(
        _plan_observation(),
        target_phrase="Email field",
        action_phrase="append text to Email",
        action_arguments=append_args,
    )
    append_plan = subsystem.build_playwright_browser_action_plan(append_preview, action_arguments=append_args)

    append_result = subsystem.execute_playwright_browser_action(
        append_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    blocked_texts = [
        "123456",
        "4111 1111 1111 1111",
        "cvv 123",
        "api key sk-test-secret",
        "recovery code 123-456",
        "routing number 021000021",
    ]
    blocked_results = []
    for text in blocked_texts:
        plan = _type_plan(subsystem, text=text)
        blocked_results.append(
            subsystem.execute_playwright_browser_action(
                plan,
                url="http://127.0.0.1:60231/type.html",
                trust_service=trust_harness["trust_service"],
                session_id="default",
                fixture_mode=True,
            )
        )

    login_fake = _FakeActionPlaywright(scenario="login_like_email")
    login_subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), login_fake)
    login_plan = _type_plan(login_subsystem, text="hello example")
    _approve_plan(login_subsystem, trust_harness["trust_service"], login_plan)
    login_result = login_subsystem.execute_playwright_browser_action(
        login_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert append_result.status == "blocked"
    assert append_result.error_code == "typing_mode_unsupported"
    assert all(result.status == "blocked" and result.error_code == "sensitive_text_blocked" for result in blocked_results)
    assert login_result.status == "blocked"
    assert login_result.error_code == "target_sensitive"
    assert fake.page.actions == []
    assert login_fake.page.actions == []


def test_type_text_verification_distinguishes_unavailable_summary_and_unchanged_field(trust_harness) -> None:
    unverifiable_fake = _FakeActionPlaywright(scenario="type_unverifiable")
    unverifiable_subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), unverifiable_fake)
    unverifiable_plan = _type_plan(unverifiable_subsystem, text="hello example")
    _approve_plan(unverifiable_subsystem, trust_harness["trust_service"], unverifiable_plan)
    unverifiable_result = unverifiable_subsystem.execute_playwright_browser_action(
        unverifiable_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    unchanged_fake = _FakeActionPlaywright(scenario="type_no_value_change")
    unchanged_subsystem = _subsystem_with_fake(_execution_config(type_text=True, dev_type_text=True), unchanged_fake)
    unchanged_plan = _type_plan(unchanged_subsystem, text="hello example")
    _approve_plan(unchanged_subsystem, trust_harness["trust_service"], unchanged_plan)
    unchanged_result = unchanged_subsystem.execute_playwright_browser_action(
        unchanged_plan,
        url="http://127.0.0.1:60231/type.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert unverifiable_result.status == "completed_unverified"
    assert unverifiable_result.verification_status == "unsupported"
    assert unchanged_result.status == "verified_unsupported"
    assert unchanged_result.verification_status == "unsupported"
    assert "submitted" not in str({"unverifiable": unverifiable_result.to_dict(), "unchanged": unchanged_result.to_dict()}).lower()


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

    assert type_result.status == "blocked"
    assert type_result.error_code == "type_text_disabled"
    assert type_result.action_attempted is False
    assert password_result.status == "blocked"
    assert password_result.error_code == "restricted_context_deferred"
    assert password_result.action_attempted is False
    assert "browser.input.click" in status["declared_action_capabilities"]
    assert "browser.input.focus" in status["declared_action_capabilities"]
    assert "browser.input.type_text" not in status["declared_action_capabilities"]
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


def test_choice_capabilities_require_choice_gates() -> None:
    disabled_subsystem = _subsystem_with_fake(_execution_config(), _FakeActionPlaywright())
    enabled_subsystem = _subsystem_with_fake(_choice_config(), _FakeActionPlaywright())

    disabled_status = disabled_subsystem.status_snapshot()["browser_adapters"]["playwright"]
    enabled_status = enabled_subsystem.status_snapshot()["browser_adapters"]["playwright"]

    assert "browser.input.check" not in disabled_status["declared_action_capabilities"]
    assert "browser.input.uncheck" not in disabled_status["declared_action_capabilities"]
    assert "browser.input.select_option" not in disabled_status["declared_action_capabilities"]
    assert "browser.input.check" in enabled_status["declared_action_capabilities"]
    assert "browser.input.uncheck" in enabled_status["declared_action_capabilities"]
    assert "browser.input.select_option" in enabled_status["declared_action_capabilities"]
    assert enabled_status["check_enabled"] is True
    assert enabled_status["uncheck_enabled"] is True
    assert enabled_status["select_option_enabled"] is True
    assert "browser.form.submit" not in enabled_status["declared_action_capabilities"]
    assert "browser.login" not in enabled_status["declared_action_capabilities"]
    assert "browser.cookies.write" not in enabled_status["declared_action_capabilities"]


def test_choice_actions_require_approval_and_bind_selected_option(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_choice_config(), fake)
    plan = _choice_plan(
        subsystem,
        target_phrase="Country dropdown",
        action_phrase="select Canada from Country",
        action_arguments={"option": "Canada"},
    )

    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/choice.html",
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
    wrong_option_plan = replace(
        plan,
        action_arguments_redacted={**plan.action_arguments_redacted, "option_fingerprint": "tampered"},
    )
    changed_action_plan = replace(plan, action_kind="check")

    wrong_option = subsystem.execute_playwright_browser_action(
        wrong_option_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    changed_action = subsystem.execute_playwright_browser_action(
        changed_action_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert pending.status == "approval_required"
    assert plan.action_kind == "select_option"
    assert plan.adapter_capability_required == "browser.input.select_option"
    assert pending.action_attempted is False
    assert wrong_option.status == "blocked"
    assert wrong_option.error_code == "approval_invalid"
    assert changed_action.status == "approval_required"
    assert changed_action.action_attempted is False
    assert fake.page.actions == []


def test_safe_checkbox_check_and_uncheck_verify_without_submit(trust_harness) -> None:
    events = EventBuffer(capacity=160)
    check_fake = _FakeActionPlaywright()
    check_subsystem = _subsystem_with_fake(_choice_config(), check_fake, events=events)
    check_plan = _choice_plan(check_subsystem, target_phrase="Newsletter checkbox", action_phrase="check Newsletter")
    _approve_plan(check_subsystem, trust_harness["trust_service"], check_plan, url="http://127.0.0.1:60231/choice.html")

    check_result = check_subsystem.execute_playwright_browser_action(
        check_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    uncheck_fake = _FakeActionPlaywright()
    uncheck_subsystem = _subsystem_with_fake(_choice_config(), uncheck_fake, events=events)
    uncheck_plan = _choice_plan(uncheck_subsystem, target_phrase="Already subscribed checkbox", action_phrase="uncheck Already subscribed")
    _approve_plan(uncheck_subsystem, trust_harness["trust_service"], uncheck_plan, url="http://127.0.0.1:60231/choice.html")
    uncheck_result = uncheck_subsystem.execute_playwright_browser_action(
        uncheck_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    event_text = str(events.recent(limit=160)).lower()

    assert check_result.status == "verified_supported"
    assert check_result.verification_status == "supported"
    assert ("check", "Newsletter") in check_fake.page.actions
    assert check_fake.page.submit_count == 0
    assert uncheck_result.status == "verified_supported"
    assert uncheck_result.verification_status == "supported"
    assert ("uncheck", "Already subscribed") in uncheck_fake.page.actions
    assert uncheck_fake.page.submit_count == 0
    assert "screen_awareness.playwright_choice_attempted" in event_text
    assert "screen_awareness.playwright_choice_verification_completed" in event_text
    assert "submitted" not in event_text


def test_already_correct_checkbox_state_noop_is_truthful_and_does_not_click(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="newsletter_already_checked")
    subsystem = _subsystem_with_fake(_choice_config(), fake)
    plan = _choice_plan(subsystem, target_phrase="Newsletter checkbox", action_phrase="check Newsletter")
    _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/choice.html")

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "verified_supported"
    assert result.action_attempted is False
    assert result.action_completed is False
    assert "already_in_expected_state" in result.limitations
    assert fake.page.actions == []
    assert fake.page.submit_count == 0


def test_choice_targets_block_disabled_hidden_sensitive_and_ambiguous_controls(trust_harness) -> None:
    cases = [
        ("disabled_checkbox", "Newsletter checkbox", "check Newsletter", "target_disabled"),
        ("hidden_checkbox", "Newsletter checkbox", "check Newsletter", "target_hidden"),
        ("choice_role_locator_duplicate", "Newsletter checkbox", "check Newsletter", "locator_ambiguous"),
    ]
    for scenario, target_phrase, action_phrase, expected_code in cases:
        fake = _FakeActionPlaywright(scenario=scenario)
        subsystem = _subsystem_with_fake(_choice_config(), fake)
        plan = _choice_plan(subsystem, target_phrase=target_phrase, action_phrase=action_phrase)
        _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/choice.html")

        result = subsystem.execute_playwright_browser_action(
            plan,
            url="http://127.0.0.1:60231/choice.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status == "blocked", scenario
        assert result.error_code == expected_code, scenario
        assert result.action_attempted is False
        assert fake.page.actions == []

    sensitive_fake = _FakeActionPlaywright()
    sensitive_subsystem = _subsystem_with_fake(_choice_config(), sensitive_fake)
    sensitive_plan = _choice_plan(sensitive_subsystem, target_phrase="I agree to terms checkbox", action_phrase="check terms")
    sensitive_result = sensitive_subsystem.execute_playwright_browser_action(
        sensitive_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert sensitive_result.status == "blocked"
    assert sensitive_result.error_code in {"restricted_context_deferred", "target_sensitive"}
    assert sensitive_result.action_attempted is False
    assert sensitive_fake.page.actions == []


def test_radio_selection_and_dropdown_exact_option_verify_supported(trust_harness) -> None:
    radio_fake = _FakeActionPlaywright()
    radio_subsystem = _subsystem_with_fake(_choice_config(), radio_fake)
    radio_plan = _choice_plan(radio_subsystem, target_phrase="Student radio", action_phrase="select Student")
    _approve_plan(radio_subsystem, trust_harness["trust_service"], radio_plan, url="http://127.0.0.1:60231/choice.html")
    radio_result = radio_subsystem.execute_playwright_browser_action(
        radio_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    dropdown_fake = _FakeActionPlaywright()
    dropdown_subsystem = _subsystem_with_fake(_choice_config(), dropdown_fake)
    dropdown_plan = _choice_plan(
        dropdown_subsystem,
        target_phrase="Country dropdown",
        action_phrase="select Canada from Country",
        action_arguments={"option": "Canada"},
    )
    _approve_plan(dropdown_subsystem, trust_harness["trust_service"], dropdown_plan, url="http://127.0.0.1:60231/choice.html")
    dropdown_result = dropdown_subsystem.execute_playwright_browser_action(
        dropdown_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert radio_plan.action_kind == "check"
    assert radio_result.status == "verified_supported"
    assert ("check", "Student") in radio_fake.page.actions
    assert dropdown_plan.action_kind == "select_option"
    assert dropdown_result.status == "verified_supported"
    assert dropdown_result.option_redacted_summary == "Canada"
    assert ("select_option", "Country", "Canada") in dropdown_fake.page.actions
    assert dropdown_fake.page.submit_count == 0


def test_dropdown_option_missing_duplicate_disabled_and_bounded_options_block(trust_harness) -> None:
    cases = [
        ("normal", {"option": "Atlantis"}, "option_not_found"),
        ("duplicate_option", {"option": "Canada"}, "option_ambiguous"),
        ("normal", {"option": "Disabled Option"}, "option_disabled"),
        ("many_options", {"option": "Option 54"}, "option_not_found"),
    ]
    for scenario, args, expected_code in cases:
        fake = _FakeActionPlaywright(scenario=scenario)
        subsystem = _subsystem_with_fake(_choice_config(), fake)
        plan = _choice_plan(
            subsystem,
            target_phrase="Country dropdown",
            action_phrase=f"select {args['option']} from Country",
            action_arguments=args,
        )
        _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/choice.html")

        result = subsystem.execute_playwright_browser_action(
            plan,
            url="http://127.0.0.1:60231/choice.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status == "blocked", scenario
        assert result.error_code == expected_code, scenario
        assert result.action_attempted is False
        assert fake.page.actions == []


def test_choice_target_drift_and_type_change_block_before_action(trust_harness) -> None:
    cases = [
        ("checkbox_missing", "target_missing"),
        ("checkbox_drift_label", "target_drift"),
        ("checkbox_drift_button", "target_type_changed"),
        ("checkbox_payment_authorization", "target_sensitive"),
    ]
    for scenario, expected_code in cases:
        fake = _FakeActionPlaywright(scenario=scenario)
        subsystem = _subsystem_with_fake(_choice_config(), fake)
        plan = _choice_plan(subsystem, target_phrase="Newsletter checkbox", action_phrase="check Newsletter")
        _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/choice.html")

        result = subsystem.execute_playwright_browser_action(
            plan,
            url="http://127.0.0.1:60231/choice.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status == "blocked", scenario
        assert result.error_code == expected_code, scenario
        assert result.action_attempted is False
        assert fake.page.actions == []
        assert result.cleanup_status == "closed"


def test_dropdown_option_drift_blocks_before_selecting(trust_harness) -> None:
    cases = [
        ("option_removed", {"option": "Canada"}, "option_not_found"),
        ("option_disabled_after_preview", {"option": "Canada"}, "option_disabled"),
        ("option_duplicate_after_preview", {"option": "Canada"}, "option_ambiguous"),
        ("option_value_drift", {"option": "Canada"}, "option_drift"),
        ("option_ordinal_drift", {"ordinal": 2}, "option_drift"),
    ]
    for scenario, args, expected_code in cases:
        fake = _FakeActionPlaywright(scenario=scenario)
        subsystem = _subsystem_with_fake(_choice_config(), fake)
        option_text = args.get("option") or f"option {args['ordinal']}"
        plan = _choice_plan(
            subsystem,
            target_phrase="Country dropdown",
            action_phrase=f"select {option_text} from Country",
            action_arguments=args,
        )
        _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/choice.html")

        result = subsystem.execute_playwright_browser_action(
            plan,
            url="http://127.0.0.1:60231/choice.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status == "blocked", scenario
        assert result.error_code == expected_code, scenario
        assert result.action_attempted is False
        assert fake.page.actions == []


def test_choice_sensitive_legal_payment_captcha_delete_controls_block(trust_harness) -> None:
    cases = [
        ("I agree to terms checkbox", "check terms"),
        ("Privacy consent checkbox", "check privacy consent"),
        ("Authorize payment checkbox", "check authorize payment"),
        ("CAPTCHA human verification checkbox", "check captcha checkbox"),
        ("Delete confirmation checkbox", "check delete confirmation"),
    ]
    for target_phrase, action_phrase in cases:
        fake = _FakeActionPlaywright()
        subsystem = _subsystem_with_fake(_choice_config(), fake)
        plan = _choice_plan(subsystem, target_phrase=target_phrase, action_phrase=action_phrase)

        result = subsystem.execute_playwright_browser_action(
            plan,
            url="http://127.0.0.1:60231/choice.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status == "blocked", target_phrase
        assert result.error_code in {"restricted_context_deferred", "target_sensitive", "sensitive_or_restricted_context"}, target_phrase
        assert result.action_attempted is False
        assert fake.page.actions == []


def test_dropdown_already_selected_noop_is_truthful_and_does_not_select(trust_harness) -> None:
    events = EventBuffer(capacity=160)
    fake = _FakeActionPlaywright(scenario="option_already_selected")
    subsystem = _subsystem_with_fake(_choice_config(), fake, events=events)
    plan = _choice_plan(
        subsystem,
        target_phrase="Country dropdown",
        action_phrase="select Canada from Country",
        action_arguments={"option": "Canada"},
    )
    _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/choice.html")

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    event_text = str(events.recent(limit=160)).lower()

    assert result.status == "verified_supported"
    assert result.action_attempted is False
    assert result.action_completed is False
    assert "already_in_expected_state" in result.limitations
    assert "screen_awareness.playwright_choice_no_op_supported" in event_text
    assert fake.page.actions == []
    assert fake.page.submit_count == 0


def test_choice_unexpected_navigation_and_warning_do_not_become_success(trust_harness) -> None:
    cases = [
        ("choice_unexpected_navigation", "failed", "unexpected_navigation"),
        ("choice_warning_on_change", "partial", "unexpected_warning_added"),
    ]
    for scenario, expected_status, expected_code in cases:
        fake = _FakeActionPlaywright(scenario=scenario)
        subsystem = _subsystem_with_fake(_choice_config(), fake)
        plan = _choice_plan(subsystem, target_phrase="Newsletter checkbox", action_phrase="check Newsletter")
        _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/choice.html")

        result = subsystem.execute_playwright_browser_action(
            plan,
            url="http://127.0.0.1:60231/choice.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status == expected_status, scenario
        assert result.error_code == expected_code, scenario
        assert result.action_attempted is True
        assert result.verification_status in {"failed", "partial"}
        assert "verified_supported" not in result.status


def test_choice_grants_cannot_cross_actions_or_be_reused(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_choice_config(), fake)
    select_plan = _choice_plan(
        subsystem,
        target_phrase="Country dropdown",
        action_phrase="select Canada from Country",
        action_arguments={"option": "Canada"},
    )
    _approve_plan(subsystem, trust_harness["trust_service"], select_plan, url="http://127.0.0.1:60231/choice.html")

    wrong_action_plan = replace(select_plan, action_kind="click", adapter_capability_required="browser.input.click")
    wrong_action = subsystem.execute_playwright_browser_action(
        wrong_action_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    first = subsystem.execute_playwright_browser_action(
        select_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    reused = subsystem.execute_playwright_browser_action(
        select_plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert wrong_action.status in {"approval_required", "blocked", "unsupported"}
    assert wrong_action.action_attempted is False
    assert first.status == "verified_supported"
    assert reused.status == "approval_required"
    assert reused.action_attempted is False


def test_choice_action_unexpected_submit_counter_is_not_success(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="choice_submit_on_change")
    subsystem = _subsystem_with_fake(_choice_config(), fake)
    plan = _choice_plan(subsystem, target_phrase="Newsletter checkbox", action_phrase="check Newsletter")
    _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/choice.html")

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status in {"failed", "partial"}
    assert result.error_code == "unexpected_form_submission"
    assert result.action_attempted is True
    assert result.verification_status == "failed"
    assert fake.page.submit_count == 1
    assert fake.page.enter_pressed is False
    assert all(action[0] not in {"press", "dispatch_event", "evaluate_submit"} for action in fake.page.actions)


def test_choice_deck_status_audit_are_bounded_and_unsupported_actions_remain_absent(trust_harness) -> None:
    events = EventBuffer(capacity=160)
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_choice_config(), fake, events=events)
    plan = _choice_plan(
        subsystem,
        target_phrase="Country dropdown",
        action_phrase="select Canada from Country",
        action_arguments={"option": "Canada"},
    )
    _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/choice.html")
    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/choice.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "browser choice execution",
            "parameters": {"result_state": "attempted", "request_stage": "execution"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": result.user_message,
            "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}},
        },
        status={"screen_awareness": subsystem.status_snapshot()},
        workspace_focus={},
    )
    audit = trust_harness["trust_service"].repository.list_recent_audit(session_id="default", limit=24)
    rendered = str(
        {
            "result": result.to_dict(),
            "status": subsystem.status_snapshot(),
            "events": events.recent(limit=160),
            "surface": surface,
            "audit": [record.to_dict() for record in audit],
        }
    ).lower()

    assert result.status == "verified_supported"
    assert "browser.input.select_option" in rendered
    assert "browser.form.submit" not in subsystem.status_snapshot()["browser_adapters"]["playwright"]["declared_action_capabilities"]
    assert "browser.login" not in subsystem.status_snapshot()["browser_adapters"]["playwright"]["declared_action_capabilities"]
    assert "browser.cookies.write" not in subsystem.status_snapshot()["browser_adapters"]["playwright"]["declared_action_capabilities"]
    assert "screen_awareness.playwright_choice_attempted" in rendered
    assert "screen_awareness.playwright_choice_verification_completed" in rendered
    assert "submit button clicked" not in rendered
    assert "submitted" not in rendered
    assert "i saw your screen" not in rendered


def test_scroll_contract_is_declared_only_when_scroll_gates_pass() -> None:
    disabled_subsystem = _subsystem_with_fake(_execution_config(), _FakeActionPlaywright())
    enabled_subsystem = _subsystem_with_fake(_scroll_config(), _FakeActionPlaywright())

    disabled_status = disabled_subsystem.status_snapshot()["browser_adapters"]["playwright"]
    enabled_status = enabled_subsystem.status_snapshot()["browser_adapters"]["playwright"]

    assert "browser.input.scroll" not in disabled_status["declared_action_capabilities"]
    assert "browser.input.scroll_to_target" not in disabled_status["declared_action_capabilities"]
    assert "browser.input.scroll" in enabled_status["declared_action_capabilities"]
    assert "browser.input.scroll_to_target" in enabled_status["declared_action_capabilities"]
    assert enabled_status["scroll_enabled"] is True
    assert enabled_status["scroll_to_target_enabled"] is True
    assert "browser.form.submit" not in enabled_status["declared_action_capabilities"]
    assert "browser.login" not in enabled_status["declared_action_capabilities"]
    assert "browser.cookies.write" not in enabled_status["declared_action_capabilities"]


def test_scroll_requires_approval_and_binds_direction_amount_and_target(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="scroll_long_page")
    subsystem = _subsystem_with_fake(_scroll_config(), fake)
    plan = _scroll_plan(
        subsystem,
        action_phrase="scroll down a little",
        action_arguments={"direction": "down", "amount_pixels": 700, "max_attempts": 1},
    )
    assert plan.action_kind == "scroll"
    assert plan.adapter_capability_required == "browser.input.scroll"

    pending = subsystem.request_playwright_browser_action_execution(
        plan,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    assert pending.status == "approval_required"
    assert fake.page.actions == []
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    changed_direction = replace(plan, action_arguments_private={"direction": "up", "amount_pixels": 700, "max_attempts": 1})
    changed_amount = replace(plan, action_arguments_private={"direction": "down", "amount_pixels": 1200, "max_attempts": 1})
    changed_target = replace(
        plan,
        action_kind="scroll_to_target",
        adapter_capability_required="browser.input.scroll_to_target",
        action_arguments_private={"direction": "down", "amount_pixels": 700, "max_attempts": 1, "target_phrase": "Privacy Policy link"},
    )

    direction_result = subsystem.execute_playwright_browser_action(
        changed_direction,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    amount_result = subsystem.execute_playwright_browser_action(
        changed_amount,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    target_result = subsystem.execute_playwright_browser_action(
        changed_target,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert direction_result.error_code == "approval_invalid"
    assert amount_result.error_code == "approval_invalid"
    assert target_result.status in {"approval_required", "blocked", "unsupported"}
    assert fake.page.actions == []


def test_scroll_down_and_up_verify_scroll_position_without_side_effects(trust_harness) -> None:
    down_fake = _FakeActionPlaywright(scenario="scroll_long_page")
    down_subsystem = _subsystem_with_fake(_scroll_config(), down_fake)
    down_plan = _scroll_plan(down_subsystem, action_phrase="scroll down", action_arguments={"direction": "down", "amount_pixels": 700})
    _approve_plan(down_subsystem, trust_harness["trust_service"], down_plan, url="http://127.0.0.1:60231/scroll.html")

    down_result = down_subsystem.execute_playwright_browser_action(
        down_plan,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    up_fake = _FakeActionPlaywright(scenario="scroll_start_middle")
    up_subsystem = _subsystem_with_fake(_scroll_config(), up_fake)
    up_plan = _scroll_plan(up_subsystem, action_phrase="scroll up", action_arguments={"direction": "up", "amount_pixels": 700})
    _approve_plan(up_subsystem, trust_harness["trust_service"], up_plan, url="http://127.0.0.1:60231/scroll.html")

    up_result = up_subsystem.execute_playwright_browser_action(
        up_plan,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert down_result.status == "verified_supported"
    assert down_result.verification_status == "supported"
    assert ("scroll", "down", "700") in down_fake.page.actions
    assert up_result.status == "verified_supported"
    assert up_result.verification_status == "supported"
    assert ("scroll", "up", "700") in up_fake.page.actions
    for fake in (down_fake, up_fake):
        assert fake.page.submit_count == 0
        assert fake.page.enter_pressed is False
        assert all(action[0] not in {"click", "type_text", "fill", "check", "uncheck", "select_option", "press", "dispatch_event", "evaluate_submit"} for action in fake.page.actions)


def test_scroll_to_already_visible_target_is_truthful_noop(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="scroll_target_visible")
    subsystem = _subsystem_with_fake(_scroll_config(), fake)
    plan = _scroll_plan(subsystem, target_phrase="Privacy Policy link", action_phrase="scroll to Privacy Policy link")
    _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/scroll.html")

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert plan.action_kind == "scroll_to_target"
    assert result.status == "verified_supported"
    assert result.action_attempted is False
    assert result.verification_status == "supported"
    assert fake.page.actions == []
    assert "no_action_needed" in result.limitations


def test_scroll_to_below_fold_target_is_bounded_and_verified(trust_harness) -> None:
    events = EventBuffer(capacity=160)
    fake = _FakeActionPlaywright(scenario="scroll_target_below_fold")
    subsystem = _subsystem_with_fake(_scroll_config(), fake, events=events)
    plan = _scroll_plan(
        subsystem,
        target_phrase="Privacy Policy link",
        action_phrase="scroll to Privacy Policy link",
        action_arguments={"direction": "down", "amount_pixels": 700, "max_attempts": 3, "target_phrase": "Privacy Policy link"},
    )
    _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/scroll.html")

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    event_text = str(events.recent(limit=160)).lower()

    assert result.status == "verified_supported"
    assert result.verification_status == "supported"
    assert result.error_code == ""
    assert ("scroll", "down", "700") in fake.page.actions
    assert "screen_awareness.playwright_scroll_target_found" in event_text
    assert "screen_awareness.playwright_scroll_verification_completed" in event_text
    assert fake.page.submit_count == 0
    assert all(action[0] not in {"click", "type_text", "check", "uncheck", "select_option", "press", "dispatch_event", "evaluate_submit"} for action in fake.page.actions)


def test_scroll_to_target_not_found_or_ambiguous_stops_with_bounded_result(trust_harness) -> None:
    missing_fake = _FakeActionPlaywright(scenario="scroll_target_never")
    missing_subsystem = _subsystem_with_fake(_scroll_config(), missing_fake)
    missing_plan = _scroll_plan(
        missing_subsystem,
        target_phrase="Privacy Policy link",
        action_phrase="scroll until you find Privacy Policy",
        action_arguments={"direction": "down", "amount_pixels": 700, "max_attempts": 2, "target_phrase": "Privacy Policy link"},
    )
    _approve_plan(missing_subsystem, trust_harness["trust_service"], missing_plan, url="http://127.0.0.1:60231/scroll.html")
    missing_result = missing_subsystem.execute_playwright_browser_action(
        missing_plan,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    duplicate_fake = _FakeActionPlaywright(scenario="scroll_duplicate_target")
    duplicate_subsystem = _subsystem_with_fake(_scroll_config(), duplicate_fake)
    duplicate_plan = _scroll_plan(
        duplicate_subsystem,
        target_phrase="Privacy Policy link",
        action_phrase="scroll to Privacy Policy link",
        action_arguments={"direction": "down", "amount_pixels": 700, "max_attempts": 2, "target_phrase": "Privacy Policy link"},
    )
    _approve_plan(duplicate_subsystem, trust_harness["trust_service"], duplicate_plan, url="http://127.0.0.1:60231/scroll.html")
    duplicate_result = duplicate_subsystem.execute_playwright_browser_action(
        duplicate_plan,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert missing_result.status in {"partial", "verified_unsupported", "completed_unverified"}
    assert missing_result.error_code == "target_not_found"
    assert len([action for action in missing_fake.page.actions if action[0] == "scroll"]) == 2
    assert duplicate_result.status == "ambiguous"
    assert duplicate_result.error_code == "target_ambiguous"
    assert duplicate_fake.page.submit_count == 0


def test_scroll_blocks_sensitive_page_and_preserves_unsupported_actions(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="scroll_sensitive_page")
    subsystem = _subsystem_with_fake(_scroll_config(), fake)
    plan = _scroll_plan(subsystem, action_phrase="scroll down", action_arguments={"direction": "down", "amount_pixels": 700})
    _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/login-payment.html")

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/login-payment.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    declared = subsystem.status_snapshot()["browser_adapters"]["playwright"]["declared_action_capabilities"]

    assert result.status == "blocked"
    assert result.error_code == "target_sensitive"
    assert fake.page.actions == []
    assert "browser.input.scroll" in declared
    assert "browser.form.submit" not in declared
    assert "browser.login" not in declared
    assert "browser.cookies.read" not in declared
    assert "browser.download" not in declared
    assert "browser.payment" not in declared


def test_scroll_deck_status_events_audit_are_bounded_and_truthful(trust_harness) -> None:
    events = EventBuffer(capacity=180)
    fake = _FakeActionPlaywright(scenario="scroll_target_below_fold")
    subsystem = _subsystem_with_fake(_scroll_config(), fake, events=events)
    plan = _scroll_plan(
        subsystem,
        target_phrase="Privacy Policy link",
        action_phrase="bring the Privacy Policy link into view",
        action_arguments={"direction": "down", "amount_pixels": 700, "max_attempts": 3, "target_phrase": "Privacy Policy link"},
    )
    _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/scroll.html")
    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/scroll.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "browser scroll execution",
            "parameters": {"result_state": "attempted", "request_stage": "execution"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": result.user_message,
            "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}},
        },
        status={"screen_awareness": subsystem.status_snapshot()},
        workspace_focus={},
    )
    audit = trust_harness["trust_service"].repository.list_recent_audit(session_id="default", limit=24)
    rendered = str(
        {
            "result": result.to_dict(),
            "status": subsystem.status_snapshot(),
            "events": events.recent(limit=180),
            "surface": surface,
            "audit": [record.to_dict() for record in audit],
        }
    ).lower()

    assert result.status == "verified_supported"
    assert result.cleanup_status == "closed"
    assert "browser.input.scroll_to_target" in rendered
    assert "screen_awareness.playwright_scroll_attempted" in rendered
    assert "screen_awareness.playwright_scroll_verification_completed" in rendered
    assert "submitted" not in rendered
    assert "clicked" not in rendered
    assert "typed text into" not in rendered
    assert "i saw your screen" not in rendered
    assert "verified truth" not in rendered


def test_interaction_kraken_sensitive_page_context_blocks_every_action_type(trust_harness) -> None:
    for action_kind in (
        "click",
        "focus",
        "type_text",
        "check",
        "uncheck",
        "select_option",
        "scroll",
        "scroll_to_target",
    ):
        fake = _FakeActionPlaywright(scenario="sensitive_page_with_safe_controls")
        subsystem = _subsystem_with_fake(_all_browser_actions_config(), fake)
        plan = _plan_for_action_kind(subsystem, action_kind)
        _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/account-security.html")

        result = subsystem.execute_playwright_browser_action(
            plan,
            url="http://127.0.0.1:60231/account-security.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status == "blocked", action_kind
        assert result.error_code in {"sensitive_page_context", "target_sensitive"}, action_kind
        assert result.action_attempted is False, action_kind
        assert result.cleanup_status == "closed", action_kind
        assert fake.page.actions == [], action_kind


def test_interaction_kraken_cross_action_approvals_do_not_transfer(trust_harness) -> None:
    cases = [
        ("click", "type_text"),
        ("click", "scroll"),
        ("click", "select_option"),
        ("focus", "click"),
        ("type_text", "click"),
        ("type_text", "focus"),
        ("type_text", "select_option"),
        ("type_text", "scroll"),
        ("select_option", "check"),
        ("select_option", "uncheck"),
        ("scroll", "click"),
        ("scroll", "type_text"),
        ("scroll", "select_option"),
    ]
    for approved_action, attempted_action in cases:
        fake = _FakeActionPlaywright()
        subsystem = _subsystem_with_fake(_all_browser_actions_config(), fake)
        approved_plan = _plan_for_action_kind(subsystem, approved_action)
        attempted_plan = replace(_plan_for_action_kind(subsystem, attempted_action), plan_id=approved_plan.plan_id)
        _approve_plan(subsystem, trust_harness["trust_service"], approved_plan, url="http://127.0.0.1:60231/kraken.html")

        result = subsystem.execute_playwright_browser_action(
            attempted_plan,
            url="http://127.0.0.1:60231/kraken.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status in {"approval_required", "blocked", "unsupported"}, (approved_action, attempted_action)
        assert result.action_attempted is False, (approved_action, attempted_action)
        assert result.cleanup_status == "not_started", (approved_action, attempted_action)
        assert fake.page.actions == [], (approved_action, attempted_action)


def test_interaction_kraken_target_binding_tampering_blocks_every_action_type(trust_harness) -> None:
    for action_kind in (
        "click",
        "focus",
        "type_text",
        "check",
        "uncheck",
        "select_option",
        "scroll",
        "scroll_to_target",
    ):
        fake = _FakeActionPlaywright()
        subsystem = _subsystem_with_fake(_all_browser_actions_config(), fake)
        plan = _plan_for_action_kind(subsystem, action_kind)
        _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/kraken.html")
        mutated_target = dict(plan.target_candidate or {})
        mutated_target["name"] = f"{mutated_target.get('name') or 'target'} changed"
        mutated_target["label"] = f"{mutated_target.get('label') or 'target'} changed"
        mutated_target["target_fingerprint"] = "tampered-target-fingerprint"
        mutated_plan = replace(plan, target_candidate=mutated_target)

        result = subsystem.execute_playwright_browser_action(
            mutated_plan,
            url="http://127.0.0.1:60231/kraken.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status == "blocked", action_kind
        assert result.error_code == "approval_invalid", action_kind
        assert result.action_attempted is False, action_kind
        assert result.cleanup_status == "not_started", action_kind
        assert fake.page.actions == [], action_kind


def test_interaction_kraken_no_submit_invariant_for_every_supported_action(trust_harness) -> None:
    cases = [
        ("click", "normal", {"click"}),
        ("focus", "normal", {"focus"}),
        ("type_text", "normal", {"focus", "type_text"}),
        ("check", "normal", {"check"}),
        ("uncheck", "normal", {"uncheck"}),
        ("select_option", "normal", {"select_option"}),
        ("scroll", "scroll_long_page", {"scroll"}),
        ("scroll_to_target", "scroll_target_below_fold", {"scroll"}),
    ]
    for action_kind, scenario, allowed_actions in cases:
        fake = _FakeActionPlaywright(scenario=scenario)
        subsystem = _subsystem_with_fake(_all_browser_actions_config(), fake)
        plan = _plan_for_action_kind(subsystem, action_kind)
        _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/no-submit.html")

        result = subsystem.execute_playwright_browser_action(
            plan,
            url="http://127.0.0.1:60231/no-submit.html",
            trust_service=trust_harness["trust_service"],
            session_id="default",
            fixture_mode=True,
        )

        assert result.status in {"verified_supported", "completed_unverified"}, action_kind
        assert "unexpected_form_submission" not in result.limitations
        _assert_no_submit_side_effects(fake, allowed_actions=allowed_actions)


def test_interaction_kraken_redaction_invariant_across_reporting_surfaces(trust_harness) -> None:
    events = EventBuffer(capacity=220)
    typed_sentinel = "TYPE-KRAKEN-RAW-SENTINEL-8-1"
    forbidden_values = [
        typed_sentinel,
        "PASSWORD-KRAKEN-RAW-SECRET-8-1",
        "HIDDEN-KRAKEN-RAW-SECRET-8-1",
        "OPTION-KRAKEN-HIDDEN-SECRET-8-1",
        "COOKIE-KRAKEN-RAW-SECRET-8-1",
    ]
    fake = _FakeActionPlaywright(scenario="redaction_sentinel_fields")
    subsystem = _subsystem_with_fake(_all_browser_actions_config(), fake, events=events)
    plan = _type_plan(subsystem, text=typed_sentinel)
    _approve_plan(subsystem, trust_harness["trust_service"], plan, url="http://127.0.0.1:60231/redaction.html")

    result = subsystem.execute_playwright_browser_action(
        plan,
        url="http://127.0.0.1:60231/redaction.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    canonical = subsystem.action_engine.result_from_browser_semantic_execution(result)
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "browser typing execution",
            "parameters": {"result_state": "attempted", "request_stage": "execution"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": result.user_message,
            "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}},
        },
        status={"screen_awareness": subsystem.status_snapshot()},
        workspace_focus={},
    )
    audit = trust_harness["trust_service"].repository.list_recent_audit(session_id="default", limit=32)
    rendered = str(
        {
            "plan": plan.to_dict(),
            "result": result.to_dict(),
            "canonical": canonical.to_dict(),
            "status": subsystem.status_snapshot(),
            "events": events.recent(limit=220),
            "surface": surface,
            "audit": [record.to_dict() for record in audit],
            "trust": trust_harness["trust_service"].status_snapshot(session_id="default"),
        }
    )

    assert result.status == "verified_supported"
    assert f"[redacted text, {len(typed_sentinel)} chars]" in rendered
    for value in forbidden_values:
        assert value not in rendered


def test_interaction_kraken_canonical_status_mapping_is_consistent() -> None:
    subsystem = _subsystem_with_fake(_all_browser_actions_config(), _FakeActionPlaywright())
    expected = {
        "verified_supported": ActionExecutionStatus.VERIFIED_SUCCESS,
        "verified_unsupported": ActionExecutionStatus.ATTEMPTED_UNVERIFIED,
        "completed_unverified": ActionExecutionStatus.ATTEMPTED_UNVERIFIED,
        "partial": ActionExecutionStatus.ATTEMPTED_UNVERIFIED,
        "ambiguous": ActionExecutionStatus.AMBIGUOUS,
        "blocked": ActionExecutionStatus.BLOCKED,
        "failed": ActionExecutionStatus.FAILED,
        "unsupported": ActionExecutionStatus.BLOCKED,
    }
    for browser_status, canonical_status in expected.items():
        browser_result = BrowserSemanticActionExecutionResult(
            action_kind="scroll" if browser_status == "partial" else "click",
            status=browser_status,
            action_attempted=browser_status in {"verified_supported", "verified_unsupported", "completed_unverified", "partial", "failed"},
            action_completed=browser_status in {"verified_supported", "verified_unsupported", "completed_unverified", "partial"},
            verification_attempted=browser_status not in {"blocked", "unsupported"},
            verification_status="supported" if browser_status == "verified_supported" else browser_status,
            target_summary={"role": "button", "name": "Continue"},
            provider="playwright_live_semantic",
            claim_ceiling="browser_semantic_action_execution",
        )

        canonical = subsystem.action_engine.result_from_browser_semantic_execution(browser_result)

        assert canonical.status == canonical_status, browser_status
        assert canonical.plan.parameters["claim_ceiling"] == "browser_semantic_action_execution"
        if browser_status != "verified_supported":
            assert canonical.status != ActionExecutionStatus.VERIFIED_SUCCESS
