from __future__ import annotations

from dataclasses import replace
import subprocess
from typing import Any
from urllib.parse import urlparse

import pytest

from stormhelm.config.models import WebRetrievalConfig
from stormhelm.config.models import WebRetrievalObscuraCDPConfig
from stormhelm.config.models import WebRetrievalObscuraConfig
from stormhelm.core.web_retrieval.cdp import CDPCommandError
from stormhelm.core.web_retrieval.cdp import CDPEndpointError
from stormhelm.core.web_retrieval.cdp import CDPProtocolError
from stormhelm.core.web_retrieval.cdp import ObscuraCDPClient
from stormhelm.core.web_retrieval.cdp import ObscuraCDPCompatibilityProbe
from stormhelm.core.web_retrieval.cdp import ObscuraCDPManager
from stormhelm.core.web_retrieval.cdp import discover_cdp_endpoints
from stormhelm.core.web_retrieval.cdp_provider import ObscuraCDPProvider
from stormhelm.core.web_retrieval.models import ObscuraCDPCompatibilityReport
from stormhelm.core.web_retrieval.models import ObscuraCDPEndpointDiscovery
from stormhelm.core.web_retrieval.models import ObscuraCDPPageInspection
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.service import WebRetrievalService


class _FakeProcess:
    def __init__(
        self,
        *,
        pid: int = 2468,
        exited: bool = False,
        graceful_timeout: bool = False,
        kill_timeout: bool = False,
        stderr: str = "",
    ) -> None:
        self.pid = pid
        self.exited = exited
        self.graceful_timeout = graceful_timeout
        self.kill_timeout = kill_timeout
        self.stderr = stderr
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return 1 if self.exited else None

    def terminate(self) -> None:
        self.terminated = True
        if not self.graceful_timeout:
            self.exited = True

    def kill(self) -> None:
        self.killed = True
        if not self.kill_timeout:
            self.exited = True

    def wait(self, timeout: float | None = None) -> int:
        if self.kill_timeout and self.killed:
            raise subprocess.TimeoutExpired(["obscura"], timeout=timeout)
        if self.graceful_timeout and not self.killed:
            raise subprocess.TimeoutExpired(["obscura"], timeout=timeout)
        self.exited = True
        return 0

    def communicate(self, timeout: float | None = None):
        return "", self.stderr


class _FakeEndpoint:
    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url: str, method: str) -> Any:
        path = urlparse(url).path
        key = (method.upper(), path)
        fallback = ("GET", path)
        self.calls.append(key)
        value = self.routes.get(key, self.routes.get(fallback, CDPEndpointError("http_404", f"{path} missing")))
        if isinstance(value, Exception):
            raise value
        return value


class _FakeSocket:
    def __init__(self, frames: list[str]) -> None:
        self.frames = list(frames)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(dict(payload))

    def recv_text(self, *, timeout: float) -> str:
        del timeout
        if not self.frames:
            return ""
        return self.frames.pop(0)

    def close(self) -> None:
        self.closed = True


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.1
        return self.now


def _cdp_config(**overrides: Any) -> WebRetrievalObscuraCDPConfig:
    return replace(WebRetrievalObscuraCDPConfig(enabled=True), **overrides)


def test_compatibility_report_serializes_levels_and_redacts_output() -> None:
    report = ObscuraCDPCompatibilityReport(
        binary_path="C:/Tools/obscura.exe",
        binary_found=True,
        binary_version="obscura 1.2.3",
        host="127.0.0.1",
        port=9222,
        process_started=True,
        process_id=2468,
        version_endpoint_status="available",
        browser_websocket_url_found=True,
        page_list_endpoint_status="available",
        page_websocket_url_found=True,
        protocol_version="1.3",
        browser_name="Obscura",
        cdp_domains_available={"Page": True, "DOM": True, "Network": "unavailable"},
        cleanup_status="graceful",
        compatible=True,
        compatibility_level="ready",
        raw_output_redacted=True,
    )

    payload = report.to_dict()

    assert payload["compatibility_level"] == "ready"
    assert payload["compatible"] is True
    assert payload["raw_output_redacted"] is True
    assert "report_id" in payload


def test_compatibility_probe_reports_binary_missing_without_starting() -> None:
    probe = ObscuraCDPCompatibilityProbe(_cdp_config(binary_path="missing"), which=lambda _binary: None)

    report = probe.run()

    assert report.binary_found is False
    assert report.process_started is False
    assert report.compatible is False
    assert report.compatibility_level == "failed"
    assert "binary_missing" in report.blocking_reasons


def test_compatibility_probe_uses_version_and_list_endpoints_and_cleans_up() -> None:
    process = _FakeProcess()
    endpoint = _FakeEndpoint(
        {
            ("GET", "/json/version"): {
                "Browser": "Obscura/1.0",
                "Protocol-Version": "1.3",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9555/devtools/browser/1",
            },
            ("GET", "/json/list"): [
                {
                    "id": "page-1",
                    "type": "page",
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9555/devtools/page/1",
                }
            ],
        }
    )
    probe = ObscuraCDPCompatibilityProbe(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: process,
        version_runner=lambda binary: "obscura 1.0",
        http_json=endpoint,
        websocket_probe=lambda url, timeout: True,
    )

    report = probe.run()

    assert report.binary_found is True
    assert report.binary_version == "obscura 1.0"
    assert report.process_started is True
    assert report.version_endpoint_status == "available"
    assert report.browser_websocket_url_found is True
    assert report.page_websocket_url_found is True
    assert report.compatibility_level == "ready"
    assert report.cleanup_status == "graceful"
    assert process.terminated is True


def test_endpoint_discovery_classifies_missing_version_with_list_fallback() -> None:
    endpoint = _FakeEndpoint(
        {
            ("GET", "/json/version"): CDPEndpointError("http_404", "missing"),
            ("GET", "/json/list"): [
                {
                    "id": "page-1",
                    "type": "page",
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9555/devtools/page/1",
                }
            ],
        }
    )

    discovery = discover_cdp_endpoints(
        "http://127.0.0.1:9555",
        http_json=endpoint,
        websocket_probe=lambda url, timeout: True,
    )

    assert discovery.version_endpoint_status == "missing"
    assert discovery.page_list_endpoint_status == "available"
    assert discovery.page_websocket_url_found is True
    assert discovery.compatibility_level == "partial"
    assert "version_endpoint_missing" in discovery.warnings


@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (CDPEndpointError("malformed_json", "bad json"), "malformed_json"),
        (CDPEndpointError("non_json_response", "html"), "non_json_response"),
        (TimeoutError("timed out"), "timeout"),
        (ConnectionRefusedError("refused"), "connection_refused"),
    ],
)
def test_endpoint_discovery_classifies_bad_version_endpoint_shapes(exception: Exception, expected_status: str) -> None:
    endpoint = _FakeEndpoint(
        {
            ("GET", "/json/version"): exception,
            ("GET", "/json/list"): CDPEndpointError("http_404", "missing"),
            ("GET", "/json"): CDPEndpointError("http_404", "missing"),
        }
    )

    discovery = discover_cdp_endpoints("http://127.0.0.1:9555", http_json=endpoint)

    assert discovery.version_endpoint_status == expected_status
    assert discovery.compatible is False
    assert discovery.compatibility_level == "unsupported"
    assert discovery.blocking_reasons


def test_endpoint_discovery_rejects_websocket_host_mismatch() -> None:
    endpoint = _FakeEndpoint(
        {
            ("GET", "/json/version"): {
                "Browser": "Obscura/1.0",
                "Protocol-Version": "1.3",
                "webSocketDebuggerUrl": "ws://evil.example/devtools/browser/1",
            },
            ("GET", "/json/list"): [
                {"type": "page", "webSocketDebuggerUrl": "ws://evil.example/devtools/page/1"}
            ],
        }
    )

    discovery = discover_cdp_endpoints("http://127.0.0.1:9555", http_json=endpoint)

    assert discovery.compatible is False
    assert "endpoint_host_mismatch" in discovery.blocking_reasons


def test_manager_reports_immediate_exit_port_conflict_and_cleanup_status() -> None:
    process = _FakeProcess(exited=True, stderr="unsupported flag --host secret-token")
    manager = ObscuraCDPManager(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: process,
        endpoint_discovery=lambda endpoint: (_ for _ in ()).throw(AssertionError("should not probe")),
    )

    with pytest.raises(RuntimeError):
        manager.start()

    readiness = manager.readiness()
    assert readiness.status == "startup_failed"
    assert readiness.last_startup_error_code == "process_exited_immediately"
    assert "secret-token" not in readiness.bounded_error_message

    manager_conflict = ObscuraCDPManager(
        _cdp_config(),
        which=lambda binary: binary,
        port_chooser=lambda host: (_ for _ in ()).throw(OSError("port busy")),
    )
    with pytest.raises(OSError):
        manager_conflict.start()
    assert manager_conflict.readiness().last_startup_error_code == "dynamic_port_unavailable"


def test_manager_and_probe_use_current_obscura_serve_port_only_syntax() -> None:
    manager_commands: list[list[str]] = []

    manager = ObscuraCDPManager(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: manager_commands.append(list(command)) or _FakeProcess(),
        endpoint_discovery=lambda endpoint: {"Browser": "Obscura/1.0", "Protocol-Version": "1.3"},
    )
    manager.start()
    manager.stop()

    assert manager_commands[0] == ["obscura", "serve", "--port", "9555"]

    discovery = ObscuraCDPEndpointDiscovery(
        endpoint_url="http://127.0.0.1:9555",
        browser_websocket_url="ws://127.0.0.1:9555/devtools/browser/1",
        page_websocket_url="ws://127.0.0.1:9555/devtools/page/1",
        browser_name="Obscura",
        protocol_version="1.3",
        compatible=True,
        compatibility_level="ready",
    )
    page_manager = ObscuraCDPManager(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: _FakeProcess(),
        endpoint_discovery=lambda endpoint: discovery,
    )
    page_session = page_manager.start()
    page_manager.stop()

    assert page_session.cdp_endpoint_url == "ws://127.0.0.1:9555/devtools/page/1"

    probe_commands: list[list[str]] = []
    endpoint = _FakeEndpoint(
        {
            ("GET", "/json/version"): {
                "Browser": "Obscura/1.0",
                "Protocol-Version": "1.3",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9555/devtools/browser/1",
            },
            ("GET", "/json/list"): [
                {"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9555/devtools/page/1"}
            ],
        }
    )
    probe = ObscuraCDPCompatibilityProbe(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: probe_commands.append(list(command)) or _FakeProcess(),
        version_runner=lambda binary: "version_unknown",
        http_json=endpoint,
        websocket_probe=lambda url, timeout: True,
    )

    report = probe.run()

    assert report.compatibility_level == "ready"
    assert probe_commands[0] == ["obscura", "serve", "--port", "9555"]


def test_manager_shutdown_tracks_already_exited_forced_and_failed_cleanup() -> None:
    already_exited = _FakeProcess(exited=True)
    manager = ObscuraCDPManager(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: already_exited,
        endpoint_discovery=lambda endpoint: {"Browser": "Obscura/1.0", "Protocol-Version": "1.3"},
    )
    manager._process = already_exited
    manager.stop()
    assert manager.readiness().last_cleanup_status == "already_exited"

    refuses = _FakeProcess(graceful_timeout=True, kill_timeout=True)
    manager._process = refuses
    manager.stop()
    assert manager.readiness().last_cleanup_status == "failed"


def test_client_uses_list_endpoint_fallback_and_extracts_links_with_base_url() -> None:
    endpoint = _FakeEndpoint(
        {
            ("PUT", "/json/new"): CDPEndpointError("endpoint_connection_closed", "closed"),
            ("GET", "/json/new"): CDPEndpointError("http_404", "missing"),
            ("GET", "/json/list"): [
                {
                    "id": "page-1",
                    "type": "page",
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9555/devtools/page/1",
                }
            ],
        }
    )
    frames = [
        '{"id":1,"result":{}}',
        '{"id":2,"result":{}}',
        '{"id":3,"error":{"code":-32601,"message":"Network missing"}}',
        '{"id":4,"error":{"code":-32601,"message":"Log missing"}}',
        '{"id":5,"result":{}}',
        '{"method":"Page.loadEventFired","params":{}}',
        '{"id":6,"result":{"frameTree":{"frame":{"url":"https://example.com/docs"}}}}',
        '{"id":7,"result":{"root":{"nodeName":"HTML","nodeId":1,"children":[{"nodeName":"HEAD","children":[{"nodeName":"TITLE","children":[{"nodeName":"#text","nodeType":3,"nodeValue":"Title"}]}]}]}}}',
        '{"id":8,"result":{"root":{"nodeName":"HTML","nodeId":1,"children":[{"nodeName":"BODY","children":[{"nodeName":"#text","nodeType":3,"nodeValue":"Visible body text for the page."}]}]}}}',
        '{"id":9,"result":{"root":{"nodeName":"HTML","nodeId":1,"children":[{"nodeName":"BODY","children":[{"nodeName":"A","attributes":["href","/next"],"children":[{"nodeName":"#text","nodeType":3,"nodeValue":"Next"}]}]}]}}}',
        '{"id":10,"result":{"root":{"nodeName":"HTML","nodeId":1}}}',
        '{"id":11,"result":{"outerHTML":"<html><body>Visible body text for the page.</body></html>"}}',
    ]
    socket = _FakeSocket(frames)
    session = _session()
    client = ObscuraCDPClient(
        _cdp_config(),
        http_json=endpoint,
        websocket_factory=lambda url, timeout: socket,
        clock=_FakeClock(),
    )

    inspection = client.inspect_url(session, "https://example.com/docs")

    assert inspection.final_url == "https://example.com/docs"
    assert inspection.links[0]["url"] == "https://example.com/next"
    assert inspection.network_summary["available"] is False
    assert inspection.console_summary["available"] is False
    assert "network_summary_unavailable" in inspection.limitations
    assert "console_summary_unavailable" in inspection.limitations


def test_client_validates_cdp_command_errors_malformed_frames_and_wrong_result_type() -> None:
    command_error_client = _client_with_socket(['{"id":1,"error":{"code":-32000,"message":"Target closed"}}'])
    with pytest.raises(CDPCommandError) as command_error:
        command_error_client._send("Page.navigate")
    assert command_error.value.code == "cdp_command_error"

    navigation_unsupported_client = _client_with_socket(
        ['{"id":1,"error":{"code":-32601,"message":"No page for session"}}']
    )
    with pytest.raises(CDPCommandError) as navigation_error:
        navigation_unsupported_client.navigate("https://example.com")
    assert navigation_error.value.code == "cdp_navigation_unsupported"

    malformed_then_success = _client_with_socket(['not-json', '{"id":1,"result":{}}'])
    assert malformed_then_success._send("Page.enable") == {}
    assert malformed_then_success.protocol_warnings["malformed_json_frames"] == 1

    wrong_result = _client_with_socket(['{"id":1,"result":[]}'])
    with pytest.raises(CDPProtocolError) as protocol_error:
        wrong_result._send("DOM.getDocument")
    assert protocol_error.value.code == "cdp_result_wrong_type"


def test_provider_maps_typed_cdp_failures_and_partial_optional_domain_diagnostics() -> None:
    class _FailingClient:
        def inspect_url(self, session: Any, url: str) -> ObscuraCDPPageInspection:
            raise CDPCommandError("page_websocket_disconnect", "socket closed mid-command")

        def close(self) -> None:
            pass

    manager = ObscuraCDPManager(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: _FakeProcess(),
        endpoint_discovery=lambda endpoint: {"Browser": "Obscura/1.0", "Protocol-Version": "1.3"},
    )
    provider = ObscuraCDPProvider(WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(cdp=_cdp_config())), manager=manager, client=_FailingClient())

    page = provider.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="cdp_inspect"), "https://example.com")

    assert page.status == "failed"
    assert page.error_code == "page_websocket_disconnect"
    assert page.claim_ceiling == "headless_cdp_page_evidence"

    inspection = ObscuraCDPPageInspection(
        requested_url="https://example.com",
        final_url="https://example.com",
        title="Example",
        dom_text="Enough visible DOM text for a useful partial result.",
        network_summary={"available": False, "unavailable_reason": "domain_unavailable"},
        console_summary={"available": False, "unavailable_reason": "domain_unavailable"},
        limitations=["network_summary_unavailable", "console_summary_unavailable"],
    )
    provider_ok = ObscuraCDPProvider(
        WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(cdp=_cdp_config())),
        manager=ObscuraCDPManager(
            _cdp_config(port=9555),
            which=lambda binary: binary,
            popen=lambda command, **kwargs: _FakeProcess(),
            endpoint_discovery=lambda endpoint: {"Browser": "Obscura/1.0", "Protocol-Version": "1.3"},
        ),
        client=type("Client", (), {"inspect_url": lambda self, session, url: inspection, "close": lambda self: None})(),
    )

    partial = provider_ok.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="cdp_inspect"), "https://example.com")

    assert partial.status == "partial"
    assert "network_summary_unavailable" in partial.limitations
    assert partial.network_summary["available"] is False


def test_navigation_unsupported_downgrades_cdp_to_diagnostic_only() -> None:
    discovery = ObscuraCDPEndpointDiscovery(
        endpoint_url="http://127.0.0.1:9555",
        version_endpoint_status="available",
        browser_websocket_url_found=True,
        browser_websocket_url="ws://127.0.0.1:9555/devtools/browser",
        page_list_endpoint_status="available",
        page_websocket_url_found=True,
        page_websocket_url="ws://127.0.0.1:9555/devtools/page/page-1",
        protocol_version="1.3",
        browser_name="Obscura",
        compatible=True,
        compatibility_level="ready",
    )

    class _NavigationUnsupportedClient:
        def inspect_url(self, session: Any, url: str) -> ObscuraCDPPageInspection:
            raise CDPCommandError("cdp_navigation_unsupported", '{"code": -32601, "message": "No page for session"}')

        def close(self) -> None:
            pass

    manager = ObscuraCDPManager(
        _cdp_config(port=9555),
        which=lambda binary: binary,
        popen=lambda command, **kwargs: _FakeProcess(),
        endpoint_discovery=lambda endpoint: discovery,
    )
    provider = ObscuraCDPProvider(
        WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(cdp=_cdp_config())),
        manager=manager,
        client=_NavigationUnsupportedClient(),
    )

    page = provider.retrieve(
        WebRetrievalRequest(urls=["https://example.com"], intent="cdp_inspect", preferred_provider="obscura_cdp"),
        "https://example.com",
    )
    readiness = manager.readiness()
    report = readiness.last_compatibility_report

    assert page.status == "unsupported"
    assert page.error_code == "cdp_navigation_unsupported"
    assert "cdp_diagnostic_only" in page.limitations
    assert readiness.status == "diagnostic_only"
    assert readiness.available is False
    assert readiness.last_navigation_error_code == "cdp_navigation_unsupported"
    assert report["endpoint_discovered"] is True
    assert report["navigation_supported"] is False
    assert report["page_inspection_supported"] is False
    assert report["diagnostic_only"] is True
    assert report["compatibility_level"] == "diagnostic_only"
    assert "cdp_navigation_unsupported" in report["blocking_reasons"]


def test_service_status_snapshot_and_deck_diagnostics_are_bounded() -> None:
    report = ObscuraCDPCompatibilityReport(
        binary_path="obscura",
        binary_found=True,
        host="127.0.0.1",
        port=9555,
        version_endpoint_status="available",
        page_list_endpoint_status="available",
        cleanup_status="graceful",
        compatible=True,
        compatibility_level="ready",
    )
    service = WebRetrievalService(
        WebRetrievalConfig(obscura=WebRetrievalObscuraConfig(cdp=_cdp_config())),
        cdp_provider=type(
            "Provider",
            (),
            {
                "name": "obscura_cdp",
                "readiness": lambda self: {
                    "provider": "obscura_cdp",
                    "status": "ready",
                    "available": True,
                    "detail": "obscura",
                },
                "compatibility_report": report,
            },
        )(),
    )

    snapshot = service.status_snapshot()

    assert snapshot["obscura_cdp"]["enabled"] is True
    assert snapshot["obscura_cdp"]["claim_ceiling"] == "headless_cdp_page_evidence"
    assert snapshot["obscura_cdp"]["last_compatibility_report"]["compatibility_level"] == "ready"
    assert "raw_page_content" not in str(snapshot).lower()


def _session():
    from stormhelm.core.web_retrieval.models import ObscuraCDPSession

    return ObscuraCDPSession(
        session_id="cdp-test",
        process_id=2468,
        host="127.0.0.1",
        active_port=9555,
        endpoint_url="http://127.0.0.1:9555",
    )


def _client_with_socket(frames: list[str]) -> ObscuraCDPClient:
    client = ObscuraCDPClient(_cdp_config(), websocket_factory=lambda url, timeout: _FakeSocket(frames), clock=_FakeClock())
    client._socket = _FakeSocket(frames)
    return client
