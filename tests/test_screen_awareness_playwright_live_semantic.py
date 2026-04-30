from __future__ import annotations

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.screen_awareness import PlaywrightBrowserSemanticAdapter
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.ui.command_surface_v2 import build_command_surface_model


def _live_screen_config() -> ScreenAwarenessConfig:
    config = ScreenAwarenessConfig()
    playwright = config.browser_adapters.playwright
    playwright.enabled = True
    playwright.allow_dev_adapter = True
    playwright.allow_browser_launch = True
    return config


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str) -> None:
        self.page = page
        self.selector = selector

    def evaluate_all(self, _script: str):
        if "button" in self.selector and "input" in self.selector:
            return list(self.page.controls)
        if "form" in self.selector:
            return list(self.page.forms)
        if "dialog" in self.selector or "alert" in self.selector:
            return list(self.page.dialogs)
        if "h1" in self.selector or "p" in self.selector:
            return list(self.page.text_regions)
        return []


class _FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.goto_calls: list[dict[str, object]] = []
        self.controls = [
            {"control_id": "button-continue", "role": "button", "name": "Continue", "text": "Continue", "selector_hint": "#continue", "enabled": True, "visible": True},
            {"control_id": "textbox-email", "role": "textbox", "label": "Email", "name": "Email", "selector_hint": "#email", "enabled": True, "visible": True, "required": True, "value_summary": ""},
            {"control_id": "checkbox-agree", "role": "checkbox", "label": "I agree", "name": "I agree", "selector_hint": "#agree", "enabled": True, "visible": True, "checked": False},
            {"control_id": "select-plan", "role": "combobox", "label": "Plan", "name": "Plan", "selector_hint": "#plan", "enabled": True, "visible": True, "value_summary": "selected value present"},
            {"control_id": "link-privacy", "role": "link", "name": "Privacy Policy", "text": "Privacy Policy", "selector_hint": "a[href='/privacy']", "enabled": True, "visible": True},
            {"control_id": "button-disabled", "role": "button", "name": "Archive", "text": "Archive", "selector_hint": "#archive", "enabled": False, "visible": True},
            {"control_id": "button-hidden", "role": "button", "name": "Hidden Danger", "text": "Hidden Danger", "selector_hint": "#hidden", "enabled": True, "visible": False},
            {"control_id": "password-current", "role": "textbox", "label": "Password", "name": "Password", "selector_hint": "#password", "enabled": True, "visible": True, "input_type": "password", "value": "super-secret-password"},
        ]
        self.forms = [{"form_id": "form-checkout", "name": "checkout", "field_count": 4, "summary": "Checkout form"}]
        self.dialogs = [{"dialog_id": "dialog-session-expired", "role": "alert", "name": "Session expired", "text": "Session expired"}]
        self.text_regions = [{"text": "Example Checkout"}, {"text": "Use this fixture for semantic observation."}]

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})
        self.url = url

    def title(self) -> str:
        return "Stormhelm Fixture Form"

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.storage_state_arg = object()
        self.clear_cookies_called = False
        self.closed = False

    def new_page(self) -> _FakePage:
        return self.page

    def clear_cookies(self) -> None:
        self.clear_cookies_called = True

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self.context = context
        self.closed = False

    def new_context(self, **kwargs):
        self.context.storage_state_arg = kwargs.get("storage_state", "not-provided")
        return self.context

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser
        self.launch_kwargs: dict[str, object] = {}

    def launch(self, **kwargs):
        self.launch_kwargs = dict(kwargs)
        return self.browser


class _FakePlaywright:
    def __init__(self) -> None:
        self.page = _FakePage()
        self.context = _FakeContext(self.page)
        self.browser = _FakeBrowser(self.context)
        self.chromium = _FakeChromium(self.browser)
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.exited = True


def _adapter_with_fake(fake: _FakePlaywright, *, events: EventBuffer | None = None) -> PlaywrightBrowserSemanticAdapter:
    config = _live_screen_config()
    return PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: True,
        browser_engine_checker=lambda: True,
        events=events,
        sync_playwright_factory=lambda: fake,
    )


def test_live_observation_requires_enabled_launch_gate() -> None:
    config = ScreenAwarenessConfig()
    config.browser_adapters.playwright.enabled = True
    config.browser_adapters.playwright.allow_dev_adapter = True
    adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: True,
        browser_engine_checker=lambda: True,
    )

    observation = adapter.observe_live_browser_page("https://example.com")

    assert observation.provider == "playwright_live_unavailable"
    assert observation.browser_context_kind == "unavailable"
    assert observation.controls == []
    assert "playwright_browser_launch_not_allowed" in observation.limitations
    assert "no_actions" in observation.limitations


def test_live_observation_extracts_bounded_controls_and_redacts_sensitive_values() -> None:
    fake = _FakePlaywright()
    events = EventBuffer(capacity=16)
    adapter = _adapter_with_fake(fake, events=events)

    observation = adapter.observe_live_browser_page("http://127.0.0.1:60123/form.html", fixture_mode=True)
    controls = {control.control_id: control for control in observation.controls}
    event_text = str(events.recent(limit=16)).lower()

    assert observation.provider == "playwright_live_semantic"
    assert observation.browser_context_kind == "isolated_playwright_context"
    assert observation.page_title == "Stormhelm Fixture Form"
    assert observation.page_url == "http://127.0.0.1:60123/form.html"
    assert observation.claim_ceiling == "browser_semantic_observation"
    assert "isolated_temporary_browser_context" in observation.limitations
    assert "not_visible_screen_verification" in observation.limitations
    assert {"button-continue", "textbox-email", "checkbox-agree", "select-plan", "link-privacy", "password-current"}.issubset(controls)
    assert controls["button-disabled"].enabled is False
    assert controls["button-hidden"].visible is False
    assert controls["password-current"].risk_hint == "sensitive_input"
    assert controls["password-current"].value_summary == "[redacted sensitive field]"
    assert "super-secret-password" not in str(observation.to_dict())
    assert len(observation.forms) == 1
    assert observation.dialogs[0]["text"] == "Session expired"
    assert fake.chromium.launch_kwargs["headless"] is True
    assert fake.context.storage_state_arg is None
    assert fake.context.clear_cookies_called is True
    assert fake.context.closed is True
    assert fake.browser.closed is True
    assert "screen_awareness.playwright_live_observation_started" in event_text
    assert "screen_awareness.playwright_live_observation_completed" in event_text
    assert "screen_awareness.playwright_cleanup_completed" in event_text
    assert "super-secret" not in event_text


def test_live_observation_reuses_existing_grounding_and_guidance_without_actions() -> None:
    adapter = _adapter_with_fake(_FakePlaywright())
    observation = adapter.observe_live_browser_page("http://127.0.0.1:60123/form.html", fixture_mode=True)

    continue_candidates = adapter.ground_target("Continue button", observation)
    email_candidates = adapter.ground_target("Email field", observation)
    privacy_candidates = adapter.ground_target("Privacy Policy link", observation)
    hidden_candidates = adapter.ground_target("Hidden Danger button", observation)
    guidance = adapter.produce_guidance_step(email_candidates[0], observation=observation)
    no_match_guidance = adapter.produce_guidance_step([], observation=observation)
    combined_text = str([guidance, no_match_guidance]).lower()

    assert [candidate.control_id for candidate in continue_candidates] == ["button-continue"]
    assert [candidate.control_id for candidate in email_candidates] == ["textbox-email"]
    assert [candidate.control_id for candidate in privacy_candidates] == ["link-privacy"]
    assert hidden_candidates == []
    assert guidance["message"] == "I found the Email field."
    assert "isolated_temporary_browser_context" in guidance["limitations"]
    assert no_match_guidance["message"] == "I could not ground that target in the latest isolated browser semantic snapshot."
    assert guidance["action_supported"] is False
    assert guidance["verification_supported"] is False
    assert "clicked" not in combined_text
    assert "typed" not in combined_text
    assert "submitted" not in combined_text
    assert "verified" not in combined_text


def test_screen_awareness_service_surfaces_live_observation_summary() -> None:
    fake = _FakePlaywright()
    config = _live_screen_config()
    subsystem = build_screen_awareness_subsystem(config)
    subsystem.playwright_browser_adapter = _adapter_with_fake(fake)

    observation = subsystem.observe_playwright_live_browser_page("http://127.0.0.1:60123/form.html", fixture_mode=True)
    subsystem.ground_playwright_live_target("email field", observation)
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]

    assert observation.provider == "playwright_live_semantic"
    assert status["last_observation_summary"]["provider"] == "playwright_live_semantic"
    assert status["last_observation_summary"]["browser_context_kind"] == "isolated_playwright_context"
    assert status["last_observation_summary"]["control_count"] == 8
    assert status["last_observation_summary"]["form_count"] == 1
    assert status["last_grounding_summary"]["candidate_count"] == 1
    assert "controls" not in status["last_observation_summary"]
    assert status["live_actions_enabled"] is False


def test_deck_payload_surfaces_live_observation_without_action_controls() -> None:
    status = {
        "screen_awareness": {
            "enabled": True,
            "phase": "phase12",
            "policy_state": {"action_policy_mode": "confirm_before_act", "summary": "Screen Awareness owns browser semantics."},
            "hardening": {"latest_trace": {"total_duration_ms": 5.5}},
            "browser_adapters": {
                "playwright": {
                    "status": "runtime_ready",
                    "playwright_runtime_ready": True,
                    "live_actions_enabled": False,
                    "claim_ceiling": "browser_semantic_observation",
                    "last_observation_summary": {
                        "provider": "playwright_live_semantic",
                        "browser_context_kind": "isolated_playwright_context",
                        "page_url": "http://127.0.0.1:60123/form.html",
                        "page_title": "Stormhelm Fixture Form",
                        "control_count": 8,
                        "form_count": 1,
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
    }

    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "fixture page",
            "parameters": {"request_stage": "observe", "result_state": "attempted"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": "I found the Email field. This came from an isolated browser observation.",
            "metadata": {
                "route_state": {
                    "winner": {"route_family": "screen_awareness", "status": "attempted"},
                    "decomposition": {"subject": "fixture page"},
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

    assert entries["Browser Adapter"]["secondary"] == "Runtime Ready"
    assert entries["Live Observation"]["secondary"] == "8 controls"
    assert "Stormhelm Fixture Form" in entries["Live Observation"]["detail"]
    assert "1 form" in entries["Live Observation"]["detail"]
    assert entries["Grounding"]["secondary"] == "1 candidate"
    assert entries["Claim Ceiling"]["secondary"] == "Browser Semantic Observation"
    assert "click" not in station_text
    assert "typed" not in station_text
    assert "submitted" not in station_text
    assert "verified" not in station_text
