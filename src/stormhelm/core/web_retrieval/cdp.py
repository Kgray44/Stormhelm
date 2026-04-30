from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
from http.client import RemoteDisconnected
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import struct
import subprocess
from time import sleep
from time import monotonic
from typing import Any, Callable
from urllib.parse import quote
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.error import URLError
from uuid import uuid4

from stormhelm.config.models import WebRetrievalObscuraCDPConfig
from stormhelm.core.web_retrieval.models import CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE
from stormhelm.core.web_retrieval.models import ObscuraCDPCompatibilityReport
from stormhelm.core.web_retrieval.models import ObscuraCDPEndpointDiscovery
from stormhelm.core.web_retrieval.models import ObscuraCDPPageInspection
from stormhelm.core.web_retrieval.models import ObscuraCDPReadiness
from stormhelm.core.web_retrieval.models import ObscuraCDPSession
from stormhelm.core.web_retrieval.safety import bounded_text
from stormhelm.core.web_retrieval.safety import redact_url_credentials


ProtocolProbe = Callable[[str], dict[str, Any] | ObscuraCDPEndpointDiscovery]
PopenFactory = Callable[..., Any]
_TRANSIENT_ENDPOINT_ERROR_CODES = {"connection_refused", "timeout", "endpoint_unreachable", "http_404", "not_found"}


class CDPCompatibilityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CDPEndpointError(CDPCompatibilityError):
    pass


class CDPProtocolError(CDPCompatibilityError):
    pass


class CDPCommandError(CDPProtocolError):
    pass


class CDPConnectionClosed(CDPProtocolError):
    def __init__(self, message: str = "CDP websocket closed.") -> None:
        super().__init__("page_websocket_disconnect", message)


class ObscuraCDPManager:
    def __init__(
        self,
        config: WebRetrievalObscuraCDPConfig,
        *,
        which: Callable[[str], str | None] | None = None,
        popen: PopenFactory | None = None,
        protocol_probe: ProtocolProbe | None = None,
        endpoint_discovery: Callable[[str], dict[str, Any] | ObscuraCDPEndpointDiscovery] | None = None,
        clock: Callable[[], float] | None = None,
        port_chooser: Callable[[str], int] | None = None,
    ) -> None:
        self.config = config
        self._which = which or shutil.which
        self._popen = popen or subprocess.Popen
        self._protocol_probe = protocol_probe
        self._endpoint_discovery = endpoint_discovery or self._probe_protocol
        self._clock = clock or monotonic
        self._port_chooser = port_chooser or _choose_local_port
        self._process: Any | None = None
        self._session: ObscuraCDPSession | None = None
        self._session_started_monotonic: float | None = None
        self._last_version: dict[str, Any] = {}
        self._last_discovery: ObscuraCDPEndpointDiscovery | None = None
        self._last_compatibility_report: ObscuraCDPCompatibilityReport | None = None
        self._status = "disabled" if not config.enabled else "ready"
        self._blocking_reasons: list[str] = []
        self._last_startup_error_code = ""
        self._last_navigation_error_code = ""
        self._last_cleanup_status = ""
        self._bounded_error_message = ""
        self._navigation_supported = False
        self._page_inspection_supported = False

    def readiness(self) -> ObscuraCDPReadiness:
        binary = self._resolved_binary()
        enabled = bool(self.config.enabled)
        running = self._is_running()
        warnings = self._config_warnings()
        blocking: list[str] = []
        status = "disabled"
        available = False
        if not enabled:
            blocking.append("cdp_disabled")
        elif not binary:
            status = "binary_missing"
            blocking.append("binary_missing")
        elif not _is_local_host(self.config.host):
            status = "startup_failed"
            blocking.append("host_must_be_localhost")
        elif running:
            status = "active"
            available = True
        else:
            status = "ready"
            available = True
        if self._status in {"startup_failed", "endpoint_unreachable", "protocol_probe_failed", "failed", "stopping", "diagnostic_only"} and enabled:
            status = self._status
            available = running or (status == "ready")
            if status == "diagnostic_only":
                available = False
            blocking = list(dict.fromkeys([*blocking, *self._blocking_reasons]))
        session = self._session
        discovery = self._last_discovery
        report_payload = self._last_compatibility_report.to_dict() if self._last_compatibility_report is not None else {}
        endpoint_discovered = bool(
            report_payload.get("endpoint_discovered")
            or (discovery is not None and discovery.endpoint_discovered)
            or (discovery is not None and (discovery.version_endpoint_status == "available" or discovery.page_list_endpoint_status == "available"))
        )
        diagnostic_only = bool(report_payload.get("diagnostic_only") or status == "diagnostic_only")
        navigation_supported = bool(report_payload.get("navigation_supported") or self._navigation_supported)
        page_inspection_supported = bool(report_payload.get("page_inspection_supported") or self._page_inspection_supported)
        extraction_supported = bool(report_payload.get("extraction_supported") or self._page_inspection_supported)
        fallback_provider = str(report_payload.get("recommended_fallback_provider") or ("obscura_cli" if diagnostic_only else ""))
        status_message = ""
        if diagnostic_only:
            status_message = "CDP endpoint detected; page navigation unsupported. Use Obscura CLI for page extraction."
        return ObscuraCDPReadiness(
            enabled=enabled,
            available=available,
            binary_path=binary or str(self.config.binary_path or "obscura"),
            host=self.config.host,
            configured_port=int(self.config.port or 0),
            active_port=int(session.active_port if session else 0),
            server_running=running,
            cdp_endpoint_url=_redacted_endpoint(session.endpoint_url if session else ""),
            browser_version=str((self._last_version or {}).get("Browser") or (session.browser_version if session else "")),
            protocol_version=str((self._last_version or {}).get("Protocol-Version") or (session.protocol_version if session else "")),
            blocking_reasons=blocking,
            warnings=warnings,
            claim_ceiling=CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
            status=status,
            endpoint_status=discovery.version_endpoint_status if discovery is not None else "",
            protocol_compatibility_level=discovery.compatibility_level if discovery is not None else "",
            optional_domains=dict(discovery.cdp_domains_available) if discovery is not None else {},
            last_startup_error_code=self._last_startup_error_code,
            last_navigation_error_code=self._last_navigation_error_code,
            last_cleanup_status=self._last_cleanup_status,
            bounded_error_message=self._bounded_error_message,
            last_compatibility_report=report_payload,
            endpoint_discovered=endpoint_discovered,
            navigation_supported=navigation_supported,
            page_inspection_supported=page_inspection_supported,
            extraction_supported=extraction_supported,
            diagnostic_only=diagnostic_only,
            recommended_fallback_provider=fallback_provider,
            status_message=status_message,
        )

    def start(self) -> ObscuraCDPSession:
        readiness = self.readiness()
        if readiness.status == "active" and self._session is not None:
            self._enforce_lifetime()
            return self._session
        if not readiness.enabled:
            self._status = "disabled"
            raise RuntimeError("Obscura CDP is disabled.")
        if "binary_missing" in readiness.blocking_reasons:
            self._status = "binary_missing"
            raise FileNotFoundError("Obscura CDP binary was not found.")
        if not _is_local_host(self.config.host):
            self._status = "startup_failed"
            self._blocking_reasons = ["host_must_be_localhost"]
            raise ValueError("Obscura CDP host must be localhost.")
        binary = self._resolved_binary()
        try:
            port = int(self.config.port or 0) or self._port_chooser(self.config.host)
        except OSError as error:
            self._status = "startup_failed"
            self._last_startup_error_code = "dynamic_port_unavailable"
            self._bounded_error_message = _bounded_error(redact_url_credentials(str(error)))
            self._blocking_reasons = ["dynamic_port_unavailable"]
            raise
        endpoint = f"http://{self.config.host}:{port}"
        command = _obscura_serve_command(binary, port)
        self._status = "startup_failed"
        try:
            self._process = self._popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
            )
        except PermissionError as error:
            self._last_startup_error_code = "permission_denied"
            self._bounded_error_message = _bounded_error(str(error))
            self._blocking_reasons = ["permission_denied"]
            raise
        except OSError as error:
            self._last_startup_error_code = "process_start_failed"
            self._bounded_error_message = _bounded_error(redact_url_credentials(str(error)))
            self._blocking_reasons = ["process_start_failed"]
            raise
        if getattr(self._process, "poll", lambda: None)() is not None:
            self._last_startup_error_code = "process_exited_immediately"
            self._bounded_error_message = _bounded_error(_process_stderr(self._process))
            self._blocking_reasons = ["process_exited_immediately"]
            raise RuntimeError("Obscura CDP process exited before the endpoint was ready.")
        try:
            version = self._wait_for_protocol(endpoint)
        except Exception as error:
            failure_status = _startup_status_from_error(error)
            self._blocking_reasons = [failure_status]
            self._status = failure_status
            self._last_startup_error_code = failure_status
            self._bounded_error_message = _bounded_error(str(error))
            self.stop()
            self._status = failure_status
            raise
        discovery = _coerce_discovery(endpoint, version)
        self._last_discovery = discovery
        self._last_version = _version_payload_from_discovery(discovery, version)
        self._status = "active"
        self._session = ObscuraCDPSession(
            session_id=f"cdp-{uuid4().hex[:12]}",
            process_id=int(getattr(self._process, "pid", 0) or 0),
            host=self.config.host,
            active_port=port,
            endpoint_url=endpoint,
            cdp_endpoint_url=discovery.page_websocket_url or discovery.browser_websocket_url,
            browser_version=discovery.browser_name,
            protocol_version=discovery.protocol_version,
        )
        self._session_started_monotonic = self._clock()
        return self._session

    def mark_page_inspection_supported(self) -> None:
        self._navigation_supported = True
        self._page_inspection_supported = True
        self._last_navigation_error_code = ""
        if self._last_discovery is not None:
            self._last_discovery.navigation_supported = True
            self._last_discovery.page_inspection_supported = True
            self._last_discovery.extraction_supported = True
            self._last_discovery.diagnostic_only = False

    def mark_navigation_unsupported(self, message: str = "") -> None:
        self._navigation_supported = False
        self._page_inspection_supported = False
        self._status = "diagnostic_only"
        self._last_navigation_error_code = "cdp_navigation_unsupported"
        self._bounded_error_message = _bounded_error(message or "CDP endpoint detected; page navigation unsupported.")
        self._blocking_reasons = list(dict.fromkeys([*self._blocking_reasons, "cdp_navigation_unsupported"]))
        discovery = self._last_discovery
        if discovery is not None:
            discovery.endpoint_discovered = True
            discovery.navigation_supported = False
            discovery.page_inspection_supported = False
            discovery.extraction_supported = False
            discovery.diagnostic_only = True
            discovery.recommended_fallback_provider = "obscura_cli"
            discovery.compatibility_level = "diagnostic_only"
            discovery.blocking_reasons = list(dict.fromkeys([*discovery.blocking_reasons, "cdp_navigation_unsupported"]))
        report = ObscuraCDPCompatibilityReport(
            binary_path=self._resolved_binary() or str(self.config.binary_path or "obscura"),
            binary_found=bool(self._resolved_binary()),
            host=self.config.host,
            port=int(self._session.active_port if self._session else self.config.port or 0),
            process_started=self._process is not None,
            process_id=int(getattr(self._process, "pid", 0) or 0),
            version_endpoint_status=discovery.version_endpoint_status if discovery is not None else "",
            browser_websocket_url_found=bool(discovery.browser_websocket_url_found) if discovery is not None else False,
            page_list_endpoint_status=discovery.page_list_endpoint_status if discovery is not None else "",
            page_websocket_url_found=bool(discovery.page_websocket_url_found) if discovery is not None else False,
            protocol_version=discovery.protocol_version if discovery is not None else "",
            browser_name=discovery.browser_name if discovery is not None else "",
            browser_revision=discovery.browser_revision if discovery is not None else "",
            cdp_domains_available=dict(discovery.cdp_domains_available) if discovery is not None else {},
            navigation_probe_status="unsupported",
            extraction_probe_status="not_run",
            cleanup_status=self._last_cleanup_status,
            compatible=False,
            compatibility_level="diagnostic_only",
            blocking_reasons=["cdp_navigation_unsupported"],
            warnings=["endpoint_discovered_navigation_unsupported"],
            bounded_error_message=self._bounded_error_message,
            endpoint_discovered=True,
            navigation_supported=False,
            page_inspection_supported=False,
            extraction_supported=False,
            diagnostic_only=True,
            recommended_fallback_provider="obscura_cli",
        )
        self._last_compatibility_report = report

    def stop(self) -> None:
        process = self._process
        if process is None:
            self._status = "diagnostic_only" if self._last_navigation_error_code == "cdp_navigation_unsupported" and self.config.enabled else "ready" if self.config.enabled else "disabled"
            self._last_cleanup_status = self._last_cleanup_status or "not_started"
            return
        self._status = "stopping"
        try:
            if getattr(process, "poll", lambda: None)() is not None:
                self._last_cleanup_status = "already_exited"
            elif getattr(process, "poll", lambda: None)() is None:
                process.terminate()
                try:
                    process.wait(timeout=float(self.config.shutdown_timeout_seconds or 4.0))
                    self._last_cleanup_status = "graceful"
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=1.0)
                        self._last_cleanup_status = "forced_kill"
                    except subprocess.TimeoutExpired:
                        self._last_cleanup_status = "failed"
                        self._bounded_error_message = "Obscura CDP process did not exit after forced kill."
        finally:
            if self._session is not None:
                self._session = replace(self._session, stopped_at=_utcish(), status="stopped")
            self._process = None
            self._session_started_monotonic = None
            self._status = "diagnostic_only" if self._last_navigation_error_code == "cdp_navigation_unsupported" and self.config.enabled else "ready" if self.config.enabled else "disabled"

    def register_page_use(self) -> None:
        if self._session is None:
            return
        self._session.page_count += 1
        if self._session.page_count > int(self.config.max_pages_per_session or 1):
            self.stop()
            raise RuntimeError("Obscura CDP max pages per session was exceeded.")

    def _enforce_lifetime(self) -> None:
        if self._session is None:
            return
        max_seconds = float(self.config.max_session_seconds or 0.0)
        if max_seconds <= 0:
            return
        started = self._session_started_monotonic
        if started is not None and self._clock() - started > max_seconds:
            self.stop()
            raise TimeoutError("Obscura CDP session lifetime expired.")

    def _wait_for_protocol(self, endpoint: str) -> dict[str, Any] | ObscuraCDPEndpointDiscovery:
        deadline = self._clock() + float(self.config.startup_timeout_seconds or 8.0)
        last_error: Exception | None = None
        while self._clock() <= deadline:
            try:
                probe = self._protocol_probe(endpoint) if self._protocol_probe is not None else self._endpoint_discovery(endpoint)
                if isinstance(probe, ObscuraCDPEndpointDiscovery):
                    if probe.compatible:
                        return probe
                    transient = _discovery_is_transient(probe)
                    error = CDPEndpointError(
                        "endpoint_unreachable"
                        if transient
                        else probe.blocking_reasons[0] if probe.blocking_reasons else "endpoint_incompatible",
                        probe.bounded_error_message or "Obscura CDP endpoint is not compatible.",
                    )
                    if not transient:
                        raise error
                    raise error
                if isinstance(probe, dict):
                    return probe
            except Exception as error:
                last_error = error
                if isinstance(error, CDPEndpointError) and error.code not in _TRANSIENT_ENDPOINT_ERROR_CODES:
                    raise
            sleep(0.05)
        raise TimeoutError(str(last_error or "Obscura CDP endpoint did not become ready."))

    def _probe_protocol(self, endpoint: str) -> ObscuraCDPEndpointDiscovery:
        return discover_cdp_endpoints(
            endpoint,
            http_json=_http_json,
            timeout=max(0.1, float(self.config.startup_timeout_seconds or 8.0)),
        )

    def _resolved_binary(self) -> str:
        binary = str(self.config.binary_path or "obscura").strip() or "obscura"
        if any(sep in binary for sep in ("/", "\\")) or (len(binary) > 1 and binary[1] == ":"):
            return binary if Path(binary).exists() else ""
        return self._which(binary) or ""

    def _is_running(self) -> bool:
        process = self._process
        return process is not None and getattr(process, "poll", lambda: None)() is None

    def _config_warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.config.allow_runtime_eval:
            warnings.append("runtime_eval_enabled")
        if self.config.allow_input_domain:
            warnings.append("input_domain_enabled")
        if self.config.allow_cookies:
            warnings.append("cookies_enabled")
        if self.config.allow_logged_in_context:
            warnings.append("logged_in_context_enabled")
        if self.config.allow_screenshots:
            warnings.append("screenshots_enabled")
        return warnings


class ObscuraCDPClient:
    def __init__(
        self,
        config: WebRetrievalObscuraCDPConfig,
        *,
        http_json: Callable[[str, str], Any] | None = None,
        websocket_factory: Callable[[str, float], "_CDPWebSocket"] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._http_json = http_json or _http_json
        self._websocket_factory = websocket_factory or _CDPWebSocket
        self._clock = clock or monotonic
        self._socket: _CDPWebSocket | None = None
        self._message_id = 0
        self._page_id = ""
        self._network_requests: list[str] = []
        self._network_failures = 0
        self._console_errors: list[str] = []
        self.protocol_warnings: dict[str, int] = {
            "malformed_json_frames": 0,
            "mismatched_response_ids": 0,
            "unsolicited_events": 0,
        }
        self._optional_domains: dict[str, bool] = {"Network": True, "Log": True}
        self._inspection_limitations: list[str] = []

    def inspect_url(self, session: ObscuraCDPSession, url: str) -> ObscuraCDPPageInspection:
        started = self._clock()
        page = self.new_page(session)
        self.navigate(url)
        load_state = self.wait_for_load_state()
        final_url = self.get_current_url() or url
        title = self.get_title()
        dom_text = self.get_dom_text()
        links = self.get_links(final_url)
        html_excerpt = self.get_html_excerpt()
        limitations = [
            "headless_cdp_page_evidence",
            "not_user_visible_screen",
            "not_truth_verified",
            "no_input_domain",
            "no_logged_in_context",
            *self._inspection_limitations,
        ]
        return ObscuraCDPPageInspection(
            requested_url=url,
            final_url=final_url,
            title=title,
            dom_text=dom_text,
            html_excerpt=html_excerpt,
            links=links,
            load_state=load_state,
            network_summary=self.get_network_summary(),
            console_summary=self.get_console_summary(),
            page_id=str(page.get("id") or self._page_id),
            elapsed_ms=(self._clock() - started) * 1000,
            limitations=list(dict.fromkeys(limitations)),
        )

    def connect(self, endpoint: str) -> None:
        version = self._http_json(f"{endpoint.rstrip('/')}/json/version", "GET")
        version = version if isinstance(version, dict) else {}
        ws_url = str(_first_nonempty(version, ("webSocketDebuggerUrl", "browserWebSocketDebuggerUrl", "websocketDebuggerUrl", "webSocketUrl")) or "")
        if ws_url:
            self._socket = self._websocket_factory(ws_url, float(self.config.navigation_timeout_seconds or 12.0))

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
        self._socket = None

    def new_page(self, session: ObscuraCDPSession) -> dict[str, Any]:
        if session.page_count > int(self.config.max_pages_per_session or 1):
            raise RuntimeError("Obscura CDP max pages per session was exceeded.")
        endpoint = session.endpoint_url.rstrip("/")
        page: dict[str, Any] = {}
        new_url = f"{endpoint}/json/new?{quote('about:blank', safe=':/')}"
        for method in ("PUT", "GET"):
            try:
                candidate = self._http_json(new_url, method)
                if isinstance(candidate, dict):
                    page = candidate
                    break
            except Exception as error:
                if not _is_target_creation_fallback_error(error):
                    raise
        if not page:
            for path in ("/json/list", "/json"):
                try:
                    page = _select_page_target(self._http_json(f"{endpoint}{path}", "GET"))
                    if page:
                        break
                except Exception as error:
                    if not _is_target_creation_fallback_error(error):
                        raise
        ws_url = str(page.get("webSocketDebuggerUrl") or "")
        if not ws_url:
            raise CDPEndpointError("page_websocket_missing", "Obscura CDP page did not expose a websocket endpoint.")
        _validate_websocket_endpoint(ws_url, expected_host=urlparse(session.endpoint_url).hostname or session.host)
        self._page_id = str(page.get("id") or "")
        self._socket = self._websocket_factory(ws_url, float(self.config.navigation_timeout_seconds or 12.0))
        for method in ("Page.enable", "DOM.enable"):
            self._send(method)
        for method, domain, limitation in (
            ("Network.enable", "Network", "network_summary_unavailable"),
            ("Log.enable", "Log", "console_summary_unavailable"),
        ):
            try:
                self._send(method)
            except CDPCompatibilityError:
                self._optional_domains[domain] = False
                self._inspection_limitations.append(limitation)
        return page

    def navigate(self, url: str) -> None:
        try:
            self._send("Page.navigate", {"url": url})
        except CDPCommandError as error:
            if "No page for session" in error.message:
                raise CDPCommandError("cdp_navigation_unsupported", error.message) from error
            raise

    def wait_for_load_state(self) -> str:
        deadline = self._clock() + float(self.config.navigation_timeout_seconds or 12.0)
        state = "loading"
        while self._clock() <= deadline:
            event = self._recv(timeout=max(0.1, min(0.5, deadline - self._clock())))
            if event is None:
                continue
            method = self._handle_event(message=event)
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            if method in {"Page.loadEventFired", "Page.lifecycleEvent"}:
                state = "loaded"
                if method == "Page.loadEventFired" or str(params.get("name") or "") in {"load", "networkIdle"}:
                    return state
        return state if state == "loaded" else "timeout"

    def get_current_url(self) -> str:
        result = self._send("Page.getFrameTree")
        frame_tree = result.get("frameTree") if isinstance(result.get("frameTree"), dict) else {}
        frame = frame_tree.get("frame") if isinstance(frame_tree.get("frame"), dict) else {}
        return str(frame.get("url") or "")

    def get_title(self) -> str:
        root = self._document_root()
        for node in _walk_dom(root):
            if str(node.get("nodeName") or "").lower() == "title":
                text = _node_text(node)
                if text:
                    return text[:180]
        return ""

    def get_dom_text(self) -> str:
        root = self._document_root()
        parts = _visible_text_parts(root)
        text = " ".join(" ".join(part.split()) for part in parts if part.strip()).strip()
        bounded, _ = bounded_text(text, int(self.config.max_dom_text_chars or 60000))
        return bounded

    def get_links(self, base_url: str) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in _walk_dom(self._document_root()):
            if str(node.get("nodeName") or "").lower() != "a":
                continue
            attrs = _attributes(node)
            href = str(attrs.get("href") or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)
            absolute = urljoin(base_url, href)
            parsed_link = urlparse(absolute)
            if parsed_link.scheme not in {"http", "https"}:
                continue
            links.append(
                {
                    "url": absolute,
                    "text": _node_text(node),
                    "title": attrs.get("title", ""),
                    "rel": attrs.get("rel", ""),
                    "same_origin": parsed_link.netloc.lower() == urlparse(base_url).netloc.lower(),
                }
            )
            if len(links) >= int(self.config.max_links or 500):
                break
        return links

    def get_html_excerpt(self) -> str:
        root = _document_element(self._document_root())
        node_id = int(root.get("nodeId") or 0)
        if not node_id:
            return ""
        result = self._send("DOM.getOuterHTML", {"nodeId": node_id})
        html, _ = bounded_text(str(result.get("outerHTML") or ""), int(self.config.max_html_chars or 250000))
        return html

    def get_network_summary(self) -> dict[str, Any]:
        if not self._optional_domains.get("Network", True):
            return {
                "available": False,
                "unavailable_reason": "domain_unavailable",
                "request_count": 0,
                "failed_count": 0,
                "sample_urls": [],
            }
        return {
            "available": True,
            "request_count": len(self._network_requests),
            "failed_count": self._network_failures,
            "sample_urls": self._network_requests[:10],
        }

    def get_console_summary(self) -> dict[str, Any]:
        if not self._optional_domains.get("Log", True):
            return {
                "available": False,
                "unavailable_reason": "domain_unavailable",
                "error_count": 0,
                "messages": [],
            }
        return {
            "available": True,
            "error_count": len(self._console_errors),
            "messages": self._console_errors[:10],
        }

    def dispose_page(self) -> None:
        self.close()

    def _document_root(self) -> dict[str, Any]:
        result = self._send("DOM.getDocument", {"depth": -1, "pierce": True})
        root = result.get("root") if isinstance(result.get("root"), dict) else {}
        return root

    def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._socket is None:
            raise CDPProtocolError("page_websocket_not_connected", "Obscura CDP client is not connected.")
        self._message_id += 1
        message_id = self._message_id
        self._socket.send_json({"id": message_id, "method": method, "params": params or {}})
        deadline = self._clock() + float(self.config.navigation_timeout_seconds or 12.0)
        while self._clock() <= deadline:
            message = self._recv(timeout=max(0.1, min(0.5, deadline - self._clock())))
            if message is None:
                continue
            if message.get("id") == message_id:
                if "error" in message:
                    error = message.get("error")
                    raise CDPCommandError("cdp_command_error", _bounded_error(json.dumps(error if isinstance(error, dict) else error)))
                if "result" not in message:
                    raise CDPProtocolError("cdp_result_missing", f"CDP response missing result for {method}.")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise CDPProtocolError("cdp_result_wrong_type", f"CDP response result had the wrong type for {method}.")
                return result
            if "id" in message:
                self.protocol_warnings["mismatched_response_ids"] = self.protocol_warnings.get("mismatched_response_ids", 0) + 1
                continue
            if "method" in message:
                self.protocol_warnings["unsolicited_events"] = self.protocol_warnings.get("unsolicited_events", 0) + 1
                self._handle_event(message=message)
                continue
        raise TimeoutError(f"CDP command timed out: {method}")

    def _recv(self, *, timeout: float) -> dict[str, Any] | None:
        if self._socket is None:
            return None
        try:
            raw = self._socket.recv_text(timeout=timeout)
        except CDPCompatibilityError:
            raise
        except ConnectionError as error:
            raise CDPConnectionClosed(str(error)) from error
        if isinstance(raw, bytes):
            raise CDPProtocolError("binary_websocket_frame", "Unexpected binary CDP websocket frame.")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self.protocol_warnings["malformed_json_frames"] = self.protocol_warnings.get("malformed_json_frames", 0) + 1
            return None
        return data if isinstance(data, dict) else None

    def _handle_event(self, *, message: dict[str, Any]) -> str:
        method = str(message.get("method") or "")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "Network.requestWillBeSent":
            request = params.get("request") if isinstance(params.get("request"), dict) else {}
            request_url = str(request.get("url") or "")
            if request_url and len(self._network_requests) < 20:
                self._network_requests.append(redact_url_credentials(request_url))
        elif method in {"Network.loadingFailed", "Network.responseReceivedExtraInfo"} and str(params.get("errorText") or ""):
            self._network_failures += 1
        elif method == "Log.entryAdded":
            entry = params.get("entry") if isinstance(params.get("entry"), dict) else {}
            if str(entry.get("level") or "").lower() in {"error", "warning"}:
                message_text, _ = bounded_text(str(entry.get("text") or ""), 240)
                if message_text and len(self._console_errors) < 20:
                    self._console_errors.append(redact_url_credentials(message_text))
        return method


def discover_cdp_endpoints(
    endpoint_url: str,
    *,
    http_json: Callable[[str, str], Any] | None = None,
    websocket_probe: Callable[[str, float], bool] | None = None,
    timeout: float = 2.0,
) -> ObscuraCDPEndpointDiscovery:
    endpoint = str(endpoint_url or "").rstrip("/")
    parsed = urlparse(endpoint)
    version_url = f"{endpoint}/json/version"
    list_url = f"{endpoint}/json/list"
    fallback_list_url = f"{endpoint}/json"
    fetch = http_json or _http_json
    blocking: list[str] = []
    warnings: list[str] = []
    cdp_domains_available: dict[str, Any] = {
        "Page": "unknown",
        "DOM": "unknown",
        "Runtime": "unknown",
        "Network": "unknown",
        "Log": "unknown",
    }
    if parsed.scheme not in {"http", "https"}:
        blocking.append("endpoint_url_unsupported_scheme")
    if parsed.hostname and not _is_local_host(parsed.hostname):
        blocking.append("endpoint_host_mismatch")

    version_payload: dict[str, Any] = {}
    list_payload: Any = None
    version_status = "unknown"
    list_status = "unknown"
    bounded_error = ""

    try:
        candidate = fetch(version_url, "GET")
        if not isinstance(candidate, dict):
            raise CDPEndpointError("version_result_wrong_type", "The /json/version endpoint did not return an object.")
        version_payload = candidate
        version_status = "available"
    except Exception as error:
        version_status = _endpoint_error_status(error)
        if version_status == "missing":
            warnings.append("version_endpoint_missing")
        else:
            bounded_error = _bounded_error(str(error))

    for candidate_url in (list_url, fallback_list_url):
        try:
            list_payload = fetch(candidate_url, "GET")
            list_status = "available"
            list_url = candidate_url
            break
        except Exception as error:
            status = _endpoint_error_status(error)
            if status == "missing":
                list_status = "missing"
                continue
            list_status = status
            bounded_error = bounded_error or _bounded_error(str(error))
            break

    browser_ws = str(
        _first_nonempty(
            version_payload,
            ("webSocketDebuggerUrl", "browserWebSocketDebuggerUrl", "websocketDebuggerUrl", "webSocketUrl"),
        )
        or ""
    )
    page_target = _select_page_target(list_payload)
    page_ws = str(page_target.get("webSocketDebuggerUrl") or "")
    browser_name, browser_revision = _browser_parts(str(version_payload.get("Browser") or version_payload.get("browser") or ""))
    protocol_version = str(version_payload.get("Protocol-Version") or version_payload.get("protocolVersion") or "")

    for ws_url in (browser_ws, page_ws):
        if not ws_url:
            continue
        try:
            _validate_websocket_endpoint(ws_url, expected_host=parsed.hostname or "127.0.0.1")
        except CDPEndpointError as error:
            blocking.append(error.code)
            bounded_error = bounded_error or _bounded_error(error.message)
            continue
        if websocket_probe is not None:
            try:
                if not websocket_probe(ws_url, timeout):
                    blocking.append("page_websocket_unreachable" if ws_url == page_ws else "browser_websocket_unreachable")
            except Exception as error:
                blocking.append("page_websocket_unreachable" if ws_url == page_ws else "browser_websocket_unreachable")
                bounded_error = bounded_error or _bounded_error(str(error))

    if not page_ws:
        blocking.append("page_websocket_missing")
        if browser_ws:
            warnings.append("browser_websocket_without_page_websocket")
    if list_status == "missing":
        warnings.append("page_list_endpoint_missing")
    blocking = list(dict.fromkeys(blocking))
    warnings = list(dict.fromkeys(warnings))
    compatible = bool(page_ws) and not blocking
    if compatible and version_status == "available":
        compatibility_level = "ready"
    elif compatible:
        compatibility_level = "partial"
    else:
        compatibility_level = "unsupported"
    endpoint_discovered = version_status == "available" or list_status == "available"

    return ObscuraCDPEndpointDiscovery(
        endpoint_url=_redacted_endpoint(endpoint),
        version_endpoint_status=version_status,
        version_endpoint_url=_redacted_endpoint(version_url),
        browser_websocket_url_found=bool(browser_ws),
        browser_websocket_url=_redacted_endpoint(browser_ws),
        page_list_endpoint_status=list_status,
        page_list_endpoint_url=_redacted_endpoint(list_url),
        page_websocket_url_found=bool(page_ws),
        page_websocket_url=_redacted_endpoint(page_ws),
        protocol_version=protocol_version,
        browser_name=browser_name,
        browser_revision=browser_revision,
        cdp_domains_available=cdp_domains_available,
        compatible=compatible,
        compatibility_level=compatibility_level,
        blocking_reasons=blocking,
        warnings=warnings,
        bounded_error_message=bounded_error,
        endpoint_discovered=endpoint_discovered,
        navigation_supported=False,
        page_inspection_supported=False,
        extraction_supported=False,
        diagnostic_only=endpoint_discovered and not compatible,
        recommended_fallback_provider="obscura_cli" if endpoint_discovered and not compatible else "",
    )


class ObscuraCDPCompatibilityProbe:
    def __init__(
        self,
        config: WebRetrievalObscuraCDPConfig,
        *,
        which: Callable[[str], str | None] | None = None,
        popen: PopenFactory | None = None,
        version_runner: Callable[[str], str] | None = None,
        http_json: Callable[[str, str], Any] | None = None,
        websocket_probe: Callable[[str, float], bool] | None = None,
        clock: Callable[[], float] | None = None,
        port_chooser: Callable[[str], int] | None = None,
    ) -> None:
        self.config = config
        self._which = which or shutil.which
        self._popen = popen or subprocess.Popen
        self._version_runner = version_runner
        self._http_json = http_json or _http_json
        self._websocket_probe = websocket_probe
        self._clock = clock or monotonic
        self._port_chooser = port_chooser or _choose_local_port

    def run(self, *, navigation_url: str = "") -> ObscuraCDPCompatibilityReport:
        del navigation_url
        report = ObscuraCDPCompatibilityReport(
            binary_path=str(self.config.binary_path or "obscura"),
            host=self.config.host,
            compatibility_level="failed",
            cleanup_status="not_started",
        )
        process: Any | None = None
        binary = self._resolved_binary()
        report.binary_path = binary or str(self.config.binary_path or "obscura")
        report.binary_found = bool(binary)
        if not binary:
            report.blocking_reasons.append("binary_missing")
            report.bounded_error_message = "Obscura CDP binary was not found."
            report.completed_at = _utcish()
            return report
        if not _is_local_host(self.config.host):
            report.blocking_reasons.append("host_must_be_localhost")
            report.bounded_error_message = "Obscura CDP host must be localhost."
            report.completed_at = _utcish()
            return report
        report.binary_version = self._probe_binary_version(binary, report)
        try:
            port = int(self.config.port or 0) or self._port_chooser(self.config.host)
        except OSError as error:
            report.blocking_reasons.append("dynamic_port_unavailable")
            report.bounded_error_message = _bounded_error(str(error))
            report.completed_at = _utcish()
            return report
        report.port = port
        endpoint = f"http://{self.config.host}:{port}"
        try:
            process = self._popen(
                _obscura_serve_command(binary, port),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
            )
            report.process_started = True
            report.process_id = int(getattr(process, "pid", 0) or 0)
            if getattr(process, "poll", lambda: None)() is not None:
                report.blocking_reasons.append("process_exited_immediately")
                report.bounded_error_message = _bounded_error(_process_stderr(process))
                report.compatibility_level = "failed"
                return report
            discovery = self._wait_for_discovery(endpoint)
            _apply_discovery_to_report(report, discovery)
        except Exception as error:
            if not report.blocking_reasons:
                report.blocking_reasons.append(getattr(error, "code", "compatibility_probe_failed"))
            report.bounded_error_message = report.bounded_error_message or _bounded_error(str(error))
            report.compatible = False
            report.compatibility_level = "failed"
        finally:
            report.cleanup_status = _cleanup_process(process, float(self.config.shutdown_timeout_seconds or 4.0))
            report.completed_at = _utcish()
        return report

    def _resolved_binary(self) -> str:
        binary = str(self.config.binary_path or "obscura").strip() or "obscura"
        if any(sep in binary for sep in ("/", "\\")) or (len(binary) > 1 and binary[1] == ":"):
            return binary if Path(binary).exists() else ""
        return self._which(binary) or ""

    def _probe_binary_version(self, binary: str, report: ObscuraCDPCompatibilityReport) -> str:
        try:
            if self._version_runner is not None:
                version = self._version_runner(binary)
            else:
                completed = subprocess.run(
                    [binary, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                    check=False,
                )
                version = completed.stdout.strip() or completed.stderr.strip()
            bounded, _ = bounded_text(redact_url_credentials(str(version or "")), 240)
            return bounded
        except Exception as error:
            report.warnings.append("binary_version_unavailable")
            report.bounded_error_message = report.bounded_error_message or _bounded_error(str(error))
            return ""

    def _wait_for_discovery(self, endpoint: str) -> ObscuraCDPEndpointDiscovery:
        deadline = self._clock() + float(self.config.startup_timeout_seconds or 8.0)
        last_discovery: ObscuraCDPEndpointDiscovery | None = None
        while self._clock() <= deadline:
            discovery = discover_cdp_endpoints(
                endpoint,
                http_json=self._http_json,
                websocket_probe=self._websocket_probe,
                timeout=max(0.1, float(self.config.startup_timeout_seconds or 8.0)),
            )
            last_discovery = discovery
            if discovery.compatible or not _discovery_is_transient(discovery):
                return discovery
            sleep(0.05)
        if last_discovery is not None:
            return last_discovery
        raise TimeoutError("Obscura CDP endpoint did not respond.")


class _CDPWebSocket:
    def __init__(self, url: str, timeout: float) -> None:
        self.url = url
        self.timeout = timeout
        self._socket = self._connect(url, timeout)

    def send_json(self, payload: dict[str, Any]) -> None:
        self._send_text(json.dumps(payload, separators=(",", ":")))

    def recv_text(self, *, timeout: float) -> str:
        self._socket.settimeout(timeout)
        while True:
            first = self._recv_exact(2)
            if not first:
                return ""
            byte1, byte2 = first[0], first[1]
            opcode = byte1 & 0x0F
            masked = bool(byte2 & 0x80)
            length = byte2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if masked:
                payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
            if opcode == 8:
                raise CDPConnectionClosed()
            if opcode == 1:
                return payload.decode("utf-8", errors="replace")
            if opcode == 2:
                raise CDPProtocolError("binary_websocket_frame", "Unexpected binary CDP websocket frame.")

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def _connect(self, url: str, timeout: float) -> socket.socket:
        parsed = urlparse(url)
        if parsed.scheme not in {"ws", "wss"}:
            raise ValueError("CDP endpoint must be ws:// or wss://.")
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        raw = socket.create_connection((host, port), timeout=timeout)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if parsed.scheme == "wss" else raw
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise ConnectionError("CDP websocket handshake failed.")
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        )
        if expected not in response:
            raise ConnectionError("CDP websocket accept key mismatch.")
        return sock

    def _send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(payload[i] ^ mask[i % 4] for i in range(length))
        self._socket.sendall(bytes(header) + masked)

    def _recv_exact(self, length: int) -> bytes:
        data = b""
        while len(data) < length:
            chunk = self._socket.recv(length - len(data))
            if not chunk:
                raise ConnectionError("CDP websocket closed.")
            data += chunk
        return data


def _http_json(url: str, method: str) -> Any:
    request = Request(url, method=method, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=12.0) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        raise CDPEndpointError(f"http_{error.code}", f"CDP endpoint returned HTTP {error.code}.") from error
    except URLError as error:
        reason = getattr(error, "reason", error)
        if isinstance(reason, TimeoutError):
            raise TimeoutError("CDP endpoint timed out.") from error
        raise CDPEndpointError("connection_refused", "CDP endpoint connection failed.") from error
    except RemoteDisconnected as error:
        raise CDPEndpointError("endpoint_connection_closed", "CDP endpoint closed the connection.") from error
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        code = "non_json_response" if body.lstrip().startswith("<") else "malformed_json"
        raise CDPEndpointError(code, f"CDP endpoint returned {code}.") from error


def _select_page_target(payload: Any) -> dict[str, Any]:
    targets: list[Any] = []
    if isinstance(payload, list):
        targets = payload
    elif isinstance(payload, dict):
        for key in ("targets", "pages", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                targets = value
                break
        if not targets and (payload.get("webSocketDebuggerUrl") or payload.get("url") or payload.get("id")):
            targets = [payload]
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_type = str(target.get("type") or target.get("targetType") or "page").lower()
        if target_type in {"page", "tab", "browser"} and str(target.get("webSocketDebuggerUrl") or ""):
            return target
    for target in targets:
        if isinstance(target, dict) and str(target.get("webSocketDebuggerUrl") or ""):
            return target
    return {}


def _first_nonempty(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value:
            return value
    return ""


def _validate_websocket_endpoint(url: str, *, expected_host: str) -> None:
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"ws", "wss"}:
        raise CDPEndpointError("endpoint_url_unsupported_scheme", "CDP websocket endpoint must use ws:// or wss://.")
    host = parsed.hostname or ""
    if not _hosts_match(host, expected_host):
        raise CDPEndpointError("endpoint_host_mismatch", "CDP websocket endpoint host did not match the local server.")


def _hosts_match(actual: str, expected: str) -> bool:
    actual_normalized = str(actual or "").strip().lower()
    expected_normalized = str(expected or "").strip().lower()
    if _is_local_host(actual_normalized) and _is_local_host(expected_normalized):
        return True
    return actual_normalized == expected_normalized


def _endpoint_error_status(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ConnectionRefusedError):
        return "connection_refused"
    code = str(getattr(error, "code", "") or "")
    if code in {"http_404", "not_found"}:
        return "missing"
    if code in {"malformed_json", "non_json_response", "connection_refused", "timeout"}:
        return code
    if code.startswith("http_"):
        return code
    return "failed"


def _is_missing_endpoint_error(error: Exception) -> bool:
    return _endpoint_error_status(error) == "missing"


def _is_target_creation_fallback_error(error: Exception) -> bool:
    return _is_missing_endpoint_error(error) or str(getattr(error, "code", "") or "") == "endpoint_connection_closed"


def _browser_parts(browser: str) -> tuple[str, str]:
    value = str(browser or "")
    if "/" in value:
        name, revision = value.split("/", 1)
        return name, revision
    return value, ""


def _coerce_discovery(endpoint: str, value: dict[str, Any] | ObscuraCDPEndpointDiscovery) -> ObscuraCDPEndpointDiscovery:
    if isinstance(value, ObscuraCDPEndpointDiscovery):
        return value
    browser_name, browser_revision = _browser_parts(str(value.get("Browser") or value.get("browser") or ""))
    browser_ws = str(_first_nonempty(value, ("webSocketDebuggerUrl", "browserWebSocketDebuggerUrl", "websocketDebuggerUrl", "webSocketUrl")) or "")
    return ObscuraCDPEndpointDiscovery(
        endpoint_url=_redacted_endpoint(endpoint),
        version_endpoint_status="available",
        version_endpoint_url=_redacted_endpoint(f"{endpoint.rstrip('/')}/json/version"),
        browser_websocket_url_found=bool(browser_ws),
        browser_websocket_url=_redacted_endpoint(browser_ws),
        page_list_endpoint_status="unknown",
        page_websocket_url_found=False,
        protocol_version=str(value.get("Protocol-Version") or value.get("protocolVersion") or ""),
        browser_name=browser_name,
        browser_revision=browser_revision,
        cdp_domains_available={"Page": "unknown", "DOM": "unknown", "Network": "unknown", "Log": "unknown"},
        compatible=True,
        compatibility_level="ready",
        endpoint_discovered=True,
    )


def _version_payload_from_discovery(discovery: ObscuraCDPEndpointDiscovery, value: dict[str, Any] | ObscuraCDPEndpointDiscovery) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    browser = discovery.browser_name
    if discovery.browser_revision:
        browser = f"{browser}/{discovery.browser_revision}"
    return {
        "Browser": browser,
        "Protocol-Version": discovery.protocol_version,
        "webSocketDebuggerUrl": discovery.browser_websocket_url,
    }


def _startup_status_from_error(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "endpoint_unreachable"
    code = str(getattr(error, "code", "") or "")
    if code in {"connection_refused", "timeout", "endpoint_unreachable"}:
        return "endpoint_unreachable"
    if code in {
        "malformed_json",
        "non_json_response",
        "http_500",
        "endpoint_incompatible",
        "page_websocket_missing",
        "endpoint_host_mismatch",
        "endpoint_url_unsupported_scheme",
    }:
        return "protocol_probe_failed"
    return "startup_failed"


def _discovery_is_transient(discovery: ObscuraCDPEndpointDiscovery) -> bool:
    statuses = {
        discovery.version_endpoint_status,
        discovery.page_list_endpoint_status,
    }
    if statuses & {"connection_refused", "timeout", "unknown", "failed"}:
        return True
    if discovery.version_endpoint_status == "missing" and discovery.page_list_endpoint_status == "missing":
        return True
    return False


def _process_stderr(process: Any) -> str:
    try:
        _stdout, stderr = process.communicate(timeout=0.2)
        return str(stderr or "")
    except Exception:
        stream = getattr(process, "stderr", None)
        try:
            if hasattr(stream, "read"):
                return str(stream.read(1000) or "")
        except Exception:
            pass
    return ""


def _bounded_error(message: str) -> str:
    text = redact_url_credentials(str(message or ""))
    for token in ("secret-token", "access_token", "refresh_token", "password"):
        text = text.replace(token, "[redacted]")
    bounded, _ = bounded_text(text, 500)
    return bounded


def _cleanup_process(process: Any | None, timeout: float) -> str:
    if process is None:
        return "not_started"
    try:
        if getattr(process, "poll", lambda: None)() is not None:
            return "already_exited"
        process.terminate()
        try:
            process.wait(timeout=timeout)
            return "graceful"
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=1.0)
                return "forced_kill"
            except subprocess.TimeoutExpired:
                return "failed"
    except Exception:
        return "failed"


def _apply_discovery_to_report(report: ObscuraCDPCompatibilityReport, discovery: ObscuraCDPEndpointDiscovery) -> None:
    report.version_endpoint_status = discovery.version_endpoint_status
    report.version_endpoint_url = discovery.version_endpoint_url
    report.browser_websocket_url_found = discovery.browser_websocket_url_found
    report.page_list_endpoint_status = discovery.page_list_endpoint_status
    report.page_websocket_url_found = discovery.page_websocket_url_found
    report.protocol_version = discovery.protocol_version
    report.browser_name = discovery.browser_name
    report.browser_revision = discovery.browser_revision
    report.cdp_domains_available = dict(discovery.cdp_domains_available)
    report.compatible = discovery.compatible
    report.compatibility_level = discovery.compatibility_level
    report.blocking_reasons = list(discovery.blocking_reasons)
    report.warnings = list(dict.fromkeys([*report.warnings, *discovery.warnings]))
    report.bounded_error_message = report.bounded_error_message or discovery.bounded_error_message
    report.endpoint_discovered = discovery.endpoint_discovered or discovery.version_endpoint_status == "available" or discovery.page_list_endpoint_status == "available"
    report.navigation_supported = discovery.navigation_supported
    report.page_inspection_supported = discovery.page_inspection_supported
    report.extraction_supported = discovery.extraction_supported
    report.diagnostic_only = discovery.diagnostic_only
    report.recommended_fallback_provider = discovery.recommended_fallback_provider


def _walk_dom(node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node]
    children = node.get("children") if isinstance(node.get("children"), list) else []
    for child in children:
        if isinstance(child, dict):
            nodes.extend(_walk_dom(child))
    return nodes


def _is_text_node(node: dict[str, Any]) -> bool:
    if int(node.get("nodeType") or 0) == 3:
        return True
    return str(node.get("nodeName") or "") == "#text"


def _node_text(node: dict[str, Any]) -> str:
    values = [str(node.get("nodeValue") or "")]
    children = node.get("children") if isinstance(node.get("children"), list) else []
    for child in children:
        if isinstance(child, dict):
            values.append(_node_text(child))
    return " ".join(" ".join(value.split()) for value in values if value.strip()).strip()


def _visible_text_parts(node: dict[str, Any], *, skip: bool = False) -> list[str]:
    node_name = str(node.get("nodeName") or "").lower()
    skip = skip or node_name in {"script", "style", "noscript", "template"}
    parts: list[str] = []
    if not skip and _is_text_node(node):
        value = str(node.get("nodeValue") or "").strip()
        if value:
            parts.append(value)
    children = node.get("children") if isinstance(node.get("children"), list) else []
    for child in children:
        if isinstance(child, dict):
            parts.extend(_visible_text_parts(child, skip=skip))
    return parts


def _document_element(root: dict[str, Any]) -> dict[str, Any]:
    if str(root.get("nodeName") or "").lower() == "html":
        return root
    for node in _walk_dom(root):
        if str(node.get("nodeName") or "").lower() == "html":
            return node
    return root


def _attributes(node: dict[str, Any]) -> dict[str, str]:
    attrs = node.get("attributes") if isinstance(node.get("attributes"), list) else []
    result: dict[str, str] = {}
    for index in range(0, len(attrs) - 1, 2):
        result[str(attrs[index])] = str(attrs[index + 1])
    return result


def _choose_local_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _obscura_serve_command(binary: str, port: int) -> list[str]:
    return [binary, "serve", "--port", str(port)]


def _is_local_host(host: str) -> bool:
    return str(host or "").strip().lower() in {"127.0.0.1", "localhost", "::1"}


def _redacted_endpoint(endpoint: str) -> str:
    parsed = urlparse(str(endpoint or ""))
    if not parsed.scheme or not parsed.hostname:
        return ""
    host = parsed.hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        host = "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


def _utcish() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
