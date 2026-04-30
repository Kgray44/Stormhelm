from __future__ import annotations

from dataclasses import replace
import subprocess
from typing import Any

import pytest

from stormhelm.config.models import WebRetrievalConfig
from stormhelm.config.models import WebRetrievalObscuraCDPConfig
from stormhelm.config.models import WebRetrievalObscuraConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.web_retrieval.cdp import ObscuraCDPManager
from stormhelm.core.web_retrieval.cdp_provider import ObscuraCDPProvider
from stormhelm.core.web_retrieval.models import ObscuraCDPPageInspection
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.service import WebRetrievalService


class _FakeProcess:
    def __init__(self, *, pid: int = 4321, graceful: bool = True) -> None:
        self.pid = pid
        self.graceful = graceful
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return 0 if self.terminated and self.graceful else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        if not self.graceful:
            raise subprocess.TimeoutExpired(["obscura"], timeout=timeout)
        return 0

    def kill(self) -> None:
        self.killed = True
        self.terminated = True


class _FakeCDPClient:
    def __init__(self, inspection: ObscuraCDPPageInspection | Exception) -> None:
        self.inspection = inspection
        self.closed = False

    def inspect_url(self, session: Any, url: str) -> ObscuraCDPPageInspection:
        del url
        if isinstance(self.inspection, Exception):
            raise self.inspection
        return self.inspection

    def close(self) -> None:
        self.closed = True


def _cdp_config(**overrides: Any) -> WebRetrievalObscuraCDPConfig:
    return replace(WebRetrievalObscuraCDPConfig(enabled=True), **overrides)


def test_cdp_readiness_distinguishes_disabled_missing_and_active_without_starting() -> None:
    disabled = ObscuraCDPManager(WebRetrievalObscuraCDPConfig(), which=lambda _binary: None)
    missing = ObscuraCDPManager(_cdp_config(binary_path="missing"), which=lambda _binary: None)

    assert disabled.readiness().status == "disabled"
    assert disabled.readiness().server_running is False
    assert missing.readiness().status == "binary_missing"

    process = _FakeProcess()
    started = ObscuraCDPManager(
        _cdp_config(port=9444),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: process,
        protocol_probe=lambda endpoint: {
            "Browser": "Obscura/1.0",
            "Protocol-Version": "1.3",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9444/devtools/browser/test",
        },
    )

    readiness_before = started.readiness()
    assert readiness_before.status == "ready"
    assert readiness_before.available is True
    assert readiness_before.server_running is False

    session = started.start()
    readiness_after = started.readiness()

    assert session.process_id == 4321
    assert session.active_port == 9444
    assert readiness_after.status == "active"
    assert readiness_after.server_running is True
    assert readiness_after.browser_version == "Obscura/1.0"
    assert readiness_after.protocol_version == "1.3"
    assert readiness_after.claim_ceiling == "headless_cdp_page_evidence"


def test_cdp_manager_startup_failure_timeout_and_forced_cleanup() -> None:
    timeout_manager = ObscuraCDPManager(
        _cdp_config(startup_timeout_seconds=0.01),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: _FakeProcess(),
        protocol_probe=lambda endpoint: (_ for _ in ()).throw(TimeoutError("not ready")),
    )

    with pytest.raises(TimeoutError):
        timeout_manager.start()
    assert timeout_manager.readiness().status == "endpoint_unreachable"

    process = _FakeProcess(graceful=False)
    manager = ObscuraCDPManager(
        _cdp_config(port=9333),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: process,
        protocol_probe=lambda endpoint: {"Browser": "Obscura/1.0", "Protocol-Version": "1.3"},
    )
    manager.start()
    manager.stop()

    assert process.terminated is True
    assert process.killed is True
    assert manager.readiness().server_running is False


def test_cdp_provider_extracts_bounded_page_evidence_and_closes_session() -> None:
    inspection = ObscuraCDPPageInspection(
        requested_url="https://example.com",
        final_url="https://example.com/final",
        title="Example CDP",
        dom_text="Hello from the rendered DOM",
        html_excerpt="<html><body>Hello from the rendered DOM</body></html>",
        links=[{"url": "https://example.com/a", "text": "A", "same_origin": True}],
        load_state="loaded",
        network_summary={"request_count": 3, "failed_count": 1, "sample_urls": ["https://example.com/app.js"]},
        console_summary={"error_count": 2, "messages": ["ReferenceError"]},
        page_id="page-1",
        elapsed_ms=42.0,
    )
    process = _FakeProcess()
    manager = ObscuraCDPManager(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: process,
        protocol_probe=lambda endpoint: {"Browser": "Obscura/1.0", "Protocol-Version": "1.3"},
    )
    client = _FakeCDPClient(inspection)
    provider = ObscuraCDPProvider(WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(cdp=_cdp_config())), manager=manager, client=client)

    page = provider.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="cdp_inspect", include_html=True), "https://example.com")

    assert page.status == "success"
    assert page.provider == "obscura_cdp"
    assert page.title == "Example CDP"
    assert page.final_url == "https://example.com/final"
    assert page.text == "Hello from the rendered DOM"
    assert page.links[0].url == "https://example.com/a"
    assert page.network_summary["request_count"] == 3
    assert page.console_summary["error_count"] == 2
    assert page.claim_ceiling == "headless_cdp_page_evidence"
    assert page.rendered_javascript is True
    assert process.terminated is True
    assert client.closed is True


def test_cdp_provider_blocks_redirect_to_private_url_before_extraction_payload_escape() -> None:
    inspection = ObscuraCDPPageInspection(
        requested_url="https://example.com/redirect",
        final_url="http://127.0.0.1/admin",
        title="Internal",
        dom_text="internal secret",
        html_excerpt="<html>internal secret</html>",
    )
    manager = ObscuraCDPManager(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: _FakeProcess(),
        protocol_probe=lambda endpoint: {"Browser": "Obscura/1.0", "Protocol-Version": "1.3"},
    )
    provider = ObscuraCDPProvider(WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(cdp=_cdp_config())), manager=manager, client=_FakeCDPClient(inspection))

    page = provider.retrieve(WebRetrievalRequest(urls=["https://example.com/redirect"], intent="cdp_inspect", include_html=True), "https://example.com/redirect")

    assert page.status == "blocked"
    assert page.error_code == "redirect_target_blocked"
    assert page.text == ""
    assert page.html == ""


def test_service_selects_cdp_only_for_cdp_requests_and_emits_bounded_events() -> None:
    events = EventBuffer(capacity=32)
    inspection = ObscuraCDPPageInspection(
        requested_url="https://example.com",
        final_url="https://example.com",
        title="CDP Title",
        dom_text="Rendered DOM body that must not be dumped in events",
        html_excerpt="<html>must not be in events</html>",
        links=[{"url": "https://example.com/a", "text": "A"}],
        network_summary={"request_count": 2},
        console_summary={"error_count": 0},
    )
    manager = ObscuraCDPManager(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: _FakeProcess(),
        protocol_probe=lambda endpoint: {"Browser": "Obscura/1.0", "Protocol-Version": "1.3"},
    )
    cdp_provider = ObscuraCDPProvider(WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(cdp=_cdp_config())), manager=manager, client=_FakeCDPClient(inspection))
    service = WebRetrievalService(
        WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(cdp=_cdp_config())),
        events=events,
        cdp_provider=cdp_provider,
    )

    bundle = service.retrieve(
        WebRetrievalRequest(
            urls=["https://example.com"],
            intent="cdp_inspect",
            preferred_provider="obscura_cdp",
            include_html=True,
        )
    )

    assert bundle.result_state == "extracted"
    assert bundle.provider_chain == ["obscura_cdp"]
    assert bundle.trace is not None
    assert bundle.trace.claim_ceiling == "headless_cdp_page_evidence"
    assert bundle.trace.cdp["session_id"]
    assert bundle.trace.provider_attempts[0]["network_request_count"] == 2
    assert bundle.trace.provider_attempts[0]["console_error_count"] == 0

    payload_text = str([event["payload"] for event in events.recent(families=["web_retrieval"])])
    assert "Rendered DOM body" not in payload_text
    assert "<html>" not in payload_text
    event_types = [event["event_type"] for event in events.recent(families=["web_retrieval"])]
    assert "web_retrieval.obscura_cdp_started" in event_types
    assert "web_retrieval.obscura_cdp_navigation_started" in event_types
