from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
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
from uuid import uuid4

from stormhelm.config.models import WebRetrievalObscuraCDPConfig
from stormhelm.core.web_retrieval.models import CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE
from stormhelm.core.web_retrieval.models import ObscuraCDPPageInspection
from stormhelm.core.web_retrieval.models import ObscuraCDPReadiness
from stormhelm.core.web_retrieval.models import ObscuraCDPSession
from stormhelm.core.web_retrieval.safety import bounded_text
from stormhelm.core.web_retrieval.safety import redact_url_credentials


ProtocolProbe = Callable[[str], dict[str, Any]]
PopenFactory = Callable[..., Any]


class ObscuraCDPManager:
    def __init__(
        self,
        config: WebRetrievalObscuraCDPConfig,
        *,
        which: Callable[[str], str | None] | None = None,
        popen: PopenFactory | None = None,
        protocol_probe: ProtocolProbe | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._which = which or shutil.which
        self._popen = popen or subprocess.Popen
        self._protocol_probe = protocol_probe or self._probe_protocol
        self._clock = clock or monotonic
        self._process: Any | None = None
        self._session: ObscuraCDPSession | None = None
        self._session_started_monotonic: float | None = None
        self._last_version: dict[str, Any] = {}
        self._status = "disabled" if not config.enabled else "ready"
        self._blocking_reasons: list[str] = []

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
        if self._status in {"startup_failed", "endpoint_unreachable", "protocol_probe_failed", "failed", "stopping"} and enabled:
            status = self._status
            available = running or (status == "ready")
            blocking = list(dict.fromkeys([*blocking, *self._blocking_reasons]))
        session = self._session
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
        port = int(self.config.port or 0) or _choose_local_port(self.config.host)
        endpoint = f"http://{self.config.host}:{port}"
        command = [binary, "serve", "--host", self.config.host, "--port", str(port)]
        self._status = "startup_failed"
        self._process = self._popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        try:
            version = self._wait_for_protocol(endpoint)
        except Exception as error:
            failure_status = "endpoint_unreachable" if isinstance(error, TimeoutError) else "protocol_probe_failed"
            self._blocking_reasons = [failure_status]
            self._status = failure_status
            self.stop()
            self._status = failure_status
            raise
        self._last_version = dict(version)
        self._status = "active"
        self._session = ObscuraCDPSession(
            session_id=f"cdp-{uuid4().hex[:12]}",
            process_id=int(getattr(self._process, "pid", 0) or 0),
            host=self.config.host,
            active_port=port,
            endpoint_url=endpoint,
            cdp_endpoint_url=str(version.get("webSocketDebuggerUrl") or ""),
            browser_version=str(version.get("Browser") or ""),
            protocol_version=str(version.get("Protocol-Version") or ""),
        )
        self._session_started_monotonic = self._clock()
        return self._session

    def stop(self) -> None:
        process = self._process
        if process is None:
            self._status = "ready" if self.config.enabled else "disabled"
            return
        self._status = "stopping"
        try:
            if getattr(process, "poll", lambda: None)() is None:
                process.terminate()
                try:
                    process.wait(timeout=float(self.config.shutdown_timeout_seconds or 4.0))
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
        finally:
            if self._session is not None:
                self._session = replace(self._session, stopped_at=_utcish(), status="stopped")
            self._process = None
            self._session_started_monotonic = None
            self._status = "ready" if self.config.enabled else "disabled"

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

    def _wait_for_protocol(self, endpoint: str) -> dict[str, Any]:
        deadline = self._clock() + float(self.config.startup_timeout_seconds or 8.0)
        last_error: Exception | None = None
        while self._clock() <= deadline:
            try:
                version = self._protocol_probe(endpoint)
                if isinstance(version, dict):
                    return version
            except Exception as error:
                last_error = error
            sleep(0.05)
        raise TimeoutError(str(last_error or "Obscura CDP endpoint did not become ready."))

    def _probe_protocol(self, endpoint: str) -> dict[str, Any]:
        request = Request(f"{endpoint.rstrip('/')}/json/version", headers={"Accept": "application/json"})
        with urlopen(request, timeout=max(0.1, float(self.config.startup_timeout_seconds or 8.0))) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

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
        http_json: Callable[[str, str], dict[str, Any]] | None = None,
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
            limitations=[
                "headless_cdp_page_evidence",
                "not_user_visible_screen",
                "not_truth_verified",
                "no_input_domain",
                "no_logged_in_context",
            ],
        )

    def connect(self, endpoint: str) -> None:
        version = self._http_json(f"{endpoint.rstrip('/')}/json/version", "GET")
        ws_url = str(version.get("webSocketDebuggerUrl") or "")
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
        try:
            page = self._http_json(f"{endpoint}/json/new?{quote('about:blank', safe=':/')}", "PUT")
        except Exception:
            page = self._http_json(f"{endpoint}/json/new?{quote('about:blank', safe=':/')}", "GET")
        ws_url = str(page.get("webSocketDebuggerUrl") or "")
        if not ws_url:
            raise RuntimeError("Obscura CDP page did not expose a websocket endpoint.")
        self._page_id = str(page.get("id") or "")
        self._socket = self._websocket_factory(ws_url, float(self.config.navigation_timeout_seconds or 12.0))
        for method in ("Page.enable", "DOM.enable", "Network.enable", "Log.enable"):
            self._send(method)
        return page

    def navigate(self, url: str) -> None:
        self._send("Page.navigate", {"url": url})

    def wait_for_load_state(self) -> str:
        deadline = self._clock() + float(self.config.navigation_timeout_seconds or 12.0)
        state = "loading"
        while self._clock() <= deadline:
            event = self._recv(timeout=max(0.1, min(0.5, deadline - self._clock())))
            if event is None:
                continue
            method = str(event.get("method") or "")
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            if method == "Network.requestWillBeSent":
                request = params.get("request") if isinstance(params.get("request"), dict) else {}
                request_url = str(request.get("url") or "")
                if request_url and len(self._network_requests) < 20:
                    self._network_requests.append(request_url)
            elif method in {"Network.loadingFailed", "Network.responseReceivedExtraInfo"} and str(params.get("errorText") or ""):
                self._network_failures += 1
            elif method == "Log.entryAdded":
                entry = params.get("entry") if isinstance(params.get("entry"), dict) else {}
                if str(entry.get("level") or "").lower() in {"error", "warning"}:
                    message, _ = bounded_text(str(entry.get("text") or ""), 240)
                    if message and len(self._console_errors) < 20:
                        self._console_errors.append(message)
            elif method in {"Page.loadEventFired", "Page.lifecycleEvent"}:
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
        del base_url
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
        return {
            "request_count": len(self._network_requests),
            "failed_count": self._network_failures,
            "sample_urls": self._network_requests[:10],
        }

    def get_console_summary(self) -> dict[str, Any]:
        return {
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
            raise RuntimeError("Obscura CDP client is not connected.")
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
                    raise RuntimeError(redact_url_credentials(json.dumps(message["error"]))[:500])
                result = message.get("result")
                return result if isinstance(result, dict) else {}
        raise TimeoutError(f"CDP command timed out: {method}")

    def _recv(self, *, timeout: float) -> dict[str, Any] | None:
        if self._socket is None:
            return None
        raw = self._socket.recv_text(timeout=timeout)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None


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
                return ""
            if opcode == 1:
                return payload.decode("utf-8", errors="replace")

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


def _http_json(url: str, method: str) -> dict[str, Any]:
    request = Request(url, method=method, headers={"Accept": "application/json"})
    with urlopen(request, timeout=12.0) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


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
