from __future__ import annotations

from stormhelm.config.models import WebRetrievalConfig
from stormhelm.config.models import WebRetrievalObscuraConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.web_retrieval.models import RenderedWebPage
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.service import WebRetrievalService


class _Provider:
    def __init__(self, name: str, page: RenderedWebPage) -> None:
        self.name = name
        self.page = page
        self.calls: list[str] = []

    def readiness(self):
        return {"status": "available", "provider": self.name}

    def retrieve(self, request: WebRetrievalRequest, url: str) -> RenderedWebPage:
        self.calls.append(url)
        return self.page


class _UnavailableProvider(_Provider):
    def __init__(self, name: str, *, status: str, reason: str) -> None:
        super().__init__(
            name,
            RenderedWebPage(requested_url="", final_url="", provider=name, status="provider_unavailable"),
        )
        self.status = status
        self.reason = reason

    def readiness(self):
        return {"status": self.status, "provider": self.name, "available": False, "reason": self.reason}


def test_service_uses_http_for_read_page_and_emits_redacted_events() -> None:
    events = EventBuffer(capacity=16)
    http = _Provider(
        "http",
        RenderedWebPage(
            requested_url="https://example.com",
            final_url="https://example.com",
            provider="http",
            status="success",
            text="Hello from a public page",
            links=[],
        ),
    )
    service = WebRetrievalService(WebRetrievalConfig(), events=events, http_provider=http, obscura_provider=None)

    bundle = service.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="read_page"))

    assert bundle.result_state == "extracted"
    assert bundle.provider_chain == ["http"]
    assert http.calls == ["https://example.com"]
    recent = events.recent(families=["web_retrieval"])
    assert [event["event_type"] for event in recent] == [
        "web_retrieval.requested",
        "web_retrieval.provider_selected",
        "web_retrieval.page_rendered",
    ]
    assert "text" not in recent[-1]["payload"]


def test_service_prefers_obscura_for_render_requests_and_falls_back_to_http() -> None:
    obscura = _Provider(
        "obscura",
        RenderedWebPage(
            requested_url="https://example.com",
            final_url="https://example.com",
            provider="obscura",
            status="failed",
            error_code="process_error",
            error_message="Obscura failed.",
        ),
    )
    http = _Provider(
        "http",
        RenderedWebPage(
            requested_url="https://example.com",
            final_url="https://example.com",
            provider="http",
            status="success",
            text="Static fallback text",
            links=[],
        ),
    )
    service = WebRetrievalService(
        WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(enabled=True)),
        http_provider=http,
        obscura_provider=obscura,
    )

    bundle = service.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="render_page", require_rendering=True))

    assert bundle.result_state == "extracted"
    assert bundle.fallback_used is True
    assert bundle.provider_chain == ["obscura", "http"]
    assert obscura.calls == ["https://example.com"]
    assert http.calls == ["https://example.com"]
    assert bundle.pages[0].provider == "http"
    assert "obscura_failed" in bundle.limitations


def test_service_blocks_private_urls_before_provider_selection() -> None:
    http = _Provider(
        "http",
        RenderedWebPage(requested_url="", final_url="", provider="http", status="success"),
    )
    service = WebRetrievalService(WebRetrievalConfig(), http_provider=http)

    bundle = service.retrieve(WebRetrievalRequest(urls=["http://127.0.0.1:8765"], intent="read_page"))

    assert bundle.result_state == "blocked"
    assert bundle.pages[0].status == "blocked"
    assert bundle.pages[0].error_code == "private_network_url_blocked"
    assert http.calls == []


def test_service_deduplicates_urls_and_traces_safety_status() -> None:
    http = _Provider(
        "http",
        RenderedWebPage(
            requested_url="https://example.com",
            final_url="https://example.com",
            provider="http",
            status="success",
            text="Hello from a public page",
        ),
    )
    service = WebRetrievalService(WebRetrievalConfig(), http_provider=http)

    bundle = service.retrieve(
        WebRetrievalRequest(urls=["https://example.com", "https://example.com/", "HTTPS://EXAMPLE.COM"], intent="read_page")
    )

    assert http.calls == ["https://example.com"]
    assert bundle.page_count == 1
    assert bundle.trace is not None
    assert bundle.trace.url_safety["initial"]["allowed"] is True


def test_service_blocks_redirect_to_private_target_after_provider_returns_final_url() -> None:
    http = _Provider(
        "http",
        RenderedWebPage(
            requested_url="https://example.com/redirect",
            final_url="http://127.0.0.1/admin",
            provider="http",
            status="success",
            text="internal admin panel",
        ),
    )
    service = WebRetrievalService(WebRetrievalConfig(), http_provider=http)

    bundle = service.retrieve(WebRetrievalRequest(urls=["https://example.com/redirect"], intent="read_page"))

    assert bundle.result_state == "blocked"
    assert bundle.pages[0].status == "blocked"
    assert bundle.pages[0].error_code == "redirect_target_blocked"
    assert bundle.pages[0].text == ""
    assert bundle.trace is not None
    assert bundle.trace.final_url == "http://127.0.0.1/admin"
    assert bundle.trace.url_safety["final"]["allowed"] is False


def test_service_records_obscura_unavailable_http_fallback_explicitly() -> None:
    obscura = _UnavailableProvider("obscura", status="binary_missing", reason="binary_missing")
    http = _Provider(
        "http",
        RenderedWebPage(
            requested_url="https://example.com",
            final_url="https://example.com",
            provider="http",
            status="success",
            text="Static fallback text",
        ),
    )
    service = WebRetrievalService(
        WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(enabled=True)),
        http_provider=http,
        obscura_provider=obscura,
    )

    bundle = service.retrieve(
        WebRetrievalRequest(urls=["https://example.com"], intent="render_page", require_rendering=True)
    )

    assert bundle.result_state == "extracted"
    assert bundle.fallback_used is True
    assert bundle.trace is not None
    assert bundle.trace.selected_provider == "http"
    assert bundle.trace.fallback_used is True
    assert bundle.trace.fallback_reason == "obscura:binary_missing"
    assert bundle.trace.fallback_outcome == "http:success"
    assert bundle.trace.provider_attempts[0]["provider"] == "obscura"
    assert bundle.trace.provider_attempts[0]["status"] == "provider_unavailable"
    assert bundle.trace.provider_attempts[1]["provider"] == "http"
    assert bundle.trace.provider_attempts[1]["status"] == "success"


def test_service_returns_failed_trace_when_all_providers_fail() -> None:
    obscura = _Provider(
        "obscura",
        RenderedWebPage(
            requested_url="https://example.com",
            final_url="https://example.com",
            provider="obscura",
            status="failed",
            error_code="process_error",
            error_message="process failed",
        ),
    )
    http = _Provider(
        "http",
        RenderedWebPage(
            requested_url="https://example.com",
            final_url="https://example.com",
            provider="http",
            status="timeout",
            error_code="timeout",
            error_message="timed out",
        ),
    )
    service = WebRetrievalService(
        WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(enabled=True), default_provider="obscura"),
        http_provider=http,
        obscura_provider=obscura,
    )

    bundle = service.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="render_page", require_rendering=True))

    assert bundle.result_state == "failed"
    assert bundle.pages[0].status == "failed"
    assert bundle.trace is not None
    assert bundle.trace.attempted_providers == ["obscura", "http"]
    assert [error["code"] for error in bundle.trace.errors] == ["process_error", "timeout"]
    assert bundle.trace.error_code == "process_error"
    assert "process failed" in bundle.trace.error_message
