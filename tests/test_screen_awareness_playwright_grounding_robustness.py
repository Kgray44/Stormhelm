from __future__ import annotations

from datetime import UTC
from datetime import datetime

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.screen_awareness import BrowserSemanticControl
from stormhelm.core.screen_awareness import BrowserSemanticObservation
from stormhelm.core.screen_awareness import PlaywrightBrowserSemanticAdapter
from stormhelm.ui.command_surface_v2 import build_command_surface_model


def _enabled_config(*, launch: bool = False) -> ScreenAwarenessConfig:
    config = ScreenAwarenessConfig()
    playwright = config.browser_adapters.playwright
    playwright.enabled = True
    playwright.allow_dev_adapter = True
    playwright.allow_browser_launch = launch
    return config


def _adapter(*, events: EventBuffer | None = None) -> PlaywrightBrowserSemanticAdapter:
    config = _enabled_config()
    return PlaywrightBrowserSemanticAdapter(config.browser_adapters.playwright, events=events)


def _observation(
    controls: list[BrowserSemanticControl],
    *,
    forms: list[dict] | None = None,
    dialogs: list[dict] | None = None,
    limitations: list[str] | None = None,
) -> BrowserSemanticObservation:
    return BrowserSemanticObservation(
        provider="playwright_live_semantic",
        adapter_id="screen_awareness.browser.playwright",
        session_id="robustness-test",
        page_url="http://127.0.0.1:60123/robust.html",
        page_title="Robust Semantic Fixture",
        browser_context_kind="isolated_playwright_context",
        observed_at=datetime.now(UTC).isoformat(),
        controls=controls,
        forms=forms or [],
        dialogs=dialogs or [],
        alerts=[item for item in dialogs or [] if item.get("role") == "alert"],
        limitations=limitations
        or [
            "live_semantic_observation_only",
            "isolated_temporary_browser_context",
            "no_actions",
            "not_visible_screen_verification",
        ],
        confidence=0.78,
    )


class _FakeLocator:
    def __init__(self, page: "_FakeRobustPage", selector: str) -> None:
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


class _FakeRobustPage:
    def __init__(self) -> None:
        self.url = "http://127.0.0.1:60123/robust.html"
        self.wait_for_timeout_calls: list[int] = []
        self.controls = [
            {
                "control_id": "search-aria-label",
                "role": "textbox",
                "name": "Search",
                "label": "Search",
                "selector_hint": "#search",
                "enabled": True,
                "visible": True,
            },
            {
                "control_id": "email-labelledby",
                "role": "textbox",
                "name": "Email address",
                "label": "Email address",
                "selector_hint": "#email",
                "enabled": True,
                "visible": True,
                "required": True,
            },
            {
                "control_id": "invite-placeholder",
                "role": "textbox",
                "name": "Enter invite code",
                "label": "Enter invite code",
                "selector_hint": "#invite",
                "enabled": True,
                "visible": True,
            },
            {
                "control_id": "settings-icon-button",
                "role": "button",
                "name": "Settings",
                "label": "Settings",
                "text": "",
                "selector_hint": "#settings",
                "enabled": True,
                "visible": True,
            },
            {
                "control_id": "readonly-ref",
                "role": "textbox",
                "name": "Reference number",
                "label": "Reference number",
                "selector_hint": "#reference",
                "enabled": True,
                "visible": True,
                "readonly": True,
            },
            {
                "control_id": "password-secret",
                "role": "textbox",
                "name": "Password",
                "label": "Password",
                "selector_hint": "#password",
                "enabled": True,
                "visible": True,
                "input_type": "password",
                "value_summary": "super-secret-password",
            },
        ]
        for index in range(50):
            self.controls.append(
                {
                    "control_id": f"button-extra-{index}",
                    "role": "button",
                    "name": f"Extra {index}",
                    "text": f"Extra {index}",
                    "enabled": True,
                    "visible": True,
                }
            )
        self.forms = [
            {
                "form_id": "form-like-checkout",
                "name": "Checkout panel",
                "field_count": 5,
                "summary": "Checkout panel",
                "inferred": True,
            }
        ]
        self.dialogs = [{"dialog_id": "alert-warning", "role": "alert", "name": "Warning", "text": "Session expired"}]
        self.text_regions = [{"text": "Robust fixture"}]
        self.goto_calls: list[dict[str, object]] = []

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})
        self.url = url

    def title(self) -> str:
        return "Robust Semantic Fixture"

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def evaluate(self, _script: str):
        return {
            "iframe_count": 2,
            "cross_origin_iframe_count": 1,
            "shadow_host_count": 1,
            "control_count": len(self.controls),
        }

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_for_timeout_calls.append(ms)


class _FakeContext:
    def __init__(self, page: _FakeRobustPage) -> None:
        self.page = page
        self.closed = False
        self.clear_cookies_called = False

    def new_page(self) -> _FakeRobustPage:
        return self.page

    def clear_cookies(self) -> None:
        self.clear_cookies_called = True

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self.context = context
        self.closed = False

    def new_context(self, **_kwargs):
        return self.context

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser

    def launch(self, **_kwargs):
        return self.browser


class _FakePlaywright:
    def __init__(self, page: _FakeRobustPage) -> None:
        self.context = _FakeContext(page)
        self.browser = _FakeBrowser(self.context)
        self.chromium = _FakeChromium(self.browser)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_live_observation_reports_real_world_labels_states_and_limitations() -> None:
    page = _FakeRobustPage()
    config = _enabled_config(launch=True)
    adapter = PlaywrightBrowserSemanticAdapter(
        config.browser_adapters.playwright,
        dependency_checker=lambda: True,
        browser_engine_checker=lambda: True,
        sync_playwright_factory=lambda: _FakePlaywright(page),
    )

    observation = adapter.observe_live_browser_page("http://127.0.0.1:60123/robust.html", fixture_mode=True)
    controls = {control.control_id: control for control in observation.controls}

    assert len(observation.controls) == 40
    assert controls["search-aria-label"].label == "Search"
    assert controls["email-labelledby"].name == "Email address"
    assert controls["invite-placeholder"].label == "Enter invite code"
    assert controls["settings-icon-button"].name == "Settings"
    assert controls["readonly-ref"].readonly is True
    assert controls["password-secret"].value_summary == "[redacted sensitive field]"
    assert "super-secret-password" not in str(observation.to_dict())
    assert "partial_semantic_observation" in observation.limitations
    assert "large_control_list_truncated" in observation.limitations
    assert "iframe_context_limited" in observation.limitations
    assert "cross_origin_iframe_not_observed" in observation.limitations
    assert "shadow_dom_context_limited" in observation.limitations
    assert page.wait_for_timeout_calls


def test_grounding_handles_synonyms_negation_last_ordinal_and_readonly_state() -> None:
    adapter = _adapter()
    observation = _observation(
        [
            BrowserSemanticControl("search", role="textbox", name="Search", label="Search", enabled=True, visible=True),
            BrowserSemanticControl("email", role="textbox", name="Email address", label="Email address", enabled=True, visible=True, required=True),
            BrowserSemanticControl("optional-note", role="textbox", name="Notes", label="Notes", enabled=True, visible=True, required=False),
            BrowserSemanticControl("reference", role="textbox", name="Reference number", label="Reference number", enabled=True, visible=True, readonly=True),
            BrowserSemanticControl("button-back", role="button", name="Back", text="Back", enabled=True, visible=True),
            BrowserSemanticControl("button-next", role="button", name="Continue", text="Continue", enabled=True, visible=True),
            BrowserSemanticControl("button-disabled", role="button", name="Submit", text="Submit", enabled=False, visible=True),
        ]
    )

    assert adapter.ground_target("e-mail input", observation)[0].control_id == "email"
    assert adapter.ground_target("find box", observation)[0].control_id == "search"
    assert adapter.ground_target("last button", observation)[0].control_id == "button-disabled"
    not_disabled = adapter.ground_target("not disabled button", observation)
    not_required = adapter.ground_target("not required field", observation)
    readonly = adapter.ground_target("readonly field", observation)

    assert [candidate.control_id for candidate in not_disabled] == ["button-back", "button-next"]
    assert all("disabled_state_mismatch" not in candidate.mismatch_terms for candidate in not_disabled)
    assert not_required[0].control_id == "optional-note"
    assert "not_required_state_match" in not_required[0].evidence_terms
    assert readonly[0].control_id == "reference"
    assert "readonly_state_match" in readonly[0].evidence_terms
    assert all(candidate.action_supported is False for candidate in not_disabled + not_required + readonly)


def test_form_summary_groups_form_like_regions_and_redacts_sensitive_state() -> None:
    adapter = _adapter()
    observation = _observation(
        [
            BrowserSemanticControl("email", role="textbox", name="Email", label="Email", required=True, visible=True, enabled=True),
            BrowserSemanticControl("password", role="textbox", name="Password", label="Password", required=True, visible=True, enabled=True, risk_hint="sensitive_input", value_summary="super-secret"),
            BrowserSemanticControl("agree", role="checkbox", name="I agree", label="I agree", required=True, checked=False, visible=True, enabled=True),
            BrowserSemanticControl("reference", role="textbox", name="Reference", label="Reference", visible=True, enabled=True, readonly=True),
            BrowserSemanticControl("submit", role="button", name="Submit", text="Submit", visible=True, enabled=False),
            BrowserSemanticControl("continue", role="button", name="Continue", text="Continue", visible=True, enabled=True),
        ],
        forms=[
            {"form_id": "checkout-panel", "name": "Checkout", "field_count": 5, "summary": "Checkout form", "inferred": True},
            {"form_id": "newsletter-panel", "name": "Newsletter", "field_count": 1, "summary": "Newsletter form", "inferred": True},
        ],
    )

    summary = adapter.summarize_observation(observation)

    assert summary["form_count"] == 2
    assert summary["multiple_forms"] is True
    assert summary["form_like_structure_inferred"] is True
    assert summary["form_groups"][0]["name"] == "Checkout"
    assert summary["readonly_fields"] == ["Reference"]
    assert summary["unchecked_required_controls"] == ["I agree"]
    assert summary["possible_submit_controls"] == ["Submit", "Continue"]
    assert summary["sensitive_fields"] == ["Password"]
    assert "super-secret" not in str(summary)


def test_grounding_events_include_bounded_candidate_evidence_without_raw_secrets() -> None:
    events = EventBuffer(capacity=16)
    adapter = _adapter(events=events)
    observation = _observation(
        [
            BrowserSemanticControl("email", role="textbox", name="Email", label="Email", required=True, visible=True, enabled=True),
            BrowserSemanticControl("password", role="textbox", name="Password", label="Password", risk_hint="sensitive_input", value_summary="super-secret", visible=True, enabled=True),
        ],
        limitations=["live_semantic_observation_only", "iframe_context_limited", "no_actions"],
    )

    candidates = adapter.ground_target("required email field", observation)
    guidance = adapter.produce_guidance_step(candidates, observation=observation)
    event_text = str(events.recent(limit=16)).lower()

    assert candidates[0].control_id == "email"
    assert "required_state_match" in candidates[0].evidence_terms
    assert "iframe_context_limited" in guidance["limitations"]
    assert "evidence_terms" in event_text
    assert "required_state_match" in event_text
    assert "iframe_context_limited" in event_text
    assert "super-secret" not in event_text


def test_deck_payload_surfaces_partial_limitations_and_form_summary() -> None:
    status = {
        "screen_awareness": {
            "enabled": True,
            "phase": "phase12",
            "policy_state": {"summary": "Screen Awareness owns browser semantics."},
            "hardening": {"latest_trace": {"total_duration_ms": 6.0}},
            "browser_adapters": {
                "playwright": {
                    "status": "runtime_ready",
                    "playwright_runtime_ready": True,
                    "live_actions_enabled": False,
                    "claim_ceiling": "browser_semantic_observation",
                    "last_observation_summary": {
                        "provider": "playwright_live_semantic",
                        "browser_context_kind": "isolated_playwright_context",
                        "page_title": "Robust Semantic Fixture",
                        "page_url": "http://127.0.0.1:60123/robust.html",
                        "control_count": 40,
                        "form_count": 2,
                        "dialog_count": 1,
                        "alert_count": 1,
                        "limitations": ["partial_semantic_observation", "iframe_context_limited"],
                        "form_summary": {
                            "field_count": 4,
                            "required_field_count": 3,
                            "disabled_control_count": 1,
                            "link_count": 0,
                            "warning_count": 1,
                            "form_count": 2,
                            "claim_ceiling": "browser_semantic_observation",
                        },
                        "claim_ceiling": "browser_semantic_observation",
                    },
                    "last_grounding_summary": {
                        "status": "ambiguous",
                        "candidate_count": 2,
                        "top_candidates": [
                            {
                                "control_id": "button-back",
                                "name": "Back",
                                "confidence": 0.62,
                                "evidence_terms": ["role_match"],
                                "mismatch_terms": ["weak_name_match"],
                            },
                            {
                                "control_id": "button-next",
                                "name": "Continue",
                                "confidence": 0.61,
                                "evidence_terms": ["role_match"],
                                "mismatch_terms": ["weak_name_match"],
                            },
                        ],
                    },
                }
            },
        }
    }

    surface = build_command_surface_model(
        active_request_state={"family": "screen_awareness", "subject": "fixture page", "parameters": {"result_state": "attempted"}},
        active_task=None,
        recent_context_resolutions=[],
        latest_message={"content": "Two matching controls found.", "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}}},
        status=status,
        workspace_focus={},
    )
    station = next(item for item in surface["deckStations"] if item["stationFamily"] == "screen_awareness")
    station_text = str(station).lower()

    assert "partial semantic observation" in station_text
    assert "iframe context limited" in station_text
    assert "2 forms" in station_text
    assert "required" in station_text
    assert "click" not in station_text
    assert "typed" not in station_text
    assert "submitted" not in station_text
    assert "verified" not in station_text
