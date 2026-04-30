from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


CLAIM_CEILING_RENDERED_PAGE_EVIDENCE = "rendered_page_evidence"
CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE = "headless_cdp_page_evidence"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {str(key): _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


@dataclass(slots=True)
class WebRetrievalProviderCapability:
    provider: str
    can_render_javascript: bool = False
    can_eval_js: bool = False
    can_use_cookies: bool = False
    can_submit_forms: bool = False
    can_click_or_type: bool = False
    can_use_logged_in_context: bool = False
    can_verify_user_visible_screen: bool = False
    supports_parallel: bool = False
    max_parallel_pages: int = 1
    claim_ceiling: str = CLAIM_CEILING_RENDERED_PAGE_EVIDENCE
    limitations: list[str] = field(default_factory=list)

    @classmethod
    def http(cls) -> "WebRetrievalProviderCapability":
        return cls(
            provider="http",
            limitations=["static_http_only", "no_javascript_rendering", "not_truth_verified"],
        )

    @classmethod
    def obscura_cli(cls) -> "WebRetrievalProviderCapability":
        return cls(
            provider="obscura",
            can_render_javascript=True,
            supports_parallel=True,
            max_parallel_pages=3,
            limitations=[
                "public_pages_only",
                "no_logged_in_context",
                "no_form_submission",
                "no_user_visible_screen_claim",
                "not_truth_verified",
            ],
        )

    @classmethod
    def obscura_cdp(cls) -> "WebRetrievalProviderCapability":
        return cls(
            provider="obscura_cdp",
            can_render_javascript=True,
            can_eval_js=False,
            can_use_cookies=False,
            can_submit_forms=False,
            can_click_or_type=False,
            can_use_logged_in_context=False,
            can_verify_user_visible_screen=False,
            supports_parallel=False,
            max_parallel_pages=1,
            claim_ceiling=CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
            limitations=[
                "public_pages_only",
                "headless_cdp_page_evidence",
                "no_runtime_eval",
                "no_input_domain",
                "no_logged_in_context",
                "no_cookies",
                "no_user_visible_screen_claim",
                "not_truth_verified",
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ProviderReadiness:
    provider: str
    status: str
    available: bool = False
    reason: str = ""
    detail: str = ""
    checked_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ObscuraCDPReadiness:
    enabled: bool
    available: bool
    binary_path: str
    host: str
    configured_port: int
    active_port: int = 0
    server_running: bool = False
    cdp_endpoint_url: str = ""
    browser_version: str = ""
    protocol_version: str = ""
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    claim_ceiling: str = CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE
    status: str = "disabled"
    endpoint_status: str = ""
    protocol_compatibility_level: str = ""
    optional_domains: dict[str, Any] = field(default_factory=dict)
    last_startup_error_code: str = ""
    last_navigation_error_code: str = ""
    last_cleanup_status: str = ""
    bounded_error_message: str = ""
    last_compatibility_report: dict[str, Any] = field(default_factory=dict)
    endpoint_discovered: bool = False
    navigation_supported: bool = False
    page_inspection_supported: bool = False
    extraction_supported: bool = False
    diagnostic_only: bool = False
    recommended_fallback_provider: str = ""
    status_message: str = ""
    checked_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ObscuraCDPEndpointDiscovery:
    endpoint_url: str
    version_endpoint_status: str = "unknown"
    version_endpoint_url: str = ""
    browser_websocket_url_found: bool = False
    browser_websocket_url: str = ""
    page_list_endpoint_status: str = "unknown"
    page_list_endpoint_url: str = ""
    page_websocket_url_found: bool = False
    page_websocket_url: str = ""
    protocol_version: str = ""
    browser_name: str = ""
    browser_revision: str = ""
    cdp_domains_available: dict[str, Any] = field(default_factory=dict)
    compatible: bool = False
    compatibility_level: str = "failed"
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bounded_error_message: str = ""
    endpoint_discovered: bool = False
    navigation_supported: bool = False
    page_inspection_supported: bool = False
    extraction_supported: bool = False
    diagnostic_only: bool = False
    recommended_fallback_provider: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ObscuraCDPCompatibilityReport:
    report_id: str = field(default_factory=lambda: f"cdp-compat-{uuid4().hex[:12]}")
    started_at: str = field(default_factory=_utc_now)
    completed_at: str = ""
    binary_path: str = ""
    binary_found: bool = False
    binary_version: str = ""
    host: str = "127.0.0.1"
    port: int = 0
    process_started: bool = False
    process_id: int = 0
    version_endpoint_status: str = "unknown"
    version_endpoint_url: str = ""
    browser_websocket_url_found: bool = False
    page_list_endpoint_status: str = "unknown"
    page_websocket_url_found: bool = False
    protocol_version: str = ""
    browser_name: str = ""
    browser_revision: str = ""
    cdp_domains_available: dict[str, Any] = field(default_factory=dict)
    navigation_probe_status: str = "not_run"
    extraction_probe_status: str = "not_run"
    cleanup_status: str = "not_started"
    compatible: bool = False
    compatibility_level: str = "failed"
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bounded_error_message: str = ""
    raw_output_redacted: bool = True
    endpoint_discovered: bool = False
    navigation_supported: bool = False
    page_inspection_supported: bool = False
    extraction_supported: bool = False
    diagnostic_only: bool = False
    recommended_fallback_provider: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ObscuraCDPSession:
    session_id: str
    process_id: int
    host: str
    active_port: int
    endpoint_url: str
    cdp_endpoint_url: str = ""
    browser_version: str = ""
    protocol_version: str = ""
    started_at: str = field(default_factory=_utc_now)
    stopped_at: str = ""
    page_count: int = 0
    status: str = "active"
    claim_ceiling: str = CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ObscuraCDPPageInspection:
    requested_url: str
    final_url: str
    title: str = ""
    dom_text: str = ""
    html_excerpt: str = ""
    links: list[dict[str, Any]] = field(default_factory=list)
    load_state: str = ""
    network_summary: dict[str, Any] = field(default_factory=dict)
    console_summary: dict[str, Any] = field(default_factory=dict)
    page_id: str = ""
    elapsed_ms: float = 0.0
    safety_status: str = "allowed"
    error_code: str = ""
    bounded_error_message: str = ""
    limitations: list[str] = field(default_factory=list)
    claim_ceiling: str = CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE

    @property
    def dom_text_chars(self) -> int:
        return len(self.dom_text or "")

    @property
    def html_excerpt_chars(self) -> int:
        return len(self.html_excerpt or "")

    @property
    def links_found(self) -> int:
        return len(self.links)

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize(self)
        payload["elapsed_ms"] = round(float(self.elapsed_ms or 0.0), 3)
        payload["dom_text_chars"] = self.dom_text_chars
        payload["html_excerpt_chars"] = self.html_excerpt_chars
        payload["links_found"] = self.links_found
        return payload


@dataclass(slots=True)
class ObscuraCDPProviderAttempt:
    cdp_session_id: str = ""
    process_id: int = 0
    active_port: int = 0
    endpoint_url: str = ""
    page_id: str = ""
    requested_url: str = ""
    final_url: str = ""
    title: str = ""
    load_state: str = ""
    dom_text_chars: int = 0
    links_found: int = 0
    html_excerpt_chars: int = 0
    network_request_count: int = 0
    console_error_count: int = 0
    elapsed_ms: float = 0.0
    provider_attempt_status: str = ""
    safety_status: str = ""
    claim_ceiling: str = CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE
    limitations: list[str] = field(default_factory=list)
    error_code: str = ""
    bounded_error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize(self)
        payload["elapsed_ms"] = round(float(self.elapsed_ms or 0.0), 3)
        return payload


@dataclass(slots=True)
class ExtractedLink:
    url: str
    text: str = ""
    title: str = ""
    rel: str = ""
    same_origin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class RenderedWebPage:
    requested_url: str
    final_url: str
    provider: str
    status: str
    title: str = ""
    text: str = ""
    html: str = ""
    links: list[ExtractedLink] = field(default_factory=list)
    elapsed_ms: float = 0.0
    rendered_javascript: bool = False
    confidence: str = "medium"
    error_code: str = ""
    error_message: str = ""
    limitations: list[str] = field(default_factory=list)
    truncated: bool = False
    load_state: str = ""
    cdp_session_id: str = ""
    process_id: int = 0
    active_port: int = 0
    page_id: str = ""
    network_summary: dict[str, Any] = field(default_factory=dict)
    console_summary: dict[str, Any] = field(default_factory=dict)
    claim_ceiling: str = CLAIM_CEILING_RENDERED_PAGE_EVIDENCE
    fallback_provider: str = ""

    @property
    def text_chars(self) -> int:
        return len(self.text or "")

    @property
    def html_chars(self) -> int:
        return len(self.html or "")

    @property
    def link_count(self) -> int:
        return len(self.links)

    @property
    def text_preview(self) -> str:
        text = " ".join(str(self.text or "").split()).strip()
        return text[:500]

    def to_dict(self, *, include_raw_html: bool = True, include_text: bool = True) -> dict[str, Any]:
        payload = {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "provider": self.provider,
            "status": self.status,
            "title": self.title,
            "text_chars": self.text_chars,
            "html_chars": self.html_chars,
            "link_count": self.link_count,
            "links": [link.to_dict() for link in self.links],
            "elapsed_ms": round(float(self.elapsed_ms or 0.0), 3),
            "rendered_javascript": self.rendered_javascript,
            "confidence": self.confidence,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "limitations": list(self.limitations),
            "truncated": self.truncated,
            "text_preview": self.text_preview,
            "load_state": self.load_state,
            "cdp_session_id": self.cdp_session_id,
            "process_id": self.process_id,
            "active_port": self.active_port,
            "page_id": self.page_id,
            "network_summary": _serialize(self.network_summary),
            "console_summary": _serialize(self.console_summary),
            "claim_ceiling": self.claim_ceiling,
            "fallback_provider": self.fallback_provider,
        }
        if include_text:
            payload["text"] = self.text
        if include_raw_html:
            payload["html"] = self.html
        return payload


@dataclass(slots=True)
class WebRetrievalRequest:
    urls: list[str]
    intent: str = "read_page"
    preferred_provider: str = "auto"
    require_rendering: bool = False
    include_html: bool = False
    include_links: bool = True
    max_text_chars: int | None = None
    max_html_chars: int | None = None
    request_id: str = field(default_factory=lambda: f"web-{uuid4().hex[:12]}")
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WebRetrievalTrace:
    request_id: str
    route_family: str = "web_retrieval"
    selected_provider: str = ""
    attempted_providers: list[str] = field(default_factory=list)
    provider_attempts: list[dict[str, Any]] = field(default_factory=list)
    result_state: str = "prepared"
    elapsed_ms: float = 0.0
    page_count: int = 0
    text_chars: int = 0
    link_count: int = 0
    fallback_used: bool = False
    fallback_reason: str = ""
    fallback_outcome: str = ""
    url_safety: dict[str, Any] = field(default_factory=dict)
    final_url: str = ""
    extraction_confidence: str = ""
    limitations: list[str] = field(default_factory=list)
    provider_readiness: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    error_code: str = ""
    error_message: str = ""
    claim_ceiling: str = CLAIM_CEILING_RENDERED_PAGE_EVIDENCE
    cdp: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize(self)
        payload["elapsed_ms"] = round(float(self.elapsed_ms or 0.0), 3)
        return payload


@dataclass(slots=True)
class WebEvidenceBundle:
    request: WebRetrievalRequest
    pages: list[RenderedWebPage] = field(default_factory=list)
    trace: WebRetrievalTrace | None = None
    result_state: str = "prepared"
    provider_chain: list[str] = field(default_factory=list)
    fallback_used: bool = False
    limitations: list[str] = field(default_factory=list)
    summary_ready: bool = False
    created_at: str = field(default_factory=_utc_now)
    claim_ceiling: str = CLAIM_CEILING_RENDERED_PAGE_EVIDENCE

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def text_chars(self) -> int:
        return sum(page.text_chars for page in self.pages)

    @property
    def link_count(self) -> int:
        return sum(page.link_count for page in self.pages)

    def to_dict(self, *, include_raw_html: bool = True, include_text: bool = True) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "pages": [
                page.to_dict(include_raw_html=include_raw_html, include_text=include_text)
                for page in self.pages
            ],
            "trace": self.trace.to_dict() if self.trace is not None else {},
            "result_state": self.result_state,
            "provider_chain": list(self.provider_chain),
            "fallback_used": self.fallback_used,
            "limitations": list(self.limitations),
            "summary_ready": self.summary_ready,
            "created_at": self.created_at,
            "claim_ceiling": self.claim_ceiling,
            "page_count": self.page_count,
            "text_chars": self.text_chars,
            "link_count": self.link_count,
        }
