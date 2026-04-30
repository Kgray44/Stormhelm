from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from datetime import datetime
from importlib.util import find_spec
import ipaddress
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from stormhelm.config.models import PlaywrightBrowserAdapterConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.events import EventFamily
from stormhelm.core.events import EventRetentionClass
from stormhelm.core.events import EventSeverity
from stormhelm.core.events import EventVisibilityScope
from stormhelm.core.screen_awareness.models import (
    BrowserGroundingCandidate,
    BrowserSemanticActionExecutionRequest,
    BrowserSemanticActionExecutionResult,
    BrowserSemanticActionPlan,
    BrowserSemanticActionPreview,
    BrowserSemanticChange,
    BrowserSemanticControl,
    BrowserSemanticObservation,
    BrowserSemanticVerificationRequest,
    BrowserSemanticVerificationResult,
    PlaywrightAdapterReadiness,
)
from stormhelm.core.trust import PermissionScope
from stormhelm.core.trust import TrustActionKind
from stormhelm.core.trust import TrustActionRequest
from stormhelm.core.trust import TrustDecisionOutcome
from stormhelm.shared.time import utc_now_iso


DependencyChecker = Callable[[], bool]
BrowserEngineChecker = Callable[[], bool]
SyncPlaywrightFactory = Callable[[], Any]

_CLAIM_CEILING = "browser_semantic_observation"
_COMPARISON_CLAIM_CEILING = "browser_semantic_observation_comparison"
_ACTION_PREVIEW_CLAIM_CEILING = "browser_semantic_action_preview"
_ACTION_EXECUTION_CLAIM_CEILING = "browser_semantic_action_execution"
_MOCK_LIMITATIONS = [
    "mock_semantic_observation",
    "no_live_browser_connection",
    "no_actions",
    "not_visible_screen_verification",
    "not_truth_verified",
]
_LIVE_LIMITATIONS = [
    "live_semantic_observation_only",
    "isolated_temporary_browser_context",
    "no_user_profile",
    "no_actions",
    "not_visible_screen_verification",
    "not_truth_verified",
]
_TEXT_LIMIT = 240
_LIST_LIMIT = 40
_GROUNDING_CANDIDATE_LIMIT = 6
_STALE_OBSERVATION_SECONDS = 120.0
_ROLE_ALIASES = {
    "button": {"button", "btn"},
    "textbox": {"textbox", "text box", "field", "input", "email field", "search field", "search box", "box"},
    "checkbox": {"checkbox", "check box"},
    "link": {"link", "anchor"},
    "alert": {"alert", "dialog", "message", "warning", "popup", "pop up"},
    "combobox": {"combobox", "combo box", "select", "dropdown", "drop down"},
}
_ROLE_SYNONYMS = {
    "field": "textbox",
    "input": "textbox",
    "search": "textbox",
    "searchbox": "textbox",
    "dropdown": "combobox",
    "select": "combobox",
    "popup": "alert",
    "dialog": "alert",
    "warning": "alert",
    "message": "alert",
}
_ROLE_DISPLAY = {
    "textbox": "field",
    "alert": "dialog",
}
_STOPWORDS = {"a", "an", "the", "this", "that", "visible", "enabled", "find", "where", "is", "are", "please", "thing", "says", "not"}
_ORDINALS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "last": -1,
}
_STATE_TERMS = {
    "disabled": ("enabled", False, "disabled_state_match"),
    "enabled": ("enabled", True, "enabled_state_match"),
    "required": ("required", True, "required_state_match"),
    "checked": ("checked", True, "checked_state_match"),
    "unchecked": ("checked", False, "unchecked_state_match"),
    "expanded": ("expanded", True, "expanded_state_match"),
    "readonly": ("readonly", True, "readonly_state_match"),
    "read only": ("readonly", True, "readonly_state_match"),
}
_CONTROL_EXTRACTION_SCRIPT = r"""elements => {
  const textOf = (node) => (node && (node.innerText || node.textContent || '') || '').trim();
  const byIdText = (id) => {
    if (!id) return '';
    const node = document.getElementById(id);
    return textOf(node);
  };
  const labelledByText = element => ((element.getAttribute && element.getAttribute('aria-labelledby') || '').split(/\s+/).map(byIdText).filter(Boolean).join(' ').trim());
  const parentLabelText = element => {
    const label = element.closest ? element.closest('label') : null;
    return textOf(label);
  };
  const nearbyText = element => {
    const previous = element.previousElementSibling;
    const parent = element.parentElement;
    return textOf(previous) || (parent ? textOf(parent.querySelector('label')) : '');
  };
  return elements.slice(0, 40).map((element, index) => {
    const tag = element.tagName.toLowerCase();
    const type = (element.getAttribute('type') || '').toLowerCase();
    const roleAttr = element.getAttribute('role') || '';
    const role = roleAttr || (tag === 'a' ? 'link' : tag === 'button' ? 'button' : tag === 'select' ? 'combobox' : tag === 'textarea' ? 'textbox' : tag === 'input' ? (type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : 'textbox') : tag);
    const labels = element.labels ? Array.from(element.labels).map(label => label.innerText || label.textContent || '').join(' ').trim() : '';
    const ariaLabel = element.getAttribute('aria-label') || '';
    const text = tag === 'input' || tag === 'textarea' || tag === 'select' ? '' : (element.innerText || element.textContent || '').trim();
    const placeholder = element.getAttribute('placeholder') || '';
    const labelledBy = labelledByText(element);
    const nearby = parentLabelText(element) || nearbyText(element);
    const name = ariaLabel || labelledBy || labels || text || placeholder || nearby || element.getAttribute('name') || '';
    const label = ariaLabel || labelledBy || labels || placeholder || nearby || '';
    const rect = element.getBoundingClientRect();
    const sensitive = type === 'password' || /password|secret|token|api key|passcode/i.test(`${name} ${label} ${element.getAttribute('name') || ''}`);
    const hasValue = !!element.value;
    return {
        control_id: element.id || `${role || 'control'}-${index + 1}`,
        role,
        name,
        label,
        text,
        selector_hint: element.id ? `#${element.id}` : tag,
        bounding_hint: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
        enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
        visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
        checked: element.checked === true,
        expanded: element.getAttribute('aria-expanded') === null ? null : element.getAttribute('aria-expanded') === 'true',
        required: element.required === true || element.getAttribute('aria-required') === 'true',
        readonly: element.readOnly === true || element.getAttribute('aria-readonly') === 'true',
        input_type: type,
        value_summary: sensitive ? '[redacted sensitive field]' : hasValue ? '[redacted value]' : '',
        risk_hint: sensitive ? 'sensitive_input' : (type === 'hidden' ? 'hidden_input' : '')
    };
  });
}"""
_FORM_EXTRACTION_SCRIPT = r"""elements => elements.slice(0, 40).map((element, index) => ({
    form_id: element.id || element.getAttribute('name') || `form-${index + 1}`,
    name: element.getAttribute('aria-label') || element.getAttribute('name') || element.id || '',
    field_count: element.querySelectorAll('input, textarea, select, button').length,
    summary: element.getAttribute('aria-label') || element.getAttribute('name') || element.id || 'form-like group',
    inferred: element.tagName.toLowerCase() !== 'form'
}))"""
_DIALOG_EXTRACTION_SCRIPT = r"""elements => elements.slice(0, 40).map((element, index) => {
    const role = element.getAttribute('role') || element.tagName.toLowerCase();
    const text = (element.innerText || element.textContent || '').trim();
    return {
        dialog_id: element.id || `${role || 'dialog'}-${index + 1}`,
        alert_id: element.id || `${role || 'alert'}-${index + 1}`,
        role,
        name: element.getAttribute('aria-label') || '',
        text
    };
})"""
_TEXT_REGION_EXTRACTION_SCRIPT = r"""elements => elements.slice(0, 40).map((element, index) => ({
    text: (element.innerText || element.textContent || '').trim(),
    role: element.getAttribute('role') || element.tagName.toLowerCase(),
    name: element.getAttribute('aria-label') || `text-${index + 1}`
}))"""
_PAGE_CONTEXT_EXTRACTION_SCRIPT = r"""() => {
    const frameNodes = Array.from(document.querySelectorAll('iframe, frame'));
    let crossOriginCount = 0;
    for (const frame of frameNodes) {
        try {
            void frame.contentWindow && frame.contentWindow.location.href;
        } catch (_error) {
            crossOriginCount += 1;
        }
    }
    const shadowHostCount = Array.from(document.querySelectorAll('*')).filter(node => !!node.shadowRoot).length;
    return {
        ready_state: document.readyState || '',
        control_count: document.querySelectorAll('button, input, textarea, select, a, [role]').length,
        iframe_count: frameNodes.length,
        cross_origin_iframe_count: crossOriginCount,
        shadow_host_count: shadowHostCount,
        form_like_count: document.querySelectorAll("form, [role='form'], [data-form], .form").length
    };
}"""


@dataclass(slots=True)
class PlaywrightBrowserSemanticAdapter:
    config: PlaywrightBrowserAdapterConfig
    dependency_checker: DependencyChecker | None = None
    browser_engine_checker: BrowserEngineChecker | None = None
    sync_playwright_factory: SyncPlaywrightFactory | None = None
    events: EventBuffer | None = None

    adapter_id: str = "screen_awareness.browser.playwright"
    provider: str = "playwright"
    _last_observation_summary: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_grounding_summary: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_verification_summary: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_action_preview_summary: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _last_action_execution_summary: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    @property
    def last_observation_summary(self) -> dict[str, Any]:
        return dict(self._last_observation_summary)

    @property
    def last_grounding_summary(self) -> dict[str, Any]:
        return dict(self._last_grounding_summary)

    @property
    def last_verification_summary(self) -> dict[str, Any]:
        return dict(self._last_verification_summary)

    @property
    def last_action_preview_summary(self) -> dict[str, Any]:
        return dict(self._last_action_preview_summary)

    @property
    def last_action_execution_summary(self) -> dict[str, Any]:
        return dict(self._last_action_execution_summary)

    def status_snapshot(self) -> dict[str, Any]:
        readiness = self.get_readiness(emit_event=False).to_dict()
        declared_action_capabilities = _declared_action_capabilities(self.config, readiness)
        readiness.update(
            {
                "playwright_adapter_enabled": readiness["enabled"],
                "playwright_adapter_status": readiness["status"],
                "playwright_dependency_available": readiness["dependency_installed"],
                "playwright_mock_ready": readiness["mock_ready"],
                "playwright_runtime_ready": readiness["runtime_ready"],
                "playwright_live_observation_enabled": bool(
                    readiness["runtime_ready"] and self.config.allow_browser_launch
                ),
                "live_actions_enabled": bool(declared_action_capabilities),
                "click_enabled": "browser.input.click" in declared_action_capabilities,
                "focus_enabled": "browser.input.focus" in declared_action_capabilities,
                "declared_action_capabilities": declared_action_capabilities,
                "forbidden_action_capabilities": [
                    "browser.input.type",
                    "browser.input.scroll",
                    "browser.form.fill",
                    "browser.form.submit",
                    "browser.login",
                    "browser.cookies.read",
                    "browser.cookies.write",
                    "browser.download",
                    "browser.payment",
                    "browser.user_profile.attach",
                    "browser.visible_screen_verify",
                    "browser.truth_verify",
                    "browser.workflow_replay",
                ],
                "last_observation_summary": self.last_observation_summary,
                "last_grounding_summary": self.last_grounding_summary,
                "last_verification_summary": self.last_verification_summary,
                "last_action_preview_summary": self.last_action_preview_summary,
                "last_action_execution_summary": self.last_action_execution_summary,
            }
        )
        return readiness

    def get_readiness(self, *, emit_event: bool = False) -> PlaywrightAdapterReadiness:
        warnings = _unsafe_flag_warnings(self.config)
        if not self.config.enabled:
            readiness = PlaywrightAdapterReadiness(
                status="disabled",
                enabled=False,
                available=False,
                dependency_installed=False,
                actions_enabled=False,
                launch_allowed=False,
                connect_existing_allowed=False,
                blocking_reasons=["playwright_adapter_disabled"],
                warnings=warnings,
            )
            self._publish_readiness(readiness, emit_event=emit_event)
            return readiness

        dependency_installed, dependency_error = self._safe_dependency_installed()
        live_runtime_allowed = bool(self.config.allow_browser_launch or self.config.allow_connect_existing)
        launch_allowed = bool(self.config.allow_browser_launch)
        connect_allowed = bool(self.config.allow_connect_existing)
        blocking: list[str] = []
        if dependency_error:
            blocking.append("playwright_dependency_check_failed")
        if not self.config.allow_dev_adapter:
            blocking.append("playwright_dev_adapter_gate_required")
        blocking.extend(_unsupported_flag_blockers(self.config))

        if dependency_error:
            readiness = PlaywrightAdapterReadiness(
                status="failed",
                enabled=True,
                available=False,
                dependency_installed=False,
                live_runtime_allowed=live_runtime_allowed,
                actions_enabled=False,
                launch_allowed=launch_allowed,
                connect_existing_allowed=connect_allowed,
                blocking_reasons=list(dict.fromkeys(blocking)),
                warnings=warnings,
                bounded_error_message=_bounded_text(dependency_error),
            )
            self._publish_readiness(readiness, emit_event=emit_event)
            return readiness

        if not self.config.allow_dev_adapter:
            readiness = PlaywrightAdapterReadiness(
                status="dev_gate_required",
                enabled=True,
                available=False,
                dependency_installed=dependency_installed,
                live_runtime_allowed=live_runtime_allowed,
                actions_enabled=False,
                launch_allowed=launch_allowed,
                connect_existing_allowed=connect_allowed,
                blocking_reasons=list(dict.fromkeys(blocking)),
                warnings=warnings,
            )
            self._publish_readiness(readiness, emit_event=emit_event)
            return readiness

        mock_ready = not _unsupported_flag_blockers(self.config)
        if not live_runtime_allowed:
            readiness = PlaywrightAdapterReadiness(
                status="mock_ready",
                enabled=True,
                available=mock_ready,
                dependency_installed=dependency_installed,
                mock_ready=mock_ready,
                mock_provider_active=mock_ready,
                runtime_ready=False,
                live_runtime_allowed=False,
                actions_enabled=False,
                launch_allowed=False,
                connect_existing_allowed=False,
                blocking_reasons=list(dict.fromkeys(blocking)),
                warnings=warnings + ([] if dependency_installed else ["playwright_dependency_missing_live_runtime_disabled"]),
            )
            self._publish_readiness(readiness, emit_event=emit_event)
            return readiness

        if not dependency_installed:
            readiness = PlaywrightAdapterReadiness(
                status="dependency_missing",
                enabled=True,
                available=False,
                dependency_installed=False,
                mock_ready=mock_ready,
                mock_provider_active=mock_ready,
                runtime_ready=False,
                live_runtime_allowed=True,
                actions_enabled=False,
                launch_allowed=launch_allowed,
                connect_existing_allowed=connect_allowed,
                blocking_reasons=list(dict.fromkeys(blocking + ["playwright_dependency_missing"])),
                warnings=warnings,
            )
            self._publish_readiness(readiness, emit_event=emit_event)
            return readiness

        engines_available, engines_checkable, engines_error = self._safe_browser_engines_available()
        if engines_error:
            readiness = PlaywrightAdapterReadiness(
                status="failed",
                enabled=True,
                available=False,
                dependency_installed=True,
                browser_engines_available=False,
                browser_engines_checkable=engines_checkable,
                mock_ready=mock_ready,
                mock_provider_active=mock_ready,
                runtime_ready=False,
                live_runtime_allowed=True,
                actions_enabled=False,
                launch_allowed=launch_allowed,
                connect_existing_allowed=connect_allowed,
                blocking_reasons=list(dict.fromkeys(blocking + ["playwright_browser_engine_check_failed"])),
                warnings=warnings,
                bounded_error_message=_bounded_text(engines_error),
            )
            self._publish_readiness(readiness, emit_event=emit_event)
            return readiness

        if engines_checkable and not engines_available:
            readiness = PlaywrightAdapterReadiness(
                status="browsers_missing",
                enabled=True,
                available=False,
                dependency_installed=True,
                browser_engines_available=False,
                browser_engines_checkable=True,
                mock_ready=mock_ready,
                mock_provider_active=mock_ready,
                runtime_ready=False,
                live_runtime_allowed=True,
                actions_enabled=False,
                launch_allowed=launch_allowed,
                connect_existing_allowed=connect_allowed,
                blocking_reasons=list(dict.fromkeys(blocking + ["playwright_browser_engines_missing"])),
                warnings=warnings,
            )
            self._publish_readiness(readiness, emit_event=emit_event)
            return readiness

        runtime_ready = not blocking
        readiness = PlaywrightAdapterReadiness(
            status="runtime_ready" if runtime_ready else "unavailable",
            enabled=True,
            available=runtime_ready,
            dependency_installed=True,
            browser_engines_available=engines_available,
            browser_engines_checkable=engines_checkable,
            mock_ready=mock_ready,
            mock_provider_active=mock_ready,
            runtime_ready=runtime_ready,
            live_runtime_allowed=True,
            actions_enabled=bool(runtime_ready and _action_gates_requested(self.config)),
            launch_allowed=launch_allowed,
            connect_existing_allowed=connect_allowed,
            blocking_reasons=list(dict.fromkeys(blocking)),
            warnings=warnings + ([] if engines_checkable else ["browser_engine_check_not_available_without_launch"]),
        )
        self._publish_readiness(readiness, emit_event=emit_event)
        return readiness

    def observe_browser_page(self, context: dict[str, Any] | None = None) -> BrowserSemanticObservation:
        readiness = self.get_readiness(emit_event=False)
        live_url = str((context or {}).get("url") or (context or {}).get("page_url") or "").strip()
        if live_url and readiness.runtime_ready and self.config.allow_browser_launch:
            return self.observe_live_browser_page(
                live_url,
                fixture_mode=bool((context or {}).get("fixture_mode", False)),
            )
        if readiness.mock_ready:
            return self.observe_mock_browser_page(context)
        return self._unavailable_mock_observation(context, readiness, publish_event=False)

    def observe_live_browser_page(
        self,
        url: str,
        *,
        fixture_mode: bool = False,
        context_options: dict[str, Any] | None = None,
    ) -> BrowserSemanticObservation:
        requested_url = _safe_display_url(url)
        readiness = self.get_readiness(emit_event=False)
        launch_blocker = _live_launch_blocker(self.config, readiness)
        url_blocker = _live_url_blocker(url, fixture_mode=fixture_mode)
        if launch_blocker or url_blocker:
            code = launch_blocker or url_blocker or "playwright_live_observation_unavailable"
            return self._unavailable_live_observation(
                url,
                code,
                readiness=readiness,
                publish_event=True,
            )

        self._publish(
            "screen_awareness.playwright_live_observation_started",
            "Playwright isolated browser semantic observation started.",
            {
                "page_url": requested_url,
                "fixture_mode": bool(fixture_mode),
                "claim_ceiling": _CLAIM_CEILING,
                "limitations": list(_LIVE_LIMITATIONS),
            },
        )
        browser = None
        context = None
        cleanup_status = "not_started"
        try:
            factory = self.sync_playwright_factory or _load_sync_playwright_factory()
            with factory() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    safe_context_options = _safe_context_options(context_options)
                    context = browser.new_context(storage_state=None, **safe_context_options)
                    page = context.new_page()
                    page.goto(
                        str(url),
                        wait_until="domcontentloaded",
                        timeout=int(self.config.navigation_timeout_seconds or 12000),
                    )
                    _wait_for_semantic_stabilization(page)
                    observation = _live_observation_from_page(
                        page,
                        adapter_id=self.adapter_id,
                        session_id=f"playwright-live-{uuid4().hex[:10]}",
                    )
                    self._last_observation_summary = _observation_summary(observation)
                    self._publish(
                        "screen_awareness.playwright_live_observation_completed",
                        "Playwright isolated browser semantic observation completed.",
                        {
                            "provider": observation.provider,
                            "browser_context_kind": observation.browser_context_kind,
                            "page_url": observation.page_url,
                            "page_title": observation.page_title,
                            "control_count": len(observation.controls),
                            "form_count": len(observation.forms),
                            "dialog_count": len(observation.dialogs),
                            "alert_count": len(observation.alerts),
                            "claim_ceiling": observation.claim_ceiling,
                            "limitations": list(observation.limitations),
                        },
                    )
                    return observation
                finally:
                    cleanup_status, _ = self._cleanup_isolated_browser_resources(
                        context,
                        browser,
                        claim_ceiling=_CLAIM_CEILING,
                        completed_message="Playwright isolated browser semantic observation cleanup completed.",
                        completed_limitations=["no_user_profile", "no_actions"],
                        failed_limitations=["cleanup_failed", "no_actions"],
                    )
                    context = None
                    browser = None
        except Exception as exc:
            self._publish(
                "screen_awareness.playwright_live_observation_failed",
                "Playwright isolated browser semantic observation failed.",
                {
                    "page_url": requested_url,
                    "error_code": _live_error_code(exc),
                    "bounded_error_message": _bounded_text(f"{type(exc).__name__}: {exc}"),
                    "claim_ceiling": _CLAIM_CEILING,
                    "limitations": ["live_observation_unavailable", "no_actions"],
                },
                severity=EventSeverity.WARNING,
            )
            return self._unavailable_live_observation(
                url,
                _live_error_code(exc),
                readiness=readiness,
                message=f"{type(exc).__name__}: {exc}",
                publish_event=False,
            )
        finally:
            if cleanup_status == "not_started" and (context is not None or browser is not None):
                self._cleanup_isolated_browser_resources(
                    context,
                    browser,
                    claim_ceiling=_CLAIM_CEILING,
                    completed_message="Playwright isolated browser semantic observation cleanup completed.",
                    completed_limitations=["no_user_profile", "no_actions"],
                    failed_limitations=["cleanup_failed", "no_actions"],
                )

    def observe_mock_browser_page(self, context: dict[str, Any] | None = None) -> BrowserSemanticObservation:
        readiness = self.get_readiness(emit_event=False)
        if not readiness.mock_ready:
            return self._unavailable_mock_observation(context, readiness)
        context = _default_mock_context() if context is None else dict(context)
        controls = [_control_from_mapping(item) for item in _mapping_list(context.get("controls"))[:_LIST_LIMIT]]
        dialogs = [_bounded_mapping(item, id_keys=("dialog_id", "role", "text", "name")) for item in _mapping_list(context.get("dialogs"))[:_LIST_LIMIT]]
        alerts = [_bounded_mapping(item, id_keys=("alert_id", "role", "text", "name")) for item in _mapping_list(context.get("alerts"))[:_LIST_LIMIT]]
        observation = BrowserSemanticObservation(
            provider="playwright_mock",
            adapter_id=self.adapter_id,
            session_id=str(context.get("session_id") or "playwright-mock-session"),
            page_url=_safe_display_url(context.get("page_url") or context.get("url") or "https://example.test/checkout"),
            page_title=_bounded_text(context.get("page_title") or context.get("title") or "Example Checkout"),
            browser_context_kind="mock",
            observed_at=utc_now_iso(),
            controls=controls,
            text_regions=[
                _bounded_mapping(item, id_keys=("text", "role", "name"))
                for item in _mapping_list(context.get("text_regions"))[:_LIST_LIMIT]
            ],
            forms=[
                _bounded_mapping(item, id_keys=("form_id", "name", "field_count", "summary"))
                for item in _mapping_list(context.get("forms"))[:_LIST_LIMIT]
            ],
            landmarks=[
                _bounded_mapping(item, id_keys=("landmark_id", "role", "name", "label"))
                for item in _mapping_list(context.get("landmarks"))[:_LIST_LIMIT]
            ],
            tables=[
                _bounded_mapping(item, id_keys=("table_id", "name", "row_count", "column_count"))
                for item in _mapping_list(context.get("tables"))[:_LIST_LIMIT]
            ],
            dialogs=dialogs,
            alerts=alerts,
            limitations=list(_MOCK_LIMITATIONS),
            confidence=float(context.get("confidence") or 0.65),
        )
        self._last_observation_summary = _observation_summary(observation)
        self._publish(
            "screen_awareness.playwright_mock_observation_created",
            "Mock browser semantic observation created.",
            {
                "provider": observation.provider,
                "browser_context_kind": observation.browser_context_kind,
                "page_url": observation.page_url,
                "page_title": observation.page_title,
                "control_count": len(observation.controls),
                "dialog_count": len(observation.dialogs),
                "alert_count": len(observation.alerts),
                "claim_ceiling": observation.claim_ceiling,
                "limitations": list(observation.limitations),
            },
        )
        return observation

    def get_semantic_snapshot(self, context: dict[str, Any] | None = None) -> BrowserSemanticObservation:
        return self.observe_browser_page(context)

    def ground_target(
        self,
        target_phrase: str,
        observation: BrowserSemanticObservation,
    ) -> list[BrowserGroundingCandidate]:
        target = _normalize(target_phrase)
        self._publish(
            "screen_awareness.playwright_grounding_started",
            "Playwright semantic grounding started.",
            {
                "target_phrase": _bounded_text(target_phrase),
                "provider": observation.provider,
                "source_observation_id": observation.observation_id,
                "claim_ceiling": _CLAIM_CEILING,
            },
        )
        if not target:
            self._last_grounding_summary = _grounding_summary(target_phrase, [], status="no_match")
            self._publish_grounding_event(target_phrase, [], status="no_match", observation=observation)
            return []

        analysis = _target_analysis(target_phrase)
        elements = _semantic_elements(observation)
        candidates = _rank_grounding_candidates(target_phrase, observation, elements, analysis)
        status = "no_match"
        if not candidates and analysis["target_role"] and not _hidden_semantic_match_exists(observation, analysis):
            candidates = _closest_grounding_candidates(target_phrase, observation, elements, analysis)
            status = "closest_match" if candidates else "no_match"
        elif candidates:
            status = "ambiguous" if len(candidates) > 1 else "completed"
        if len(candidates) > 1:
            for candidate in candidates:
                candidate.ambiguity_reason = "multiple_semantic_controls_matched"
        self._last_grounding_summary = _grounding_summary(target_phrase, candidates, status=status)
        self._publish_grounding_event(target_phrase, candidates, status=status, observation=observation)
        return candidates

    def produce_guidance_step(
        self,
        candidate: BrowserGroundingCandidate | Sequence[BrowserGroundingCandidate],
        *,
        observation: BrowserSemanticObservation | None = None,
    ) -> dict[str, Any]:
        candidates = list(candidate) if isinstance(candidate, Sequence) and not isinstance(candidate, BrowserGroundingCandidate) else [candidate]  # type: ignore[list-item]
        limitations = _guidance_limitations(observation.limitations if observation is not None else _MOCK_LIMITATIONS)
        if candidates and any("stale_observation" in candidate.mismatch_terms for candidate in candidates):
            limitations = list(dict.fromkeys(limitations + ["observation_may_be_stale"]))
        if len(candidates) > 1:
            role = _plural_role(candidates[0].role if candidates else "control")
            names = [_candidate_label(item) for item in candidates[:4]]
            message = f"I found {_number_word(len(candidates))} matching {role}: {_human_list(names)}. Which one do you mean?"
            status = "ambiguous"
        elif candidates:
            one = candidates[0]
            if one.match_reason == "closest_match":
                message = f"I did not find a {_target_display_phrase(one.target_phrase)}. The closest match is {_candidate_label(one)}."
                status = "closest_match"
            else:
                message = _found_message(one)
                status = "guidance_only"
                if one.role == "button" and "disabled_state_match" in one.evidence_terms:
                    message += " The button appears disabled."
                elif one.role == "checkbox" and "unchecked_state_match" in one.evidence_terms:
                    message += " The checkbox appears unchecked."
                elif one.role == "checkbox" and "checked_state_match" in one.evidence_terms:
                    message += " The checkbox appears checked."
        else:
            if any(limitation in limitations for limitation in {"playwright_adapter_disabled", "mock_observation_unavailable"}):
                message = "Playwright browser semantic observation is unavailable."
                status = "unavailable"
            elif observation is not None and observation.provider == "playwright_live_semantic":
                message = "I could not ground that target in the latest isolated browser semantic snapshot."
                status = "no_match"
            else:
                message = "I could not ground that target in the mock browser observation."
                status = "no_match"
        payload = {
            "adapter_id": self.adapter_id,
            "candidate_id": candidates[0].candidate_id if len(candidates) == 1 else "",
            "status": status,
            "message": message,
            "candidate_count": len(candidates),
            "source_provider": observation.provider if observation is not None else "",
            "source_observation_id": observation.observation_id if observation is not None else "",
            "top_candidates": [_candidate_summary(item) for item in candidates[:_GROUNDING_CANDIDATE_LIMIT]],
            "action_supported": False,
            "verification_supported": False,
            "claim_ceiling": _CLAIM_CEILING,
            "limitations": limitations,
        }
        live = observation is not None and observation.provider == "playwright_live_semantic"
        self._publish(
            "screen_awareness.playwright_live_guidance_created" if live else "screen_awareness.playwright_guidance_created",
            "Playwright live guidance created." if live else "Playwright mock guidance created.",
            {
                "status": status,
                "candidate_count": len(candidates),
                "source_provider": observation.provider if observation is not None else "",
                "claim_ceiling": _CLAIM_CEILING,
                "limitations": limitations,
            },
        )
        return payload

    def summarize_observation(self, observation: BrowserSemanticObservation) -> dict[str, Any]:
        summary = _form_page_summary(observation)
        self._publish(
            "screen_awareness.playwright_form_summary_created",
            "Playwright semantic form/page summary created.",
            {
                "provider": observation.provider,
                "source_observation_id": observation.observation_id,
                "field_count": summary["field_count"],
                "required_field_count": len(summary["required_fields"]),
                "disabled_control_count": len(summary["disabled_controls"]),
                "link_count": len(summary["links"]),
                "warning_count": len(summary["warnings"]),
                "claim_ceiling": _CLAIM_CEILING,
                "limitations": summary["limitations"],
            },
        )
        self._last_observation_summary = dict(self._last_observation_summary or _observation_summary(observation))
        self._last_observation_summary["form_summary"] = {
            "field_count": summary["field_count"],
            "required_field_count": len(summary["required_fields"]),
            "readonly_field_count": len(summary["readonly_fields"]),
            "unchecked_required_count": len(summary["unchecked_required_controls"]),
            "disabled_control_count": len(summary["disabled_controls"]),
            "possible_submit_count": len(summary["possible_submit_controls"]),
            "link_count": len(summary["links"]),
            "warning_count": len(summary["warnings"]),
            "form_count": summary["form_count"],
            "multiple_forms": summary["multiple_forms"],
            "form_like_structure_inferred": summary["form_like_structure_inferred"],
            "claim_ceiling": _CLAIM_CEILING,
        }
        return summary

    def compare_semantic_observations(
        self,
        before: BrowserSemanticObservation | None,
        after: BrowserSemanticObservation | None,
        expected: BrowserSemanticVerificationRequest | dict[str, Any] | None = None,
    ) -> BrowserSemanticVerificationResult:
        request = _coerce_verification_request(expected, before=before, after=after)
        self._publish(
            "screen_awareness.playwright_semantic_comparison_started",
            "Playwright semantic browser comparison started.",
            {
                "before_observation_id": request.before_observation_id,
                "after_observation_id": request.after_observation_id,
                "expected_change_kind": request.expected_change_kind,
                "target_phrase": _bounded_text(request.target_phrase),
                "claim_ceiling": _COMPARISON_CLAIM_CEILING,
                "limitations": ["semantic_comparison_only", "no_actions"],
            },
        )
        try:
            result = _compare_semantic_observations(before, after, request=request, adapter=self)
        except Exception as exc:
            result = BrowserSemanticVerificationResult(
                request_id=request.request_id,
                status="failed",
                summary="Semantic browser comparison failed.",
                before_observation_id=request.before_observation_id,
                after_observation_id=request.after_observation_id,
                confidence=0.0,
                limitations=["comparison_failed", "no_actions", "not_visible_screen_verification", "not_truth_verified"],
                user_message="I cannot verify that from these observations.",
                expected_change_missing=[_bounded_text(f"{type(exc).__name__}: {exc}")],
            )
            self._publish(
                "screen_awareness.playwright_semantic_comparison_failed",
                "Playwright semantic browser comparison failed.",
                {
                    "before_observation_id": request.before_observation_id,
                    "after_observation_id": request.after_observation_id,
                    "status": result.status,
                    "bounded_error_message": _bounded_text(f"{type(exc).__name__}: {exc}"),
                    "claim_ceiling": _COMPARISON_CLAIM_CEILING,
                    "limitations": result.limitations,
                },
                severity=EventSeverity.WARNING,
            )
        self._last_verification_summary = _verification_summary(result)
        self._publish_comparison_completed(result, request)
        return result

    def verify_semantic_change(
        self,
        request: BrowserSemanticVerificationRequest | dict[str, Any],
        *,
        before: BrowserSemanticObservation | None,
        after: BrowserSemanticObservation | None,
    ) -> BrowserSemanticVerificationResult:
        return self.compare_semantic_observations(before, after, expected=request)

    def build_action_preview(self, candidate: BrowserGroundingCandidate) -> dict[str, Any]:
        preview = BrowserSemanticActionPreview(
            observation_id=candidate.source_observation_id,
            source_provider=candidate.source_provider,
            target_phrase=candidate.target_phrase,
            target_candidate_id=candidate.candidate_id,
            target_role=candidate.role,
            target_name=candidate.name,
            target_label=candidate.label,
            action_kind="unsupported",
            preview_state="unsupported",
            reason_not_executable="unsupported_action_preview",
            confidence=round(float(candidate.confidence or 0.0), 3),
            risk_level="medium",
            approval_required=True,
            required_trust_scope="browser_action_once_future",
            expected_outcome=[],
            limitations=["preview_only", "action_execution_deferred", "unsupported_action_preview", "no_actions"],
        )
        self._last_action_preview_summary = _action_preview_summary(preview)
        payload = preview.to_dict()
        payload["status"] = preview.preview_state
        return payload

    def preview_semantic_action(
        self,
        observation: BrowserSemanticObservation,
        target_phrase: str,
        action_phrase: str,
        *,
        action_arguments: dict[str, Any] | None = None,
    ) -> BrowserSemanticActionPreview:
        candidates = self.ground_target(target_phrase, observation)
        action_kind = _classify_action_kind(action_phrase, candidates[0] if candidates else None)
        if len(candidates) > 1:
            preview = _action_preview_from_state(
                observation,
                target_phrase=target_phrase,
                action_kind=action_kind,
                state="ambiguous",
                reason="ambiguous_target",
                candidates=candidates,
            )
        elif not candidates and action_kind != "scroll_to":
            preview = _action_preview_from_state(
                observation,
                target_phrase=target_phrase,
                action_kind=action_kind,
                state="unsupported",
                reason="target_not_grounded",
            )
        elif candidates and candidates[0].match_reason == "closest_match":
            preview = _action_preview_from_state(
                observation,
                target_phrase=target_phrase,
                action_kind=action_kind,
                state="unsupported",
                reason="target_not_grounded",
                candidates=candidates,
            )
        elif action_kind == "unsupported":
            preview = _action_preview_from_state(
                observation,
                target_phrase=target_phrase,
                action_kind="unsupported",
                state="unsupported",
                reason="unsupported_action_preview",
                candidates=candidates,
            )
        else:
            candidate = candidates[0] if candidates else _page_scroll_candidate(target_phrase, observation)
            preview = _action_preview_for_candidate(
                observation,
                candidate,
                target_phrase=target_phrase,
                action_kind=action_kind,
                action_arguments=action_arguments,
                config=self.config,
            )
        self._last_action_preview_summary = _action_preview_summary(preview)
        self._publish_action_preview(preview)
        return preview

    def build_semantic_action_plan(
        self,
        preview: BrowserSemanticActionPreview | dict[str, Any],
        *,
        action_arguments: dict[str, Any] | None = None,
    ) -> BrowserSemanticActionPlan:
        preview_model = _coerce_action_preview(preview)
        plan = _action_plan_from_preview(preview_model, action_arguments=action_arguments, config=self.config)
        self._last_action_preview_summary = _action_preview_summary(preview_model, plan=plan)
        self._publish(
            "screen_awareness.playwright_action_plan_created",
            "Playwright browser action plan preview created.",
            {
                "preview_id": preview_model.preview_id,
                "plan_id": plan.plan_id,
                "action_kind": preview_model.action_kind,
                "target_role": preview_model.target_role,
                "target_name": _bounded_text(preview_model.target_name, 80),
                "confidence": round(float(preview_model.confidence or 0.0), 3),
                "risk_level": preview_model.risk_level,
                "approval_required": preview_model.approval_required,
                "executable_now": plan.executable_now,
                "claim_ceiling": _ACTION_PREVIEW_CLAIM_CEILING,
                "limitations": list(plan.limitations)[:8],
            },
        )
        return plan

    def request_semantic_action_execution(
        self,
        plan: BrowserSemanticActionPlan | dict[str, Any],
        *,
        url: str,
        trust_service: Any | None = None,
        session_id: str = "default",
        task_id: str = "",
        fixture_mode: bool = False,
        context_options: dict[str, Any] | None = None,
    ) -> BrowserSemanticActionExecutionResult:
        return self.execute_semantic_action(
            plan,
            url=url,
            trust_service=trust_service,
            session_id=session_id,
            task_id=task_id,
            fixture_mode=fixture_mode,
            context_options=context_options,
            require_only=True,
        )

    def execute_semantic_action(
        self,
        plan: BrowserSemanticActionPlan | dict[str, Any],
        *,
        url: str,
        trust_service: Any | None = None,
        session_id: str = "default",
        task_id: str = "",
        fixture_mode: bool = False,
        context_options: dict[str, Any] | None = None,
        require_only: bool = False,
    ) -> BrowserSemanticActionExecutionResult:
        plan_model = _coerce_action_plan(plan)
        request = _execution_request_from_plan(plan_model, session_id=session_id, task_id=task_id)
        self._publish(
            "screen_awareness.playwright_action_execution_requested",
            "Playwright browser action execution requested.",
            _execution_event_payload(request, plan_model, status="requested"),
        )

        gate_result = self._execution_gate_result(request, plan_model)
        if gate_result is not None:
            return self._finalize_action_execution(gate_result, event_type="screen_awareness.playwright_action_execution_blocked")

        action_request = _trust_action_request(request, plan_model)
        if trust_service is None:
            result = _execution_result(
                request,
                plan_model,
                status="approval_required",
                error_code="trust_service_required",
                user_message="Approval is required before this browser action can run.",
                limitations=["approval_required", "trust_service_required", "no_action_attempted"],
            )
            return self._finalize_action_execution(result, event_type="screen_awareness.playwright_action_approval_required")

        trust_decision = trust_service.evaluate_action(action_request)
        if trust_decision.outcome != TrustDecisionOutcome.ALLOWED:
            approval_request = trust_decision.approval_request
            blocked_by_operator = trust_decision.outcome == TrustDecisionOutcome.BLOCKED
            result = _execution_result(
                request,
                plan_model,
                status="blocked" if blocked_by_operator else "approval_required",
                trust_request_id=action_request.request_id,
                approval_request_id=approval_request.approval_request_id if approval_request is not None else "",
                trust_scope=action_request.suggested_scope.value,
                error_code="approval_denied" if blocked_by_operator else "",
                user_message=trust_decision.operator_message or "Approval is required before this browser action can run.",
                limitations=[("approval_denied" if blocked_by_operator else "approval_required"), "no_action_attempted"],
            )
            return self._finalize_action_execution(
                result,
                event_type=(
                    "screen_awareness.playwright_action_execution_blocked"
                    if blocked_by_operator
                    else "screen_awareness.playwright_action_approval_required"
                ),
            )

        if require_only:
            result = _execution_result(
                request,
                plan_model,
                status="approved",
                trust_request_id=action_request.request_id,
                approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                user_message="Approval is available for this browser action.",
                limitations=["approval_available", "action_not_attempted"],
            )
            return self._finalize_action_execution(result)

        browser = None
        context = None
        before: BrowserSemanticObservation | None = None
        after: BrowserSemanticObservation | None = None
        comparison: BrowserSemanticVerificationResult | None = None
        action_completed = False
        final_result: BrowserSemanticActionExecutionResult | None = None
        cleanup_status = "not_started"
        cleanup_error: Exception | None = None
        try:
            readiness = self.get_readiness(emit_event=False)
            launch_blocker = _live_launch_blocker(self.config, readiness)
            url_blocker = _live_url_blocker(url, fixture_mode=fixture_mode)
            if launch_blocker or url_blocker:
                result = _execution_result(
                    request,
                    plan_model,
                    status="blocked",
                    trust_request_id=action_request.request_id,
                    approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                    trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                    error_code=launch_blocker or url_blocker,
                    user_message="That browser action is not available under the current Playwright gates.",
                    limitations=["launch_or_url_blocked", launch_blocker or url_blocker],
                )
                final_result = self._finalize_action_execution(result, event_type="screen_awareness.playwright_action_execution_blocked")
                return final_result

            self._publish(
                "screen_awareness.playwright_action_execution_started",
                "Trust-gated Playwright browser action execution started.",
                _execution_event_payload(request, plan_model, status="executing"),
            )
            factory = self.sync_playwright_factory or _load_sync_playwright_factory()
            with factory() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    safe_context_options = _safe_context_options(context_options)
                    context = browser.new_context(storage_state=None, **safe_context_options)
                    page = context.new_page()
                    page.goto(
                        str(url),
                        wait_until="domcontentloaded",
                        timeout=int(self.config.navigation_timeout_seconds or 12000),
                    )
                    _wait_for_semantic_stabilization(page)
                    before = _live_observation_from_page(
                        page,
                        adapter_id=self.adapter_id,
                        session_id=f"playwright-action-before-{uuid4().hex[:10]}",
                    )
                    target_candidate = _resolve_execution_candidate(plan_model, before)
                    candidate_blocker = _candidate_execution_blocker(plan_model.action_kind, target_candidate)
                    if candidate_blocker:
                        result = _execution_result(
                            request,
                            plan_model,
                            status="blocked",
                            trust_request_id=action_request.request_id,
                            approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                            trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                            before_observation_id=before.observation_id,
                            error_code=candidate_blocker,
                            user_message="That browser target is not safe or specific enough for click/focus execution.",
                            limitations=["target_blocked", candidate_blocker],
                        )
                        final_result = self._finalize_action_execution(result, event_type="screen_awareness.playwright_action_execution_blocked")
                        return final_result

                    locator, locator_blocker = _locator_for_execution(page, target_candidate)
                    if locator_blocker:
                        result = _execution_result(
                            request,
                            plan_model,
                            status="blocked",
                            trust_request_id=action_request.request_id,
                            approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                            trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                            before_observation_id=before.observation_id,
                            error_code=locator_blocker,
                            user_message="The grounded browser target was ambiguous or unavailable at execution time.",
                            limitations=["locator_blocked", locator_blocker],
                        )
                        final_result = self._finalize_action_execution(result, event_type="screen_awareness.playwright_action_execution_blocked")
                        return final_result

                    if plan_model.action_kind == "click":
                        locator.click(timeout=int(self.config.observation_timeout_seconds or 8000))
                    elif plan_model.action_kind == "focus":
                        locator.focus(timeout=int(self.config.observation_timeout_seconds or 8000))
                    else:
                        raise RuntimeError(f"Unsupported action kind reached execution: {plan_model.action_kind}")
                    action_completed = True
                    self._publish(
                        "screen_awareness.playwright_action_command_returned",
                        "Playwright browser action command returned.",
                        _execution_event_payload(request, plan_model, status="action_command_returned", target=target_candidate),
                    )
                    self._publish(
                        "screen_awareness.playwright_action_execution_attempted",
                        "Playwright browser action command was issued.",
                        _execution_event_payload(request, plan_model, status="attempted", target=target_candidate),
                    )
                    trust_service.mark_action_executed(
                        action_request=action_request,
                        grant=trust_decision.grant,
                        summary=f"Attempted Playwright {plan_model.action_kind} on {target_candidate.get('name') or target_candidate.get('role')}.",
                        details={
                            "plan_id": plan_model.plan_id,
                            "preview_id": plan_model.preview_id,
                            "action_kind": plan_model.action_kind,
                            "claim_ceiling": _ACTION_EXECUTION_CLAIM_CEILING,
                        },
                    )
                    _wait_for_semantic_stabilization(page)
                    self._publish(
                        "screen_awareness.playwright_action_after_observation_started",
                        "Playwright browser action after-observation started.",
                        _execution_event_payload(request, plan_model, status="after_observation_started", target=target_candidate),
                    )
                    after = _live_observation_from_page(
                        page,
                        adapter_id=self.adapter_id,
                        session_id=f"playwright-action-after-{uuid4().hex[:10]}",
                    )
                    if _after_observation_unusable(before, after):
                        result = _execution_result(
                            request,
                            plan_model,
                            status="completed_unverified",
                            action_attempted=True,
                            action_completed=action_completed,
                            verification_attempted=False,
                            verification_status="unavailable",
                            before_observation_id=before.observation_id,
                            after_observation_id=after.observation_id,
                            trust_request_id=action_request.request_id,
                            approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                            trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                            error_code="after_observation_failed",
                            bounded_error_message="After-action semantic observation was empty or unusable.",
                            user_message="The browser action command returned, but the after-observation was not usable enough to verify the expected change.",
                            limitations=[
                                "after_observation_failed",
                                "completed_unverified",
                                "isolated_temporary_browser_context",
                                "not_visible_screen_verification",
                                "not_truth_verified",
                            ],
                        )
                        final_result = self._finalize_action_execution(
                            result,
                            event_type="screen_awareness.playwright_action_verification_completed",
                            severity=EventSeverity.WARNING,
                        )
                        return final_result
                    self._publish(
                        "screen_awareness.playwright_action_after_observation_captured",
                        "Playwright browser action after-observation captured.",
                        _execution_event_payload(request, plan_model, status="after_observation_captured", target=target_candidate),
                    )
                    comparison = _best_action_comparison(self, before, after, plan_model)
                    status, verification_status, user_message = _execution_status_from_comparison(plan_model.action_kind, comparison)
                    result = _execution_result(
                        request,
                        plan_model,
                        status=status,
                        action_attempted=True,
                        action_completed=action_completed,
                        verification_attempted=True,
                        verification_status=verification_status,
                        before_observation_id=before.observation_id,
                        after_observation_id=after.observation_id,
                        comparison_result_id=comparison.result_id if comparison is not None else "",
                        trust_request_id=action_request.request_id,
                        approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                        trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                        user_message=user_message,
                        limitations=list(
                            dict.fromkeys(
                                ["isolated_temporary_browser_context", "no_user_profile", "not_visible_screen_verification", "not_truth_verified"]
                                + (comparison.limitations if comparison is not None else ["comparison_unavailable"])
                            )
                        ),
                    )
                    final_result = self._finalize_action_execution(result, event_type="screen_awareness.playwright_action_verification_completed")
                    return final_result
                finally:
                    cleanup_status, cleanup_error = self._cleanup_isolated_browser_resources(
                        context,
                        browser,
                        claim_ceiling=_ACTION_EXECUTION_CLAIM_CEILING,
                        completed_message="Playwright isolated browser action cleanup completed.",
                        completed_limitations=["no_user_profile", "no_cookies_persisted"],
                        failed_limitations=["cleanup_failed", "no_user_profile", "no_cookies_persisted"],
                    )
                    context = None
                    browser = None
        except Exception as exc:
            if action_completed:
                result = _execution_result(
                    request,
                    plan_model,
                    status="completed_unverified",
                    action_attempted=True,
                    action_completed=True,
                    verification_attempted=False,
                    before_observation_id=before.observation_id if before is not None else "",
                    trust_request_id=action_request.request_id,
                    approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                    trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                    error_code="after_observation_failed",
                    bounded_error_message=_bounded_text(f"{type(exc).__name__}: {exc}"),
                    user_message="The browser action command returned, but Stormhelm could not capture a usable after-observation.",
                    limitations=["after_observation_failed", "completed_unverified", "isolated_temporary_browser_context"],
                )
                final_result = self._finalize_action_execution(
                    result,
                    event_type="screen_awareness.playwright_action_verification_completed",
                    severity=EventSeverity.WARNING,
                )
                return final_result
            result = _execution_result(
                request,
                plan_model,
                status="failed",
                action_attempted=action_completed,
                action_completed=action_completed,
                verification_attempted=before is not None and after is not None,
                before_observation_id=before.observation_id if before is not None else "",
                after_observation_id=after.observation_id if after is not None else "",
                comparison_result_id=comparison.result_id if comparison is not None else "",
                trust_request_id=action_request.request_id,
                approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                error_code=_live_error_code(exc),
                bounded_error_message=_bounded_text(f"{type(exc).__name__}: {exc}"),
                user_message="The browser action failed before Stormhelm could produce a bounded verified result.",
                limitations=["action_execution_failed", "isolated_temporary_browser_context"],
            )
            final_result = self._finalize_action_execution(result, event_type="screen_awareness.playwright_action_execution_failed", severity=EventSeverity.WARNING)
            return final_result
        finally:
            if cleanup_status == "not_started" and (context is not None or browser is not None):
                cleanup_status, cleanup_error = self._cleanup_isolated_browser_resources(
                    context,
                    browser,
                    claim_ceiling=_ACTION_EXECUTION_CLAIM_CEILING,
                    completed_message="Playwright isolated browser action cleanup completed.",
                    completed_limitations=["no_user_profile", "no_cookies_persisted"],
                    failed_limitations=["cleanup_failed", "no_user_profile", "no_cookies_persisted"],
                )
            if final_result is not None:
                final_result.cleanup_status = cleanup_status
                if cleanup_error is not None:
                    final_result.limitations = list(dict.fromkeys(list(final_result.limitations) + ["cleanup_failed"]))
                    final_result.error_code = final_result.error_code or "cleanup_failed"
                self._last_action_execution_summary = _action_execution_summary(final_result)

    def _execution_gate_result(
        self,
        request: BrowserSemanticActionExecutionRequest,
        plan: BrowserSemanticActionPlan,
    ) -> BrowserSemanticActionExecutionResult | None:
        if plan.action_kind not in {"click", "focus"}:
            return _execution_result(
                request,
                plan,
                status="unsupported",
                error_code="unsupported_action_kind",
                user_message="That browser action is not implemented in this phase.",
                limitations=["unsupported_action_kind", "no_action_attempted"],
            )
        freshness_blocker = _plan_freshness_blocker(plan)
        if freshness_blocker:
            return _execution_result(
                request,
                plan,
                status="blocked",
                error_code=freshness_blocker,
                user_message="That browser action plan is stale. Refresh the semantic observation before executing.",
                limitations=["stale_plan", freshness_blocker, "no_action_attempted"],
            )
        target_binding_blocker = _plan_target_binding_blocker(plan)
        if target_binding_blocker:
            return _execution_result(
                request,
                plan,
                status="blocked",
                error_code=target_binding_blocker,
                user_message="That approval cannot be used because the planned browser target changed.",
                limitations=["approval_binding_mismatch", target_binding_blocker, "no_action_attempted"],
            )
        if plan.result_state in {"blocked", "ambiguous", "unsupported"}:
            error_code = next(
                (
                    item
                    for item in plan.limitations
                    if item
                    not in {
                        "preview_only",
                        "action_execution_deferred",
                        "no_actions",
                        "plan_only",
                        "operator_approval_required",
                        "no_action_execution",
                    }
                ),
                plan.result_state,
            )
            if error_code == "sensitive_or_restricted_context":
                error_code = "restricted_context_deferred"
            return _execution_result(
                request,
                plan,
                status="blocked" if plan.result_state == "blocked" else plan.result_state,
                error_code=error_code,
                user_message=plan.user_message or "That browser action plan is not executable.",
                limitations=list(plan.limitations) + ["no_action_attempted"],
            )
        gate_reason = _action_gate_blocker(self.config, plan.action_kind)
        if gate_reason:
            return _execution_result(
                request,
                plan,
                status="blocked",
                error_code=gate_reason,
                user_message="That browser action is not enabled by the current Playwright action gates.",
                limitations=["action_gate_blocked", gate_reason, "no_action_attempted"],
            )
        return None

    def _finalize_action_execution(
        self,
        result: BrowserSemanticActionExecutionResult,
        *,
        event_type: str = "screen_awareness.playwright_action_execution_requested",
        severity: EventSeverity = EventSeverity.INFO,
    ) -> BrowserSemanticActionExecutionResult:
        if not result.completed_at and result.status not in {"approval_required", "approved"}:
            result.completed_at = utc_now_iso()
        self._last_action_execution_summary = _action_execution_summary(result)
        if event_type:
            self._publish(
                event_type,
                _action_execution_event_message(result),
                _action_execution_event_payload(result),
                severity=severity,
            )
        return result

    def verify_after_action(
        self,
        before: BrowserSemanticObservation,
        after: BrowserSemanticObservation,
        expected_change: str,
    ) -> dict[str, Any]:
        del before, after, expected_change
        return {
            "adapter_id": self.adapter_id,
            "status": "unsupported",
            "verification_supported": False,
            "reason": "Playwright browser action verification is intentionally deferred.",
            "claim_ceiling": _CLAIM_CEILING,
        }

    def _unavailable_mock_observation(
        self,
        context: dict[str, Any] | None,
        readiness: PlaywrightAdapterReadiness,
        *,
        publish_event: bool = True,
    ) -> BrowserSemanticObservation:
        context = dict(context or {})
        limitations = list(
            dict.fromkeys(
                [
                    *readiness.blocking_reasons,
                    "mock_observation_unavailable",
                    "no_live_browser_connection",
                    "no_actions",
                    "not_visible_screen_verification",
                    "not_truth_claimed",
                ]
            )
        )
        observation = BrowserSemanticObservation(
            provider="playwright_mock_unavailable",
            adapter_id=self.adapter_id,
            session_id=str(context.get("session_id") or ""),
            page_url=_safe_display_url(context.get("page_url") or context.get("url") or ""),
            page_title=_bounded_text(context.get("page_title") or context.get("title") or ""),
            browser_context_kind="unavailable",
            observed_at=utc_now_iso(),
            controls=[],
            limitations=limitations,
            confidence=0.0,
        )
        self._last_observation_summary = _observation_summary(observation)
        self._last_observation_summary["status"] = readiness.status
        if publish_event:
            self._publish(
                "screen_awareness.playwright_mock_observation_unavailable",
                "Playwright mock browser semantic observation is unavailable.",
                {
                    "status": readiness.status,
                    "provider": observation.provider,
                    "browser_context_kind": observation.browser_context_kind,
                    "control_count": 0,
                    "claim_ceiling": observation.claim_ceiling,
                    "blocking_reasons": list(readiness.blocking_reasons),
                    "limitations": limitations,
                },
                severity=EventSeverity.WARNING,
            )
        return observation

    def _unavailable_live_observation(
        self,
        url: str,
        code: str,
        *,
        readiness: PlaywrightAdapterReadiness,
        message: str = "",
        publish_event: bool = True,
    ) -> BrowserSemanticObservation:
        limitations = list(
            dict.fromkeys(
                [
                    code,
                    *readiness.blocking_reasons,
                    "live_observation_unavailable",
                    "no_actions",
                    "not_visible_screen_verification",
                    "not_truth_claimed",
                ]
            )
        )
        observation = BrowserSemanticObservation(
            provider="playwright_live_unavailable",
            adapter_id=self.adapter_id,
            session_id="",
            page_url=_safe_display_url(url),
            page_title="",
            browser_context_kind="unavailable",
            observed_at=utc_now_iso(),
            controls=[],
            limitations=limitations,
            confidence=0.0,
        )
        self._last_observation_summary = _observation_summary(observation)
        self._last_observation_summary["status"] = code
        if publish_event:
            self._publish(
                "screen_awareness.playwright_live_observation_failed",
                "Playwright isolated browser semantic observation failed.",
                {
                    "status": code,
                    "page_url": observation.page_url,
                    "control_count": 0,
                    "claim_ceiling": observation.claim_ceiling,
                    "bounded_error_message": _bounded_text(message),
                    "limitations": limitations,
                },
                severity=EventSeverity.WARNING,
            )
        return observation

    def _safe_dependency_installed(self) -> tuple[bool, str]:
        try:
            return self._dependency_installed(), ""
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def _dependency_installed(self) -> bool:
        if self.dependency_checker is not None:
            return bool(self.dependency_checker())
        return find_spec("playwright") is not None

    def _safe_browser_engines_available(self) -> tuple[bool, bool, str]:
        if self.browser_engine_checker is None:
            return False, False, ""
        try:
            return bool(self.browser_engine_checker()), True, ""
        except Exception as exc:
            return False, True, f"{type(exc).__name__}: {exc}"

    def _publish_readiness(self, readiness: PlaywrightAdapterReadiness, *, emit_event: bool) -> None:
        if not emit_event:
            return
        self._publish(
            "screen_awareness.playwright_readiness_checked",
            "Playwright browser adapter readiness checked.",
            {
                "status": readiness.status,
                "enabled": readiness.enabled,
                "available": readiness.available,
                "dependency_installed": readiness.dependency_installed,
                "browser_engines_available": readiness.browser_engines_available,
                "browser_engines_checkable": readiness.browser_engines_checkable,
                "mock_ready": readiness.mock_ready,
                "runtime_ready": readiness.runtime_ready,
                "live_runtime_allowed": readiness.live_runtime_allowed,
                "actions_enabled": False,
                "claim_ceiling": readiness.claim_ceiling,
                "blocking_reasons": list(readiness.blocking_reasons),
                "warnings": list(readiness.warnings),
            },
            severity=EventSeverity.INFO if readiness.status in {"mock_ready", "runtime_ready", "disabled"} else EventSeverity.WARNING,
        )

    def _publish_grounding_event(
        self,
        target_phrase: str,
        candidates: Sequence[BrowserGroundingCandidate],
        *,
        status: str,
        observation: BrowserSemanticObservation,
    ) -> None:
        live = observation.provider == "playwright_live_semantic"
        if status == "ambiguous":
            event_type = "screen_awareness.playwright_live_grounding_completed" if live else "screen_awareness.playwright_grounding_ambiguous"
            message = "Playwright live grounding is ambiguous." if live else "Playwright mock grounding is ambiguous."
            severity = EventSeverity.WARNING
        elif status == "no_match":
            event_type = "screen_awareness.playwright_live_grounding_completed" if live else "screen_awareness.playwright_grounding_no_match"
            message = "Playwright live grounding found no matching target." if live else "Playwright mock grounding found no matching target."
            severity = EventSeverity.INFO
        else:
            event_type = "screen_awareness.playwright_live_grounding_completed" if live else "screen_awareness.playwright_grounding_completed"
            message = "Playwright live grounding completed." if live else "Playwright mock grounding completed."
            severity = EventSeverity.INFO
        payload = {
            "target_phrase": _bounded_text(target_phrase),
            "status": status,
            "candidate_count": len(candidates),
            "roles": sorted({candidate.role for candidate in candidates if candidate.role})[:8],
            "limitations": list(observation.limitations)[:8],
            "ambiguity_reason": candidates[0].ambiguity_reason if candidates else "",
            "claim_ceiling": _CLAIM_CEILING,
            "provider": observation.provider,
        }
        if live:
            payload["top_candidates"] = [_candidate_summary(candidate) for candidate in candidates[:_GROUNDING_CANDIDATE_LIMIT]]
        self._publish(event_type, message, payload, severity=severity)

    def _publish_comparison_completed(
        self,
        result: BrowserSemanticVerificationResult,
        request: BrowserSemanticVerificationRequest,
    ) -> None:
        payload = {
            "before_observation_id": result.before_observation_id,
            "after_observation_id": result.after_observation_id,
            "status": result.status,
            "change_count": len(result.changes),
            "expected_change_kind": request.expected_change_kind,
            "target_phrase": _bounded_text(request.target_phrase),
            "confidence": round(float(result.confidence or 0.0), 3),
            "claim_ceiling": result.claim_ceiling,
            "limitations": list(result.limitations)[:8],
            "summary": _bounded_text(result.summary),
        }
        self._publish(
            "screen_awareness.playwright_semantic_comparison_completed",
            "Playwright semantic browser comparison completed.",
            payload,
            severity=EventSeverity.INFO if result.status in {"supported", "partial"} else EventSeverity.WARNING,
        )
        if request.expected_change_kind or request.target_phrase:
            event_type = {
                "supported": "screen_awareness.playwright_semantic_verification_supported",
                "unsupported": "screen_awareness.playwright_semantic_verification_unsupported",
                "ambiguous": "screen_awareness.playwright_semantic_verification_ambiguous",
                "unverifiable": "screen_awareness.playwright_semantic_verification_unverifiable",
                "insufficient_basis": "screen_awareness.playwright_semantic_verification_unverifiable",
                "stale_basis": "screen_awareness.playwright_semantic_verification_unverifiable",
                "partial": "screen_awareness.playwright_semantic_verification_supported",
            }.get(result.status, "screen_awareness.playwright_semantic_verification_unverifiable")
            self._publish(
                event_type,
                "Playwright semantic browser expected outcome evaluated.",
                payload,
                severity=EventSeverity.INFO if result.status in {"supported", "partial"} else EventSeverity.WARNING,
            )

    def _publish_action_preview(self, preview: BrowserSemanticActionPreview) -> None:
        if preview.preview_state == "blocked":
            event_type = "screen_awareness.playwright_action_preview_blocked"
            message = "Playwright browser action preview blocked."
            severity = EventSeverity.WARNING
        elif preview.preview_state == "ambiguous":
            event_type = "screen_awareness.playwright_action_preview_ambiguous"
            message = "Playwright browser action preview is ambiguous."
            severity = EventSeverity.WARNING
        else:
            event_type = "screen_awareness.playwright_action_preview_created"
            message = "Playwright browser action preview created."
            severity = EventSeverity.INFO if preview.preview_state == "preview_only" else EventSeverity.WARNING
        self._publish(
            event_type,
            message,
            {
                "preview_id": preview.preview_id,
                "action_kind": preview.action_kind,
                "preview_state": preview.preview_state,
                "target_role": preview.target_role,
                "target_name": _bounded_text(preview.target_name, 80),
                "confidence": round(float(preview.confidence or 0.0), 3),
                "risk_level": preview.risk_level,
                "approval_required": preview.approval_required,
                "executable_now": False,
                "claim_ceiling": _ACTION_PREVIEW_CLAIM_CEILING,
                "limitations": list(preview.limitations)[:8],
            },
            severity=severity,
        )

    def _cleanup_isolated_browser_resources(
        self,
        context: Any | None,
        browser: Any | None,
        *,
        claim_ceiling: str,
        completed_message: str,
        completed_limitations: Sequence[str],
        failed_limitations: Sequence[str],
    ) -> tuple[str, Exception | None]:
        cleanup_error: Exception | None = None
        cleanup_started = context is not None or browser is not None
        if context is not None:
            try:
                clear_cookies = getattr(context, "clear_cookies", None)
                if callable(clear_cookies):
                    clear_cookies()
            except Exception as exc:
                cleanup_error = exc
            try:
                context.close()
            except Exception as exc:
                cleanup_error = cleanup_error or exc
        if browser is not None:
            try:
                browser.close()
            except Exception as exc:
                cleanup_error = cleanup_error or exc
        if cleanup_error is not None:
            self._publish_cleanup_failed(
                cleanup_error,
                claim_ceiling=claim_ceiling,
                limitations=failed_limitations,
            )
            return "cleanup_failed", cleanup_error
        if cleanup_started:
            self._publish(
                "screen_awareness.playwright_cleanup_completed",
                completed_message,
                {
                    "cleanup_status": "closed",
                    "claim_ceiling": claim_ceiling,
                    "limitations": list(completed_limitations),
                },
            )
            return "closed", None
        return "not_started", None

    def _publish_cleanup_failed(
        self,
        exc: Exception,
        *,
        claim_ceiling: str = _CLAIM_CEILING,
        limitations: Sequence[str] = ("cleanup_failed", "no_actions"),
    ) -> None:
        self._publish(
            "screen_awareness.playwright_cleanup_failed",
            "Playwright isolated browser semantic observation cleanup failed.",
            {
                "cleanup_status": "failed",
                "bounded_error_message": _bounded_text(f"{type(exc).__name__}: {exc}"),
                "claim_ceiling": claim_ceiling,
                "limitations": list(limitations),
            },
            severity=EventSeverity.WARNING,
        )

    def _publish(
        self,
        event_type: str,
        message: str,
        payload: dict[str, Any],
        *,
        severity: EventSeverity = EventSeverity.INFO,
    ) -> None:
        if self.events is None or not bool(getattr(self.config, "debug_events_enabled", True)):
            return
        self.events.publish(
            event_family=EventFamily.SCREEN_AWARENESS,
            event_type=event_type,
            severity=severity,
            subsystem="screen_awareness",
            visibility_scope=EventVisibilityScope.DECK_CONTEXT,
            retention_class=EventRetentionClass.BOUNDED_RECENT,
            provenance={"channel": "screen_awareness", "kind": "browser_semantic_mock"},
            message=message,
            payload=dict(payload),
        )


def _unsafe_flag_warnings(config: PlaywrightBrowserAdapterConfig) -> list[str]:
    warnings: list[str] = []
    if config.allow_browser_launch:
        warnings.append("browser_launch_allowed")
    if config.allow_connect_existing:
        warnings.append("connect_existing_allowed")
    if config.allow_actions:
        warnings.append("actions_requested_requires_specific_click_focus_gates")
    if getattr(config, "allow_click", False):
        warnings.append("click_requested_requires_trust_gate")
    if getattr(config, "allow_focus", False):
        warnings.append("focus_requested_requires_trust_gate")
    if getattr(config, "allow_dev_actions", False):
        warnings.append("dev_actions_allowed")
    if getattr(config, "allow_type_text", False):
        warnings.append("type_text_requested_but_unsupported")
    if getattr(config, "allow_scroll", False):
        warnings.append("scroll_requested_but_unsupported")
    if config.allow_form_fill:
        warnings.append("form_fill_requested_but_unsupported")
    if getattr(config, "allow_form_submit", False):
        warnings.append("form_submit_requested_but_unsupported")
    if config.allow_login:
        warnings.append("login_requested_but_unsupported")
    if config.allow_cookies:
        warnings.append("cookies_requested_but_unsupported")
    if getattr(config, "allow_user_profile", False):
        warnings.append("user_profile_requested_but_unsupported")
    if config.allow_screenshots:
        warnings.append("screenshots_requested_but_not_screen_truth")
    if config.allow_dev_adapter:
        warnings.append("dev_adapter_allowed")
    return warnings


def _live_launch_blocker(config: PlaywrightBrowserAdapterConfig, readiness: PlaywrightAdapterReadiness) -> str:
    if not config.enabled:
        return "playwright_adapter_disabled"
    if not config.allow_dev_adapter:
        return "playwright_dev_adapter_gate_required"
    if not config.allow_browser_launch:
        return "playwright_browser_launch_not_allowed"
    blockers = _unsupported_flag_blockers(config)
    if blockers:
        return blockers[0]
    if readiness.status == "dependency_missing" or not readiness.dependency_installed:
        return "dependency_missing"
    if readiness.status == "browsers_missing":
        return "browsers_missing"
    if readiness.status == "failed":
        return readiness.blocking_reasons[0] if readiness.blocking_reasons else "playwright_readiness_failed"
    if not readiness.runtime_ready:
        return readiness.blocking_reasons[0] if readiness.blocking_reasons else "playwright_runtime_unavailable"
    return ""


def _live_url_blocker(url: str, *, fixture_mode: bool) -> str:
    text = str(url or "").strip()
    if not text:
        return "unsupported_url"
    try:
        parsed = urlsplit(text)
    except ValueError:
        return "unsupported_url"
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return "unsupported_url"
    host = parsed.hostname or ""
    if not host:
        return "unsupported_url"
    if fixture_mode:
        return ""
    lowered = host.lower()
    if lowered in {"localhost", "localhost."}:
        return "unsupported_url"
    try:
        address = ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        return ""
    if address.is_loopback or address.is_private or address.is_link_local or address.is_multicast:
        return "unsupported_url"
    return ""


def _safe_context_options(context_options: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context_options, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in context_options.items():
        key_text = str(key or "").strip()
        if key_text in {"storage_state", "user_data_dir", "record_video_dir", "record_har_path"}:
            continue
        if key_text:
            safe[key_text] = value
    return safe


def _load_sync_playwright_factory() -> SyncPlaywrightFactory:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright dependency is not available.") from exc
    return sync_playwright


def _live_error_code(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if "timeout" in text:
        return "navigation_timeout"
    if "executable doesn't exist" in text or "browser" in text and "install" in text:
        return "browsers_missing"
    if "goto" in text or "net::" in text or "navigation" in text:
        return "navigation_failed"
    return "snapshot_failed"


def _live_observation_from_page(
    page: Any,
    *,
    adapter_id: str,
    session_id: str,
) -> BrowserSemanticObservation:
    controls_payload = _evaluate_locator(
        page,
        "button, input, textarea, select, a, [role]",
        _CONTROL_EXTRACTION_SCRIPT,
    )
    forms_payload = _evaluate_locator(page, "form, [role='form'], [data-form], .form", _FORM_EXTRACTION_SCRIPT)
    dialogs_payload = _evaluate_locator(page, "dialog, [role='dialog'], [role='alert'], [aria-modal='true']", _DIALOG_EXTRACTION_SCRIPT)
    text_payload = _evaluate_locator(page, "h1, h2, h3, p, li, [role='heading']", _TEXT_REGION_EXTRACTION_SCRIPT)
    page_context = _evaluate_page_context(page)
    controls = [_control_from_live_payload(item) for item in controls_payload[:_LIST_LIMIT] if isinstance(item, dict)]
    page_title = _bounded_text(_call_text(page, "title"), limit=_TEXT_LIMIT)
    page_url = _safe_display_url(getattr(page, "url", ""))
    limitations = _live_observation_limitations(page_context, controls_payload=controls_payload, forms_payload=forms_payload)
    return BrowserSemanticObservation(
        provider="playwright_live_semantic",
        adapter_id=adapter_id,
        session_id=session_id,
        page_url=page_url,
        page_title=page_title,
        browser_context_kind="isolated_playwright_context",
        observed_at=utc_now_iso(),
        controls=controls,
        text_regions=[_bounded_mapping(item, id_keys=("text", "role", "name")) for item in text_payload[:_LIST_LIMIT] if isinstance(item, dict)],
        forms=[_bounded_mapping(item, id_keys=("form_id", "name", "field_count", "summary")) for item in forms_payload[:_LIST_LIMIT] if isinstance(item, dict)],
        dialogs=[_bounded_mapping(item, id_keys=("dialog_id", "role", "text", "name")) for item in dialogs_payload[:_LIST_LIMIT] if isinstance(item, dict)],
        alerts=[
            _bounded_mapping(item, id_keys=("alert_id", "role", "text", "name"))
            for item in dialogs_payload[:_LIST_LIMIT]
            if isinstance(item, dict) and str(item.get("role") or "").lower() == "alert"
        ],
        limitations=limitations,
        confidence=0.74 if controls else 0.42,
    )


def _after_observation_unusable(before: BrowserSemanticObservation, after: BrowserSemanticObservation) -> bool:
    before_had_semantics = bool(before.controls or before.dialogs or before.alerts or before.text_regions or before.forms)
    after_has_semantics = bool(after.controls or after.dialogs or after.alerts or after.text_regions or after.forms)
    if before_had_semantics and not after_has_semantics and not after.page_title:
        return True
    return False


def _wait_for_semantic_stabilization(page: Any) -> None:
    try:
        wait_for_timeout = getattr(page, "wait_for_timeout")
    except Exception:
        return
    if not callable(wait_for_timeout):
        return
    try:
        wait_for_timeout(150)
    except Exception:
        return


def _evaluate_locator(page: Any, selector: str, script: str) -> list[dict[str, Any]]:
    try:
        value = page.locator(selector).evaluate_all(script)
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _evaluate_page_context(page: Any) -> dict[str, Any]:
    try:
        value = page.evaluate(_PAGE_CONTEXT_EXTRACTION_SCRIPT)
    except Exception:
        return {}
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _live_observation_limitations(
    page_context: dict[str, Any],
    *,
    controls_payload: Sequence[dict[str, Any]],
    forms_payload: Sequence[dict[str, Any]],
) -> list[str]:
    limitations = list(_LIVE_LIMITATIONS)
    partial = False
    control_count = _safe_int(page_context.get("control_count"), default=len(controls_payload))
    if control_count > _LIST_LIMIT or len(controls_payload) > _LIST_LIMIT:
        limitations.append("large_control_list_truncated")
        partial = True
    if len(forms_payload) > _LIST_LIMIT:
        limitations.append("large_form_list_truncated")
        partial = True
    iframe_count = _safe_int(page_context.get("iframe_count"), default=0)
    if iframe_count > 0:
        limitations.append("iframe_context_limited")
        partial = True
    cross_origin_count = _safe_int(page_context.get("cross_origin_iframe_count"), default=0)
    if cross_origin_count > 0:
        limitations.append("cross_origin_iframe_not_observed")
        partial = True
    shadow_count = _safe_int(page_context.get("shadow_host_count"), default=0)
    if shadow_count > 0:
        limitations.append("shadow_dom_context_limited")
        partial = True
    ready_state = str(page_context.get("ready_state") or "").strip().lower()
    if ready_state and ready_state != "complete":
        limitations.append("page_load_may_be_incomplete")
    if partial:
        limitations.append("partial_semantic_observation")
    return list(dict.fromkeys(limitations))


def _call_text(obj: Any, method_name: str) -> str:
    try:
        value = getattr(obj, method_name)()
    except Exception:
        return ""
    return str(value or "")


def _control_from_live_payload(raw: dict[str, Any]) -> BrowserSemanticControl:
    input_type = str(raw.get("input_type") or raw.get("type") or "").strip().lower()
    sensitive = _control_payload_is_sensitive(raw)
    value_summary = _bounded_text(raw.get("value_summary") or "")
    if sensitive:
        value_summary = "[redacted sensitive field]"
    elif value_summary and value_summary not in {"checked", "unchecked", "selected value present"}:
        value_summary = "[redacted value]"
    return BrowserSemanticControl(
        control_id=_bounded_text(raw.get("control_id") or raw.get("id") or f"live-control-{uuid4().hex[:6]}", 80),
        role=_bounded_text(raw.get("role") or ""),
        name=_bounded_text(raw.get("name") or ""),
        label=_bounded_text(raw.get("label") or ""),
        text="" if sensitive else _bounded_text(raw.get("text") or ""),
        selector_hint=_bounded_text(raw.get("selector_hint") or "", 120),
        bounding_hint=dict(raw.get("bounding_hint") or {}) if isinstance(raw.get("bounding_hint"), dict) else {},
        enabled=_optional_bool(raw.get("enabled")),
        visible=_optional_bool(raw.get("visible")),
        checked=_optional_bool(raw.get("checked")),
        expanded=_optional_bool(raw.get("expanded")),
        required=_optional_bool(raw.get("required")),
        readonly=_optional_bool(raw.get("readonly")),
        value_summary=value_summary,
        risk_hint="sensitive_input" if sensitive else _bounded_text(raw.get("risk_hint") or ""),
        confidence=float(raw.get("confidence") or 0.76),
    )


def _unsupported_flag_blockers(config: PlaywrightBrowserAdapterConfig) -> list[str]:
    blockers: list[str] = []
    if getattr(config, "allow_type_text", False):
        blockers.append("type_text_not_supported")
    if getattr(config, "allow_scroll", False):
        blockers.append("scroll_not_supported")
    if config.allow_form_fill:
        blockers.append("form_fill_not_supported")
    if getattr(config, "allow_form_submit", False):
        blockers.append("form_submit_not_supported")
    if config.allow_login:
        blockers.append("login_not_supported")
    if config.allow_cookies:
        blockers.append("cookies_not_supported")
    if getattr(config, "allow_user_profile", False):
        blockers.append("user_profile_not_supported")
    if config.allow_screenshots:
        blockers.append("screenshots_not_supported")
    return blockers


def _control_from_mapping(raw: dict[str, Any]) -> BrowserSemanticControl:
    sensitive = _control_payload_is_sensitive(raw)
    value_summary = _bounded_text(raw.get("value_summary") or "")
    if sensitive:
        value_summary = "[redacted sensitive field]"
    elif value_summary and _looks_like_secret(value_summary):
        value_summary = "[redacted value]"
    return BrowserSemanticControl(
        control_id=_bounded_text(raw.get("control_id") or raw.get("id") or "mock-control"),
        role=_bounded_text(raw.get("role") or ""),
        name=_bounded_text(raw.get("name") or ""),
        label=_bounded_text(raw.get("label") or ""),
        text=_bounded_text(raw.get("text") or ""),
        selector_hint=_bounded_text(raw.get("selector_hint") or ""),
        bounding_hint=dict(raw.get("bounding_hint") or raw.get("bounds") or {}) if isinstance(raw.get("bounding_hint") or raw.get("bounds"), dict) else {},
        enabled=_optional_bool(raw.get("enabled")),
        visible=_optional_bool(raw.get("visible")),
        checked=_optional_bool(raw.get("checked")),
        expanded=_optional_bool(raw.get("expanded")),
        required=_optional_bool(raw.get("required")),
        readonly=_optional_bool(raw.get("readonly")),
        value_summary=value_summary,
        risk_hint="sensitive_input" if sensitive else _bounded_text(raw.get("risk_hint") or ""),
        confidence=float(raw.get("confidence") or 0.72),
    )


def _control_payload_is_sensitive(raw: dict[str, Any]) -> bool:
    input_type = str(raw.get("input_type") or raw.get("type") or "").strip().lower()
    haystack = " ".join(
        str(raw.get(key) or "")
        for key in ("label", "name", "text", "selector_hint", "risk_hint")
    ).lower()
    return input_type in {"password", "hidden"} or _looks_like_secret(haystack)


def _looks_like_secret(value: str) -> bool:
    lowered = str(value or "").lower()
    return any(term in lowered for term in ("password", "secret", "token", "api key", "apikey", "passcode", "credential"))


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _bounded_mapping(raw: dict[str, Any], *, id_keys: Iterable[str]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key in id_keys:
        value = raw.get(key)
        if isinstance(value, (int, float, bool)):
            bounded[key] = value
        elif value is not None:
            bounded[key] = _bounded_text(value)
    return bounded


def _bounded_text(value: Any, limit: int = _TEXT_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def _safe_display_url(value: Any, limit: int = _TEXT_LIMIT) -> str:
    text = _bounded_text(value, limit=limit)
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return text
    host = parsed.hostname or ""
    if not host:
        return ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = ""
    try:
        if parsed.port is not None:
            port = f":{parsed.port}"
    except ValueError:
        port = ""
    return _bounded_text(urlunsplit((parsed.scheme, f"{host}{port}", parsed.path or "", "", "")), limit=limit)


def _observation_summary(observation: BrowserSemanticObservation) -> dict[str, Any]:
    summary = {
        "provider": observation.provider,
        "page_url": _safe_display_url(observation.page_url),
        "page_title": observation.page_title,
        "control_count": len(observation.controls),
        "dialog_count": len(observation.dialogs),
        "alert_count": len(observation.alerts),
        "claim_ceiling": observation.claim_ceiling,
    }
    if observation.provider == "playwright_live_semantic":
        summary.update(
            {
                "browser_context_kind": observation.browser_context_kind,
                "form_count": len(observation.forms),
                "text_region_count": len(observation.text_regions),
                "link_count": sum(1 for control in observation.controls if control.role == "link"),
                "limitations": list(observation.limitations),
            }
        )
    return summary


def _grounding_summary(
    target_phrase: str,
    candidates: Sequence[BrowserGroundingCandidate],
    *,
    status: str,
) -> dict[str, Any]:
    return {
        "target_phrase": _bounded_text(target_phrase),
        "status": status,
        "candidate_count": len(candidates),
        "ambiguous": len(candidates) > 1,
        "roles": sorted({candidate.role for candidate in candidates if candidate.role})[:8],
        "source_provider": candidates[0].source_provider if candidates else "",
        "source_observation_id": candidates[0].source_observation_id if candidates else "",
        "top_candidates": [_candidate_summary(candidate) for candidate in candidates[:_GROUNDING_CANDIDATE_LIMIT]],
        "claim_ceiling": _CLAIM_CEILING,
    }


def _semantic_elements(observation: BrowserSemanticObservation) -> list[dict[str, Any]]:
    elements = []
    for index, control in enumerate(observation.controls):
        if control.visible is False:
            continue
        elements.append(
            {
                "control_id": control.control_id,
                "role": _canonical_role(control.role),
                "name": control.name,
                "label": control.label,
                "text": control.text,
                "selector_hint": control.selector_hint,
                "enabled": control.enabled,
                "visible": control.visible,
                "checked": control.checked,
                "expanded": control.expanded,
                "required": control.required,
                "readonly": control.readonly,
                "value_summary": control.value_summary,
                "risk_hint": control.risk_hint,
                "confidence": control.confidence,
                "index": index,
            }
        )
    for index, dialog in enumerate(observation.dialogs):
        role = _canonical_role(str(dialog.get("role") or "dialog"))
        text = str(dialog.get("text") or dialog.get("name") or "")
        elements.append(
            {
                "control_id": str(dialog.get("dialog_id") or f"dialog-{index + 1}"),
                "role": role,
                "name": str(dialog.get("name") or ""),
                "label": str(dialog.get("label") or ""),
                "text": text,
                "selector_hint": "",
                "enabled": True,
                "visible": True,
                "confidence": 0.66,
                "index": len(observation.controls) + index,
            }
        )
    return elements


def _target_analysis(target_phrase: str) -> dict[str, Any]:
    target = _normalize(target_phrase)
    target_role = _target_role(target)
    ordinal = _target_ordinal(target)
    states = _target_states(target)
    relation_phrase = ""
    if " near " in f" {target} ":
        relation_phrase = target.split(" near ", 1)[1].strip()
    stripped = _strip_role_words(target, target_role)
    stripped = _strip_state_words(stripped)
    stripped = _strip_ordinal_words(stripped)
    if relation_phrase:
        stripped = stripped.split(" near ", 1)[0].strip()
    return {
        "target": target,
        "target_role": target_role,
        "ordinal": ordinal,
        "states": states,
        "relation_phrase": relation_phrase,
        "stripped": stripped,
    }


def _rank_grounding_candidates(
    target_phrase: str,
    observation: BrowserSemanticObservation,
    elements: Sequence[dict[str, Any]],
    analysis: dict[str, Any],
) -> list[BrowserGroundingCandidate]:
    anchor_index = _relation_anchor_index(elements, str(analysis.get("relation_phrase") or ""))
    scored: list[tuple[float, BrowserGroundingCandidate]] = []
    matching_role_seen = 0
    stale = _observation_is_stale(observation)
    for element in elements:
        role = _canonical_role(element.get("role"))
        target_role = str(analysis.get("target_role") or "")
        if target_role and role != target_role:
            continue
        if target_role:
            matching_role_seen += 1
        score, reason, evidence, mismatch = _score_element(element, analysis, anchor_index=anchor_index)
        if score < 0.25:
            continue
        if stale:
            score = max(0.05, score - 0.14)
            mismatch.append("stale_observation")
        candidate = _candidate_from_element(
            target_phrase,
            element,
            observation,
            match_reason=reason,
            confidence=round(min(score, 0.99), 3),
            evidence_terms=evidence,
            mismatch_terms=mismatch,
        )
        scored.append((candidate.confidence, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    candidates = [candidate for _, candidate in scored]
    ordinal = int(analysis.get("ordinal") or 0)
    target_role = str(analysis.get("target_role") or "")
    if ordinal and target_role:
        role_candidates = [candidate for candidate in candidates if candidate.role == target_role]
        selected_index = len(role_candidates) - 1 if ordinal < 0 else ordinal - 1
        if 0 <= selected_index < len(role_candidates):
            selected = role_candidates[selected_index]
            selected.match_reason = "ordinal_match"
            selected.evidence_terms = list(dict.fromkeys(selected.evidence_terms + ["ordinal_match"]))
            selected.confidence = max(selected.confidence, 0.74)
            return [selected]
        return []
    if target_role and not str(analysis.get("stripped") or "") and not analysis.get("states") and matching_role_seen:
        return candidates[:_GROUNDING_CANDIDATE_LIMIT]
    return [candidate for candidate in candidates if candidate.confidence >= 0.5][:_GROUNDING_CANDIDATE_LIMIT]


def _closest_grounding_candidates(
    target_phrase: str,
    observation: BrowserSemanticObservation,
    elements: Sequence[dict[str, Any]],
    analysis: dict[str, Any],
) -> list[BrowserGroundingCandidate]:
    target_role = str(analysis.get("target_role") or "")
    if not target_role:
        return []
    for element in elements:
        if _canonical_role(element.get("role")) != target_role:
            continue
        return [
            _candidate_from_element(
                target_phrase,
                element,
                observation,
                match_reason="closest_match",
                confidence=0.44 if not _observation_is_stale(observation) else 0.3,
                evidence_terms=["role_match", "closest_available_same_role"],
                mismatch_terms=["exact_target_not_found"] + (["stale_observation"] if _observation_is_stale(observation) else []),
            )
        ]
    return []


def _score_element(element: dict[str, Any], analysis: dict[str, Any], *, anchor_index: int | None) -> tuple[float, str, list[str], list[str]]:
    target = str(analysis.get("target") or "")
    target_role = str(analysis.get("target_role") or "")
    stripped = str(analysis.get("stripped") or "")
    role = _canonical_role(element.get("role"))
    name = _normalize(element.get("name"))
    label = _normalize(element.get("label"))
    text = _normalize(element.get("text"))
    value_summary = _normalize(element.get("value_summary"))
    stripped_variants = _semantic_variants(stripped)
    target_variants = _semantic_variants(target)
    values = [value for value in (name, label, text, value_summary) if value]
    score = 0.0
    reason = ""
    evidence: list[str] = []
    mismatch: list[str] = []
    if target_role and role == target_role:
        score += 0.46
        reason = "role_match"
        evidence.append("role_match")
    for _term, field, expected, evidence_term in analysis.get("states") or []:
        actual = element.get(field)
        if actual is expected:
            score += 0.18
            evidence.append(evidence_term)
            reason = evidence_term if not reason else reason
        else:
            mismatch.append(f"{evidence_term}_missing")
            score -= 0.32
    if anchor_index is not None:
        index = int(element.get("index") or 0)
        distance = abs(index - anchor_index)
        if distance <= 2:
            score += max(0.09, 0.24 - (0.06 * distance))
            evidence.append("nearby_context_match")
            if not reason or reason == "role_match":
                reason = "nearby_context_match"
    if stripped:
        if name and any(variant == name or target_variant == name for variant in stripped_variants for target_variant in target_variants):
            score += 0.52 if not target_role else 0.48
            reason = "role_name_match" if target_role else "exact_name_match"
            evidence.append(reason)
        elif label and any(variant == label or target_variant == label for variant in stripped_variants for target_variant in target_variants):
            score += 0.44
            reason = "label_match"
            evidence.append("label_match")
        elif text and any(variant == text or target_variant == text for variant in stripped_variants for target_variant in target_variants):
            score += 0.52
            reason = "text_match"
            evidence.append("text_match")
        else:
            for value in values:
                if any(variant and (variant in value or value in variant) for variant in stripped_variants):
                    score += 0.52 if not target_role else 0.28
                    reason = "fuzzy_contains_match"
                    evidence.append("fuzzy_contains_match")
                    break
    elif target_role and role == target_role:
        score += 0.06
    if not evidence and values and target:
        for value in values:
            if value and any(variant and (variant in value or value in variant) for variant in target_variants):
                score += 0.24
                reason = "fuzzy_contains_match"
                evidence.append("fuzzy_contains_match")
                break
    return score, reason or "semantic_match", list(dict.fromkeys(evidence)), list(dict.fromkeys(mismatch))


def _candidate_from_element(
    target_phrase: str,
    element: dict[str, Any],
    observation: BrowserSemanticObservation,
    *,
    match_reason: str,
    confidence: float,
    evidence_terms: Sequence[str],
    mismatch_terms: Sequence[str],
) -> BrowserGroundingCandidate:
    return BrowserGroundingCandidate(
        target_phrase=target_phrase,
        control_id=str(element.get("control_id") or ""),
        role=_canonical_role(element.get("role")),
        name=_bounded_text(element.get("name") or ""),
        label=_bounded_text(element.get("label") or ""),
        text=_bounded_text(element.get("text") or ""),
        selector_hint=_bounded_text(element.get("selector_hint") or "", 120),
        match_reason=match_reason,
        confidence=confidence,
        action_supported=False,
        verification_supported=False,
        evidence_terms=list(evidence_terms),
        mismatch_terms=list(mismatch_terms),
        source_observation_id=observation.observation_id,
        source_provider=observation.provider,
        claim_ceiling=_CLAIM_CEILING,
    )


def _relation_anchor_index(elements: Sequence[dict[str, Any]], relation_phrase: str) -> int | None:
    if not relation_phrase:
        return None
    analysis = _target_analysis(relation_phrase)
    best: tuple[float, int] | None = None
    for element in elements:
        score, _reason, _evidence, _mismatch = _score_element(element, analysis, anchor_index=None)
        if best is None or score > best[0]:
            best = (score, int(element.get("index") or 0))
    if best is not None and best[0] >= 0.5:
        return best[1]
    return None


def _hidden_semantic_match_exists(observation: BrowserSemanticObservation, analysis: dict[str, Any]) -> bool:
    stripped = str(analysis.get("stripped") or "")
    target_role = str(analysis.get("target_role") or "")
    if not stripped:
        return False
    for control in observation.controls:
        if control.visible is not False:
            continue
        if target_role and _canonical_role(control.role) != target_role:
            continue
        values = [_normalize(control.name), _normalize(control.label), _normalize(control.text)]
        if any(value and (stripped == value or stripped in value or value in stripped) for value in values):
            return True
    return False


def _target_role(normalized_target: str) -> str:
    for role, aliases in _ROLE_ALIASES.items():
        for alias in aliases:
            if _normalize(alias) in normalized_target.split() or _normalize(alias) == normalized_target:
                return role
            if f" {_normalize(alias)} " in f" {normalized_target} ":
                return role
    return ""


def _canonical_role(value: Any) -> str:
    normalized = _normalize(value)
    return _ROLE_SYNONYMS.get(normalized, normalized)


def _target_ordinal(normalized_target: str) -> int:
    words = normalized_target.split()
    for word in words:
        if word in _ORDINALS:
            return _ORDINALS[word]
    return 0


def _target_states(normalized_target: str) -> list[tuple[str, str, bool, str]]:
    states: list[tuple[str, str, bool, str]] = []
    words = normalized_target.split()
    if "not disabled" in normalized_target:
        states.append(("not disabled", "enabled", True, "not_disabled_state_match"))
    if "not required" in normalized_target or "optional" in words:
        states.append(("not required", "required", False, "not_required_state_match"))
    if "not checked" in normalized_target:
        states.append(("not checked", "checked", False, "unchecked_state_match"))
    for term, (field, expected, evidence) in _STATE_TERMS.items():
        term_present = term in normalized_target if " " in term else term in words
        if term_present and not any(existing[1] == field and existing[2] != expected for existing in states):
            states.append((term, field, expected, evidence))
    return list(dict.fromkeys(states))


def _strip_role_words(normalized_target: str, role: str) -> str:
    aliases = {_normalize(role)}
    aliases.update(_normalize(alias) for alias in _ROLE_ALIASES.get(role, set()))
    words = [
        word
        for word in normalized_target.split()
        if word not in _STOPWORDS and word not in aliases
    ]
    return " ".join(words).strip()


def _strip_state_words(normalized_target: str) -> str:
    text = normalized_target.replace("not disabled", "").replace("not required", "").replace("not checked", "")
    text = text.replace("read only", "")
    words = [word for word in text.split() if word not in _STATE_TERMS and word != "optional"]
    return " ".join(words).strip()


def _strip_ordinal_words(normalized_target: str) -> str:
    words = [word for word in normalized_target.split() if word not in _ORDINALS]
    return " ".join(words).strip()


def _normalize(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    normalized = " ".join("".join(ch for ch in text if ch.isalnum() or ch.isspace()).split())
    return normalized.replace("e mail", "email")


def _semantic_variants(value: str) -> list[str]:
    normalized = _normalize(value)
    if not normalized:
        return []
    variants = [normalized]
    replacements = {
        "find": "search",
        "search": "find",
        "next": "continue",
        "continue": "next",
        "submit": "continue",
        "cancel": "back",
        "back": "cancel",
        "passcode": "password",
        "password": "passcode",
        "warning": "alert",
        "alert": "warning",
        "dialog": "alert",
        "dropdown": "combobox",
        "select": "combobox",
        "input": "textbox",
        "field": "textbox",
    }
    words = normalized.split()
    for index, word in enumerate(words):
        replacement = replacements.get(word)
        if replacement:
            copy = list(words)
            copy[index] = replacement
            variants.append(" ".join(copy))
    return list(dict.fromkeys(variants))


def _found_message(candidate: BrowserGroundingCandidate) -> str:
    label = _candidate_label(candidate)
    role = _ROLE_DISPLAY.get(candidate.role, candidate.role or "target")
    if candidate.role in {"alert", "dialog"}:
        return f"The {label} dialog is present."
    return f"I found the {label} {role}."


def _candidate_label(candidate: BrowserGroundingCandidate) -> str:
    return _bounded_text(candidate.label or candidate.name or candidate.text or candidate.role or "target", 80)


def _candidate_summary(candidate: BrowserGroundingCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "control_id": candidate.control_id,
        "role": candidate.role,
        "name": _candidate_label(candidate),
        "match_reason": candidate.match_reason,
        "confidence": round(float(candidate.confidence or 0.0), 3),
        "evidence_terms": list(candidate.evidence_terms)[:8],
        "mismatch_terms": list(candidate.mismatch_terms)[:8],
        "ambiguity_reason": candidate.ambiguity_reason,
        "source_provider": candidate.source_provider,
        "source_observation_id": candidate.source_observation_id,
        "claim_ceiling": candidate.claim_ceiling,
    }


def _human_list(values: Sequence[str]) -> str:
    cleaned = [value for value in values if value]
    if not cleaned:
        return "matching controls"
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _target_display_phrase(target_phrase: str) -> str:
    analysis = _target_analysis(target_phrase)
    role = str(analysis.get("target_role") or "")
    stripped = str(analysis.get("stripped") or "").strip()
    display_role = _ROLE_DISPLAY.get(role, role or "target")
    if stripped:
        return f"{stripped.title()} {display_role}".strip()
    return display_role


def _guidance_limitations(limitations: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for limitation in limitations:
        text = str(limitation or "").strip()
        if text == "not_truth_verified":
            text = "not_truth_claimed"
        if text:
            cleaned.append(text)
    return cleaned


def _plural_role(role: str) -> str:
    display = _ROLE_DISPLAY.get(role, role or "controls")
    if display.endswith("s"):
        return display
    if display == "field":
        return "fields"
    return f"{display}s"


def _number_word(value: int) -> str:
    return {0: "no", 1: "one", 2: "two", 3: "three"}.get(value, str(value))


def _observation_is_stale(observation: BrowserSemanticObservation) -> bool:
    if not observation.observed_at:
        return False
    try:
        observed = datetime.fromisoformat(str(observation.observed_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return (datetime.now(UTC) - observed.astimezone(UTC)).total_seconds() > _STALE_OBSERVATION_SECONDS


def _form_page_summary(observation: BrowserSemanticObservation) -> dict[str, Any]:
    visible_controls = [control for control in observation.controls if control.visible is not False]
    fields = [
        control
        for control in visible_controls
        if _canonical_role(control.role) in {"textbox", "checkbox", "radio", "combobox"}
    ]
    required_fields = [_control_label(control) for control in fields if control.required is True]
    readonly_fields = [_control_label(control) for control in fields if control.readonly is True]
    unchecked_required_controls = [
        _control_label(control)
        for control in fields
        if _canonical_role(control.role) in {"checkbox", "radio"} and control.required is True and control.checked is False
    ]
    disabled_controls = [_control_label(control) for control in visible_controls if control.enabled is False]
    links = [_control_label(control) for control in visible_controls if _canonical_role(control.role) == "link"]
    possible_submit_controls = [
        _control_label(control)
        for control in visible_controls
        if _canonical_role(control.role) == "button"
        and any(term in _normalize(_control_label(control)) for term in ("submit", "continue", "next", "save"))
    ]
    sensitive_fields = [_control_label(control) for control in fields if "sensitive" in _normalize(control.risk_hint)]
    warnings = []
    for item in list(observation.dialogs) + list(observation.alerts):
        text = _bounded_text(item.get("name") or item.get("text") or "", 80)
        if text and text not in warnings:
            warnings.append(text)
    field_summaries = [
        {
            "name": _control_label(control),
            "role": _canonical_role(control.role),
            "required": bool(control.required),
            "enabled": control.enabled is not False,
            "checked": control.checked,
            "readonly": control.readonly is True,
            "sensitive": "sensitive" in _normalize(control.risk_hint),
            "value_summary": "[redacted sensitive field]" if "sensitive" in _normalize(control.risk_hint) else _bounded_text(control.value_summary, 80),
        }
        for control in fields[:_LIST_LIMIT]
    ]
    form_groups = [
        {
            "form_id": _bounded_text(form.get("form_id") or form.get("id") or ""),
            "name": _bounded_text(form.get("name") or form.get("summary") or "form-like group", 80),
            "field_count": _safe_int(form.get("field_count"), default=0),
            "inferred": bool(form.get("inferred")),
        }
        for form in observation.forms[:_LIST_LIMIT]
        if isinstance(form, dict)
    ]
    form_like_inferred = any(group.get("inferred") for group in form_groups)
    return {
        "provider": observation.provider,
        "source_observation_id": observation.observation_id,
        "page_url": _safe_display_url(observation.page_url),
        "page_title": _bounded_text(observation.page_title),
        "field_count": len(fields),
        "fields": field_summaries,
        "form_count": len(observation.forms),
        "form_groups": form_groups,
        "multiple_forms": len(observation.forms) > 1,
        "form_like_structure_inferred": form_like_inferred,
        "required_fields": required_fields[:_LIST_LIMIT],
        "readonly_fields": readonly_fields[:_LIST_LIMIT],
        "unchecked_required_controls": unchecked_required_controls[:_LIST_LIMIT],
        "disabled_controls": disabled_controls[:_LIST_LIMIT],
        "possible_submit_controls": possible_submit_controls[:_LIST_LIMIT],
        "links": links[:_LIST_LIMIT],
        "warnings": warnings[:_LIST_LIMIT],
        "sensitive_fields": sensitive_fields[:_LIST_LIMIT],
        "claim_ceiling": _CLAIM_CEILING,
        "limitations": list(observation.limitations),
    }


def _coerce_verification_request(
    value: BrowserSemanticVerificationRequest | dict[str, Any] | None,
    *,
    before: BrowserSemanticObservation | None,
    after: BrowserSemanticObservation | None,
) -> BrowserSemanticVerificationRequest:
    if isinstance(value, BrowserSemanticVerificationRequest):
        if not value.before_observation_id and before is not None:
            value.before_observation_id = before.observation_id
        if not value.after_observation_id and after is not None:
            value.after_observation_id = after.observation_id
        return value
    payload = dict(value or {})
    return BrowserSemanticVerificationRequest(
        before_observation_id=str(payload.get("before_observation_id") or (before.observation_id if before is not None else "")),
        after_observation_id=str(payload.get("after_observation_id") or (after.observation_id if after is not None else "")),
        expected_change_kind=_bounded_text(payload.get("expected_change_kind") or payload.get("change_kind") or ""),
        target_phrase=_bounded_text(payload.get("target_phrase") or payload.get("expected_target") or ""),
        expected_target=_bounded_text(payload.get("expected_target") or ""),
        expected_state=payload.get("expected_state"),
        source_provider=_bounded_text(payload.get("source_provider") or "playwright"),
    )


def _compare_semantic_observations(
    before: BrowserSemanticObservation | None,
    after: BrowserSemanticObservation | None,
    *,
    request: BrowserSemanticVerificationRequest,
    adapter: PlaywrightBrowserSemanticAdapter,
) -> BrowserSemanticVerificationResult:
    if before is None or after is None:
        return BrowserSemanticVerificationResult(
            request_id=request.request_id,
            status="insufficient_basis",
            summary="Missing before or after semantic browser observation.",
            before_observation_id=request.before_observation_id,
            after_observation_id=request.after_observation_id,
            confidence=0.0,
            limitations=["insufficient_basis", "no_actions", "not_visible_screen_verification", "not_truth_verified"],
            user_message="I cannot verify that from these observations.",
        )

    changes = _semantic_changes(before, after)
    limitations = _comparison_limitations(before, after)
    stale = _observation_is_stale(before) or _observation_is_stale(after)
    partial = _observation_is_partial(before) or _observation_is_partial(after)
    expected_requested = bool(request.expected_change_kind or request.target_phrase or request.expected_state is not None)
    if stale:
        return _semantic_result(
            request,
            before,
            after,
            changes,
            status="stale_basis",
            supported=False,
            evidence=[],
            missing=["stale_semantic_observation"],
            limitations=list(dict.fromkeys(limitations + ["stale"])),
            confidence=0.24,
            message="The before or after semantic snapshot is stale, so I would not rely on this comparison.",
        )
    if expected_requested:
        status, supported, evidence, missing, message, confidence = _evaluate_expected_change(request, before, after, changes, adapter)
        if partial and status == "supported":
            status = "partial"
            confidence = min(confidence, 0.56)
            message = "I found related semantic evidence, but the observation basis is partial."
        return _semantic_result(
            request,
            before,
            after,
            changes,
            status=status,
            supported=supported,
            evidence=evidence,
            missing=missing,
            limitations=limitations,
            confidence=confidence,
            message=message,
        )

    status = "supported" if changes else "unsupported"
    if partial and changes:
        status = "partial"
    return _semantic_result(
        request,
        before,
        after,
        changes,
        status=status,
        supported=False,
        evidence=[change.change_type for change in changes[:_LIST_LIMIT]],
        missing=[] if changes else ["no_semantic_changes_detected"],
        limitations=limitations,
        confidence=0.78 if changes and not partial else 0.5 if changes else 0.42,
        message="Semantic snapshots show bounded page changes." if changes else "The semantic snapshots do not show a browser-page change.",
    )


def _semantic_result(
    request: BrowserSemanticVerificationRequest,
    before: BrowserSemanticObservation,
    after: BrowserSemanticObservation,
    changes: Sequence[BrowserSemanticChange],
    *,
    status: str,
    supported: bool,
    evidence: Sequence[str],
    missing: Sequence[str],
    limitations: Sequence[str],
    confidence: float,
    message: str,
) -> BrowserSemanticVerificationResult:
    return BrowserSemanticVerificationResult(
        request_id=request.request_id,
        status=status,
        summary=_comparison_summary(changes, request=request, status=status),
        changes=list(changes)[:_LIST_LIMIT],
        expected_change_supported=bool(supported),
        expected_change_evidence=[_bounded_text(item, 120) for item in evidence[:_LIST_LIMIT]],
        expected_change_missing=[_bounded_text(item, 120) for item in missing[:_LIST_LIMIT]],
        before_observation_id=before.observation_id,
        after_observation_id=after.observation_id,
        confidence=round(float(confidence or 0.0), 3),
        comparison_basis="isolated_browser_semantic_observation",
        claim_ceiling=_COMPARISON_CLAIM_CEILING,
        limitations=list(dict.fromkeys(list(limitations) + ["semantic_comparison_only", "no_actions", "not_visible_screen_verification", "not_truth_verified"])),
        user_message=message,
    )


def _semantic_changes(before: BrowserSemanticObservation, after: BrowserSemanticObservation) -> list[BrowserSemanticChange]:
    changes: list[BrowserSemanticChange] = []
    if _safe_display_url(before.page_url) != _safe_display_url(after.page_url):
        changes.append(_change("page_url_changed", before_summary=_safe_display_url(before.page_url), after_summary=_safe_display_url(after.page_url), evidence_terms=["page_url_changed"], confidence=0.86))
    if _bounded_text(before.page_title) != _bounded_text(after.page_title):
        changes.append(_change("page_title_changed", before_summary=before.page_title, after_summary=after.page_title, evidence_terms=["page_title_changed"], confidence=0.82))

    matched, removed, added = _match_controls(before.controls, after.controls)
    for before_control, after_control in matched:
        changes.extend(_control_state_changes(before_control, after_control))
        if _control_text_tuple(before_control) != _control_text_tuple(after_control):
            changes.append(
                _change(
                    "control_text_changed",
                    before_summary=_control_public_summary(before_control),
                    after_summary=_control_public_summary(after_control),
                    control_id_before=before_control.control_id,
                    control_id_after=after_control.control_id,
                    role=_canonical_role(before_control.role or after_control.role),
                    name=_control_label(after_control) or _control_label(before_control),
                    label=after_control.label or before_control.label,
                    evidence_terms=["control_text_changed"],
                    confidence=0.68,
                    sensitive_redacted=_is_sensitive_control(before_control) or _is_sensitive_control(after_control),
                )
            )
    for control in removed:
        change_type = "link_removed" if _canonical_role(control.role) == "link" else "form_field_removed" if _canonical_role(control.role) in {"textbox", "checkbox", "radio", "combobox"} else "control_removed"
        changes.append(_control_presence_change(change_type, control, before=True))
    for control in added:
        change_type = "link_added" if _canonical_role(control.role) == "link" else "form_field_added" if _canonical_role(control.role) in {"textbox", "checkbox", "radio", "combobox"} else "control_added"
        changes.append(_control_presence_change(change_type, control, before=False))

    changes.extend(_dialog_changes(before, after))
    if _form_signature(before.forms) != _form_signature(after.forms):
        changes.append(_change("form_summary_changed", before_summary=_form_signature(before.forms), after_summary=_form_signature(after.forms), evidence_terms=["form_summary_changed"], confidence=0.64))
    if set(before.limitations) != set(after.limitations):
        limitation_terms = sorted(set(before.limitations).symmetric_difference(set(after.limitations)))[:8]
        embedded = any("iframe" in term or "shadow" in term for term in limitation_terms)
        changes.append(
            _change(
                "embedded_context_changed" if embedded else "observation_limitation_changed",
                before_summary=", ".join(before.limitations[:4]),
                after_summary=", ".join(after.limitations[:4]),
                evidence_terms=["observation_limitation_changed"],
                confidence=0.46,
                limitations=limitation_terms,
            )
        )
    return changes[:_LIST_LIMIT]


def _control_state_changes(before: BrowserSemanticControl, after: BrowserSemanticControl) -> list[BrowserSemanticChange]:
    changes: list[BrowserSemanticChange] = []
    fields = [
        ("enabled", "enabled_state_changed"),
        ("required", "required_state_changed"),
        ("readonly", "readonly_state_changed"),
        ("checked", "checked_state_changed"),
        ("expanded", "expanded_state_changed"),
    ]
    for field_name, change_type in fields:
        before_value = getattr(before, field_name)
        after_value = getattr(after, field_name)
        if before_value != after_value:
            changes.append(
                _change(
                    change_type,
                    before_summary=f"{_control_label(before)} {field_name}={before_value}",
                    after_summary=f"{_control_label(after)} {field_name}={after_value}",
                    control_id_before=before.control_id,
                    control_id_after=after.control_id,
                    role=_canonical_role(after.role or before.role),
                    name=_control_label(after) or _control_label(before),
                    label=after.label or before.label,
                    evidence_terms=[change_type],
                    confidence=0.78,
                    sensitive_redacted=_is_sensitive_control(before) or _is_sensitive_control(after),
                )
            )
    if before.value_summary != after.value_summary:
        changes.append(
            _change(
                "value_summary_changed",
                before_summary=_safe_value_summary(before),
                after_summary=_safe_value_summary(after),
                control_id_before=before.control_id,
                control_id_after=after.control_id,
                role=_canonical_role(after.role or before.role),
                name=_control_label(after) or _control_label(before),
                label=after.label or before.label,
                evidence_terms=["value_summary_changed"],
                confidence=0.52,
                sensitive_redacted=_is_sensitive_control(before) or _is_sensitive_control(after),
            )
        )
    return changes


def _change(
    change_type: str,
    *,
    before_summary: str = "",
    after_summary: str = "",
    control_id_before: str = "",
    control_id_after: str = "",
    role: str = "",
    name: str = "",
    label: str = "",
    evidence_terms: Sequence[str] = (),
    confidence: float = 0.0,
    sensitive_redacted: bool = False,
    limitations: Sequence[str] = (),
) -> BrowserSemanticChange:
    return BrowserSemanticChange(
        change_type=change_type,
        before_summary=_redacted_summary(before_summary, sensitive=sensitive_redacted),
        after_summary=_redacted_summary(after_summary, sensitive=sensitive_redacted),
        control_id_before=_bounded_text(control_id_before, 80),
        control_id_after=_bounded_text(control_id_after, 80),
        role=_bounded_text(role, 80),
        name=_bounded_text(name, 80),
        label=_bounded_text(label, 80),
        evidence_terms=list(dict.fromkeys(str(term) for term in evidence_terms if term))[:8],
        confidence=round(float(confidence or 0.0), 3),
        sensitive_redacted=bool(sensitive_redacted),
        limitations=[_bounded_text(item, 80) for item in limitations[:8]],
    )


def _control_presence_change(change_type: str, control: BrowserSemanticControl, *, before: bool) -> BrowserSemanticChange:
    return _change(
        change_type,
        before_summary=_control_public_summary(control) if before else "",
        after_summary="" if before else _control_public_summary(control),
        control_id_before=control.control_id if before else "",
        control_id_after="" if before else control.control_id,
        role=_canonical_role(control.role),
        name=_control_label(control),
        label=control.label,
        evidence_terms=[change_type],
        confidence=0.72,
        sensitive_redacted=_is_sensitive_control(control),
    )


def _dialog_changes(before: BrowserSemanticObservation, after: BrowserSemanticObservation) -> list[BrowserSemanticChange]:
    changes: list[BrowserSemanticChange] = []
    before_items = _dialog_map(before)
    after_items = _dialog_map(after)
    for key, item in before_items.items():
        if key not in after_items:
            role = _canonical_role(item.get("role") or "dialog")
            change_type = "warning_removed" if role == "alert" else "dialog_removed"
            changes.append(_change(change_type, before_summary=_dialog_summary(item), evidence_terms=[change_type], role=role, name=_dialog_summary(item), confidence=0.74))
    for key, item in after_items.items():
        if key not in before_items:
            role = _canonical_role(item.get("role") or "dialog")
            change_type = "warning_added" if role == "alert" else "dialog_added"
            changes.append(_change(change_type, after_summary=_dialog_summary(item), evidence_terms=[change_type], role=role, name=_dialog_summary(item), confidence=0.74))
    return changes


def _evaluate_expected_change(
    request: BrowserSemanticVerificationRequest,
    before: BrowserSemanticObservation,
    after: BrowserSemanticObservation,
    changes: Sequence[BrowserSemanticChange],
    adapter: PlaywrightBrowserSemanticAdapter,
) -> tuple[str, bool, list[str], list[str], str, float]:
    target_phrase = request.target_phrase or request.expected_target
    expected_kind = _normalize(request.expected_change_kind)
    matching = [change for change in changes if _change_matches_request(change, request)]
    if matching:
        status = "supported"
        evidence = [change.change_type for change in matching[:_LIST_LIMIT]]
        message = _supported_message(request, matching[0])
        confidence = min(0.86, max(change.confidence for change in matching) + 0.08)
        return status, True, evidence, [], message, confidence
    if target_phrase:
        before_candidates = adapter.ground_target(target_phrase, before)
        after_candidates = adapter.ground_target(target_phrase, after)
        if len(before_candidates) > 1 or len(after_candidates) > 1:
            return "ambiguous", False, [], ["multiple_semantic_targets_matched"], "The comparison is ambiguous for that target.", 0.36
        if not before_candidates and not after_candidates:
            return "unsupported", False, [], ["target_missing_from_semantic_snapshots"], "The semantic snapshots do not support that expected change.", 0.42
    related = [change for change in changes if _related_change(change, request)]
    if related:
        return "partial", False, [change.change_type for change in related[:_LIST_LIMIT]], ["exact_expected_change_not_found"], "I found a related semantic change, but not enough to say the expected outcome happened.", 0.5
    return "unsupported", False, [], ["expected_change_not_observed"], "The semantic snapshots do not support that expected change.", 0.44


def _change_matches_request(change: BrowserSemanticChange, request: BrowserSemanticVerificationRequest) -> bool:
    expected_kind = _normalize(request.expected_change_kind)
    if expected_kind and expected_kind != _normalize(change.change_type):
        return False
    target = _normalize(request.target_phrase or request.expected_target)
    if target and not _change_matches_target(change, target):
        return False
    expected_state = request.expected_state
    if expected_state is not None:
        after_summary = _normalize(change.after_summary)
        if isinstance(expected_state, bool):
            if expected_state is True and "true" not in after_summary:
                return False
            if expected_state is False and "false" not in after_summary:
                return False
    return True


def _related_change(change: BrowserSemanticChange, request: BrowserSemanticVerificationRequest) -> bool:
    target = _normalize(request.target_phrase or request.expected_target)
    return bool(target and _change_matches_target(change, target))


def _change_matches_target(change: BrowserSemanticChange, normalized_target: str) -> bool:
    values = _semantic_variants(
        " ".join(
            [
                change.name,
                change.label,
                change.role,
                change.before_summary,
                change.after_summary,
            ]
        )
    )
    target_variants = _semantic_variants(normalized_target)
    return any(target and value and (target in value or value in target) for target in target_variants for value in values)


def _supported_message(request: BrowserSemanticVerificationRequest, change: BrowserSemanticChange) -> str:
    kind = _normalize(request.expected_change_kind)
    label = _bounded_text(change.name or change.label or request.target_phrase or "target", 80)
    if kind == "warning removed":
        return "The semantic snapshots support that the warning disappeared."
    if kind == "enabled state changed" and request.expected_state is True:
        return f"The {label} button appears to have become enabled."
    if kind == "checked state changed":
        return f"The {label} checkbox appears to have changed checked state."
    if kind == "required state changed":
        return f"The {label} field appears to have changed required state."
    if kind == "page url changed":
        return "The semantic snapshots support that the page URL changed."
    if kind in {"dialog added", "warning added"}:
        return "The semantic snapshots support that a browser-page warning or dialog appeared."
    if kind in {"control added", "link added"}:
        return f"The semantic snapshots support that {label} appeared."
    return "The semantic snapshots support the expected semantic change."


def _comparison_limitations(before: BrowserSemanticObservation, after: BrowserSemanticObservation) -> list[str]:
    limitations = ["semantic_comparison_only", "not_user_visible_screen", "not_truth_verified"]
    for item in list(before.limitations) + list(after.limitations):
        text = str(item or "").strip()
        if text:
            limitations.append(text)
    if _observation_is_partial(before) or _observation_is_partial(after):
        limitations.append("partial_semantic_observation")
    return list(dict.fromkeys(limitations))


def _observation_is_partial(observation: BrowserSemanticObservation) -> bool:
    return any("partial" in str(item) or "limited" in str(item) or "not_observed" in str(item) for item in observation.limitations)


def _comparison_summary(
    changes: Sequence[BrowserSemanticChange],
    *,
    request: BrowserSemanticVerificationRequest,
    status: str,
) -> str:
    if request.expected_change_kind or request.target_phrase:
        return f"Semantic comparison {status}; {len(changes)} bounded changes found."
    return f"Semantic comparison found {len(changes)} bounded changes."


def _verification_summary(result: BrowserSemanticVerificationResult) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "request_id": result.request_id,
        "status": result.status,
        "summary": _bounded_text(result.summary),
        "change_count": len(result.changes),
        "expected_change_supported": result.expected_change_supported,
        "expected_change_evidence": list(result.expected_change_evidence)[:8],
        "expected_change_missing": list(result.expected_change_missing)[:8],
        "before_observation_id": result.before_observation_id,
        "after_observation_id": result.after_observation_id,
        "confidence": round(float(result.confidence or 0.0), 3),
        "claim_ceiling": result.claim_ceiling,
        "limitations": list(result.limitations)[:8],
        "user_message": _bounded_text(result.user_message),
        "top_changes": [_change_summary(change) for change in result.changes[:_GROUNDING_CANDIDATE_LIMIT]],
    }


def _classify_action_kind(action_phrase: str, candidate: BrowserGroundingCandidate | None = None) -> str:
    phrase = _normalize(action_phrase)
    role = _canonical_role(candidate.role) if candidate is not None else ""
    if not phrase:
        if role in {"button", "link"}:
            return "click"
        if role == "textbox":
            return "focus"
        if role == "checkbox":
            return "check"
        if role == "combobox":
            return "select_option"
        return "unsupported"
    if "submit" in phrase and ("form" in phrase or role == "button"):
        return "submit_form"
    if any(term in phrase for term in ("type", "enter", "write", "fill")):
        return "type_text"
    if any(term in phrase for term in ("uncheck", "untick", "clear checkbox")):
        return "uncheck"
    if any(term in phrase for term in ("check", "tick")) and role == "checkbox":
        return "check"
    if any(term in phrase for term in ("select", "choose", "pick")) and role == "combobox":
        return "select_option"
    if any(term in phrase for term in ("scroll", "move down", "move up")):
        return "scroll_to"
    if any(term in phrase for term in ("focus", "place cursor", "go to")):
        return "focus"
    if any(term in phrase for term in ("click", "press", "open", "tap")):
        return "click"
    return "unsupported"


def _action_preview_from_state(
    observation: BrowserSemanticObservation,
    *,
    target_phrase: str,
    action_kind: str,
    state: str,
    reason: str,
    candidates: Sequence[BrowserGroundingCandidate] | None = None,
) -> BrowserSemanticActionPreview:
    candidates = list(candidates or [])
    target = candidates[0] if candidates else None
    limitations = ["preview_only", "action_execution_deferred", reason, "no_actions"]
    return BrowserSemanticActionPreview(
        observation_id=observation.observation_id,
        source_provider=observation.provider,
        target_phrase=_bounded_text(target_phrase),
        target_candidate_id=target.candidate_id if target is not None and len(candidates) == 1 else "",
        target_role=target.role if target is not None else "",
        target_name=_candidate_label(target) if target is not None else "",
        target_label=target.label if target is not None else "",
        action_kind=action_kind,
        preview_state=state,
        reason_not_executable=reason if state == "unsupported" else "action_execution_deferred",
        confidence=round(float(target.confidence or 0.0), 3) if target is not None else 0.0,
        risk_level="medium" if state != "blocked" else "blocked",
        approval_required=True,
        required_trust_scope="browser_action_once_future" if state != "blocked" else "blocked_until_future_policy",
        expected_outcome=[] if state != "ambiguous" else _expected_outcomes_for_action(action_kind),
        verification_strategy="semantic_before_after_comparison_required",
        limitations=limitations,
    )


def _action_preview_for_candidate(
    observation: BrowserSemanticObservation,
    candidate: BrowserGroundingCandidate,
    *,
    target_phrase: str,
    action_kind: str,
    action_arguments: dict[str, Any] | None = None,
    config: PlaywrightBrowserAdapterConfig | None = None,
) -> BrowserSemanticActionPreview:
    risk_level, trust_scope, blocked_reason = _action_risk_and_trust(action_kind, candidate)
    state = "blocked" if blocked_reason else "preview_only"
    capability_declared = _action_capability_declared(config, action_kind)
    limitations = ["preview_only"]
    if capability_declared and not blocked_reason:
        limitations.extend(["approval_required", "execution_requires_trust"])
    else:
        limitations.extend(["action_execution_deferred", "no_actions"])
    if blocked_reason:
        limitations.append(blocked_reason)
    if _redacted_action_arguments(action_kind, action_arguments):
        limitations.append("action_arguments_redacted")
    return BrowserSemanticActionPreview(
        observation_id=observation.observation_id,
        source_provider=observation.provider,
        target_phrase=_bounded_text(target_phrase),
        target_candidate_id=candidate.candidate_id,
        target_role=candidate.role,
        target_name=_candidate_label(candidate),
        target_label=candidate.label,
        action_kind=action_kind,
        preview_state=state,
        action_supported_now=bool(capability_declared and not blocked_reason),
        action_supported=bool(capability_declared and not blocked_reason),
        executable_now=False,
        reason_not_executable="approval_required" if capability_declared and not blocked_reason else "action_execution_deferred" if not blocked_reason else "restricted_context_deferred",
        confidence=round(float(candidate.confidence or 0.0), 3),
        risk_level=risk_level,
        approval_required=True,
        required_trust_scope=trust_scope,
        expected_outcome=_expected_outcomes_for_action(action_kind),
        verification_strategy="semantic_before_after_comparison_required",
        limitations=limitations,
    )


def _page_scroll_candidate(target_phrase: str, observation: BrowserSemanticObservation) -> BrowserGroundingCandidate:
    return BrowserGroundingCandidate(
        target_phrase=target_phrase,
        control_id="page",
        role="page",
        name=observation.page_title or "page",
        label=observation.page_title or "page",
        match_reason="page_scroll_preview",
        confidence=0.48,
        source_observation_id=observation.observation_id,
        source_provider=observation.provider,
        claim_ceiling=_CLAIM_CEILING,
    )


def _action_risk_and_trust(action_kind: str, candidate: BrowserGroundingCandidate) -> tuple[str, str, str]:
    haystack = _normalize(" ".join([candidate.name, candidate.label, candidate.text, candidate.role, candidate.control_id]))
    if any(term in haystack for term in ("password", "passcode", "secret", "token", "credential", "login", "sign in", "captcha")):
        return "blocked", "blocked_until_future_policy", "sensitive_or_restricted_context"
    if any(term in haystack for term in ("payment", "billing", "checkout", "card", "purchase")):
        return "blocked", "blocked_until_future_policy", "payment_or_restricted_context"
    if action_kind in {"type_text", "submit_form"}:
        return "high", "browser_action_strong_confirmation_future", ""
    if action_kind in {"focus", "scroll_to"}:
        return "low", "browser_action_once_future", ""
    if action_kind in {"click", "check", "uncheck", "select_option"}:
        return "medium", "browser_action_once_future", ""
    return "medium", "browser_action_once_future", ""


def _expected_outcomes_for_action(action_kind: str) -> list[str]:
    if action_kind == "click":
        return [
            "page_url_changed",
            "dialog_added",
            "dialog_removed",
            "enabled_state_changed",
            "warning_added",
            "warning_removed",
            "form_summary_changed",
        ]
    if action_kind in {"check", "uncheck"}:
        return ["checked_state_changed"]
    if action_kind in {"type_text", "select_option"}:
        return ["value_summary_changed"]
    if action_kind == "submit_form":
        return [
            "page_url_changed",
            "page_title_changed",
            "dialog_added",
            "warning_added",
            "warning_removed",
            "form_summary_changed",
        ]
    if action_kind in {"focus", "scroll_to"}:
        return ["control_state_changed"]
    return []


def _action_capability_required(action_kind: str) -> str:
    return {
        "click": "browser.input.click",
        "focus": "browser.input.focus",
        "type_text": "browser.input.type",
        "select_option": "browser.input.select_option",
        "check": "browser.input.check",
        "uncheck": "browser.input.uncheck",
        "scroll_to": "browser.input.scroll",
        "submit_form": "browser.form.submit",
    }.get(action_kind, "browser.action.unsupported")


def _redacted_action_arguments(action_kind: str, action_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = dict(action_arguments or {})
    redacted: dict[str, Any] = {}
    if action_kind == "type_text":
        if "text" in raw or "value" in raw:
            redacted["text"] = "[redacted text]"
    elif action_kind == "select_option":
        if "option" in raw:
            redacted["option"] = _bounded_text(raw.get("option"), 80)
    elif action_kind in {"check", "uncheck", "click", "focus", "scroll_to", "submit_form"}:
        for key in ("direction", "position", "button"):
            if key in raw:
                redacted[key] = _bounded_text(raw.get(key), 80)
    return redacted


def _coerce_action_preview(value: BrowserSemanticActionPreview | dict[str, Any]) -> BrowserSemanticActionPreview:
    if isinstance(value, BrowserSemanticActionPreview):
        return value
    payload = dict(value or {})
    return BrowserSemanticActionPreview(
        preview_id=_bounded_text(payload.get("preview_id") or ""),
        observation_id=_bounded_text(payload.get("observation_id") or ""),
        source_provider=_bounded_text(payload.get("source_provider") or ""),
        target_phrase=_bounded_text(payload.get("target_phrase") or ""),
        target_candidate_id=_bounded_text(payload.get("target_candidate_id") or payload.get("candidate_id") or ""),
        target_role=_bounded_text(payload.get("target_role") or payload.get("role") or ""),
        target_name=_bounded_text(payload.get("target_name") or payload.get("name") or ""),
        target_label=_bounded_text(payload.get("target_label") or payload.get("label") or ""),
        action_kind=_bounded_text(payload.get("action_kind") or "unsupported"),
        preview_state=_bounded_text(payload.get("preview_state") or payload.get("status") or "unsupported"),
        action_supported_now=bool(payload.get("action_supported_now", payload.get("action_supported", False))),
        action_supported=bool(payload.get("action_supported", payload.get("action_supported_now", False))),
        executable_now=bool(payload.get("executable_now", False)),
        reason_not_executable=_bounded_text(payload.get("reason_not_executable") or payload.get("reason") or "action_execution_deferred"),
        confidence=float(payload.get("confidence") or 0.0),
        risk_level=_bounded_text(payload.get("risk_level") or "medium"),
        approval_required=True,
        required_trust_scope=_bounded_text(payload.get("required_trust_scope") or "browser_action_once_future"),
        expected_outcome=list(payload.get("expected_outcome") or []),
        verification_strategy=_bounded_text(payload.get("verification_strategy") or "semantic_before_after_comparison_required"),
        limitations=list(payload.get("limitations") or ["preview_only", "action_execution_deferred", "no_actions"]),
    )


def _action_plan_from_preview(
    preview: BrowserSemanticActionPreview,
    *,
    action_arguments: dict[str, Any] | None = None,
    config: PlaywrightBrowserAdapterConfig | None = None,
) -> BrowserSemanticActionPlan:
    result_state = {
        "preview_only": "preview_only",
        "ambiguous": "ambiguous",
        "blocked": "blocked",
        "unsupported": "unsupported",
    }.get(preview.preview_state, "unsupported")
    verification_template = {
        "route_family": "screen_awareness",
        "before_observation_id": preview.observation_id,
        "expected_change_kind": preview.expected_outcome[0] if preview.expected_outcome else "",
        "target_phrase": preview.target_phrase,
        "source_provider": preview.source_provider,
        "claim_ceiling": _COMPARISON_CLAIM_CEILING,
    }
    capability_declared = _action_capability_declared(config, preview.action_kind)
    target_candidate = {
        "candidate_id": preview.target_candidate_id,
        "role": preview.target_role,
        "name": _bounded_text(preview.target_name, 80),
        "label": _bounded_text(preview.target_label, 80),
        "confidence": round(float(preview.confidence or 0.0), 3),
    }
    target_candidate["target_fingerprint"] = _target_fingerprint(target_candidate)
    redacted_arguments = _redacted_action_arguments(preview.action_kind, action_arguments)
    redacted_arguments["target_fingerprint"] = target_candidate["target_fingerprint"]
    return BrowserSemanticActionPlan(
        preview_id=preview.preview_id,
        observation_id=preview.observation_id,
        target_candidate=target_candidate,
        action_kind=preview.action_kind,
        action_arguments_redacted=redacted_arguments,
        preconditions=[
            "fresh_semantic_observation_required",
            "operator_approval_required",
            "adapter_action_capability_required",
            "post_action_semantic_comparison_required",
        ],
        approval_request_hint=_approval_hint(preview),
        adapter_capability_required=_action_capability_required(preview.action_kind),
        adapter_capability_declared=capability_declared,
        executable_now=False,
        verification_request_template=verification_template,
        result_state=result_state,
        user_message=_preview_user_message(preview),
        limitations=list(
            dict.fromkeys(
                list(preview.limitations)
                + ["plan_only", "operator_approval_required"]
                + ([] if capability_declared else ["no_action_execution"])
            )
        ),
    )


def _coerce_action_plan(value: BrowserSemanticActionPlan | dict[str, Any]) -> BrowserSemanticActionPlan:
    if isinstance(value, BrowserSemanticActionPlan):
        return value
    payload = dict(value or {})
    target_candidate = payload.get("target_candidate") if isinstance(payload.get("target_candidate"), dict) else {}
    return BrowserSemanticActionPlan(
        plan_id=_bounded_text(payload.get("plan_id") or ""),
        preview_id=_bounded_text(payload.get("preview_id") or ""),
        observation_id=_bounded_text(payload.get("observation_id") or ""),
        target_candidate=dict(target_candidate),
        action_kind=_bounded_text(payload.get("action_kind") or "unsupported"),
        action_arguments_redacted=dict(payload.get("action_arguments_redacted") or {})
        if isinstance(payload.get("action_arguments_redacted"), dict)
        else {},
        preconditions=list(payload.get("preconditions") or []),
        approval_request_hint=_bounded_text(payload.get("approval_request_hint") or ""),
        adapter_capability_required=_bounded_text(payload.get("adapter_capability_required") or ""),
        adapter_capability_declared=bool(payload.get("adapter_capability_declared", False)),
        executable_now=bool(payload.get("executable_now", False)),
        verification_request_template=dict(payload.get("verification_request_template") or {})
        if isinstance(payload.get("verification_request_template"), dict)
        else {},
        result_state=_bounded_text(payload.get("result_state") or "unsupported"),
        user_message=_bounded_text(payload.get("user_message") or ""),
        claim_ceiling=_bounded_text(payload.get("claim_ceiling") or _ACTION_PREVIEW_CLAIM_CEILING),
        limitations=list(payload.get("limitations") or []),
    )


def _action_gates_requested(config: PlaywrightBrowserAdapterConfig) -> bool:
    return bool(config.allow_actions and getattr(config, "allow_dev_actions", False) and (getattr(config, "allow_click", False) or getattr(config, "allow_focus", False)))


def _parse_utc_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _plan_freshness_blocker(plan: BrowserSemanticActionPlan) -> str:
    created = _parse_utc_timestamp(plan.created_at)
    if created is None:
        return ""
    age_seconds = (datetime.now(UTC) - created).total_seconds()
    if age_seconds > _STALE_OBSERVATION_SECONDS:
        return "blocked_stale_plan"
    return ""


def _target_fingerprint(target: dict[str, Any]) -> str:
    pieces = [
        _bounded_text(target.get("candidate_id") or target.get("control_id") or "", 80),
        _canonical_role(str(target.get("role") or "")),
        _normalize(str(target.get("name") or "")),
        _normalize(str(target.get("label") or "")),
        _normalize(str(target.get("text") or "")),
        _safe_selector_hint(str(target.get("selector_hint") or "")),
    ]
    return _bounded_text("|".join(pieces), 220)


def _plan_target_binding_blocker(plan: BrowserSemanticActionPlan) -> str:
    target = dict(plan.target_candidate or {})
    stored_from_target = _bounded_text(target.get("target_fingerprint") or "", 220)
    stored_from_args = ""
    if isinstance(plan.action_arguments_redacted, dict):
        stored_from_args = _bounded_text(plan.action_arguments_redacted.get("target_fingerprint") or "", 220)
    computed = _target_fingerprint(target)
    if stored_from_target and computed and stored_from_target != computed:
        return "approval_invalid"
    if stored_from_args and computed and stored_from_args != computed:
        return "approval_invalid"
    if stored_from_args and stored_from_target and stored_from_args != stored_from_target:
        return "approval_invalid"
    return ""


def _declared_action_capabilities(
    config: PlaywrightBrowserAdapterConfig,
    readiness: PlaywrightAdapterReadiness | dict[str, Any] | None = None,
) -> list[str]:
    runtime_ready = True
    if isinstance(readiness, PlaywrightAdapterReadiness):
        runtime_ready = bool(readiness.runtime_ready)
    elif isinstance(readiness, dict):
        runtime_ready = bool(readiness.get("runtime_ready") or readiness.get("playwright_runtime_ready"))
    if not runtime_ready:
        return []
    if not (config.enabled and config.allow_browser_launch and config.allow_actions and getattr(config, "allow_dev_actions", False)):
        return []
    capabilities: list[str] = []
    if getattr(config, "allow_click", False):
        capabilities.append("browser.input.click")
    if getattr(config, "allow_focus", False):
        capabilities.append("browser.input.focus")
    return capabilities


def _action_capability_declared(config: PlaywrightBrowserAdapterConfig | None, action_kind: str) -> bool:
    if config is None:
        return False
    capability = _action_capability_required(action_kind)
    if capability not in {"browser.input.click", "browser.input.focus"}:
        return False
    return capability in _declared_action_capabilities(config)


def _action_gate_blocker(config: PlaywrightBrowserAdapterConfig, action_kind: str) -> str:
    if not config.enabled:
        return "playwright_adapter_disabled"
    if not config.allow_dev_adapter:
        return "playwright_dev_adapter_gate_required"
    if not config.allow_browser_launch:
        return "playwright_browser_launch_not_allowed"
    if not config.allow_actions:
        return "actions_disabled"
    if not getattr(config, "allow_dev_actions", False):
        return "dev_actions_gate_required"
    if action_kind == "click" and not getattr(config, "allow_click", False):
        return "click_disabled"
    if action_kind == "focus" and not getattr(config, "allow_focus", False):
        return "focus_disabled"
    if action_kind not in {"click", "focus"}:
        return "unsupported_action_kind"
    blockers = _unsupported_flag_blockers(config)
    return blockers[0] if blockers else ""


def _execution_request_from_plan(
    plan: BrowserSemanticActionPlan,
    *,
    session_id: str,
    task_id: str,
) -> BrowserSemanticActionExecutionRequest:
    target = dict(plan.target_candidate or {})
    expected = []
    template = dict(plan.verification_request_template or {})
    if template.get("expected_change_kind"):
        expected.append(_bounded_text(template.get("expected_change_kind")))
    for item in _expected_outcomes_for_action(plan.action_kind):
        if item not in expected:
            expected.append(item)
    return BrowserSemanticActionExecutionRequest(
        plan_id=plan.plan_id,
        preview_id=plan.preview_id,
        observation_id=plan.observation_id,
        target_candidate_id=_bounded_text(target.get("candidate_id") or ""),
        action_kind=plan.action_kind,
        session_id=session_id,
        task_id=task_id,
        source_provider="playwright_live_semantic",
        expected_outcome=expected,
    )


def _target_summary_from_plan(plan: BrowserSemanticActionPlan) -> dict[str, Any]:
    target = dict(plan.target_candidate or {})
    return {
        "candidate_id": _bounded_text(target.get("candidate_id") or "", 80),
        "role": _bounded_text(target.get("role") or "", 40),
        "name": _bounded_text(target.get("name") or "", 80),
        "label": _bounded_text(target.get("label") or "", 80),
        "confidence": round(float(target.get("confidence") or 0.0), 3),
    }


def _execution_result(
    request: BrowserSemanticActionExecutionRequest,
    plan: BrowserSemanticActionPlan,
    *,
    status: str,
    action_attempted: bool = False,
    action_completed: bool = False,
    verification_attempted: bool = False,
    verification_status: str = "",
    before_observation_id: str = "",
    after_observation_id: str = "",
    comparison_result_id: str = "",
    trust_request_id: str = "",
    approval_request_id: str = "",
    approval_grant_id: str = "",
    trust_scope: str = "",
    error_code: str = "",
    bounded_error_message: str = "",
    user_message: str = "",
    cleanup_status: str = "not_started",
    limitations: Sequence[str] | None = None,
) -> BrowserSemanticActionExecutionResult:
    return BrowserSemanticActionExecutionResult(
        request_id=request.request_id,
        plan_id=plan.plan_id,
        preview_id=plan.preview_id,
        action_kind=plan.action_kind,
        status=status,
        action_attempted=action_attempted,
        action_completed=action_completed,
        verification_attempted=verification_attempted,
        verification_status=verification_status,
        before_observation_id=before_observation_id,
        after_observation_id=after_observation_id,
        comparison_result_id=comparison_result_id,
        target_summary=_target_summary_from_plan(plan),
        risk_level=_risk_level_from_plan(plan),
        trust_scope=trust_scope,
        trust_request_id=trust_request_id,
        approval_request_id=approval_request_id,
        approval_grant_id=approval_grant_id,
        provider="playwright_live_semantic",
        claim_ceiling=_ACTION_EXECUTION_CLAIM_CEILING,
        limitations=list(dict.fromkeys([_bounded_text(item, 120) for item in list(limitations or []) if _bounded_text(item, 120)])),
        error_code=_bounded_text(error_code, 80),
        bounded_error_message=_bounded_text(bounded_error_message),
        user_message=_bounded_text(user_message or _default_execution_user_message(status, plan.action_kind)),
        cleanup_status=_bounded_text(cleanup_status, 40),
        completed_at=utc_now_iso() if status not in {"approval_required", "approved"} else "",
    )


def _risk_level_from_plan(plan: BrowserSemanticActionPlan) -> str:
    target = dict(plan.target_candidate or {})
    risk = str(target.get("risk_level") or "").strip().lower()
    if risk:
        return _bounded_text(risk, 40)
    if plan.action_kind == "focus":
        return "low"
    if plan.action_kind == "click":
        return "medium"
    return "blocked" if plan.result_state == "blocked" else "medium"


def _trust_action_request(
    request: BrowserSemanticActionExecutionRequest,
    plan: BrowserSemanticActionPlan,
) -> TrustActionRequest:
    target = _target_summary_from_plan(plan)
    target_fingerprint = _target_fingerprint(dict(plan.target_candidate or {}))
    subject = f"{plan.action_kind} {target.get('role') or 'target'} {target.get('name') or target.get('label') or ''}".strip()
    return TrustActionRequest(
        request_id=f"trust-playwright-action-{uuid4().hex[:12]}",
        family="screen_awareness",
        action_key=f"screen_awareness.playwright.{plan.action_kind}.{plan.plan_id}.{target_fingerprint}",
        subject=_bounded_text(subject, 120),
        session_id=request.session_id or "default",
        task_id=request.task_id,
        action_kind=TrustActionKind.TOOL,
        approval_required=True,
        preview_allowed=False,
        suggested_scope=PermissionScope.ONCE,
        available_scopes=[PermissionScope.ONCE, PermissionScope.SESSION, PermissionScope.TASK],
        operator_justification=(
            f"Playwright would {plan.action_kind} a grounded browser target inside an isolated temporary browser context."
        ),
        operator_message=f"Approval is required before Stormhelm can {plan.action_kind} {target.get('name') or 'this browser target'}.",
        verification_label="Semantic before/after browser comparison",
        details={
            "plan_id": plan.plan_id,
            "preview_id": plan.preview_id,
            "action_kind": plan.action_kind,
            "target_fingerprint": target_fingerprint,
            "target": target,
            "claim_ceiling": _ACTION_EXECUTION_CLAIM_CEILING,
            "expected_outcome": list(request.expected_outcome)[:8],
        },
    )


def _resolve_execution_candidate(plan: BrowserSemanticActionPlan, observation: BrowserSemanticObservation) -> dict[str, Any]:
    target = dict(plan.target_candidate or {})
    target_id = _bounded_text(target.get("candidate_id") or "")
    role = _canonical_role(str(target.get("role") or ""))
    name = _normalize(str(target.get("name") or ""))
    label = _normalize(str(target.get("label") or ""))
    controls = [control.to_dict() for control in observation.controls]
    matches: list[dict[str, Any]] = []
    for control in controls:
        control_role = _canonical_role(str(control.get("role") or ""))
        control_id = str(control.get("control_id") or "")
        control_name = _normalize(str(control.get("name") or ""))
        control_label = _normalize(str(control.get("label") or ""))
        if target_id and target_id == control_id:
            matches.append(control)
            continue
        if role and control_role != role:
            continue
        if name and (control_name == name or control_label == name):
            matches.append(control)
        elif label and (control_label == label or control_name == label):
            matches.append(control)
    if not matches:
        return {"_execution_blocker": "target_not_found_at_execution"}
    if len(matches) > 1:
        return {"_execution_blocker": "ambiguous_target_at_execution", "match_count": len(matches)}
    return matches[0]


def _candidate_execution_blocker(action_kind: str, target: dict[str, Any]) -> str:
    if target.get("_execution_blocker"):
        return str(target.get("_execution_blocker"))
    role = _canonical_role(str(target.get("role") or ""))
    haystack = _normalize(
        " ".join(
            str(target.get(key) or "")
            for key in ("control_id", "role", "name", "label", "text", "value_summary", "risk_hint")
        )
    )
    if any(term in haystack for term in ("password", "passcode", "secret", "token", "credential", "login", "sign in", "captcha")):
        return "restricted_context_deferred"
    if any(term in haystack for term in ("payment", "billing", "card", "purchase")):
        return "payment_or_restricted_context"
    if target.get("visible") is False:
        return "target_not_visible"
    if target.get("enabled") is False:
        return "target_disabled"
    if action_kind == "click" and role not in {"button", "link"}:
        return "click_target_role_not_allowed"
    if action_kind == "focus" and role not in {"textbox", "button", "link", "checkbox", "radio", "combobox"}:
        return "focus_target_role_not_allowed"
    return ""


def _safe_selector_hint(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        return ""
    if text.startswith("#") and all(ch.isalnum() or ch in {"#", "-", "_", ":"} for ch in text):
        return text
    return ""


def _locator_for_execution(page: Any, target: dict[str, Any]) -> tuple[Any | None, str]:
    role = _canonical_role(str(target.get("role") or ""))
    name = _bounded_text(target.get("name") or target.get("label") or "", 120)
    selector = _safe_selector_hint(str(target.get("selector_hint") or ""))
    if role and name:
        try:
            locator = page.get_by_role(role, name=name, exact=True)
            count = int(locator.count())
        except Exception:
            count = -1
        if count == 1:
            if selector:
                try:
                    selector_locator = page.locator(selector)
                    selector_count = int(selector_locator.count())
                except Exception:
                    return None, "locator_selector_disagrees"
                if selector_count == 0:
                    return None, "locator_selector_disagrees"
                if selector_count > 1:
                    return None, "locator_ambiguous"
                try:
                    evaluate = getattr(locator, "evaluate")
                except Exception:
                    evaluate = None
                if callable(evaluate):
                    try:
                        same_element = bool(
                            evaluate(
                                "(element, selector) => element === document.querySelector(selector)",
                                selector,
                            )
                        )
                    except TypeError:
                        same_element = True
                    except Exception:
                        same_element = True
                    if not same_element:
                        return None, "locator_selector_disagrees"
            return locator, ""
        if count > 1:
            return None, "locator_ambiguous"
    if selector:
        try:
            locator = page.locator(selector)
            count = int(locator.count())
        except Exception:
            return None, "locator_unavailable"
        if count == 1:
            return locator, ""
        if count > 1:
            return None, "locator_ambiguous"
    return None, "locator_not_found"


def _best_action_comparison(
    adapter: PlaywrightBrowserSemanticAdapter,
    before: BrowserSemanticObservation,
    after: BrowserSemanticObservation,
    plan: BrowserSemanticActionPlan,
) -> BrowserSemanticVerificationResult:
    template = dict(plan.verification_request_template or {})
    expected_kinds: list[str] = []
    if template.get("expected_change_kind"):
        expected_kinds.append(_bounded_text(template.get("expected_change_kind")))
    for kind in _expected_outcomes_for_action(plan.action_kind):
        if kind not in expected_kinds:
            expected_kinds.append(kind)
    if not expected_kinds:
        return adapter.compare_semantic_observations(before, after)

    results: list[BrowserSemanticVerificationResult] = []
    for kind in expected_kinds[:8]:
        request = BrowserSemanticVerificationRequest(
            before_observation_id=before.observation_id,
            after_observation_id=after.observation_id,
            expected_change_kind=kind,
            target_phrase=_comparison_target_phrase(kind, plan, template),
            source_provider="playwright_live_semantic",
        )
        result = adapter.compare_semantic_observations(before, after, expected=request)
        if result.status == "supported":
            return result
        results.append(result)
    return results[0] if results else adapter.compare_semantic_observations(before, after)


def _execution_status_from_comparison(
    action_kind: str,
    comparison: BrowserSemanticVerificationResult | None,
) -> tuple[str, str, str]:
    if comparison is None:
        return "completed_unverified", "unavailable", "The action was attempted, but semantic comparison was unavailable."
    if comparison.status == "supported":
        return "verified_supported", "supported", comparison.user_message or "The expected semantic change is supported."
    if comparison.status == "partial":
        return "partial", "partial", comparison.user_message or "I found a related semantic change, but not the full expected outcome."
    if comparison.status == "ambiguous":
        return "ambiguous", "ambiguous", comparison.user_message or "The semantic comparison is ambiguous."
    if comparison.status == "unsupported":
        if action_kind == "focus":
            return "completed_unverified", "unsupported", "Focus was attempted, but semantic comparison did not support the expected change."
        return "verified_unsupported", "unsupported", "The action was attempted, but the expected semantic change is not supported."
    return "completed_unverified", comparison.status, "The action was attempted, but I could not verify the expected change from semantic snapshots."


def _comparison_target_phrase(kind: str, plan: BrowserSemanticActionPlan, template: dict[str, Any]) -> str:
    page_level_kinds = {
        "page_url_changed",
        "page_title_changed",
        "dialog_added",
        "dialog_removed",
        "warning_added",
        "warning_removed",
        "form_summary_changed",
    }
    if kind in page_level_kinds:
        return ""
    return _bounded_text(template.get("target_phrase") or _target_summary_from_plan(plan).get("name") or "")


def _default_execution_user_message(status: str, action_kind: str) -> str:
    if status == "approval_required":
        return "Approval is required before this browser action can run."
    if status == "unsupported":
        return "That browser action is not implemented in this phase."
    if status == "blocked":
        return "That browser action is blocked by the current gates or target safety."
    if status == "verified_supported":
        return f"The semantic snapshots support the expected result of the {action_kind}."
    if status == "verified_unsupported":
        return f"The {action_kind} was attempted, but the expected semantic change is not supported."
    if status == "completed_unverified":
        return f"The {action_kind} was attempted, but semantic verification is not conclusive."
    return "Browser action execution produced a bounded result."


def _action_execution_summary(result: BrowserSemanticActionExecutionResult) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "request_id": result.request_id,
        "plan_id": result.plan_id,
        "preview_id": result.preview_id,
        "action_kind": result.action_kind,
        "status": result.status,
        "action_attempted": result.action_attempted,
        "action_completed": result.action_completed,
        "verification_attempted": result.verification_attempted,
        "verification_status": result.verification_status,
        "before_observation_id": result.before_observation_id,
        "after_observation_id": result.after_observation_id,
        "comparison_result_id": result.comparison_result_id,
        "target_summary": dict(result.target_summary),
        "risk_level": result.risk_level,
        "trust_scope": result.trust_scope,
        "approval_request_id": result.approval_request_id,
        "approval_grant_id": result.approval_grant_id,
        "cleanup_status": result.cleanup_status,
        "provider": result.provider,
        "claim_ceiling": result.claim_ceiling,
        "limitations": list(result.limitations)[:8],
        "error_code": result.error_code,
        "user_message": _bounded_text(result.user_message),
    }


def _execution_event_payload(
    request: BrowserSemanticActionExecutionRequest,
    plan: BrowserSemanticActionPlan,
    *,
    status: str,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "plan_id": plan.plan_id,
        "preview_id": plan.preview_id,
        "action_kind": plan.action_kind,
        "status": status,
        "target": _target_summary_from_plan(plan) if target is None else {
            "role": _bounded_text(target.get("role") or "", 40),
            "name": _bounded_text(target.get("name") or "", 80),
            "label": _bounded_text(target.get("label") or "", 80),
        },
        "risk_level": _risk_level_from_plan(plan),
        "claim_ceiling": _ACTION_EXECUTION_CLAIM_CEILING,
        "limitations": ["isolated_temporary_browser_context", "no_user_profile", "not_visible_screen_verification", "not_truth_verified"],
    }


def _action_execution_event_payload(result: BrowserSemanticActionExecutionResult) -> dict[str, Any]:
    return {
        "request_id": result.request_id,
        "plan_id": result.plan_id,
        "action_kind": result.action_kind,
        "target": dict(result.target_summary),
        "risk_level": result.risk_level,
        "approval_state": result.status if result.status == "approval_required" else "approved" if result.approval_grant_id else "",
        "execution_status": result.status,
        "verification_status": result.verification_status,
        "cleanup_status": result.cleanup_status,
        "claim_ceiling": result.claim_ceiling,
        "limitations": list(result.limitations)[:8],
        "error_code": result.error_code,
        "bounded_error_message": _bounded_text(result.bounded_error_message),
    }


def _action_execution_event_message(result: BrowserSemanticActionExecutionResult) -> str:
    if result.status == "approval_required":
        return "Playwright browser action approval is required."
    if result.status in {"blocked", "unsupported", "ambiguous"}:
        return "Playwright browser action execution was blocked."
    if result.status == "failed":
        return "Playwright browser action execution failed."
    if result.status in {"verified_supported", "verified_unsupported", "partial", "completed_unverified"}:
        return "Playwright browser action verification completed."
    return "Playwright browser action execution state updated."


def _approval_hint(preview: BrowserSemanticActionPreview) -> str:
    if preview.preview_state == "blocked":
        return "Future execution is blocked for this target until a later trust policy exists."
    if preview.risk_level == "high":
        return "Future execution would require explicit approval and strong confirmation."
    return "Future execution would require approval."


def _preview_user_message(preview: BrowserSemanticActionPreview) -> str:
    if preview.preview_state == "ambiguous":
        return "Target is ambiguous. Execution is not enabled yet."
    if preview.preview_state == "blocked":
        return "That browser action is blocked in this scaffold. Execution is not enabled yet."
    if preview.preview_state == "unsupported":
        return "That browser action preview is unsupported. Execution is not enabled yet."
    return "Action preview ready. Execution is not enabled yet."


def _action_preview_summary(
    preview: BrowserSemanticActionPreview,
    *,
    plan: BrowserSemanticActionPlan | None = None,
) -> dict[str, Any]:
    summary = {
        "preview_id": preview.preview_id,
        "observation_id": preview.observation_id,
        "source_provider": preview.source_provider,
        "target_phrase": _bounded_text(preview.target_phrase, 120),
        "target_candidate_id": preview.target_candidate_id,
        "target_role": preview.target_role,
        "target_name": _bounded_text(preview.target_name, 80),
        "action_kind": preview.action_kind,
        "preview_state": preview.preview_state,
        "action_supported_now": bool(preview.action_supported_now or preview.action_supported),
        "executable_now": bool(preview.executable_now),
        "reason_not_executable": preview.reason_not_executable,
        "confidence": round(float(preview.confidence or 0.0), 3),
        "risk_level": preview.risk_level,
        "approval_required": preview.approval_required,
        "required_trust_scope": preview.required_trust_scope,
        "expected_outcome": list(preview.expected_outcome)[:8],
        "verification_strategy": preview.verification_strategy,
        "claim_ceiling": preview.claim_ceiling,
        "limitations": list(preview.limitations)[:8],
        "user_message": _preview_user_message(preview),
    }
    if plan is not None:
        summary.update(
            {
                "plan_id": plan.plan_id,
                "result_state": plan.result_state,
                "adapter_capability_required": plan.adapter_capability_required,
                "adapter_capability_declared": plan.adapter_capability_declared,
                "executable_now": plan.executable_now,
            }
        )
    return summary


def _change_summary(change: BrowserSemanticChange) -> dict[str, Any]:
    return {
        "change_type": change.change_type,
        "before_summary": _bounded_text(change.before_summary, 120),
        "after_summary": _bounded_text(change.after_summary, 120),
        "role": change.role,
        "name": change.name,
        "confidence": round(float(change.confidence or 0.0), 3),
        "evidence_terms": list(change.evidence_terms)[:6],
        "sensitive_redacted": change.sensitive_redacted,
    }


def _match_controls(
    before_controls: Sequence[BrowserSemanticControl],
    after_controls: Sequence[BrowserSemanticControl],
) -> tuple[list[tuple[BrowserSemanticControl, BrowserSemanticControl]], list[BrowserSemanticControl], list[BrowserSemanticControl]]:
    unmatched_after = list(after_controls)
    matched: list[tuple[BrowserSemanticControl, BrowserSemanticControl]] = []
    removed: list[BrowserSemanticControl] = []
    after_by_id = {control.control_id: control for control in unmatched_after if control.control_id}
    for before_control in before_controls:
        after_control = after_by_id.get(before_control.control_id)
        if after_control is None:
            after_control = _pop_unique_semantic_match(before_control, unmatched_after)
        if after_control is not None:
            matched.append((before_control, after_control))
            if after_control in unmatched_after:
                unmatched_after.remove(after_control)
        else:
            removed.append(before_control)
    return matched, removed, unmatched_after


def _pop_unique_semantic_match(before_control: BrowserSemanticControl, after_controls: Sequence[BrowserSemanticControl]) -> BrowserSemanticControl | None:
    key = _control_semantic_key(before_control)
    matches = [control for control in after_controls if _control_semantic_key(control) == key]
    return matches[0] if len(matches) == 1 else None


def _control_semantic_key(control: BrowserSemanticControl) -> str:
    return "|".join([_canonical_role(control.role), _normalize(control.label or control.name or control.text)])


def _control_text_tuple(control: BrowserSemanticControl) -> tuple[str, str, str]:
    return (_normalize(control.name), _normalize(control.label), _normalize(control.text))


def _control_public_summary(control: BrowserSemanticControl) -> str:
    label = _control_label(control)
    role = _canonical_role(control.role)
    pieces = [
        f"{label} {role}".strip(),
        f"enabled={control.enabled}" if control.enabled is not None else "",
        f"required={control.required}" if control.required is not None else "",
        f"checked={control.checked}" if control.checked is not None else "",
        f"readonly={control.readonly}" if control.readonly is not None else "",
        f"value={_safe_value_summary(control)}" if control.value_summary else "",
    ]
    return _bounded_text("; ".join(piece for piece in pieces if piece), 160)


def _safe_value_summary(control: BrowserSemanticControl) -> str:
    if _is_sensitive_control(control):
        return "[redacted sensitive field]"
    if _looks_like_secret(control.value_summary):
        return "[redacted value]"
    return _bounded_text(control.value_summary, 80)


def _is_sensitive_control(control: BrowserSemanticControl) -> bool:
    return "sensitive" in _normalize(control.risk_hint) or _looks_like_secret(" ".join([control.name, control.label, control.value_summary]))


def _redacted_summary(value: str, *, sensitive: bool) -> str:
    if sensitive:
        return "[redacted sensitive field]"
    text = _bounded_text(value, 160)
    if _looks_like_secret(text):
        return "[redacted value]"
    return text


def _dialog_map(observation: BrowserSemanticObservation) -> dict[str, dict[str, Any]]:
    items = {}
    for item in list(observation.dialogs) + list(observation.alerts):
        if not isinstance(item, dict):
            continue
        key = _normalize(item.get("name") or item.get("text") or item.get("dialog_id") or item.get("alert_id"))
        if key:
            items[key] = dict(item)
    return items


def _dialog_summary(item: dict[str, Any]) -> str:
    return _bounded_text(item.get("name") or item.get("text") or item.get("dialog_id") or item.get("alert_id") or "dialog", 120)


def _form_signature(forms: Sequence[dict[str, Any]]) -> str:
    pieces = []
    for form in forms[:_LIST_LIMIT]:
        if not isinstance(form, dict):
            continue
        pieces.append(
            "|".join(
                [
                    _bounded_text(form.get("form_id") or form.get("name") or "", 80),
                    _bounded_text(form.get("summary") or "", 80),
                    str(_safe_int(form.get("field_count"), default=0)),
                    str(bool(form.get("inferred"))),
                ]
            )
        )
    return "; ".join(pieces)


def _control_label(control: BrowserSemanticControl) -> str:
    return _bounded_text(control.label or control.name or control.text or control.role or "control", 80)


def _default_mock_context() -> dict[str, Any]:
    return {
        "session_id": "playwright-mock-session",
        "page_url": "https://example.test/checkout",
        "page_title": "Example Checkout",
        "controls": [
            {"control_id": "button-continue", "role": "button", "name": "Continue", "visible": True, "enabled": True},
            {"control_id": "textbox-email", "role": "textbox", "label": "Email", "visible": True, "enabled": True},
            {"control_id": "checkbox-agree", "role": "checkbox", "label": "I agree", "visible": True, "enabled": True},
            {"control_id": "link-privacy", "role": "link", "name": "Privacy Policy", "visible": True, "enabled": True},
        ],
        "text_regions": [{"text": "Example checkout"}],
        "forms": [{"name": "checkout", "field_count": 1}],
        "dialogs": [{"dialog_id": "dialog-session-expired", "role": "alert", "text": "Session expired"}],
        "alerts": [{"alert_id": "alert-session-expired", "text": "Session expired"}],
    }
