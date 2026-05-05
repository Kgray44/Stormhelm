from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from datetime import datetime
from importlib.util import find_spec
import hashlib
import ipaddress
import json
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
    BrowserSemanticTaskExecutionResult,
    BrowserSemanticTaskPlan,
    BrowserSemanticTaskStep,
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
_TASK_PLAN_CLAIM_CEILING = "browser_semantic_task_plan"
_TASK_EXECUTION_CLAIM_CEILING = "browser_semantic_task_execution"
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
    const options = tag === 'select' ? Array.from(element.options).slice(0, 40).map((option, optionIndex) => ({
        label: (option.label || option.textContent || '').trim(),
        value_summary: option.value ? `[option value, ${String(option.value).length} chars]` : '',
        selected: option.selected === true,
        disabled: option.disabled === true,
        ordinal: optionIndex + 1
    })) : [];
    const selectedOption = tag === 'select' ? options.find(option => option.selected) : null;
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
        value_summary: sensitive ? '[redacted sensitive field]' : selectedOption ? `selected option: ${selectedOption.label}` : hasValue ? '[redacted value]' : '',
        options,
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
    _last_task_execution_summary: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

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

    @property
    def last_task_execution_summary(self) -> dict[str, Any]:
        return dict(self._last_task_execution_summary)

    def adapter_semantics_payload(self, observation: BrowserSemanticObservation) -> dict[str, Any]:
        """Convert a Playwright semantic observation into the canonical browser adapter payload."""
        return _adapter_semantics_payload(observation)

    def status_snapshot(self) -> dict[str, Any]:
        readiness = self.get_readiness(emit_event=False).to_dict()
        declared_action_capabilities = _declared_action_capabilities(self.config, readiness)
        forbidden_action_capabilities = [
            capability
            for capability in [
                "browser.input.type",
                "browser.input.type_text",
                "browser.input.check",
                "browser.input.uncheck",
                "browser.input.select_option",
                "browser.input.scroll",
                "browser.input.scroll_to_target",
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
            ]
            if capability not in declared_action_capabilities
        ]
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
                "type_text_enabled": "browser.input.type_text" in declared_action_capabilities,
                "check_enabled": "browser.input.check" in declared_action_capabilities,
                "uncheck_enabled": "browser.input.uncheck" in declared_action_capabilities,
                "select_option_enabled": "browser.input.select_option" in declared_action_capabilities,
                "scroll_enabled": "browser.input.scroll" in declared_action_capabilities,
                "scroll_to_target_enabled": "browser.input.scroll_to_target" in declared_action_capabilities,
                "task_plans_enabled": "browser.task.safe_sequence" in declared_action_capabilities,
                "declared_action_capabilities": declared_action_capabilities,
                "forbidden_action_capabilities": forbidden_action_capabilities,
                "last_observation_summary": self.last_observation_summary,
                "last_grounding_summary": self.last_grounding_summary,
                "last_verification_summary": self.last_verification_summary,
                "last_action_preview_summary": self.last_action_preview_summary,
                "last_action_execution_summary": self.last_action_execution_summary,
                "last_task_execution_summary": self.last_task_execution_summary,
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
        elif not candidates and action_kind not in {"scroll", "scroll_to_target"}:
            preview = _action_preview_from_state(
                observation,
                target_phrase=target_phrase,
                action_kind=action_kind,
                state="unsupported",
                reason="target_not_grounded",
            )
        elif candidates and candidates[0].match_reason == "closest_match" and action_kind not in {"scroll", "scroll_to_target"}:
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
            candidate = _page_scroll_candidate(target_phrase, observation) if action_kind in {"scroll", "scroll_to_target"} else candidates[0]
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

    def build_semantic_task_plan(
        self,
        observation: BrowserSemanticObservation,
        *,
        task_phrase: str = "",
        steps: Sequence[dict[str, Any]] | None = None,
        expected_final_state: Sequence[str] | None = None,
    ) -> BrowserSemanticTaskPlan:
        max_steps = max(1, int(getattr(self.config, "max_task_steps", 5) or 5))
        stop_policy = _task_stop_policy_from_config(self.config)
        task_plan = BrowserSemanticTaskPlan(
            source_observation_id=observation.observation_id,
            provider="playwright_live_semantic",
            max_steps=max_steps,
            expected_final_state=[_bounded_text(item, 160) for item in list(expected_final_state or [])[:8]],
            stop_policy=stop_policy,
            source_task_phrase=_bounded_text(task_phrase, 240),
            limitations=[
                "approval_required",
                "isolated_temporary_browser_context",
                "safe_primitives_only",
                "no_form_submit",
                "no_user_profile",
                "not_visible_screen_verification",
                "not_truth_verified",
            ],
        )
        raw_steps = list(steps or [])
        if not raw_steps:
            task_plan.reason_not_executable = "explicit_steps_required"
            task_plan.limitations = list(dict.fromkeys(task_plan.limitations + ["explicit_steps_required"]))
            task_plan.user_message = "A safe browser task plan needs explicit supported steps."
            self._last_task_execution_summary = _task_plan_summary(task_plan)
            self._publish("screen_awareness.playwright_task_plan_created", "Playwright safe browser task plan created.", _task_plan_event_payload(task_plan))
            return task_plan
        if len(raw_steps) > max_steps:
            raw_steps = raw_steps[:max_steps]
            task_plan.reason_not_executable = "max_steps_exceeded"
            task_plan.limitations = list(dict.fromkeys(task_plan.limitations + ["max_steps_exceeded"]))
        built_steps: list[BrowserSemanticTaskStep] = []
        for index, spec in enumerate(raw_steps, start=1):
            action_kind = _bounded_text(spec.get("action_kind") or "", 40)
            target_phrase = _bounded_text(spec.get("target_phrase") or spec.get("target") or "", 120)
            action_phrase = _bounded_text(spec.get("action_phrase") or action_kind.replace("_", " "), 160)
            action_arguments = dict(spec.get("action_arguments") or {})
            expected_outcome = [
                _bounded_text(item, 80)
                for item in list(spec.get("expected_outcome") or _expected_outcomes_for_action(action_kind))[:8]
                if _bounded_text(item, 80)
            ]
            step_limitations: list[str] = []
            if action_kind not in _SAFE_TASK_ACTION_KINDS:
                step = BrowserSemanticTaskStep(
                    step_index=index,
                    action_kind=action_kind or "unsupported",
                    target_phrase=target_phrase,
                    action_args_redacted=_redacted_task_step_args(action_kind, action_arguments),
                    expected_outcome=expected_outcome,
                    required_capability=_action_capability_required(action_kind),
                    status="blocked",
                    limitations=["unsupported_step", "no_action_attempted"],
                )
                step.approval_binding_fingerprint = _task_step_binding_fingerprint(step)
                built_steps.append(step)
                task_plan.reason_not_executable = task_plan.reason_not_executable or "unsupported_step"
                continue
            preview = self.preview_semantic_action(
                observation,
                target_phrase=target_phrase,
                action_phrase=action_phrase,
                action_arguments=action_arguments,
            )
            action_plan = self.build_semantic_action_plan(preview, action_arguments=action_arguments)
            if action_plan.action_kind != action_kind:
                step_limitations.append("action_kind_mismatch")
            if action_plan.result_state in {"blocked", "unsupported", "ambiguous"}:
                step_limitations.extend(list(action_plan.limitations)[:4])
            target = dict(action_plan.target_candidate or {})
            step_status = "blocked" if step_limitations or action_plan.result_state in {"blocked", "unsupported", "ambiguous"} else "pending"
            step = BrowserSemanticTaskStep(
                step_index=index,
                action_kind=action_plan.action_kind,
                target_phrase=target_phrase,
                target_candidate_id=_bounded_text(target.get("candidate_id") or "", 80),
                target_fingerprint=_target_fingerprint(target),
                action_args_redacted=dict(action_plan.action_arguments_redacted or {}),
                action_arguments_private=dict(action_plan.action_arguments_private or {}),
                expected_outcome=expected_outcome or _expected_outcomes_for_action(action_plan.action_kind),
                required_capability=action_plan.adapter_capability_required,
                status=step_status,
                limitations=list(dict.fromkeys(step_limitations)),
                action_plan_private=action_plan,
            )
            step.approval_binding_fingerprint = _task_step_binding_fingerprint(step)
            built_steps.append(step)
            if step_status == "blocked":
                task_plan.reason_not_executable = task_plan.reason_not_executable or "unsafe_task_step"
        task_plan.steps = built_steps
        task_plan.risk_level = _task_risk_level(built_steps)
        task_plan.stop_policy = _task_stop_policy_with_approval_bindings(task_plan.stop_policy, built_steps)
        task_plan.approval_binding_fingerprint = _task_plan_binding_fingerprint(task_plan)
        if any(step.status == "blocked" for step in built_steps):
            task_plan.executable_now = False
            task_plan.reason_not_executable = task_plan.reason_not_executable or "unsafe_task_step"
            task_plan.user_message = "This safe browser task plan contains a blocked or unsupported step."
        else:
            task_plan.executable_now = False
            task_plan.reason_not_executable = "approval_required"
            task_plan.user_message = "Plan ready; approval required."
        self._last_task_execution_summary = _task_plan_summary(task_plan)
        self._publish(
            "screen_awareness.playwright_task_plan_created",
            "Playwright safe browser task plan created.",
            _task_plan_event_payload(task_plan),
        )
        return task_plan

    def request_semantic_task_execution(
        self,
        plan: BrowserSemanticTaskPlan | dict[str, Any],
        *,
        url: str,
        trust_service: Any | None = None,
        session_id: str = "default",
        task_id: str = "",
        fixture_mode: bool = False,
        context_options: dict[str, Any] | None = None,
    ) -> BrowserSemanticTaskExecutionResult:
        return self.execute_semantic_task_plan(
            plan,
            url=url,
            trust_service=trust_service,
            session_id=session_id,
            task_id=task_id,
            fixture_mode=fixture_mode,
            context_options=context_options,
            require_only=True,
        )

    def execute_semantic_task_plan(
        self,
        plan: BrowserSemanticTaskPlan | dict[str, Any],
        *,
        url: str,
        trust_service: Any | None = None,
        session_id: str = "default",
        task_id: str = "",
        fixture_mode: bool = False,
        context_options: dict[str, Any] | None = None,
        require_only: bool = False,
    ) -> BrowserSemanticTaskExecutionResult:
        plan_model = _coerce_task_plan(plan)
        self._publish(
            "screen_awareness.playwright_task_execution_started" if not require_only else "screen_awareness.playwright_task_plan_approval_required",
            "Playwright safe browser task execution requested.",
            _task_plan_event_payload(plan_model, status="requested"),
        )
        gate_result = self._task_plan_gate_result(plan_model)
        if gate_result is not None:
            return self._finalize_task_execution(
                gate_result,
                event_type="screen_awareness.playwright_task_step_blocked",
                severity=EventSeverity.WARNING,
            )
        action_request = _trust_task_plan_request(plan_model, session_id=session_id, task_id=task_id)
        if trust_service is None:
            result = _task_execution_result(
                plan_model,
                status="approval_required",
                trust_request_id=action_request.request_id,
                user_message="Approval is required before this safe browser task plan can run.",
                limitations=["approval_required", "trust_service_required", "no_action_attempted"],
            )
            return self._finalize_task_execution(result, event_type="screen_awareness.playwright_task_plan_approval_required")
        trust_decision = trust_service.evaluate_action(action_request)
        if trust_decision.outcome != TrustDecisionOutcome.ALLOWED:
            approval_request = trust_decision.approval_request
            blocked_by_operator = trust_decision.outcome == TrustDecisionOutcome.BLOCKED
            result = _task_execution_result(
                plan_model,
                status="blocked" if blocked_by_operator else "approval_required",
                trust_request_id=action_request.request_id,
                approval_request_id=approval_request.approval_request_id if approval_request is not None else "",
                failure_reason="approval_denied" if blocked_by_operator else "",
                user_message=trust_decision.operator_message or "Approval is required before this safe browser task plan can run.",
                limitations=[("approval_denied" if blocked_by_operator else "approval_required"), "no_action_attempted"],
            )
            return self._finalize_task_execution(
                result,
                event_type=(
                    "screen_awareness.playwright_task_step_blocked"
                    if blocked_by_operator
                    else "screen_awareness.playwright_task_plan_approval_required"
                ),
                severity=EventSeverity.WARNING if blocked_by_operator else EventSeverity.INFO,
            )
        if require_only:
            result = _task_execution_result(
                plan_model,
                status="running",
                trust_request_id=action_request.request_id,
                approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                user_message="Approval is available for this safe browser task plan.",
                limitations=["approval_available", "task_not_attempted"],
            )
            return self._finalize_task_execution(result, event_type="")

        browser = None
        context = None
        cleanup_status = "not_started"
        cleanup_error: Exception | None = None
        step_results: list[BrowserSemanticActionExecutionResult] = []
        final_status = "failed"
        final_verification_status = ""
        blocked_step_id = ""
        failure_reason = ""
        final_result: BrowserSemanticTaskExecutionResult | None = None
        try:
            readiness = self.get_readiness(emit_event=False)
            launch_blocker = _live_launch_blocker(self.config, readiness)
            url_blocker = _live_url_blocker(url, fixture_mode=fixture_mode)
            if launch_blocker or url_blocker:
                result = _task_execution_result(
                    plan_model,
                    status="blocked",
                    trust_request_id=action_request.request_id,
                    approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                    failure_reason=launch_blocker or url_blocker,
                    user_message="That safe browser task plan is not available under the current Playwright gates.",
                    limitations=["launch_or_url_blocked", launch_blocker or url_blocker, "no_action_attempted"],
                )
                final_result = self._finalize_task_execution(result, event_type="screen_awareness.playwright_task_step_blocked")
                return final_result
            self._publish(
                "screen_awareness.playwright_task_execution_started",
                "Trust-gated Playwright safe browser task execution started.",
                _task_plan_event_payload(plan_model, status="running"),
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
                    for step_position, step in enumerate(plan_model.steps):
                        self._publish(
                            "screen_awareness.playwright_task_step_started",
                            "Playwright safe browser task step started.",
                            _task_step_event_payload(plan_model, step, status="executing"),
                        )
                        before = _live_observation_from_page(
                            page,
                            adapter_id=self.adapter_id,
                            session_id=f"playwright-task-before-{uuid4().hex[:10]}",
                        )
                        step_result = self._execute_task_step_on_page(
                            step,
                            page=page,
                            before=before,
                            session_id=session_id,
                            task_id=task_id,
                            trust_request_id=action_request.request_id,
                            approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                            trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                        )
                        step.status = step_result.status
                        step.verification_result_id = step_result.comparison_result_id
                        step_results.append(step_result)
                        event_type = (
                            "screen_awareness.playwright_task_step_failed"
                            if step_result.status == "failed"
                            else "screen_awareness.playwright_task_step_blocked"
                            if step_result.status in {"blocked", "unsupported", "ambiguous"}
                            else "screen_awareness.playwright_task_step_completed"
                        )
                        self._publish(
                            event_type,
                            "Playwright safe browser task step completed.",
                            _task_step_event_payload(plan_model, step, result=step_result, status=step_result.status),
                            severity=EventSeverity.WARNING if event_type != "screen_awareness.playwright_task_step_completed" else EventSeverity.INFO,
                        )
                        stop_status = _task_stop_status(step_result, self.config)
                        if stop_status:
                            final_status = stop_status
                            final_verification_status = step_result.verification_status or step_result.status
                            blocked_step_id = step.step_id
                            failure_reason = step_result.error_code or step_result.status
                            self._publish(
                                "screen_awareness.playwright_task_stopped",
                                "Playwright safe browser task plan stopped before later steps.",
                                _task_step_event_payload(plan_model, step, result=step_result, status=final_status),
                                severity=EventSeverity.WARNING,
                            )
                            for skipped_step in _mark_task_steps_skipped(plan_model, start_index=step_position + 1):
                                self._publish(
                                    "screen_awareness.playwright_task_step_skipped",
                                    "Playwright safe browser task step skipped after prior stop.",
                                    _task_step_event_payload(plan_model, skipped_step, status="skipped"),
                                    severity=EventSeverity.INFO,
                                )
                            break
                    if not final_verification_status:
                        final_verification_status = "supported" if all(item.status == "verified_supported" for item in step_results) else "partial"
                    if final_status == "failed":
                        final_status = "completed_verified" if final_verification_status == "supported" else "completed_partial"
                    if step_results:
                        trust_service.mark_action_executed(
                            action_request=action_request,
                            grant=trust_decision.grant,
                            summary=f"Executed Playwright safe browser task plan with {len(step_results)} attempted step(s).",
                            details={
                                "plan_id": plan_model.plan_id,
                                "step_count": len(plan_model.steps),
                                "completed_step_count": len(step_results),
                                "final_status": final_status,
                                "claim_ceiling": _TASK_EXECUTION_CLAIM_CEILING,
                                "steps": [_task_step_audit_summary(step, result) for step, result in zip(plan_model.steps, step_results)],
                            },
                        )
                    final_result = _task_execution_result(
                        plan_model,
                        status=final_status,
                        step_results=step_results,
                        completed_step_count=len(step_results),
                        blocked_step_id=blocked_step_id,
                        failure_reason=failure_reason,
                        final_verification_status=final_verification_status,
                        action_attempted=any(item.action_attempted for item in step_results),
                        trust_request_id=action_request.request_id,
                        approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                        limitations=_task_execution_limitations(step_results, extra=["safe_browser_sequence", "no_form_submit"]),
                    )
                    self._publish(
                        "screen_awareness.playwright_task_final_verification_completed",
                        "Playwright safe browser task final verification completed.",
                        _task_execution_event_payload(final_result),
                        severity=EventSeverity.WARNING if final_status != "completed_verified" else EventSeverity.INFO,
                    )
                    return self._finalize_task_execution(final_result, event_type="")
                finally:
                    cleanup_status, cleanup_error = self._cleanup_isolated_browser_resources(
                        context,
                        browser,
                        claim_ceiling=_TASK_EXECUTION_CLAIM_CEILING,
                        completed_message="Playwright isolated browser task cleanup completed.",
                        completed_limitations=["no_user_profile", "no_cookies_persisted"],
                        failed_limitations=["cleanup_failed", "no_user_profile", "no_cookies_persisted"],
                    )
                    context = None
                    browser = None
        except Exception as exc:
            result = _task_execution_result(
                plan_model,
                status="failed",
                step_results=step_results,
                completed_step_count=len(step_results),
                failure_reason=_live_error_code(exc),
                final_verification_status="failed",
                action_attempted=any(item.action_attempted for item in step_results),
                trust_request_id=action_request.request_id,
                approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                user_message="The safe browser task plan failed before Stormhelm could produce a bounded verified result.",
                limitations=["task_execution_failed", "isolated_temporary_browser_context"],
            )
            final_result = self._finalize_task_execution(
                result,
                event_type="screen_awareness.playwright_task_step_failed",
                severity=EventSeverity.WARNING,
            )
            return final_result
        finally:
            if cleanup_status == "not_started" and (context is not None or browser is not None):
                cleanup_status, cleanup_error = self._cleanup_isolated_browser_resources(
                    context,
                    browser,
                    claim_ceiling=_TASK_EXECUTION_CLAIM_CEILING,
                    completed_message="Playwright isolated browser task cleanup completed.",
                    completed_limitations=["no_user_profile", "no_cookies_persisted"],
                    failed_limitations=["cleanup_failed", "no_user_profile", "no_cookies_persisted"],
                )
            if final_result is not None:
                final_result.cleanup_status = cleanup_status
                if cleanup_error is not None:
                    final_result.limitations = list(dict.fromkeys(list(final_result.limitations) + ["cleanup_failed"]))
                    final_result.failure_reason = final_result.failure_reason or "cleanup_failed"
                self._last_task_execution_summary = _task_execution_summary(final_result)
                self._publish(
                    "screen_awareness.playwright_task_cleanup_completed",
                    "Playwright safe browser task cleanup completed.",
                    _task_execution_event_payload(final_result),
                    severity=EventSeverity.WARNING if cleanup_error is not None else EventSeverity.INFO,
                )

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
            _action_event_type(
                plan_model.action_kind,
                "screen_awareness.playwright_action_execution_requested",
                "screen_awareness.playwright_type_request_created",
            ),
            "Playwright browser action execution requested.",
            _execution_event_payload(request, plan_model, status="requested"),
        )

        gate_result = self._execution_gate_result(request, plan_model)
        if gate_result is not None:
            return self._finalize_action_execution(
                gate_result,
                event_type=_action_event_type(
                    plan_model.action_kind,
                    "screen_awareness.playwright_action_execution_blocked",
                    "screen_awareness.playwright_type_blocked",
                ),
            )

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
            return self._finalize_action_execution(
                result,
                event_type=_action_event_type(
                    plan_model.action_kind,
                    "screen_awareness.playwright_action_approval_required",
                    "screen_awareness.playwright_type_approval_required",
                ),
            )

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
                    _action_event_type(
                        plan_model.action_kind,
                        "screen_awareness.playwright_action_execution_blocked",
                        "screen_awareness.playwright_type_blocked",
                    )
                    if blocked_by_operator
                    else _action_event_type(
                        plan_model.action_kind,
                        "screen_awareness.playwright_action_approval_required",
                        "screen_awareness.playwright_type_approval_required",
                    )
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
                final_result = self._finalize_action_execution(
                    result,
                    event_type=_action_event_type(
                        plan_model.action_kind,
                        "screen_awareness.playwright_action_execution_blocked",
                        "screen_awareness.playwright_type_blocked",
                    ),
                )
                return final_result

            self._publish(
                _action_event_type(
                    plan_model.action_kind,
                    "screen_awareness.playwright_action_execution_started",
                    "screen_awareness.playwright_type_execution_started",
                ),
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
                    action_context_blocker = _action_context_blocker(before, plan_model.action_kind)
                    if action_context_blocker and plan_model.action_kind not in {"scroll", "scroll_to_target"}:
                        result = _execution_result(
                            request,
                            plan_model,
                            status="blocked",
                            trust_request_id=action_request.request_id,
                            approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                            trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                            before_observation_id=before.observation_id,
                            error_code=action_context_blocker,
                            user_message="Browser action blocked: page appears sensitive or restricted.",
                            limitations=["sensitive_page_context", action_context_blocker, "no_action_attempted"],
                        )
                        final_result = self._finalize_action_execution(
                            result,
                            event_type=_action_event_type(
                                plan_model.action_kind,
                                "screen_awareness.playwright_action_execution_blocked",
                                "screen_awareness.playwright_type_blocked",
                            ),
                            severity=EventSeverity.WARNING,
                        )
                        return final_result
                    if plan_model.action_kind in {"scroll", "scroll_to_target"}:
                        scroll_context_blocker = _scroll_context_blocker(before)
                        if scroll_context_blocker:
                            result = _execution_result(
                                request,
                                plan_model,
                                status="blocked",
                                trust_request_id=action_request.request_id,
                                approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                                trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                                before_observation_id=before.observation_id,
                                error_code=scroll_context_blocker,
                                user_message="Scroll blocked: page appears sensitive or restricted.",
                                limitations=["scroll_blocked", scroll_context_blocker, "no_action_attempted"],
                            )
                            final_result = self._finalize_action_execution(
                                result,
                                event_type="screen_awareness.playwright_scroll_blocked",
                            )
                            return final_result
                        submit_count_before = _safe_submit_counter(page)
                        scroll_before = _safe_scroll_state(page)
                        scroll_details = _scroll_details_from_plan(plan_model, request)
                        target_phrase = _bounded_text(scroll_details.get("target_phrase") or request.scroll_target_phrase or plan_model.target_candidate.get("name") or "", 120)
                        if plan_model.action_kind == "scroll_to_target":
                            target_match, target_blocker = _scroll_target_match(before, target_phrase)
                            if target_blocker == "target_ambiguous":
                                result = _execution_result(
                                    request,
                                    plan_model,
                                    status="ambiguous",
                                    trust_request_id=action_request.request_id,
                                    approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                                    trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                                    before_observation_id=before.observation_id,
                                    error_code=target_blocker,
                                    user_message="Scroll blocked: the requested target is ambiguous.",
                                    limitations=["target_ambiguous", "no_action_attempted"],
                                )
                                final_result = self._finalize_action_execution(result, event_type="screen_awareness.playwright_scroll_blocked")
                                return final_result
                            if target_blocker == "target_sensitive":
                                result = _execution_result(
                                    request,
                                    plan_model,
                                    status="blocked",
                                    trust_request_id=action_request.request_id,
                                    approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                                    trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                                    before_observation_id=before.observation_id,
                                    error_code=target_blocker,
                                    user_message="Scroll blocked: target appears sensitive.",
                                    limitations=["target_sensitive", "no_action_attempted"],
                                )
                                final_result = self._finalize_action_execution(result, event_type="screen_awareness.playwright_scroll_blocked")
                                return final_result
                            if target_match is not None:
                                trust_service.mark_action_executed(
                                    action_request=action_request,
                                    grant=trust_decision.grant,
                                    summary=f"No-op Playwright scroll_to_target; target {target_phrase or target_match.get('name') or 'target'} was already present.",
                                    details={
                                        "plan_id": plan_model.plan_id,
                                        "preview_id": plan_model.preview_id,
                                        "action_kind": plan_model.action_kind,
                                        "claim_ceiling": _ACTION_EXECUTION_CLAIM_CEILING,
                                        "target_phrase": target_phrase,
                                        "already_in_expected_state": True,
                                    },
                                )
                                result = _execution_result(
                                    request,
                                    plan_model,
                                    status="verified_supported",
                                    action_attempted=False,
                                    action_completed=False,
                                    verification_attempted=True,
                                    verification_status="supported",
                                    before_observation_id=before.observation_id,
                                    after_observation_id=before.observation_id,
                                    trust_request_id=action_request.request_id,
                                    approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                                    trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                                    user_message="Scroll target was already present; no browser scroll was issued.",
                                    limitations=[
                                        "target_found",
                                        "already_in_expected_state",
                                        "no_action_needed",
                                        "isolated_temporary_browser_context",
                                        "not_visible_screen_verification",
                                        "not_truth_verified",
                                    ],
                                )
                                self._publish(
                                    "screen_awareness.playwright_scroll_target_found",
                                    "Playwright scroll target was already present.",
                                    _execution_event_payload(request, plan_model, status="target_found", target=target_match),
                                )
                                final_result = self._finalize_action_execution(
                                    result,
                                    event_type="screen_awareness.playwright_scroll_no_op_supported",
                                )
                                return final_result

                        self._publish(
                            "screen_awareness.playwright_scroll_execution_started",
                            "Trust-gated Playwright scroll execution started.",
                            _execution_event_payload(request, plan_model, status="executing"),
                        )
                        observed_after_attempt: BrowserSemanticObservation | None = None
                        target_found = False
                        target_ambiguous = False
                        target_sensitive = False
                        attempts = 1 if plan_model.action_kind == "scroll" else int(scroll_details.get("max_attempts") or 1)
                        for _attempt_index in range(attempts):
                            _perform_scroll(page, str(scroll_details.get("direction") or "down"), int(scroll_details.get("amount_pixels") or 700))
                            action_completed = True
                            self._publish(
                                "screen_awareness.playwright_scroll_attempted",
                                "Playwright browser scroll command was issued.",
                                _execution_event_payload(request, plan_model, status="attempted"),
                            )
                            _wait_for_semantic_stabilization(page)
                            observed_after_attempt = _live_observation_from_page(
                                page,
                                adapter_id=self.adapter_id,
                                session_id=f"playwright-action-scroll-{uuid4().hex[:10]}",
                            )
                            if plan_model.action_kind == "scroll_to_target":
                                target_match, target_blocker = _scroll_target_match(observed_after_attempt, target_phrase)
                                if target_blocker == "target_ambiguous":
                                    target_ambiguous = True
                                    break
                                if target_blocker == "target_sensitive":
                                    target_sensitive = True
                                    break
                                if target_match is not None:
                                    target_found = True
                                    self._publish(
                                        "screen_awareness.playwright_scroll_target_found",
                                        "Playwright scroll target found within bounded attempts.",
                                        _execution_event_payload(request, plan_model, status="target_found", target=target_match),
                                    )
                                    break
                            if plan_model.action_kind == "scroll":
                                break
                        trust_service.mark_action_executed(
                            action_request=action_request,
                            grant=trust_decision.grant,
                            summary=f"Attempted Playwright {plan_model.action_kind} with bounded scroll.",
                            details={
                                "plan_id": plan_model.plan_id,
                                "preview_id": plan_model.preview_id,
                                "action_kind": plan_model.action_kind,
                                "claim_ceiling": _ACTION_EXECUTION_CLAIM_CEILING,
                                "scroll_direction": request.scroll_direction,
                                "scroll_amount_pixels": request.scroll_amount_pixels,
                                "scroll_max_attempts": request.scroll_max_attempts,
                                "scroll_target_phrase": request.scroll_target_phrase,
                            },
                        )
                        after = observed_after_attempt
                        if after is None:
                            after = _live_observation_from_page(
                                page,
                                adapter_id=self.adapter_id,
                                session_id=f"playwright-action-after-{uuid4().hex[:10]}",
                            )
                        submit_count_after = _safe_submit_counter(page)
                        self._publish(
                            "screen_awareness.playwright_scroll_after_observation_captured",
                            "Playwright browser scroll after-observation captured.",
                            _execution_event_payload(request, plan_model, status="after_observation_captured"),
                        )
                        if _submit_counter_changed(submit_count_before, submit_count_after):
                            result = _execution_result(
                                request,
                                plan_model,
                                status="failed",
                                action_attempted=True,
                                action_completed=action_completed,
                                verification_attempted=True,
                                verification_status="failed",
                                before_observation_id=before.observation_id,
                                after_observation_id=after.observation_id,
                                trust_request_id=action_request.request_id,
                                approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                                trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                                error_code="unexpected_form_submission",
                                user_message="Scroll changed a fixture submit counter, so Stormhelm is not treating it as successful.",
                                limitations=["unexpected_form_submission", "submit_prevention_failed", "not_visible_screen_verification", "not_truth_verified"],
                            )
                            final_result = self._finalize_action_execution(result, event_type="screen_awareness.playwright_scroll_verification_completed", severity=EventSeverity.WARNING)
                            return final_result
                        scroll_after = _safe_scroll_state(page)
                        comparison = _best_action_comparison(self, before, after, plan_model)
                        status, verification_status, user_message = _scroll_execution_status(
                            plan_model,
                            comparison,
                            scroll_before,
                            scroll_after,
                            target_found=target_found,
                            target_ambiguous=target_ambiguous,
                            target_sensitive=target_sensitive,
                        )
                        error_code = ""
                        if target_ambiguous:
                            error_code = "target_ambiguous"
                            self._publish(
                                "screen_awareness.playwright_scroll_target_not_found",
                                "Playwright scroll target became ambiguous.",
                                _execution_event_payload(request, plan_model, status="target_ambiguous"),
                                severity=EventSeverity.WARNING,
                            )
                        elif target_sensitive:
                            error_code = "target_sensitive"
                        elif plan_model.action_kind == "scroll_to_target" and not target_found:
                            error_code = "target_not_found"
                            self._publish(
                                "screen_awareness.playwright_scroll_target_not_found",
                                "Playwright scroll target was not found within bounded attempts.",
                                _execution_event_payload(request, plan_model, status="target_not_found"),
                                severity=EventSeverity.WARNING,
                            )
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
                            error_code=error_code,
                            user_message=user_message,
                            limitations=_action_execution_limitations(
                                list(comparison.limitations if comparison is not None else ["comparison_unavailable"])
                                + [
                                    "scroll_bounds_enforced",
                                    "side_effects_prevented",
                                    "target_found" if target_found else "",
                                    error_code,
                                ]
                            ),
                        )
                        final_result = self._finalize_action_execution(
                            result,
                            event_type="screen_awareness.playwright_scroll_verification_completed",
                            severity=EventSeverity.WARNING if status in {"partial", "failed", "ambiguous", "completed_unverified"} else EventSeverity.INFO,
                        )
                        return final_result
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
                            user_message="That browser target is not safe or specific enough for Playwright action execution.",
                            limitations=["target_blocked", candidate_blocker],
                        )
                        final_result = self._finalize_action_execution(
                            result,
                            event_type=_action_event_type(
                                plan_model.action_kind,
                                "screen_awareness.playwright_action_execution_blocked",
                                "screen_awareness.playwright_type_blocked",
                            ),
                        )
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
                        final_result = self._finalize_action_execution(
                            result,
                            event_type=_action_event_type(
                                plan_model.action_kind,
                                "screen_awareness.playwright_action_execution_blocked",
                                "screen_awareness.playwright_type_blocked",
                            ),
                        )
                        return final_result

                    submit_count_before = _safe_submit_counter(page)
                    if plan_model.action_kind in {"check", "uncheck"} and _choice_already_in_expected_state(plan_model.action_kind, target_candidate):
                        trust_service.mark_action_executed(
                            action_request=action_request,
                            grant=trust_decision.grant,
                            summary=f"No-op Playwright {plan_model.action_kind} on {target_candidate.get('name') or target_candidate.get('role')}; target already had requested state.",
                            details={
                                "plan_id": plan_model.plan_id,
                                "preview_id": plan_model.preview_id,
                                "action_kind": plan_model.action_kind,
                                "claim_ceiling": _ACTION_EXECUTION_CLAIM_CEILING,
                                "expected_checked_state": _expected_checked_state_for_action(plan_model.action_kind),
                                "already_in_expected_state": True,
                            },
                        )
                        result = _execution_result(
                            request,
                            plan_model,
                            status="verified_supported",
                            action_attempted=False,
                            action_completed=False,
                            verification_attempted=True,
                            verification_status="supported",
                            before_observation_id=before.observation_id,
                            after_observation_id=before.observation_id,
                            trust_request_id=action_request.request_id,
                            approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                            trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                            user_message="Choice already had the requested state; no browser action was issued.",
                            limitations=[
                                "already_in_expected_state",
                                "no_action_needed",
                                "isolated_temporary_browser_context",
                                "not_visible_screen_verification",
                                "not_truth_verified",
                            ],
                        )
                        final_result = self._finalize_action_execution(
                            result,
                            event_type="screen_awareness.playwright_choice_no_op_supported",
                        )
                        return final_result

                    selected_option, option_blocker = _select_option_for_execution(plan_model, target_candidate)
                    if option_blocker:
                        result = _execution_result(
                            request,
                            plan_model,
                            status="blocked",
                            trust_request_id=action_request.request_id,
                            approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                            trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                            before_observation_id=before.observation_id,
                            error_code=option_blocker,
                            user_message="That dropdown option is unavailable, disabled, ambiguous, or unsafe.",
                            limitations=["option_blocked", option_blocker],
                        )
                        final_result = self._finalize_action_execution(
                            result,
                            event_type=_action_event_type(
                                plan_model.action_kind,
                                "screen_awareness.playwright_action_execution_blocked",
                                "screen_awareness.playwright_type_blocked",
                            ),
                        )
                        return final_result

                    if _select_option_already_in_expected_state(plan_model, selected_option):
                        trust_service.mark_action_executed(
                            action_request=action_request,
                            grant=trust_decision.grant,
                            summary=f"No-op Playwright select_option on {target_candidate.get('name') or target_candidate.get('role')}; option already selected.",
                            details={
                                "plan_id": plan_model.plan_id,
                                "preview_id": plan_model.preview_id,
                                "action_kind": plan_model.action_kind,
                                "claim_ceiling": _ACTION_EXECUTION_CLAIM_CEILING,
                                "option_redacted_summary": request.option_redacted_summary,
                                "option_fingerprint": request.option_fingerprint,
                                "option_ordinal": request.option_ordinal,
                                "already_in_expected_state": True,
                            },
                        )
                        result = _execution_result(
                            request,
                            plan_model,
                            status="verified_supported",
                            action_attempted=False,
                            action_completed=False,
                            verification_attempted=True,
                            verification_status="supported",
                            before_observation_id=before.observation_id,
                            after_observation_id=before.observation_id,
                            trust_request_id=action_request.request_id,
                            approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                            trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                            user_message="Choice already had the requested selected option; no browser action was issued.",
                            limitations=[
                                "already_in_expected_state",
                                "no_action_needed",
                                "isolated_temporary_browser_context",
                                "not_visible_screen_verification",
                                "not_truth_verified",
                            ],
                        )
                        final_result = self._finalize_action_execution(
                            result,
                            event_type="screen_awareness.playwright_choice_no_op_supported",
                        )
                        return final_result

                    if plan_model.action_kind == "click":
                        locator.click(timeout=int(self.config.observation_timeout_seconds or 8000))
                    elif plan_model.action_kind == "focus":
                        locator.focus(timeout=int(self.config.observation_timeout_seconds or 8000))
                    elif plan_model.action_kind == "type_text":
                        locator.focus(timeout=int(self.config.observation_timeout_seconds or 8000))
                        locator.fill(
                            _typed_text_value(getattr(plan_model, "action_arguments_private", {}) or {}),
                            timeout=int(self.config.observation_timeout_seconds or 8000),
                        )
                    elif plan_model.action_kind == "check":
                        locator.check(timeout=int(self.config.observation_timeout_seconds or 8000))
                    elif plan_model.action_kind == "uncheck":
                        locator.uncheck(timeout=int(self.config.observation_timeout_seconds or 8000))
                    elif plan_model.action_kind == "select_option":
                        locator.select_option(
                            label=selected_option.get("label"),
                            timeout=int(self.config.observation_timeout_seconds or 8000),
                        )
                    else:
                        raise RuntimeError(f"Unsupported action kind reached execution: {plan_model.action_kind}")
                    action_completed = True
                    self._publish(
                        "screen_awareness.playwright_action_command_returned",
                        "Playwright browser action command returned.",
                        _execution_event_payload(request, plan_model, status="action_command_returned", target=target_candidate),
                    )
                    self._publish(
                        _action_event_type(
                            plan_model.action_kind,
                            "screen_awareness.playwright_action_execution_attempted",
                            "screen_awareness.playwright_type_attempted",
                        ),
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
                            "typed_text_redacted": request.typed_text_redacted,
                            "text_redacted_summary": request.text_redacted_summary,
                            "text_length": request.text_length,
                            "text_fingerprint": request.text_fingerprint,
                            "option_redacted_summary": request.option_redacted_summary,
                            "option_fingerprint": request.option_fingerprint,
                            "option_ordinal": request.option_ordinal,
                            "expected_checked_state": request.expected_checked_state,
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
                    submit_count_after = _safe_submit_counter(page)
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
                            event_type=_action_event_type(
                                plan_model.action_kind,
                                "screen_awareness.playwright_action_verification_completed",
                                "screen_awareness.playwright_type_verification_completed",
                            ),
                            severity=EventSeverity.WARNING,
                        )
                        return final_result
                    self._publish(
                        _action_event_type(
                            plan_model.action_kind,
                            "screen_awareness.playwright_action_after_observation_captured",
                            "screen_awareness.playwright_type_after_observation_captured",
                        ),
                        "Playwright browser action after-observation captured.",
                        _execution_event_payload(request, plan_model, status="after_observation_captured", target=target_candidate),
                    )
                    if _submit_counter_changed(submit_count_before, submit_count_after):
                        result = _execution_result(
                            request,
                            plan_model,
                            status="failed",
                            action_attempted=True,
                            action_completed=action_completed,
                            verification_attempted=True,
                            verification_status="failed",
                            before_observation_id=before.observation_id,
                            after_observation_id=after.observation_id,
                            trust_request_id=action_request.request_id,
                            approval_grant_id=trust_decision.grant.grant_id if trust_decision.grant is not None else "",
                            trust_scope=trust_decision.grant.scope.value if trust_decision.grant is not None else action_request.suggested_scope.value,
                            error_code="unexpected_form_submission",
                            user_message="The browser action changed a fixture submit counter, so Stormhelm is not treating it as successful.",
                            limitations=[
                                "unexpected_form_submission",
                                "submit_prevention_failed",
                                "not_visible_screen_verification",
                                "not_truth_verified",
                            ],
                        )
                        final_result = self._finalize_action_execution(
                            result,
                            event_type=_action_event_type(
                                plan_model.action_kind,
                                "screen_awareness.playwright_action_verification_completed",
                                "screen_awareness.playwright_type_verification_completed",
                            ),
                            severity=EventSeverity.WARNING,
                        )
                        return final_result
                    comparison = _best_action_comparison(self, before, after, plan_model)
                    status, verification_status, user_message = _execution_status_from_comparison(plan_model.action_kind, comparison)
                    error_code = ""
                    comparison_limitations = list(comparison.limitations if comparison is not None else ["comparison_unavailable"])
                    if plan_model.action_kind in {"check", "uncheck", "select_option"} and _choice_unexpected_navigation(before, after):
                        status = "failed"
                        verification_status = "failed"
                        error_code = "unexpected_navigation"
                        user_message = "Choice action changed the page URL unexpectedly, so Stormhelm is not treating it as successful."
                        comparison_limitations.append("unexpected_navigation")
                    elif (
                        plan_model.action_kind in {"check", "uncheck", "select_option"}
                        and _choice_unexpected_warning_added(before, after)
                        and status == "verified_supported"
                    ):
                        status = "partial"
                        verification_status = "partial"
                        error_code = "unexpected_warning_added"
                        user_message = "Choice state changed, but an unexpected warning appeared, so the result is only partial."
                        comparison_limitations.append("unexpected_warning_added")
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
                        error_code=error_code,
                        user_message=user_message,
                        limitations=_action_execution_limitations(comparison_limitations),
                    )
                    final_result = self._finalize_action_execution(
                        result,
                        event_type=_action_event_type(
                            plan_model.action_kind,
                            "screen_awareness.playwright_action_verification_completed",
                            "screen_awareness.playwright_type_verification_completed",
                        ),
                    )
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
                    event_type=_action_event_type(
                        plan_model.action_kind,
                        "screen_awareness.playwright_action_verification_completed",
                        "screen_awareness.playwright_type_verification_completed",
                    ),
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
            final_result = self._finalize_action_execution(
                result,
                event_type=_action_event_type(
                    plan_model.action_kind,
                    "screen_awareness.playwright_action_execution_failed",
                    "screen_awareness.playwright_type_failed",
                ),
                severity=EventSeverity.WARNING,
            )
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
        if plan.action_kind not in {"click", "focus", "type_text", "check", "uncheck", "select_option", "scroll", "scroll_to_target"}:
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
        argument_binding_blocker = _plan_argument_binding_blocker(plan)
        if argument_binding_blocker:
            argument_family = "scroll_arguments_blocked" if plan.action_kind in {"scroll", "scroll_to_target"} else "typed_text_blocked"
            return _execution_result(
                request,
                plan,
                status="blocked",
                error_code=argument_binding_blocker,
                user_message=(
                    "Scrolling is blocked because the approved direction, amount, or target no longer matches the plan."
                    if plan.action_kind in {"scroll", "scroll_to_target"}
                    else "Typing is blocked because the text payload is missing, sensitive-like, or no longer matches the approved plan."
                ),
                limitations=[argument_family, argument_binding_blocker, "no_action_attempted"],
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
            if error_code in {"sensitive_or_restricted_context", "payment_or_restricted_context"}:
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

    def _task_plan_gate_result(self, plan: BrowserSemanticTaskPlan) -> BrowserSemanticTaskExecutionResult | None:
        if plan.plan_kind != "safe_browser_sequence":
            return _task_execution_result(
                plan,
                status="unsupported",
                failure_reason="unsupported_task_plan_kind",
                user_message="That browser task plan kind is not supported.",
                limitations=["unsupported_task_plan_kind", "no_action_attempted"],
            )
        if not plan.steps:
            return _task_execution_result(
                plan,
                status="blocked",
                failure_reason="explicit_steps_required",
                user_message="A safe browser task plan needs explicit supported steps.",
                limitations=["explicit_steps_required", "no_action_attempted"],
            )
        if len(plan.steps) > max(1, int(getattr(self.config, "max_task_steps", 5) or 5)):
            return _task_execution_result(
                plan,
                status="blocked",
                failure_reason="max_steps_exceeded",
                user_message="That browser task plan has too many steps for the current safe bound.",
                limitations=["max_steps_exceeded", "no_action_attempted"],
            )
        freshness_blocker = _task_plan_freshness_blocker(plan)
        if freshness_blocker:
            return _task_execution_result(
                plan,
                status="blocked",
                failure_reason=freshness_blocker,
                user_message="That browser task plan is stale. Refresh the semantic observation before executing.",
                limitations=["stale_plan", freshness_blocker, "no_action_attempted"],
            )
        computed_binding = _task_plan_binding_fingerprint(plan)
        if plan.approval_binding_fingerprint and computed_binding != plan.approval_binding_fingerprint:
            tamper_reason = _task_plan_tamper_reason(plan)
            return _task_execution_result(
                plan,
                status="blocked",
                failure_reason=tamper_reason,
                user_message="That approval cannot be used because the ordered browser task plan changed.",
                limitations=["approval_binding_mismatch", tamper_reason, "approval_invalid", "no_action_attempted"],
            )
        task_gate = _task_gate_blocker(self.config)
        if task_gate:
            return _task_execution_result(
                plan,
                status="blocked",
                failure_reason=task_gate,
                user_message="Safe browser task plans are not enabled by the current Playwright gates.",
                limitations=["task_plan_gate_blocked", task_gate, "no_action_attempted"],
            )
        for step in plan.steps:
            if step.action_kind not in _SAFE_TASK_ACTION_KINDS:
                return _task_execution_result(
                    plan,
                    status="unsupported",
                    blocked_step_id=step.step_id,
                    failure_reason="unsupported_step",
                    user_message="That browser task plan includes an unsupported step.",
                    limitations=["unsupported_step", step.action_kind, "no_action_attempted"],
                )
            if step.status == "blocked":
                return _task_execution_result(
                    plan,
                    status="blocked",
                    blocked_step_id=step.step_id,
                    failure_reason=next((item for item in step.limitations if item), "blocked_step"),
                    user_message="That browser task plan contains a blocked step.",
                    limitations=list(step.limitations) + ["no_action_attempted"],
                )
            if _action_gate_blocker(self.config, step.action_kind):
                return _task_execution_result(
                    plan,
                    status="blocked",
                    blocked_step_id=step.step_id,
                    failure_reason=_action_gate_blocker(self.config, step.action_kind),
                    user_message="A step in that browser task plan is not enabled by the current Playwright gates.",
                    limitations=["step_capability_blocked", _action_gate_blocker(self.config, step.action_kind), "no_action_attempted"],
                )
        return None

    def _execute_task_step_on_page(
        self,
        step: BrowserSemanticTaskStep,
        *,
        page: Any,
        before: BrowserSemanticObservation,
        session_id: str,
        task_id: str,
        trust_request_id: str,
        approval_grant_id: str,
        trust_scope: str,
    ) -> BrowserSemanticActionExecutionResult:
        plan = step.action_plan_private
        if plan is None:
            request = BrowserSemanticActionExecutionRequest(
                plan_id=step.step_id,
                action_kind=step.action_kind,
                session_id=session_id,
                task_id=task_id,
                expected_outcome=list(step.expected_outcome),
            )
            return _execution_result(
                request,
                BrowserSemanticActionPlan(plan_id=step.step_id, action_kind=step.action_kind),
                status="blocked",
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                before_observation_id=before.observation_id,
                error_code="serialized_plan_replay_blocked",
                user_message="Serialized browser task plans cannot execute without fresh in-memory step payloads.",
                limitations=["serialized_plan_replay_blocked", "no_action_attempted"],
            )
        request = _execution_request_from_plan(plan, session_id=session_id, task_id=task_id)
        target_context_blocker = _scroll_context_blocker(before) if plan.action_kind in {"scroll", "scroll_to_target"} else _action_context_blocker(before, plan.action_kind)
        if target_context_blocker:
            return _execution_result(
                request,
                plan,
                status="blocked",
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                before_observation_id=before.observation_id,
                error_code=target_context_blocker,
                user_message="Browser task step blocked: page appears sensitive or restricted.",
                limitations=["sensitive_page_context", target_context_blocker, "no_action_attempted"],
            )
        binding_blocker = _plan_target_binding_blocker(plan) or _plan_argument_binding_blocker(plan)
        if binding_blocker:
            return _execution_result(
                request,
                plan,
                status="blocked",
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                before_observation_id=before.observation_id,
                error_code=binding_blocker,
                user_message="Browser task step blocked because its approval binding no longer matches.",
                limitations=["approval_binding_mismatch", binding_blocker, "no_action_attempted"],
            )
        if plan.action_kind in {"scroll", "scroll_to_target"}:
            return self._execute_scroll_task_step(
                plan,
                request=request,
                page=page,
                before=before,
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
            )

        target_candidate = _resolve_execution_candidate(plan, before)
        candidate_blocker = _candidate_execution_blocker(plan.action_kind, target_candidate)
        if candidate_blocker:
            return _execution_result(
                request,
                plan,
                status="blocked",
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                before_observation_id=before.observation_id,
                error_code=candidate_blocker,
                user_message="That browser task step target is not safe or specific enough for execution.",
                limitations=["target_blocked", candidate_blocker],
            )
        locator, locator_blocker = _locator_for_execution(page, target_candidate)
        if locator_blocker:
            return _execution_result(
                request,
                plan,
                status="blocked",
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                before_observation_id=before.observation_id,
                error_code=locator_blocker,
                user_message="The grounded browser task step target was ambiguous or unavailable at execution time.",
                limitations=["locator_blocked", locator_blocker],
            )
        submit_count_before = _safe_submit_counter(page)
        if plan.action_kind in {"check", "uncheck"} and _choice_already_in_expected_state(plan.action_kind, target_candidate):
            return _execution_result(
                request,
                plan,
                status="verified_supported",
                action_attempted=False,
                action_completed=False,
                verification_attempted=True,
                verification_status="supported",
                before_observation_id=before.observation_id,
                after_observation_id=before.observation_id,
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                user_message="Choice already had the requested state; no browser action was issued.",
                limitations=["already_in_expected_state", "no_action_needed", "isolated_temporary_browser_context"],
            )
        selected_option, option_blocker = _select_option_for_execution(plan, target_candidate)
        if option_blocker:
            return _execution_result(
                request,
                plan,
                status="blocked",
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                before_observation_id=before.observation_id,
                error_code=option_blocker,
                user_message="That dropdown option is unavailable, disabled, ambiguous, or unsafe.",
                limitations=["option_blocked", option_blocker],
            )
        if _select_option_already_in_expected_state(plan, selected_option):
            return _execution_result(
                request,
                plan,
                status="verified_supported",
                action_attempted=False,
                action_completed=False,
                verification_attempted=True,
                verification_status="supported",
                before_observation_id=before.observation_id,
                after_observation_id=before.observation_id,
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                user_message="Choice already had the requested selected option; no browser action was issued.",
                limitations=["already_in_expected_state", "no_action_needed", "isolated_temporary_browser_context"],
            )
        action_completed = False
        if plan.action_kind == "click":
            locator.click(timeout=int(self.config.observation_timeout_seconds or 8000))
        elif plan.action_kind == "focus":
            locator.focus(timeout=int(self.config.observation_timeout_seconds or 8000))
        elif plan.action_kind == "type_text":
            locator.focus(timeout=int(self.config.observation_timeout_seconds or 8000))
            locator.fill(
                _typed_text_value(getattr(plan, "action_arguments_private", {}) or {}),
                timeout=int(self.config.observation_timeout_seconds or 8000),
            )
        elif plan.action_kind == "check":
            locator.check(timeout=int(self.config.observation_timeout_seconds or 8000))
        elif plan.action_kind == "uncheck":
            locator.uncheck(timeout=int(self.config.observation_timeout_seconds or 8000))
        elif plan.action_kind == "select_option":
            locator.select_option(label=selected_option.get("label"), timeout=int(self.config.observation_timeout_seconds or 8000))
        else:
            raise RuntimeError(f"Unsupported task step action kind reached execution: {plan.action_kind}")
        action_completed = True
        _wait_for_semantic_stabilization(page)
        after = _live_observation_from_page(
            page,
            adapter_id=self.adapter_id,
            session_id=f"playwright-task-after-{uuid4().hex[:10]}",
        )
        submit_count_after = _safe_submit_counter(page)
        if _after_observation_unusable(before, after):
            return _execution_result(
                request,
                plan,
                status="completed_unverified",
                action_attempted=True,
                action_completed=action_completed,
                verification_attempted=False,
                verification_status="unavailable",
                before_observation_id=before.observation_id,
                after_observation_id=after.observation_id,
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                error_code="after_observation_failed",
                user_message="The task step command returned, but the after-observation was not usable enough to verify the expected change.",
                limitations=["after_observation_failed", "completed_unverified", "isolated_temporary_browser_context"],
            )
        if _submit_counter_changed(submit_count_before, submit_count_after):
            return _execution_result(
                request,
                plan,
                status="failed",
                action_attempted=True,
                action_completed=action_completed,
                verification_attempted=True,
                verification_status="failed",
                before_observation_id=before.observation_id,
                after_observation_id=after.observation_id,
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                error_code="unexpected_form_submission",
                user_message="The browser task step changed a fixture submit counter, so Stormhelm stopped the plan.",
                limitations=["unexpected_form_submission", "submit_prevention_failed", "not_visible_screen_verification", "not_truth_verified"],
            )
        comparison = _best_action_comparison(self, before, after, plan)
        status, verification_status, user_message = _execution_status_from_comparison(plan.action_kind, comparison)
        error_code = ""
        comparison_limitations = list(comparison.limitations if comparison is not None else ["comparison_unavailable"])
        if plan.action_kind in {"check", "uncheck", "select_option"} and _choice_unexpected_navigation(before, after):
            status = "failed"
            verification_status = "failed"
            error_code = "unexpected_navigation"
            user_message = "Choice action changed the page URL unexpectedly, so Stormhelm stopped the task plan."
            comparison_limitations.append("unexpected_navigation")
        elif (
            plan.action_kind in {"check", "uncheck", "select_option"}
            and _choice_unexpected_warning_added(before, after)
            and status == "verified_supported"
        ):
            status = "partial"
            verification_status = "partial"
            error_code = "unexpected_warning_added"
            user_message = "Choice state changed, but an unexpected warning appeared, so Stormhelm stopped the task plan."
            comparison_limitations.append("unexpected_warning_added")
        return _execution_result(
            request,
            plan,
            status=status,
            action_attempted=True,
            action_completed=action_completed,
            verification_attempted=True,
            verification_status=verification_status,
            before_observation_id=before.observation_id,
            after_observation_id=after.observation_id,
            comparison_result_id=comparison.result_id if comparison is not None else "",
            trust_request_id=trust_request_id,
            approval_grant_id=approval_grant_id,
            trust_scope=trust_scope,
            error_code=error_code,
            user_message=user_message,
            limitations=_action_execution_limitations(comparison_limitations),
        )

    def _execute_scroll_task_step(
        self,
        plan: BrowserSemanticActionPlan,
        *,
        request: BrowserSemanticActionExecutionRequest,
        page: Any,
        before: BrowserSemanticObservation,
        trust_request_id: str,
        approval_grant_id: str,
        trust_scope: str,
    ) -> BrowserSemanticActionExecutionResult:
        submit_count_before = _safe_submit_counter(page)
        scroll_before = _safe_scroll_state(page)
        scroll_details = _scroll_details_from_plan(plan, request)
        target_phrase = _bounded_text(scroll_details.get("target_phrase") or request.scroll_target_phrase or plan.target_candidate.get("name") or "", 120)
        target_found = False
        target_ambiguous = False
        target_sensitive = False
        if plan.action_kind == "scroll_to_target":
            target_match, target_blocker = _scroll_target_match(before, target_phrase)
            if target_blocker == "target_ambiguous":
                return _execution_result(
                    request,
                    plan,
                    status="ambiguous",
                    before_observation_id=before.observation_id,
                    trust_request_id=trust_request_id,
                    approval_grant_id=approval_grant_id,
                    trust_scope=trust_scope,
                    error_code=target_blocker,
                    user_message="Scroll task step blocked: the requested target is ambiguous.",
                    limitations=["target_ambiguous", "no_action_attempted"],
                )
            if target_blocker == "target_sensitive":
                return _execution_result(
                    request,
                    plan,
                    status="blocked",
                    before_observation_id=before.observation_id,
                    trust_request_id=trust_request_id,
                    approval_grant_id=approval_grant_id,
                    trust_scope=trust_scope,
                    error_code=target_blocker,
                    user_message="Scroll task step blocked: target appears sensitive.",
                    limitations=["target_sensitive", "no_action_attempted"],
                )
            if target_match is not None:
                return _execution_result(
                    request,
                    plan,
                    status="verified_supported",
                    action_attempted=False,
                    action_completed=False,
                    verification_attempted=True,
                    verification_status="supported",
                    before_observation_id=before.observation_id,
                    after_observation_id=before.observation_id,
                    trust_request_id=trust_request_id,
                    approval_grant_id=approval_grant_id,
                    trust_scope=trust_scope,
                    user_message="Scroll target was already available; no scroll command was issued.",
                    limitations=["target_already_available", "no_action_needed", "isolated_temporary_browser_context"],
                )
        attempts = max(1, min(int(scroll_details.get("max_attempts") or self.config.max_scroll_attempts or 1), int(self.config.max_scroll_attempts or 5)))
        amount = min(
            max(1, int(scroll_details.get("amount_pixels") or self.config.scroll_step_pixels or 700)),
            max(1, int(self.config.max_scroll_distance_pixels or 5000)),
        )
        after = before
        for _index in range(attempts):
            _perform_scroll(page, str(scroll_details.get("direction") or "down"), amount)
            _wait_for_semantic_stabilization(page)
            after = _live_observation_from_page(
                page,
                adapter_id=self.adapter_id,
                session_id=f"playwright-task-scroll-after-{uuid4().hex[:10]}",
            )
            if plan.action_kind == "scroll_to_target":
                target_match, target_blocker = _scroll_target_match(after, target_phrase)
                target_found = target_match is not None
                target_ambiguous = target_blocker == "target_ambiguous"
                target_sensitive = target_blocker == "target_sensitive"
                if target_found or target_ambiguous or target_sensitive:
                    break
            else:
                break
        submit_count_after = _safe_submit_counter(page)
        if _submit_counter_changed(submit_count_before, submit_count_after):
            return _execution_result(
                request,
                plan,
                status="failed",
                action_attempted=True,
                action_completed=True,
                verification_attempted=True,
                verification_status="failed",
                before_observation_id=before.observation_id,
                after_observation_id=after.observation_id,
                trust_request_id=trust_request_id,
                approval_grant_id=approval_grant_id,
                trust_scope=trust_scope,
                error_code="unexpected_form_submission",
                user_message="Scroll changed a fixture submit counter, so Stormhelm stopped the task plan.",
                limitations=["unexpected_form_submission", "submit_prevention_failed"],
            )
        scroll_after = _safe_scroll_state(page)
        comparison = _best_action_comparison(self, before, after, plan)
        status, verification_status, user_message = _scroll_execution_status(
            plan,
            comparison,
            scroll_before,
            scroll_after,
            target_found=target_found,
            target_ambiguous=target_ambiguous,
            target_sensitive=target_sensitive,
        )
        return _execution_result(
            request,
            plan,
            status=status,
            action_attempted=True,
            action_completed=True,
            verification_attempted=True,
            verification_status=verification_status,
            before_observation_id=before.observation_id,
            after_observation_id=after.observation_id,
            comparison_result_id=comparison.result_id if comparison is not None else "",
            trust_request_id=trust_request_id,
            approval_grant_id=approval_grant_id,
            trust_scope=trust_scope,
            user_message=user_message,
            limitations=_action_execution_limitations(list(comparison.limitations if comparison is not None else [])),
        )

    def _finalize_task_execution(
        self,
        result: BrowserSemanticTaskExecutionResult,
        *,
        event_type: str = "screen_awareness.playwright_task_execution_started",
        severity: EventSeverity = EventSeverity.INFO,
    ) -> BrowserSemanticTaskExecutionResult:
        if not result.completed_at and result.status not in {"approval_required", "running"}:
            result.completed_at = utc_now_iso()
        self._last_task_execution_summary = _task_execution_summary(result)
        if event_type:
            self._publish(event_type, _task_execution_event_message(result), _task_execution_event_payload(result), severity=severity)
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
        warnings.append("actions_requested_requires_specific_action_gates")
    if getattr(config, "allow_click", False):
        warnings.append("click_requested_requires_trust_gate")
    if getattr(config, "allow_focus", False):
        warnings.append("focus_requested_requires_trust_gate")
    if getattr(config, "allow_type_text", False):
        warnings.append("type_text_requested_requires_trust_gate")
    if getattr(config, "allow_dev_type_text", False):
        warnings.append("dev_type_text_allowed")
    if getattr(config, "allow_dev_actions", False):
        warnings.append("dev_actions_allowed")
    if getattr(config, "allow_scroll", False):
        warnings.append("scroll_requested_requires_trust_gate")
    if getattr(config, "allow_scroll_to_target", False):
        warnings.append("scroll_to_target_requested_requires_trust_gate")
    if getattr(config, "allow_dev_scroll", False):
        warnings.append("dev_scroll_allowed")
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
    if getattr(config, "allow_payment", False):
        warnings.append("payment_requested_but_unsupported")
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
    elif value_summary.startswith("selected option: "):
        value_summary = _bounded_text(value_summary, 80)
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
        options=_bounded_choice_options(raw.get("options")),
        confidence=float(raw.get("confidence") or 0.76),
    )


def _unsupported_flag_blockers(config: PlaywrightBrowserAdapterConfig) -> list[str]:
    blockers: list[str] = []
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
    if getattr(config, "allow_payment", False):
        blockers.append("payment_not_supported")
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
        options=_bounded_choice_options(raw.get("options")),
        confidence=float(raw.get("confidence") or 0.72),
    )


def _bounded_choice_options(value: Any) -> list[dict[str, Any]]:
    options = _mapping_list(value)[:_LIST_LIMIT]
    bounded: list[dict[str, Any]] = []
    for index, option in enumerate(options, start=1):
        label = _bounded_text(option.get("label") or option.get("text") or option.get("name") or "", 80)
        value_summary = _bounded_text(option.get("value_summary") or option.get("value") or "", 80)
        if _looks_like_secret(value_summary):
            value_summary = "[redacted option value]"
        bounded.append(
            {
                "label": label,
                "value_summary": value_summary,
                "selected": bool(option.get("selected", False)),
                "disabled": bool(option.get("disabled", False)),
                "ordinal": _safe_int(option.get("ordinal"), default=index),
                "option_fingerprint": _option_fingerprint(label, value_summary, _safe_int(option.get("ordinal"), default=index)),
            }
        )
    return bounded


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


def _adapter_semantics_payload(observation: BrowserSemanticObservation) -> dict[str, Any]:
    page_url = _safe_display_url(observation.page_url)
    controls: list[dict[str, Any]] = []
    for control in observation.controls[:_LIST_LIMIT]:
        label = _bounded_text(control.label or control.name or control.text or control.control_id, 120)
        control_id = _bounded_text(control.control_id or label, 100)
        if not label or not control_id:
            continue
        controls.append(
            {
                "field_id": control_id,
                "control_id": control_id,
                "label": label,
                "name": _bounded_text(control.name or label, 120),
                "role": _bounded_text(control.role or "control", 40),
                "kind": _bounded_text(control.role or "control", 40),
                "visible": bool(control.visible if control.visible is not None else True),
                "enabled": control.enabled if isinstance(control.enabled, bool) else None,
                "bounds": dict(control.bounding_hint or {}),
                "selector_hint": _bounded_text(control.selector_hint, 120),
                "checked": control.checked,
                "expanded": control.expanded,
                "required": control.required,
                "readonly": control.readonly,
                "value_summary": _bounded_text(control.value_summary, 80),
                "options": _bounded_choice_options(control.options)[:_LIST_LIMIT],
                "semantic_type": _bounded_text(control.risk_hint, 80),
                "source_provider": observation.provider,
                "source_observation_id": observation.observation_id,
                "claim_ceiling": observation.claim_ceiling,
            }
        )
    validation_messages: list[str] = []
    for item in (list(observation.dialogs) + list(observation.alerts))[:_LIST_LIMIT]:
        if not isinstance(item, dict):
            continue
        text = _bounded_text(item.get("name") or item.get("text") or item.get("dialog_id") or item.get("alert_id"), 160)
        if text and text not in validation_messages:
            validation_messages.append(text)
    return {
        "page": {
            "title": _bounded_text(observation.page_title, 160),
            "url": page_url,
        },
        "tab": {
            "title": _bounded_text(observation.page_title, 160),
            "url": page_url,
            "active": True,
        },
        "loading_state": "complete" if observation.controls or observation.page_title or observation.page_url else "unknown",
        "controls": controls,
        "validation_messages": validation_messages,
        "freshness_seconds": _observation_age_seconds(observation),
        "metadata": {
            "adapter_id": observation.adapter_id,
            "source_provider": observation.provider,
            "source_observation_id": observation.observation_id,
            "browser_context_kind": observation.browser_context_kind,
            "claim_ceiling": observation.claim_ceiling,
            "limitations": list(observation.limitations)[:8],
        },
    }


def _observation_age_seconds(observation: BrowserSemanticObservation) -> float | None:
    parsed = _parse_utc_timestamp(observation.observed_at)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


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
        if role == "radio":
            return "check"
        if role == "combobox":
            return "select_option"
        return "unsupported"
    if "submit" in phrase and ("form" in phrase or role == "button"):
        return "submit_form"
    if any(term in phrase for term in ("type", "enter", "write", "fill", "append text", "add text", "add more text")):
        return "type_text"
    if any(term in phrase for term in ("uncheck", "untick", "clear checkbox")):
        return "uncheck"
    if any(term in phrase for term in ("check", "tick")) and role in {"checkbox", "radio"}:
        return "check"
    if any(term in phrase for term in ("select", "choose", "pick")) and role == "radio":
        return "check"
    if any(term in phrase for term in ("select", "choose", "pick")) and role == "combobox":
        return "select_option"
    if any(term in phrase for term in ("scroll", "move down", "move up", "bring")):
        if any(term in phrase for term in ("scroll to", "bring", "until you find", "find the")) and not any(
            term in phrase for term in ("top", "bottom")
        ):
            return "scroll_to_target"
        return "scroll"
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


def _control_options_for_candidate(
    observation: BrowserSemanticObservation,
    candidate: BrowserGroundingCandidate | None,
) -> list[dict[str, Any]]:
    if candidate is None:
        return []
    candidate_ids = {
        _bounded_text(candidate.control_id or "", 80),
        _bounded_text(candidate.candidate_id or "", 80),
    }
    candidate_ids.discard("")
    for control in observation.controls:
        control_id = _bounded_text(getattr(control, "control_id", "") or "", 80)
        if control_id in candidate_ids:
            return _bounded_choice_options(getattr(control, "options", None))
    return []


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
    if _redacted_action_arguments(action_kind, action_arguments, target_phrase=target_phrase, config=config):
        limitations.append("action_arguments_redacted")
    target_options = _control_options_for_candidate(observation, candidate) if action_kind == "select_option" else []
    return BrowserSemanticActionPreview(
        observation_id=observation.observation_id,
        source_provider=observation.provider,
        target_phrase=_bounded_text(target_phrase),
        target_candidate_id=_bounded_text(candidate.control_id or candidate.candidate_id, 80),
        target_role=candidate.role,
        target_name=_candidate_label(candidate),
        target_label=candidate.label,
        target_options=target_options,
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
    if action_kind in {"check", "uncheck", "select_option"} and any(
        term in haystack
        for term in (
            "terms",
            "privacy",
            "privacy consent",
            "legal",
            "authorize",
            "authorization",
            "delete",
            "permanent",
            "remove my data",
            "consent",
            "security",
            "robot",
            "human verification",
            "captcha",
            "remember me",
            "trust this device",
            "age",
            "compliance",
            "export",
            "unsubscribe",
        )
    ):
        return "blocked", "blocked_until_future_policy", "sensitive_or_restricted_context"
    if action_kind in {"type_text", "submit_form"}:
        return "high", "browser_action_strong_confirmation_future", ""
    if action_kind in {"focus", "scroll", "scroll_to_target"}:
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
    if action_kind == "scroll":
        return ["page_scroll_position_changed"]
    if action_kind == "scroll_to_target":
        return ["target_available_after_scroll"]
    if action_kind == "focus":
        return ["control_state_changed"]
    return []


def _action_capability_required(action_kind: str) -> str:
    return {
        "click": "browser.input.click",
        "focus": "browser.input.focus",
        "type_text": "browser.input.type_text",
        "select_option": "browser.input.select_option",
        "check": "browser.input.check",
        "uncheck": "browser.input.uncheck",
        "scroll": "browser.input.scroll",
        "scroll_to_target": "browser.input.scroll_to_target",
        "scroll_to": "browser.input.scroll_to_target",
        "submit_form": "browser.form.submit",
    }.get(action_kind, "browser.action.unsupported")


def _typed_text_value(action_arguments: dict[str, Any] | None = None) -> str:
    raw = dict(action_arguments or {})
    if "text" in raw:
        return str(raw.get("text") or "")
    if "value" in raw:
        return str(raw.get("value") or "")
    return ""


def _typed_text_redacted_summary(text: str) -> str:
    return f"[redacted text, {len(str(text or ''))} chars]"


def _typed_text_fingerprint(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _option_value(action_arguments: dict[str, Any] | None = None) -> str:
    raw = dict(action_arguments or {})
    for key in ("option", "label", "value"):
        if key in raw:
            return str(raw.get(key) or "")
    return ""


def _option_fingerprint(label: str, value_summary: str = "", ordinal: int = 0) -> str:
    material = "|".join([_normalize(label), _normalize(value_summary), str(int(ordinal or 0))])
    return hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _scroll_direction(action_arguments: dict[str, Any] | None = None, action_phrase: str = "") -> str:
    raw = dict(action_arguments or {})
    direction = _normalize(str(raw.get("direction") or ""))
    phrase = _normalize(action_phrase)
    if direction in {"up", "down"}:
        return direction
    if direction in {"top"}:
        return "up"
    if "up" in phrase or "top" in phrase:
        return "up"
    return "down"


def _scroll_amount_pixels(action_arguments: dict[str, Any] | None = None, config: PlaywrightBrowserAdapterConfig | None = None) -> int:
    raw = dict(action_arguments or {})
    default = int(getattr(config, "scroll_step_pixels", 700) or 700)
    amount = _safe_int(raw.get("amount_pixels") or raw.get("amount") or raw.get("pixels"), default=default)
    if amount <= 0:
        amount = default
    max_distance = int(getattr(config, "max_scroll_distance_pixels", 5000) or 5000)
    return max(1, min(amount, max_distance))


def _scroll_max_attempts(action_arguments: dict[str, Any] | None = None, config: PlaywrightBrowserAdapterConfig | None = None) -> int:
    raw = dict(action_arguments or {})
    default = int(getattr(config, "max_scroll_attempts", 5) or 5)
    attempts = _safe_int(raw.get("max_attempts") or raw.get("attempts"), default=default)
    return max(1, min(attempts, default, 10))


def _scroll_target_phrase(
    action_arguments: dict[str, Any] | None = None,
    *,
    fallback: str = "",
) -> str:
    raw = dict(action_arguments or {})
    return _bounded_text(raw.get("target_phrase") or raw.get("target") or fallback, 120)


def _scroll_fingerprint(direction: str, amount_pixels: int, max_attempts: int, target_phrase: str = "") -> str:
    material = "|".join([_normalize(direction), str(int(amount_pixels or 0)), str(int(max_attempts or 0)), _normalize(target_phrase)])
    return hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _scroll_metadata(
    action_kind: str,
    action_arguments: dict[str, Any] | None = None,
    *,
    target_phrase: str = "",
    config: PlaywrightBrowserAdapterConfig | None = None,
) -> dict[str, Any]:
    raw = dict(action_arguments or {})
    direction = _scroll_direction(raw)
    amount = _scroll_amount_pixels(raw, config)
    attempts = _scroll_max_attempts(raw, config)
    target = _scroll_target_phrase(raw, fallback=target_phrase) if action_kind == "scroll_to_target" else ""
    return {
        "direction": direction,
        "amount_pixels": amount,
        "max_attempts": attempts,
        "target_phrase": target,
        "scroll_fingerprint": _scroll_fingerprint(direction, amount, attempts, target),
    }


def _select_option_metadata(
    action_arguments: dict[str, Any] | None = None,
    target_options: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw = dict(action_arguments or {})
    option = _option_value(raw)
    ordinal = _safe_int(raw.get("ordinal"), default=0)
    if not option and ordinal <= 0:
        return {
            "option_redacted_summary": "",
            "option_fingerprint": "",
            "option_request_fingerprint": "",
            "option_ordinal": 0,
        }
    request_fingerprint = _option_fingerprint(option, "", ordinal)
    bound_fingerprint = request_fingerprint
    options = _bounded_choice_options(target_options)
    matched_option: dict[str, Any] | None = None
    if options:
        if option:
            matches = [item for item in options if _normalize(item.get("label") or "") == _normalize(option)]
        else:
            matches = [item for item in options if _safe_int(item.get("ordinal"), default=0) == ordinal]
        if len(matches) == 1:
            matched_option = dict(matches[0])
    if matched_option is not None:
        bound_fingerprint = _option_fingerprint(
            str(matched_option.get("label") or option),
            str(matched_option.get("value_summary") or ""),
            _safe_int(matched_option.get("ordinal"), default=ordinal),
        )
    return {
        "option_redacted_summary": _bounded_text(option or f"option {ordinal}", 80),
        "option_fingerprint": bound_fingerprint,
        "option_request_fingerprint": request_fingerprint,
        "option_ordinal": ordinal,
    }


def _compact_digits(text: str) -> str:
    return "".join(ch for ch in str(text or "") if ch.isdigit())


def _classify_typed_text(text: str) -> str:
    value = str(text or "")
    lowered = value.lower()
    digits = _compact_digits(value)
    if not value:
        return "blocked"
    if _looks_like_secret(lowered):
        return "sensitive_like"
    if any(
        term in lowered
        for term in (
            "password",
            "passcode",
            "secret",
            "token",
            "api key",
            "apikey",
            "recovery code",
            "2fa",
            "mfa",
            "otp",
            "cvv",
            "cvc",
            "security code",
            "expiration date",
            "expiry date",
            "bank",
            "routing",
            "account number",
        )
    ):
        return "sensitive_like"
    if value.strip().lower().startswith(("sk-", "pk_live_", "rk_live_")):
        return "sensitive_like"
    if len(digits) == 6 and value.strip().isdigit():
        return "sensitive_like"
    if len(digits) in range(13, 20):
        return "sensitive_like"
    pieces = value.replace("-", " ").split()
    if len(pieces) == 3 and all(piece.isdigit() for piece in pieces) and [len(piece) for piece in pieces] == [3, 2, 4]:
        return "sensitive_like"
    if any(
        term in lowered
        for term in (
            "credit card",
            "card number",
            "bank account",
            "routing number",
            "ssn",
            "social security",
            "billing",
            "checkout",
            "payment",
        )
    ):
        return "sensitive_like"
    return "plain"


def _type_text_metadata(action_arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    text = _typed_text_value(action_arguments)
    if text == "":
        return {
            "typed_text_redacted": True,
            "text_redacted_summary": "[redacted text, 0 chars]",
            "text_length": 0,
            "text_fingerprint": "",
            "text_classification": "blocked",
        }
    return {
        "typed_text_redacted": True,
        "text_redacted_summary": _typed_text_redacted_summary(text),
        "text_length": len(text),
        "text_fingerprint": _typed_text_fingerprint(text),
        "text_classification": _classify_typed_text(text),
    }


def _private_action_arguments(
    action_kind: str,
    action_arguments: dict[str, Any] | None = None,
    *,
    target_phrase: str = "",
    config: PlaywrightBrowserAdapterConfig | None = None,
) -> dict[str, Any]:
    raw = dict(action_arguments or {})
    if action_kind == "type_text":
        text = _typed_text_value(raw)
        return {"text": text, "mode": _bounded_text(raw.get("mode") or "replace_value", 40)}
    if action_kind == "select_option":
        return {
            "option": _option_value(raw),
            "ordinal": _safe_int(raw.get("ordinal"), default=0),
        }
    if action_kind in {"scroll", "scroll_to_target"}:
        return _scroll_metadata(action_kind, raw, target_phrase=target_phrase, config=config)
    return {}


def _redacted_action_arguments(
    action_kind: str,
    action_arguments: dict[str, Any] | None = None,
    *,
    target_options: Sequence[dict[str, Any]] | None = None,
    target_phrase: str = "",
    config: PlaywrightBrowserAdapterConfig | None = None,
) -> dict[str, Any]:
    raw = dict(action_arguments or {})
    redacted: dict[str, Any] = {}
    if action_kind == "type_text":
        redacted.update(_type_text_metadata(raw))
        redacted["mode"] = _bounded_text(raw.get("mode") or "replace_value", 40)
    elif action_kind == "select_option":
        redacted.update(_select_option_metadata(raw, target_options=target_options))
    elif action_kind in {"scroll", "scroll_to_target"}:
        redacted.update(_scroll_metadata(action_kind, raw, target_phrase=target_phrase, config=config))
    elif action_kind in {"check", "uncheck", "click", "focus", "scroll_to", "submit_form"}:
        for key in ("direction", "position", "button"):
            if key in raw:
                redacted[key] = _bounded_text(raw.get(key), 80)
        if action_kind == "check":
            redacted["expected_checked_state"] = True
        if action_kind == "uncheck":
            redacted["expected_checked_state"] = False
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
        target_options=_bounded_choice_options(payload.get("target_options")),
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
    if preview.action_kind == "select_option":
        target_candidate["options"] = _bounded_choice_options(preview.target_options)
    target_candidate["target_fingerprint"] = _target_fingerprint(target_candidate)
    redacted_arguments = _redacted_action_arguments(
        preview.action_kind,
        action_arguments,
        target_options=preview.target_options,
        target_phrase=preview.target_phrase,
        config=config,
    )
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
        action_arguments_private=_private_action_arguments(
            preview.action_kind,
            action_arguments,
            target_phrase=preview.target_phrase,
            config=config,
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
        action_arguments_private={},
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
    return bool(
        config.allow_actions
        and getattr(config, "allow_dev_actions", False)
        and (
            getattr(config, "allow_click", False)
            or getattr(config, "allow_focus", False)
            or (getattr(config, "allow_type_text", False) and getattr(config, "allow_dev_type_text", False))
            or (
                getattr(config, "allow_dev_choice_controls", False)
                and (
                    getattr(config, "allow_check", False)
                    or getattr(config, "allow_uncheck", False)
                    or getattr(config, "allow_select_option", False)
                )
            )
            or (
                getattr(config, "allow_dev_scroll", False)
                and (
                    getattr(config, "allow_scroll", False)
                    or getattr(config, "allow_scroll_to_target", False)
                )
            )
        )
    )


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
        return "stale_plan"
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


def _plan_argument_binding_blocker(plan: BrowserSemanticActionPlan) -> str:
    if plan.action_kind == "type_text":
        private_text = _typed_text_value(getattr(plan, "action_arguments_private", {}) or {})
        stored = ""
        if isinstance(plan.action_arguments_redacted, dict):
            stored = _bounded_text(plan.action_arguments_redacted.get("text_fingerprint") or "", 80)
        if not private_text:
            return "typed_text_missing"
        computed = _typed_text_fingerprint(private_text)
        if stored and stored != computed:
            return "approval_invalid"
        classification = _classify_typed_text(private_text)
        if classification != "plain":
            return "sensitive_text_blocked"
        mode = _bounded_text((getattr(plan, "action_arguments_private", {}) or {}).get("mode") or "replace_value", 40)
        if mode != "replace_value":
            return "typing_mode_unsupported"
    if plan.action_kind == "select_option":
        private_args = getattr(plan, "action_arguments_private", {}) or {}
        option = _option_value(private_args)
        ordinal = _safe_int(private_args.get("ordinal"), default=0)
        stored = ""
        stored_full = ""
        if isinstance(plan.action_arguments_redacted, dict):
            stored = _bounded_text(
                plan.action_arguments_redacted.get("option_request_fingerprint")
                or plan.action_arguments_redacted.get("option_fingerprint")
                or "",
                80,
            )
            stored_full = _bounded_text(plan.action_arguments_redacted.get("option_fingerprint") or "", 80)
        if not option and ordinal <= 0:
            return "option_missing"
        computed = _option_fingerprint(option, "", ordinal)
        if stored and stored != computed:
            return "approval_invalid"
        if stored_full and stored_full != computed:
            options = _bounded_choice_options((plan.target_candidate or {}).get("options"))
            if options:
                if option:
                    matches = [item for item in options if _normalize(item.get("label") or "") == _normalize(option)]
                else:
                    matches = [item for item in options if _safe_int(item.get("ordinal"), default=0) == ordinal]
                if len(matches) == 1:
                    expected_full = _option_fingerprint(
                        str(matches[0].get("label") or ""),
                        str(matches[0].get("value_summary") or ""),
                        _safe_int(matches[0].get("ordinal"), default=0),
                    )
                    if expected_full != stored_full:
                        return "approval_invalid"
    if plan.action_kind in {"scroll", "scroll_to_target"}:
        private_args = getattr(plan, "action_arguments_private", {}) or {}
        direction = _bounded_text(private_args.get("direction") or "", 20)
        amount = _safe_int(private_args.get("amount_pixels"), default=0)
        attempts = _safe_int(private_args.get("max_attempts"), default=0)
        target = _bounded_text(private_args.get("target_phrase") or "", 120)
        stored = ""
        if isinstance(plan.action_arguments_redacted, dict):
            stored = _bounded_text(plan.action_arguments_redacted.get("scroll_fingerprint") or "", 80)
        if not direction or amount <= 0 or attempts <= 0:
            return "scroll_arguments_missing"
        computed = _scroll_fingerprint(direction, amount, attempts, target)
        if stored and stored != computed:
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
    if getattr(config, "allow_type_text", False) and getattr(config, "allow_dev_type_text", False):
        capabilities.append("browser.input.type_text")
    if getattr(config, "allow_dev_choice_controls", False):
        if getattr(config, "allow_check", False):
            capabilities.append("browser.input.check")
        if getattr(config, "allow_uncheck", False):
            capabilities.append("browser.input.uncheck")
        if getattr(config, "allow_select_option", False):
            capabilities.append("browser.input.select_option")
    if getattr(config, "allow_dev_scroll", False):
        if getattr(config, "allow_scroll", False):
            capabilities.append("browser.input.scroll")
        if getattr(config, "allow_scroll_to_target", False):
            capabilities.append("browser.input.scroll_to_target")
    if getattr(config, "allow_task_plans", False) and getattr(config, "allow_dev_task_plans", False):
        capabilities.append("browser.task.safe_sequence")
    return capabilities


def _action_capability_declared(config: PlaywrightBrowserAdapterConfig | None, action_kind: str) -> bool:
    if config is None:
        return False
    capability = _action_capability_required(action_kind)
    if capability not in {
        "browser.input.click",
        "browser.input.focus",
        "browser.input.type_text",
        "browser.input.check",
        "browser.input.uncheck",
        "browser.input.select_option",
        "browser.input.scroll",
        "browser.input.scroll_to_target",
    }:
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
    if action_kind == "type_text":
        if not getattr(config, "allow_type_text", False):
            return "type_text_disabled"
        if not getattr(config, "allow_dev_type_text", False):
            return "dev_type_text_gate_required"
    if action_kind in {"check", "uncheck", "select_option"}:
        if not getattr(config, "allow_dev_choice_controls", False):
            return "dev_choice_controls_gate_required"
        if action_kind == "check" and not getattr(config, "allow_check", False):
            return "check_disabled"
        if action_kind == "uncheck" and not getattr(config, "allow_uncheck", False):
            return "uncheck_disabled"
        if action_kind == "select_option" and not getattr(config, "allow_select_option", False):
            return "select_option_disabled"
    if action_kind in {"scroll", "scroll_to_target"}:
        if not getattr(config, "allow_dev_scroll", False):
            return "dev_scroll_gate_required"
        if action_kind == "scroll" and not getattr(config, "allow_scroll", False):
            return "scroll_disabled"
        if action_kind == "scroll_to_target" and not getattr(config, "allow_scroll_to_target", False):
            return "scroll_to_target_disabled"
    if action_kind not in {"click", "focus", "type_text", "check", "uncheck", "select_option", "scroll", "scroll_to_target"}:
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
    text_meta = dict(plan.action_arguments_redacted or {}) if plan.action_kind == "type_text" else {}
    option_meta = dict(plan.action_arguments_redacted or {}) if plan.action_kind == "select_option" else {}
    checked_meta = dict(plan.action_arguments_redacted or {}) if plan.action_kind in {"check", "uncheck"} else {}
    scroll_meta = dict(plan.action_arguments_redacted or {}) if plan.action_kind in {"scroll", "scroll_to_target"} else {}
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
        typed_text_redacted=bool(text_meta.get("typed_text_redacted", False)),
        text_fingerprint=_bounded_text(text_meta.get("text_fingerprint") or "", 80),
        text_length=_safe_int(text_meta.get("text_length"), default=0),
        text_classification=_bounded_text(text_meta.get("text_classification") or "", 40),
        text_redacted_summary=_bounded_text(text_meta.get("text_redacted_summary") or "", 80),
        option_redacted_summary=_bounded_text(option_meta.get("option_redacted_summary") or "", 80),
        option_fingerprint=_bounded_text(option_meta.get("option_fingerprint") or "", 80),
        option_ordinal=_safe_int(option_meta.get("option_ordinal"), default=0),
        expected_checked_state=checked_meta.get("expected_checked_state") if isinstance(checked_meta.get("expected_checked_state"), bool) else None,
        scroll_direction=_bounded_text(scroll_meta.get("direction") or "", 20),
        scroll_amount_pixels=_safe_int(scroll_meta.get("amount_pixels"), default=0),
        scroll_max_attempts=_safe_int(scroll_meta.get("max_attempts"), default=0),
        scroll_target_phrase=_bounded_text(scroll_meta.get("target_phrase") or "", 120),
        scroll_fingerprint=_bounded_text(scroll_meta.get("scroll_fingerprint") or "", 80),
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
        typed_text_redacted=bool(request.typed_text_redacted),
        text_fingerprint=_bounded_text(request.text_fingerprint, 80),
        text_length=int(request.text_length or 0),
        text_classification=_bounded_text(request.text_classification, 40),
        text_redacted_summary=_bounded_text(request.text_redacted_summary, 80),
        option_redacted_summary=_bounded_text(request.option_redacted_summary, 80),
        option_fingerprint=_bounded_text(request.option_fingerprint, 80),
        option_ordinal=int(request.option_ordinal or 0),
        expected_checked_state=request.expected_checked_state,
        scroll_direction=_bounded_text(request.scroll_direction, 20),
        scroll_amount_pixels=int(request.scroll_amount_pixels or 0),
        scroll_max_attempts=int(request.scroll_max_attempts or 0),
        scroll_target_phrase=_bounded_text(request.scroll_target_phrase, 120),
        scroll_target_found="target_found" in list(limitations or []),
        scroll_fingerprint=_bounded_text(request.scroll_fingerprint, 80),
        limitations=list(dict.fromkeys([_bounded_text(item, 120) for item in list(limitations or []) if _bounded_text(item, 120)])),
        error_code=_bounded_text(error_code, 80),
        bounded_error_message=_bounded_text(bounded_error_message),
        user_message=_bounded_text(user_message or _default_execution_user_message(status, plan.action_kind)),
        cleanup_status=_bounded_text(cleanup_status, 40),
        completed_at=utc_now_iso() if status not in {"approval_required", "approved"} else "",
    )


_SAFE_TASK_ACTION_KINDS = {
    "focus",
    "click",
    "type_text",
    "check",
    "uncheck",
    "select_option",
    "scroll",
    "scroll_to_target",
}


def _task_execution_result(
    plan: BrowserSemanticTaskPlan,
    *,
    status: str,
    step_results: Sequence[BrowserSemanticActionExecutionResult] | None = None,
    completed_step_count: int = 0,
    blocked_step_id: str = "",
    failure_reason: str = "",
    final_verification_status: str = "",
    cleanup_status: str = "not_started",
    action_attempted: bool = False,
    approval_request_id: str = "",
    approval_grant_id: str = "",
    trust_request_id: str = "",
    limitations: Sequence[str] | None = None,
    user_message: str = "",
) -> BrowserSemanticTaskExecutionResult:
    return BrowserSemanticTaskExecutionResult(
        plan_id=plan.plan_id,
        status=_bounded_text(status, 80),
        step_results=list(step_results or []),
        completed_step_count=int(completed_step_count or 0),
        blocked_step_id=_bounded_text(blocked_step_id, 80),
        failure_reason=_bounded_text(failure_reason, 120),
        final_verification_status=_bounded_text(final_verification_status, 80),
        cleanup_status=_bounded_text(cleanup_status, 40),
        action_attempted=bool(action_attempted),
        approval_request_id=_bounded_text(approval_request_id, 80),
        approval_grant_id=_bounded_text(approval_grant_id, 80),
        trust_request_id=_bounded_text(trust_request_id, 80),
        limitations=list(dict.fromkeys([_bounded_text(item, 120) for item in list(limitations or []) if _bounded_text(item, 120)])),
        user_message=_bounded_text(user_message or _default_task_execution_user_message(status)),
        completed_at=utc_now_iso() if status not in {"approval_required", "running"} else "",
    )


def _default_task_execution_user_message(status: str) -> str:
    if status == "approval_required":
        return "Plan ready; approval required."
    if status == "completed_verified":
        return "The safe form preparation is verified. I did not submit it."
    if status == "completed_partial":
        return "The safe browser task plan completed with partial semantic support."
    if status == "stopped_on_unverified":
        return "I stopped because a step could not be semantically verified."
    if status == "stopped_on_ambiguity":
        return "I stopped because a step became ambiguous."
    if status == "stopped_on_failure":
        return "I stopped because a step failed."
    if status == "stopped_on_unexpected_side_effect":
        return "I stopped because an unexpected browser side effect was detected."
    if status in {"blocked", "unsupported"}:
        return "That safe browser task plan is blocked or unsupported."
    return "Safe browser task plan state updated."


def _task_stop_policy_from_config(config: PlaywrightBrowserAdapterConfig) -> dict[str, Any]:
    return {
        "stop_on_blocked": True,
        "stop_on_failed": True,
        "stop_on_ambiguous_step": bool(getattr(config, "stop_on_ambiguous_step", True)),
        "stop_on_unverified_step": bool(getattr(config, "stop_on_unverified_step", True)),
        "stop_on_partial_step": bool(getattr(config, "stop_on_partial_step", True)),
        "stop_on_unexpected_navigation": bool(getattr(config, "stop_on_unexpected_navigation", True)),
        "stop_on_submit_counter_change": True,
    }


def _task_stop_status(result: BrowserSemanticActionExecutionResult, config: PlaywrightBrowserAdapterConfig) -> str:
    if result.error_code == "unexpected_form_submission":
        return "stopped_on_unexpected_side_effect"
    if result.error_code == "unexpected_navigation" and bool(getattr(config, "stop_on_unexpected_navigation", True)):
        return "stopped_on_unexpected_side_effect"
    if result.status in {"blocked", "unsupported"}:
        return "stopped_on_blocked"
    if result.status == "failed":
        return "stopped_on_failure"
    if result.status == "ambiguous" and bool(getattr(config, "stop_on_ambiguous_step", True)):
        return "stopped_on_ambiguity"
    if result.status == "partial" and bool(getattr(config, "stop_on_partial_step", True)):
        return "stopped_on_unverified"
    if result.status in {"completed_unverified", "verified_unsupported"} and bool(getattr(config, "stop_on_unverified_step", True)):
        return "stopped_on_unverified"
    return ""


def _task_execution_limitations(
    step_results: Sequence[BrowserSemanticActionExecutionResult],
    *,
    extra: Sequence[str] | None = None,
) -> list[str]:
    limitations = [
        "isolated_temporary_browser_context",
        "no_user_profile",
        "no_cookies_persisted",
        "no_form_submit",
        "not_visible_screen_verification",
        "not_truth_verified",
    ]
    for result in step_results:
        limitations.extend(list(result.limitations)[:6])
    limitations.extend(list(extra or []))
    return list(dict.fromkeys([_bounded_text(item, 120) for item in limitations if _bounded_text(item, 120)]))


def _task_risk_level(steps: Sequence[BrowserSemanticTaskStep]) -> str:
    if any(step.action_kind == "type_text" for step in steps):
        return "high"
    if any(step.action_kind in {"click", "check", "uncheck", "select_option"} for step in steps):
        return "medium"
    return "low"


def _task_gate_blocker(config: PlaywrightBrowserAdapterConfig) -> str:
    if not config.enabled:
        return "playwright_adapter_disabled"
    if not getattr(config, "allow_dev_adapter", False):
        return "playwright_dev_adapter_gate_required"
    if not getattr(config, "allow_browser_launch", False):
        return "playwright_browser_launch_not_allowed"
    if not getattr(config, "allow_actions", False):
        return "actions_disabled"
    if not getattr(config, "allow_dev_actions", False):
        return "dev_actions_gate_required"
    if not getattr(config, "allow_task_plans", False):
        return "task_plans_disabled"
    if not getattr(config, "allow_dev_task_plans", False):
        return "dev_task_plans_gate_required"
    blockers = _unsupported_flag_blockers(config)
    return blockers[0] if blockers else ""


def _task_plan_freshness_blocker(plan: BrowserSemanticTaskPlan) -> str:
    created = _parse_utc_timestamp(plan.created_at)
    if created is None:
        return ""
    if (datetime.now(UTC) - created).total_seconds() > _STALE_OBSERVATION_SECONDS:
        return "stale_plan"
    expires = _parse_utc_timestamp(plan.expires_at)
    if expires is not None and expires <= datetime.now(UTC):
        return "plan_expired"
    return ""


def _task_stop_policy_with_approval_bindings(
    stop_policy: dict[str, Any],
    steps: Sequence[BrowserSemanticTaskStep],
) -> dict[str, Any]:
    policy = dict(stop_policy or {})
    policy["approval_step_count"] = len(steps)
    policy["approval_step_ids"] = [step.step_id for step in steps[:8]]
    policy["approval_step_bindings"] = {step.step_id: _task_step_binding_payload(step) for step in steps[:8]}
    return policy


def _task_plan_tamper_reason(plan: BrowserSemanticTaskPlan) -> str:
    policy = dict(plan.stop_policy or {})
    expected_count = _safe_int(policy.get("approval_step_count"), default=0)
    expected_ids = [str(item) for item in list(policy.get("approval_step_ids") or [])[:8]]
    current_ids = [step.step_id for step in plan.steps[:8]]
    if expected_count and len(plan.steps) != expected_count:
        return "step_count_changed"
    if expected_ids:
        if len(current_ids) != len(expected_ids):
            return "step_count_changed"
        if current_ids != expected_ids:
            if set(current_ids) == set(expected_ids):
                return "step_order_changed"
            return "step_count_changed"
    expected_bindings = {
        str(step_id): dict(payload)
        for step_id, payload in dict(policy.get("approval_step_bindings") or {}).items()
        if isinstance(payload, dict)
    }
    for step in plan.steps:
        expected = expected_bindings.get(step.step_id)
        current = _task_step_binding_payload(step)
        if expected is None:
            if step.approval_binding_fingerprint and _task_step_binding_fingerprint(step) != step.approval_binding_fingerprint:
                return "plan_fingerprint_mismatch"
            continue
        if current == expected:
            continue
        if current.get("step_index") != expected.get("step_index"):
            return "step_order_changed"
        if current.get("action_kind") != expected.get("action_kind") or current.get("required_capability") != expected.get("required_capability"):
            return "step_action_changed"
        if (
            current.get("target_candidate_id") != expected.get("target_candidate_id")
            or current.get("target_fingerprint") != expected.get("target_fingerprint")
            or current.get("target_phrase") != expected.get("target_phrase")
        ):
            return "step_target_changed"
        if current.get("expected_outcome") != expected.get("expected_outcome"):
            return "step_expected_outcome_changed"
        if current.get("args") != expected.get("args"):
            return "step_argument_changed"
        return "plan_fingerprint_mismatch"
    return "plan_fingerprint_mismatch"


def _mark_task_steps_skipped(
    plan: BrowserSemanticTaskPlan,
    *,
    start_index: int,
) -> list[BrowserSemanticTaskStep]:
    skipped: list[BrowserSemanticTaskStep] = []
    for step in plan.steps[start_index:]:
        if step.status in {"pending", "approval_required"}:
            step.status = "skipped"
            step.limitations = list(dict.fromkeys(list(step.limitations) + ["skipped_after_prior_step_stop", "no_action_attempted"]))
            skipped.append(step)
    return skipped


def _redacted_task_step_args(action_kind: str, action_arguments: dict[str, Any]) -> dict[str, Any]:
    if action_kind in _SAFE_TASK_ACTION_KINDS:
        return _redacted_action_arguments(action_kind, action_arguments)
    return {}


def _task_step_binding_payload(step: BrowserSemanticTaskStep) -> dict[str, Any]:
    args = dict(step.action_args_redacted or {})
    binding_args = {
        key: args.get(key)
        for key in sorted(args)
        if key
        in {
            "typed_text_redacted",
            "text_length",
            "text_fingerprint",
            "text_classification",
            "mode",
            "option_fingerprint",
            "option_request_fingerprint",
            "option_ordinal",
            "expected_checked_state",
            "direction",
            "amount_pixels",
            "max_attempts",
            "target_phrase",
            "scroll_fingerprint",
        }
    }
    return {
        "step_index": step.step_index,
        "action_kind": step.action_kind,
        "target_candidate_id": step.target_candidate_id,
        "target_fingerprint": step.target_fingerprint,
        "target_phrase": _bounded_text(step.target_phrase, 120),
        "required_capability": step.required_capability,
        "expected_outcome": list(step.expected_outcome)[:8],
        "args": binding_args,
    }


def _task_step_binding_fingerprint(step: BrowserSemanticTaskStep) -> str:
    payload = json.dumps(_task_step_binding_payload(step), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _task_plan_binding_fingerprint(plan: BrowserSemanticTaskPlan) -> str:
    payload = {
        "plan_id": plan.plan_id,
        "plan_kind": plan.plan_kind,
        "steps": [_task_step_binding_payload(step) for step in plan.steps],
        "expected_final_state": list(plan.expected_final_state)[:8],
        "claim_ceiling": plan.claim_ceiling,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8", errors="ignore")).hexdigest()[:24]


def _coerce_task_step(value: BrowserSemanticTaskStep | dict[str, Any]) -> BrowserSemanticTaskStep:
    if isinstance(value, BrowserSemanticTaskStep):
        return value
    payload = dict(value or {})
    return BrowserSemanticTaskStep(
        step_id=_bounded_text(payload.get("step_id") or "", 80) or f"browser-semantic-task-step-{uuid4().hex[:12]}",
        step_index=_safe_int(payload.get("step_index"), default=0),
        action_kind=_bounded_text(payload.get("action_kind") or "unsupported", 40),
        target_phrase=_bounded_text(payload.get("target_phrase") or "", 120),
        target_candidate_id=_bounded_text(payload.get("target_candidate_id") or "", 80),
        target_fingerprint=_bounded_text(payload.get("target_fingerprint") or "", 220),
        action_args_redacted=dict(payload.get("action_args_redacted") or {}),
        expected_outcome=[_bounded_text(item, 80) for item in list(payload.get("expected_outcome") or [])[:8]],
        required_capability=_bounded_text(payload.get("required_capability") or "", 80),
        approval_binding_fingerprint=_bounded_text(payload.get("approval_binding_fingerprint") or "", 80),
        status=_bounded_text(payload.get("status") or "pending", 40),
        verification_result_id=_bounded_text(payload.get("verification_result_id") or "", 80),
        limitations=[_bounded_text(item, 120) for item in list(payload.get("limitations") or [])[:8] if _bounded_text(item, 120)],
    )


def _coerce_task_plan(value: BrowserSemanticTaskPlan | dict[str, Any]) -> BrowserSemanticTaskPlan:
    if isinstance(value, BrowserSemanticTaskPlan):
        return value
    payload = dict(value or {})
    steps = [_coerce_task_step(item) for item in list(payload.get("steps") or [])]
    return BrowserSemanticTaskPlan(
        plan_id=_bounded_text(payload.get("plan_id") or "", 80) or f"browser-semantic-task-plan-{uuid4().hex[:12]}",
        source_observation_id=_bounded_text(payload.get("source_observation_id") or "", 80),
        provider=_bounded_text(payload.get("provider") or "playwright_live_semantic", 80),
        plan_kind=_bounded_text(payload.get("plan_kind") or "safe_browser_sequence", 80),
        steps=steps,
        max_steps=_safe_int(payload.get("max_steps"), default=5),
        risk_level=_bounded_text(payload.get("risk_level") or "medium", 40),
        approval_required=bool(payload.get("approval_required", True)),
        approval_request_id=_bounded_text(payload.get("approval_request_id") or "", 80),
        approval_grant_id=_bounded_text(payload.get("approval_grant_id") or "", 80),
        executable_now=bool(payload.get("executable_now", False)),
        reason_not_executable=_bounded_text(payload.get("reason_not_executable") or "", 120),
        expected_final_state=[_bounded_text(item, 160) for item in list(payload.get("expected_final_state") or [])[:8]],
        stop_policy=dict(payload.get("stop_policy") or {}),
        created_at=_bounded_text(payload.get("created_at") or "", 80),
        expires_at=_bounded_text(payload.get("expires_at") or "", 80),
        limitations=[_bounded_text(item, 120) for item in list(payload.get("limitations") or [])[:12] if _bounded_text(item, 120)],
        approval_binding_fingerprint=_bounded_text(payload.get("approval_binding_fingerprint") or "", 80),
        source_task_phrase=_bounded_text(payload.get("source_task_phrase") or "", 240),
        user_message=_bounded_text(payload.get("user_message") or "", 240),
    )


def _trust_task_plan_request(plan: BrowserSemanticTaskPlan, *, session_id: str, task_id: str) -> TrustActionRequest:
    binding = _task_plan_binding_fingerprint(plan)
    return TrustActionRequest(
        request_id=f"trust-playwright-task-{uuid4().hex[:12]}",
        family="screen_awareness",
        action_key=f"screen_awareness.playwright.task_plan.{plan.plan_id}.{binding}",
        subject=_bounded_text(f"safe browser task plan with {len(plan.steps)} step(s)", 120),
        session_id=session_id or "default",
        task_id=task_id,
        action_kind=TrustActionKind.TOOL,
        approval_required=True,
        preview_allowed=False,
        suggested_scope=PermissionScope.ONCE,
        available_scopes=[PermissionScope.ONCE, PermissionScope.SESSION, PermissionScope.TASK],
        operator_justification="Playwright would execute a short sequence of safe browser primitives inside an isolated temporary browser context.",
        operator_message="Approval is required before Stormhelm can run this safe browser task plan.",
        verification_label="Per-step semantic before/after browser comparison",
        details={
            "plan_id": plan.plan_id,
            "plan_kind": plan.plan_kind,
            "step_count": len(plan.steps),
            "ordered_step_bindings": [_task_step_binding_payload(step) for step in plan.steps],
            "approval_binding_fingerprint": binding,
            "risk_level": plan.risk_level,
            "provider": plan.provider,
            "claim_ceiling": _TASK_EXECUTION_CLAIM_CEILING,
            "expected_final_state": list(plan.expected_final_state)[:8],
        },
    )


def _task_plan_summary(plan: BrowserSemanticTaskPlan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "status": "plan_created",
        "plan_kind": plan.plan_kind,
        "step_count": len(plan.steps),
        "max_steps": plan.max_steps,
        "risk_level": plan.risk_level,
        "approval_required": plan.approval_required,
        "executable_now": plan.executable_now,
        "reason_not_executable": plan.reason_not_executable,
        "claim_ceiling": plan.claim_ceiling,
        "limitations": list(plan.limitations)[:8],
        "steps": [step.to_dict() for step in plan.steps[:8]],
        "user_message": _bounded_text(plan.user_message, 240),
    }


def _task_execution_summary(result: BrowserSemanticTaskExecutionResult) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "plan_id": result.plan_id,
        "status": result.status,
        "completed_step_count": result.completed_step_count,
        "blocked_step_id": result.blocked_step_id,
        "failure_reason": result.failure_reason,
        "final_verification_status": result.final_verification_status,
        "cleanup_status": result.cleanup_status,
        "action_attempted": result.action_attempted,
        "approval_request_id": result.approval_request_id,
        "approval_grant_id": result.approval_grant_id,
        "provider": result.provider,
        "claim_ceiling": result.claim_ceiling,
        "limitations": list(result.limitations)[:8],
        "step_results": [_action_execution_summary(step) for step in result.step_results[:8]],
        "user_message": _bounded_text(result.user_message, 240),
    }


def _task_plan_event_payload(plan: BrowserSemanticTaskPlan, *, status: str = "plan_created") -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "status": status,
        "plan_kind": plan.plan_kind,
        "step_count": len(plan.steps),
        "risk_level": plan.risk_level,
        "approval_required": plan.approval_required,
        "claim_ceiling": plan.claim_ceiling,
        "limitations": list(plan.limitations)[:8],
        "steps": [
            {
                "step_id": step.step_id,
                "step_index": step.step_index,
                "action_kind": step.action_kind,
                "target_phrase": _bounded_text(step.target_phrase, 120),
                "target_candidate_id": step.target_candidate_id,
                "redacted_args": dict(step.action_args_redacted),
                "status": step.status,
            }
            for step in plan.steps[:8]
        ],
    }


def _task_step_event_payload(
    plan: BrowserSemanticTaskPlan,
    step: BrowserSemanticTaskStep,
    *,
    result: BrowserSemanticActionExecutionResult | None = None,
    status: str = "",
) -> dict[str, Any]:
    payload = {
        "plan_id": plan.plan_id,
        "step_id": step.step_id,
        "step_index": step.step_index,
        "action_kind": step.action_kind,
        "target_summary": {
            "target_phrase": _bounded_text(step.target_phrase, 120),
            "target_candidate_id": step.target_candidate_id,
        },
        "redacted_args": dict(step.action_args_redacted),
        "step_status": status or step.status,
        "claim_ceiling": _TASK_EXECUTION_CLAIM_CEILING,
        "limitations": list(step.limitations)[:8],
    }
    if result is not None:
        payload.update(
            {
                "execution_status": result.status,
                "verification_status": result.verification_status,
                "before_observation_id": result.before_observation_id,
                "after_observation_id": result.after_observation_id,
                "error_code": result.error_code,
                "action_attempted": result.action_attempted,
            }
        )
    return payload


def _task_execution_event_payload(result: BrowserSemanticTaskExecutionResult) -> dict[str, Any]:
    return {
        "plan_id": result.plan_id,
        "result_id": result.result_id,
        "final_status": result.status,
        "completed_step_count": result.completed_step_count,
        "blocked_step_id": result.blocked_step_id,
        "stop_reason": result.failure_reason,
        "final_verification_status": result.final_verification_status,
        "cleanup_status": result.cleanup_status,
        "claim_ceiling": result.claim_ceiling,
        "limitations": list(result.limitations)[:8],
        "steps": [
            {
                "action_kind": step.action_kind,
                "status": step.status,
                "verification_status": step.verification_status,
                "target": dict(step.target_summary),
                "text_redacted_summary": step.text_redacted_summary,
                "option_redacted_summary": step.option_redacted_summary,
                "scroll_target_phrase": step.scroll_target_phrase,
            }
            for step in result.step_results[:8]
        ],
    }


def _task_execution_event_message(result: BrowserSemanticTaskExecutionResult) -> str:
    if result.status == "approval_required":
        return "Playwright safe browser task plan approval is required."
    if result.status == "completed_verified":
        return "Playwright safe browser task plan verification completed."
    if result.status.startswith("stopped_"):
        return "Playwright safe browser task plan stopped."
    if result.status in {"blocked", "unsupported"}:
        return "Playwright safe browser task plan was blocked."
    if result.status == "failed":
        return "Playwright safe browser task plan failed."
    return "Playwright safe browser task plan state updated."


def _task_step_audit_summary(step: BrowserSemanticTaskStep, result: BrowserSemanticActionExecutionResult) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "step_index": step.step_index,
        "action_kind": step.action_kind,
        "target_candidate_id": step.target_candidate_id,
        "status": result.status,
        "action_attempted": result.action_attempted,
        "verification_status": result.verification_status,
        "typed_text_redacted": result.typed_text_redacted,
        "text_redacted_summary": result.text_redacted_summary,
        "option_redacted_summary": result.option_redacted_summary,
        "scroll_target_phrase": result.scroll_target_phrase,
        "error_code": result.error_code,
    }


def _risk_level_from_plan(plan: BrowserSemanticActionPlan) -> str:
    target = dict(plan.target_candidate or {})
    risk = str(target.get("risk_level") or "").strip().lower()
    if risk:
        return _bounded_text(risk, 40)
    if plan.action_kind == "type_text":
        return "high"
    if plan.action_kind == "focus":
        return "low"
    if plan.action_kind in {"scroll", "scroll_to_target"}:
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
    text_fingerprint = _bounded_text(request.text_fingerprint or "", 80)
    option_fingerprint = _bounded_text(request.option_fingerprint or "", 80)
    scroll_fingerprint = _bounded_text(request.scroll_fingerprint or "", 80)
    if plan.action_kind == "type_text":
        action_key_tail = f"{target_fingerprint}.{text_fingerprint}"
    elif plan.action_kind == "select_option":
        action_key_tail = f"{target_fingerprint}.{option_fingerprint}"
    elif plan.action_kind in {"scroll", "scroll_to_target"}:
        action_key_tail = f"{target_fingerprint}.{scroll_fingerprint}"
    else:
        action_key_tail = target_fingerprint
    subject = f"{plan.action_kind} {target.get('role') or 'target'} {target.get('name') or target.get('label') or ''}".strip()
    return TrustActionRequest(
        request_id=f"trust-playwright-action-{uuid4().hex[:12]}",
        family="screen_awareness",
        action_key=f"screen_awareness.playwright.{plan.action_kind}.{plan.plan_id}.{action_key_tail}",
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
        operator_message=(
            f"Approval is required before Stormhelm can type redacted text into {target.get('name') or 'this browser target'}."
            if plan.action_kind == "type_text"
            else f"Approval is required before Stormhelm can change {target.get('name') or 'this browser choice control'}."
            if plan.action_kind in {"check", "uncheck", "select_option"}
            else f"Approval is required before Stormhelm can perform bounded browser scrolling."
            if plan.action_kind in {"scroll", "scroll_to_target"}
            else f"Approval is required before Stormhelm can {plan.action_kind} {target.get('name') or 'this browser target'}."
        ),
        verification_label="Semantic before/after browser comparison",
        details={
            "plan_id": plan.plan_id,
            "preview_id": plan.preview_id,
            "action_kind": plan.action_kind,
            "target_fingerprint": target_fingerprint,
            "target": target,
            "claim_ceiling": _ACTION_EXECUTION_CLAIM_CEILING,
            "expected_outcome": list(request.expected_outcome)[:8],
            "typed_text_redacted": request.typed_text_redacted,
            "text_redacted_summary": request.text_redacted_summary,
            "text_length": request.text_length,
            "text_fingerprint": text_fingerprint,
            "text_classification": request.text_classification,
            "option_redacted_summary": request.option_redacted_summary,
            "option_fingerprint": option_fingerprint,
            "option_ordinal": request.option_ordinal,
            "expected_checked_state": request.expected_checked_state,
            "scroll_direction": request.scroll_direction,
            "scroll_amount_pixels": request.scroll_amount_pixels,
            "scroll_max_attempts": request.scroll_max_attempts,
            "scroll_target_phrase": request.scroll_target_phrase,
            "scroll_fingerprint": scroll_fingerprint,
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
            resolved = dict(control)
            if (role and control_role and role != control_role) or (
                name and control_name and name != control_name and name != control_label
            ) or (label and control_label and label != control_label and label != control_name):
                resolved["_target_drift"] = True
                resolved["_expected_role"] = role
                resolved["_expected_name"] = name
                resolved["_expected_label"] = label
            matches.append(resolved)
            continue
        if role and control_role != role:
            continue
        if name and (control_name == name or control_label == name):
            matches.append(control)
        elif label and (control_label == label or control_name == label):
            matches.append(control)
    if not matches:
        return {"_execution_blocker": "target_missing"}
    if len(matches) > 1:
        return {"_execution_blocker": "target_ambiguous", "match_count": len(matches)}
    return matches[0]


def _sensitive_target_haystack(haystack: str) -> bool:
    sensitive_terms = (
        "password",
        "passcode",
        "secret",
        "token",
        "api key",
        "apikey",
        "credential",
        "login",
        "sign in",
        "signin",
        "2fa",
        "mfa",
        "otp",
        "recovery code",
        "captcha",
        "payment",
        "billing",
        "card",
        "cvv",
        "cvc",
        "checkout",
        "purchase",
        "ssn",
        "social security",
        "bank",
        "routing",
        "account number",
        "profile",
        "sensitive",
        "terms",
        "terms agreement",
        "legal",
        "consent",
        "privacy",
        "privacy consent",
        "authorize",
        "authorization",
        "delete",
        "permanent",
        "charge my card",
        "save payment",
        "remember me",
        "robot",
        "human verification",
        "trust this device",
        "age",
        "compliance",
        "account deletion",
        "export",
        "unsubscribe",
        "remove my data",
        "security",
    )
    return any(term in haystack for term in sensitive_terms)


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
    if _sensitive_target_haystack(haystack):
        return "target_sensitive"
    if any(term in haystack for term in ("file input", "file upload", "upload file", "upload")):
        return "target_uneditable"
    if target.get("visible") is False:
        return "target_hidden"
    if target.get("enabled") is False:
        return "target_disabled"
    if target.get("readonly") is True:
        return "target_readonly"
    if (
        target.get("_target_drift")
        and action_kind in {"check", "uncheck", "select_option"}
        and _canonical_role(str(target.get("_expected_role") or ""))
        and role != _canonical_role(str(target.get("_expected_role") or ""))
    ):
        return "target_type_changed"
    if target.get("_target_drift"):
        return "target_drift"
    if action_kind == "click" and role not in {"button", "link"}:
        return "click_target_role_not_allowed"
    if action_kind == "focus" and role not in {"textbox", "button", "link", "checkbox", "radio", "combobox"}:
        return "focus_target_role_not_allowed"
    if action_kind == "type_text":
        if role not in {"textbox", "searchbox"}:
            return "target_uneditable"
        if any(term in haystack for term in ("readonly", "read only", "hidden", "file input", "upload")):
            if "readonly" in haystack or "read only" in haystack:
                return "target_readonly"
            if "hidden" in haystack:
                return "target_hidden"
            return "target_uneditable"
    if action_kind == "check" and role not in {"checkbox", "radio"}:
        return "target_type_changed"
    if action_kind == "uncheck" and role != "checkbox":
        return "target_type_changed"
    if action_kind == "select_option" and role not in {"combobox", "select"}:
        return "target_type_changed"
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
                    return None, "locator_missing"
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
            return None, "locator_missing"
        if count == 1:
            return locator, ""
        if count > 1:
            return None, "locator_ambiguous"
    return None, "locator_missing"


def _expected_checked_state_for_action(action_kind: str) -> bool | None:
    if action_kind == "check":
        return True
    if action_kind == "uncheck":
        return False
    return None


def _choice_already_in_expected_state(action_kind: str, target: dict[str, Any]) -> bool:
    expected = _expected_checked_state_for_action(action_kind)
    if expected is None:
        return False
    return target.get("checked") is expected


def _select_option_already_in_expected_state(plan: BrowserSemanticActionPlan, selected_option: dict[str, Any]) -> bool:
    if plan.action_kind != "select_option":
        return False
    return bool(selected_option.get("selected"))


def _select_option_for_execution(
    plan: BrowserSemanticActionPlan,
    target: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if plan.action_kind != "select_option":
        return {}, ""
    raw = getattr(plan, "action_arguments_private", {}) or {}
    option_label = _option_value(raw)
    option_ordinal = _safe_int(raw.get("ordinal"), default=0)
    options = _bounded_choice_options(target.get("options"))
    if not options:
        return {}, "options_unavailable"
    if option_label:
        matches = [option for option in options if _normalize(option.get("label") or "") == _normalize(option_label)]
    elif option_ordinal > 0:
        matches = [option for option in options if _safe_int(option.get("ordinal"), default=0) == option_ordinal]
    else:
        return {}, "option_missing"
    if not matches:
        return {}, "option_not_found"
    if len(matches) > 1:
        return {}, "option_ambiguous"
    option = dict(matches[0])
    if option.get("disabled"):
        return {}, "option_disabled"
    haystack = _normalize(" ".join(str(option.get(key) or "") for key in ("label", "value_summary")))
    if _sensitive_target_haystack(haystack):
        return {}, "option_sensitive"
    if isinstance(plan.action_arguments_redacted, dict):
        stored_fingerprint = _bounded_text(plan.action_arguments_redacted.get("option_fingerprint") or "", 80)
        request_fingerprint = _bounded_text(plan.action_arguments_redacted.get("option_request_fingerprint") or "", 80)
        if stored_fingerprint and stored_fingerprint != request_fingerprint:
            current_fingerprint = _option_fingerprint(
                str(option.get("label") or ""),
                str(option.get("value_summary") or ""),
                _safe_int(option.get("ordinal"), default=0),
            )
            if current_fingerprint != stored_fingerprint:
                return {}, "option_drift"
    return option, ""


def _scroll_details_from_plan(
    plan: BrowserSemanticActionPlan,
    request: BrowserSemanticActionExecutionRequest,
) -> dict[str, Any]:
    private_args = dict(getattr(plan, "action_arguments_private", {}) or {})
    return {
        "direction": _bounded_text(private_args.get("direction") or request.scroll_direction or "down", 20),
        "amount_pixels": _safe_int(private_args.get("amount_pixels") or request.scroll_amount_pixels, default=700),
        "max_attempts": _safe_int(private_args.get("max_attempts") or request.scroll_max_attempts, default=1),
        "target_phrase": _bounded_text(private_args.get("target_phrase") or request.scroll_target_phrase or "", 120),
    }


def _scroll_context_blocker(observation: BrowserSemanticObservation) -> str:
    if _page_context_looks_sensitive(observation):
        return "target_sensitive"
    return ""


def _action_context_blocker(observation: BrowserSemanticObservation, action_kind: str) -> str:
    if action_kind in {"scroll", "scroll_to_target"}:
        return ""
    if _page_context_looks_sensitive(observation):
        return "sensitive_page_context"
    return ""


def _page_context_looks_sensitive(observation: BrowserSemanticObservation) -> bool:
    page_haystack = _normalize(" ".join([str(observation.page_url or ""), str(observation.page_title or "")]))
    restricted_terms = (
        "captcha",
        "robot verification",
        "human verification",
        "payment",
        "checkout",
        "billing",
        "credit card",
        "login",
        "log in",
        "sign in",
        "signin",
        "security",
        "profile",
        "account",
        "delete",
        "destructive",
        "permanent",
        "legal consent",
        "terms agreement",
        "privacy consent",
    )
    return any(term in page_haystack for term in restricted_terms)


def _safe_scroll_state(page: Any) -> dict[str, Any]:
    try:
        value = page.evaluate(
            "() => ({__stormhelmScrollState: true, x: Number(window.scrollX || 0), y: Number(window.scrollY || 0), max_y: Math.max(0, Number(document.documentElement.scrollHeight || 0) - Number(window.innerHeight || 0)), at_top: Number(window.scrollY || 0) <= 0, at_bottom: Number(window.scrollY || 0) >= Math.max(0, Number(document.documentElement.scrollHeight || 0) - Number(window.innerHeight || 0))})"
        )
    except Exception:
        return {}
    if not isinstance(value, dict):
        return {}
    return {
        "x": _safe_int(value.get("x"), default=0),
        "y": _safe_int(value.get("y"), default=0),
        "max_y": _safe_int(value.get("max_y"), default=0),
        "at_top": bool(value.get("at_top", False)),
        "at_bottom": bool(value.get("at_bottom", False)),
    }


def _perform_scroll(page: Any, direction: str, amount_pixels: int) -> None:
    delta = abs(int(amount_pixels or 0))
    if delta <= 0:
        delta = 700
    if _normalize(direction) == "up":
        delta = -delta
    mouse = getattr(page, "mouse", None)
    wheel = getattr(mouse, "wheel", None)
    if not callable(wheel):
        raise RuntimeError("Playwright page mouse wheel is unavailable for bounded scroll.")
    wheel(0, delta)


def _scroll_target_match(
    observation: BrowserSemanticObservation,
    target_phrase: str,
) -> tuple[dict[str, Any] | None, str]:
    phrase = _normalize(target_phrase)
    if not phrase:
        return None, "target_missing"
    matches: list[dict[str, Any]] = []
    for control in observation.controls:
        control_map = control.to_dict()
        haystack = _normalize(
            " ".join(
                str(control_map.get(key) or "")
                for key in ("control_id", "role", "name", "label", "text", "risk_hint")
            )
        )
        phrase_terms = [term for term in phrase.split() if len(term) > 1 and term not in {"the", "a", "an", "to"}]
        if phrase not in haystack and haystack not in phrase and not all(term in haystack for term in phrase_terms):
            continue
        role = _canonical_role(str(control_map.get("role") or ""))
        if _sensitive_target_haystack(haystack) and not (role == "link" and "privacy policy" in haystack):
            return None, "target_sensitive"
        if control_map.get("visible") is False:
            continue
        matches.append(control_map)
    if not matches:
        return None, "target_missing"
    if len(matches) > 1:
        return None, "target_ambiguous"
    return matches[0], ""


def _safe_submit_counter(page: Any) -> int | None:
    try:
        value = page.evaluate("() => Number(window.__stormhelmSubmitCount || 0)")
    except Exception:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _submit_counter_changed(before: int | None, after: int | None) -> bool:
    if before is None or after is None:
        return False
    return after != before


def _choice_unexpected_navigation(before: BrowserSemanticObservation, after: BrowserSemanticObservation) -> bool:
    before_url = str(before.page_url or "").strip()
    after_url = str(after.page_url or "").strip()
    return bool(before_url and after_url and before_url != after_url)


def _warning_keys(observation: BrowserSemanticObservation) -> set[str]:
    keys: set[str] = set()
    for item in list(observation.alerts or []) + list(observation.dialogs or []):
        if not isinstance(item, dict):
            continue
        role = _normalize(str(item.get("role") or ""))
        name = _normalize(str(item.get("name") or ""))
        text = _normalize(str(item.get("text") or ""))
        item_id = _normalize(str(item.get("alert_id") or item.get("dialog_id") or ""))
        if role in {"alert", "dialog"} or name or text or item_id:
            keys.add("|".join([role, name, text, item_id]))
    return keys


def _choice_unexpected_warning_added(before: BrowserSemanticObservation, after: BrowserSemanticObservation) -> bool:
    return bool(_warning_keys(after) - _warning_keys(before))


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
            expected_state=_expected_checked_state_for_action(plan.action_kind),
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
        if action_kind == "type_text":
            return "verified_supported", "supported", "Text entered; semantic verification supports the field changed."
        if action_kind in {"check", "uncheck", "select_option"}:
            return "verified_supported", "supported", "Choice updated; semantic verification supports the change."
        return "verified_supported", "supported", comparison.user_message or "The expected semantic change is supported."
    if comparison.status == "partial":
        return "partial", "partial", comparison.user_message or "I found a related semantic change, but not the full expected outcome."
    if comparison.status == "ambiguous":
        return "ambiguous", "ambiguous", comparison.user_message or "The semantic comparison is ambiguous."
    if comparison.status == "unsupported":
        if action_kind == "focus":
            return "completed_unverified", "unsupported", "Focus was attempted, but semantic comparison did not support the expected change."
        if action_kind == "type_text":
            change_types = {change.change_type for change in comparison.changes}
            if not change_types:
                return "verified_unsupported", "unsupported", "Typing was attempted, but the semantic snapshots show the field did not change."
            if "value_summary_changed" not in change_types:
                return "completed_unverified", "unsupported", "Typing was attempted, but the field value could not be verified from semantic snapshots."
            return "verified_unsupported", "unsupported", "Typing was attempted, but semantic comparison did not support the expected field change."
        if action_kind in {"check", "uncheck", "select_option"}:
            change_types = {change.change_type for change in comparison.changes}
            if not change_types:
                return "verified_unsupported", "unsupported", "Choice action was attempted, but the semantic snapshots show the selected state did not change."
            return "completed_unverified", "unsupported", "Choice action was attempted, but I could not verify the selected state."
        return "verified_unsupported", "unsupported", "The action was attempted, but the expected semantic change is not supported."
    return "completed_unverified", comparison.status, "The action was attempted, but I could not verify the expected change from semantic snapshots."


def _scroll_position_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if not before or not after:
        return False
    return _safe_int(before.get("y"), default=0) != _safe_int(after.get("y"), default=0)


def _scroll_execution_status(
    plan: BrowserSemanticActionPlan,
    comparison: BrowserSemanticVerificationResult | None,
    before_scroll: dict[str, Any],
    after_scroll: dict[str, Any],
    *,
    target_found: bool,
    target_ambiguous: bool,
    target_sensitive: bool,
) -> tuple[str, str, str]:
    if target_sensitive:
        return "blocked", "blocked", "Scroll target appears sensitive."
    if target_ambiguous:
        return "ambiguous", "ambiguous", "Scroll target became ambiguous within the bounded scroll limit."
    if plan.action_kind == "scroll_to_target":
        if target_found:
            return "verified_supported", "supported", "Scroll attempted; target found."
        if comparison is not None and comparison.status == "partial":
            return "partial", "partial", "I could not find that target within the bounded scroll limit, though related page content changed."
        return "partial", "not_found", "I could not find that target within the bounded scroll limit."
    if _scroll_position_changed(before_scroll, after_scroll):
        return "verified_supported", "supported", "Scroll attempted; semantic evidence supports that the page position changed."
    if comparison is not None and comparison.status == "supported":
        return "verified_supported", "supported", comparison.user_message or "Scroll attempted; semantic evidence supports a page change."
    if comparison is not None and comparison.status == "partial":
        return "partial", "partial", comparison.user_message or "Scroll attempted and related semantic content changed."
    if comparison is not None and comparison.status == "ambiguous":
        return "ambiguous", "ambiguous", comparison.user_message or "Scroll comparison is ambiguous."
    if comparison is not None and comparison.status == "unsupported":
        return "verified_unsupported", "unsupported", "Scroll was attempted, but semantic evidence did not show the expected change."
    return "completed_unverified", "unavailable", "Scroll attempted, but I could not verify a semantic change."


def _action_execution_limitations(comparison_limitations: Sequence[str]) -> list[str]:
    action_limits = [
        "isolated_temporary_browser_context",
        "no_user_profile",
        "not_visible_screen_verification",
        "not_truth_verified",
    ]
    observation_only = {"no_actions"}
    for item in comparison_limitations:
        text = str(item or "").strip()
        if text and text not in observation_only:
            action_limits.append(text)
    return list(dict.fromkeys(action_limits))


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
        if action_kind == "type_text":
            return "Text entered; semantic verification supports the field changed."
        if action_kind in {"check", "uncheck", "select_option"}:
            return "Choice updated; semantic verification supports the change."
        if action_kind in {"scroll", "scroll_to_target"}:
            return "Scroll attempted; semantic verification supports the change."
        return f"The semantic snapshots support the expected result of the {action_kind}."
    if status == "verified_unsupported":
        return f"The {action_kind} was attempted, but the expected semantic change is not supported."
    if status == "completed_unverified":
        if action_kind == "type_text":
            return "Typing was attempted, but the field value could not be verified from semantic snapshots."
        if action_kind in {"check", "uncheck", "select_option"}:
            return "Choice action was attempted, but I could not verify the selected state."
        if action_kind in {"scroll", "scroll_to_target"}:
            return "Scroll attempted, but I could not verify a semantic change."
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
        "typed_text_redacted": result.typed_text_redacted,
        "text_redacted_summary": result.text_redacted_summary,
        "text_length": result.text_length,
        "text_classification": result.text_classification,
        "option_redacted_summary": result.option_redacted_summary,
        "option_ordinal": result.option_ordinal,
        "expected_checked_state": result.expected_checked_state,
        "scroll_direction": result.scroll_direction,
        "scroll_amount_pixels": result.scroll_amount_pixels,
        "scroll_max_attempts": result.scroll_max_attempts,
        "scroll_target_phrase": result.scroll_target_phrase,
        "scroll_target_found": result.scroll_target_found,
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
    payload = {
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
    if plan.action_kind == "type_text":
        payload.update(
            {
                "typed_text_redacted": True,
                "text_redacted_summary": request.text_redacted_summary,
                "text_length": request.text_length,
                "text_classification": request.text_classification,
            }
        )
    if plan.action_kind in {"check", "uncheck", "select_option"}:
        payload.update(
            {
                "option_redacted_summary": request.option_redacted_summary,
                "option_ordinal": request.option_ordinal,
                "expected_checked_state": request.expected_checked_state,
                "submit_prevented": True,
            }
        )
    if plan.action_kind in {"scroll", "scroll_to_target"}:
        payload.update(
            {
                "scroll_direction": request.scroll_direction,
                "scroll_amount_pixels": request.scroll_amount_pixels,
                "scroll_max_attempts": request.scroll_max_attempts,
                "target_phrase": request.scroll_target_phrase,
                "side_effects_prevented": True,
            }
        )
    return payload


def _action_execution_event_payload(result: BrowserSemanticActionExecutionResult) -> dict[str, Any]:
    payload = {
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
    if result.action_kind == "type_text":
        payload.update(
            {
                "typed_text_redacted": True,
                "text_redacted_summary": result.text_redacted_summary,
                "text_length": result.text_length,
                "text_classification": result.text_classification,
            }
        )
    if result.action_kind in {"check", "uncheck", "select_option"}:
        payload.update(
            {
                "option_redacted_summary": result.option_redacted_summary,
                "option_ordinal": result.option_ordinal,
                "expected_checked_state": result.expected_checked_state,
                "submit_prevented": "unexpected_form_submission" not in result.limitations,
            }
        )
    if result.action_kind in {"scroll", "scroll_to_target"}:
        payload.update(
            {
                "scroll_direction": result.scroll_direction,
                "scroll_amount_pixels": result.scroll_amount_pixels,
                "scroll_max_attempts": result.scroll_max_attempts,
                "target_phrase": result.scroll_target_phrase,
                "target_found": result.scroll_target_found,
                "side_effects_prevented": "unexpected_form_submission" not in result.limitations,
            }
        )
    return payload


def _action_execution_event_message(result: BrowserSemanticActionExecutionResult) -> str:
    if result.action_kind == "type_text":
        if result.status == "approval_required":
            return "Playwright browser typing approval is required."
        if result.status in {"blocked", "unsupported", "ambiguous"}:
            return "Playwright browser typing was blocked."
        if result.status == "failed":
            return "Playwright browser typing failed."
        if result.status in {"verified_supported", "verified_unsupported", "partial", "completed_unverified"}:
            return "Playwright browser typing verification completed."
        return "Playwright browser typing state updated."
    if result.action_kind in {"check", "uncheck", "select_option"}:
        if result.status == "approval_required":
            return "Playwright browser choice-control approval is required."
        if result.status in {"blocked", "unsupported", "ambiguous"}:
            return "Playwright browser choice-control action was blocked."
        if result.status == "failed":
            return "Playwright browser choice-control action failed."
        if result.status in {"verified_supported", "verified_unsupported", "partial", "completed_unverified"}:
            return "Playwright browser choice-control verification completed."
        return "Playwright browser choice-control state updated."
    if result.action_kind in {"scroll", "scroll_to_target"}:
        if result.status == "approval_required":
            return "Playwright browser scroll approval is required."
        if result.status in {"blocked", "unsupported", "ambiguous"}:
            return "Playwright browser scroll was blocked."
        if result.status == "failed":
            return "Playwright browser scroll failed."
        if result.status in {"verified_supported", "verified_unsupported", "partial", "completed_unverified"}:
            return "Playwright browser scroll verification completed."
        return "Playwright browser scroll state updated."
    if result.status == "approval_required":
        return "Playwright browser action approval is required."
    if result.status in {"blocked", "unsupported", "ambiguous"}:
        return "Playwright browser action execution was blocked."
    if result.status == "failed":
        return "Playwright browser action execution failed."
    if result.status in {"verified_supported", "verified_unsupported", "partial", "completed_unverified"}:
        return "Playwright browser action verification completed."
    return "Playwright browser action execution state updated."


def _action_event_type(action_kind: str, generic: str, type_text_event: str) -> str:
    if action_kind == "type_text":
        return type_text_event
    if action_kind in {"check", "uncheck", "select_option"}:
        mapping = {
            "screen_awareness.playwright_action_execution_requested": "screen_awareness.playwright_choice_request_created",
            "screen_awareness.playwright_action_approval_required": "screen_awareness.playwright_choice_approval_required",
            "screen_awareness.playwright_action_execution_started": "screen_awareness.playwright_choice_execution_started",
            "screen_awareness.playwright_action_execution_attempted": "screen_awareness.playwright_choice_attempted",
            "screen_awareness.playwright_action_after_observation_captured": "screen_awareness.playwright_choice_after_observation_captured",
            "screen_awareness.playwright_action_verification_completed": "screen_awareness.playwright_choice_verification_completed",
            "screen_awareness.playwright_action_execution_blocked": "screen_awareness.playwright_choice_blocked",
            "screen_awareness.playwright_action_execution_failed": "screen_awareness.playwright_choice_failed",
        }
        return mapping.get(generic, generic)
    if action_kind in {"scroll", "scroll_to_target"}:
        mapping = {
            "screen_awareness.playwright_action_execution_requested": "screen_awareness.playwright_scroll_request_created",
            "screen_awareness.playwright_action_approval_required": "screen_awareness.playwright_scroll_approval_required",
            "screen_awareness.playwright_action_execution_started": "screen_awareness.playwright_scroll_execution_started",
            "screen_awareness.playwright_action_execution_attempted": "screen_awareness.playwright_scroll_attempted",
            "screen_awareness.playwright_action_after_observation_captured": "screen_awareness.playwright_scroll_after_observation_captured",
            "screen_awareness.playwright_action_verification_completed": "screen_awareness.playwright_scroll_verification_completed",
            "screen_awareness.playwright_action_execution_blocked": "screen_awareness.playwright_scroll_blocked",
            "screen_awareness.playwright_action_execution_failed": "screen_awareness.playwright_scroll_failed",
        }
        return mapping.get(generic, generic)
    return generic


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
