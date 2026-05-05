from __future__ import annotations

from dataclasses import replace
import socket
import subprocess
from urllib.error import URLError

import pytest

from stormhelm.config.models import WebRetrievalConfig
from stormhelm.config.models import WebRetrievalHttpConfig
from stormhelm.config.models import WebRetrievalObscuraConfig
from stormhelm.core.web_retrieval.http_provider import HttpWebRetrievalProvider
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.obscura_provider import ObscuraCliProvider


class _Response:
    def __init__(self, body: bytes, *, url: str = "https://example.com/final", status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.url = url
        self.status = status
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self.url

    def getcode(self) -> int:
        return self.status


def test_http_provider_extracts_title_text_and_links() -> None:
    def opener(_request, timeout):
        assert timeout == pytest.approx(8.0)
        return _Response(
            b"<html><head><title>Example</title><script>ignored()</script></head>"
            b"<body><main>Hello <b>world</b>. This public fixture contains enough readable "
            b"body text for Stormhelm to treat it as meaningful page evidence."
            b"<a href='/next'>Next</a></main></body></html>"
        )

    provider = HttpWebRetrievalProvider(WebRetrievalConfig(http=WebRetrievalHttpConfig()), opener=opener)
    page = provider.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="read_page"), "https://example.com")

    assert page.status == "success"
    assert page.title == "Example"
    assert "Hello world" in page.text
    assert page.links[0].url == "https://example.com/next"
    assert page.rendered_javascript is False


def test_http_provider_marks_javascript_app_shell_as_partial_low_confidence() -> None:
    def opener(_request, timeout):
        return _Response(
            b"<html><head><title>Dashboard</title></head>"
            b"<body><div id='root'>Loading...</div><script src='/app.js'></script>"
            b"<noscript>Please enable JavaScript to use this app.</noscript></body></html>"
        )

    provider = HttpWebRetrievalProvider(WebRetrievalConfig(), opener=opener)
    page = provider.retrieve(WebRetrievalRequest(urls=["https://example.com/app"], intent="read_page"), "https://example.com/app")

    assert page.status == "partial"
    assert page.confidence == "low"
    assert page.error_code == "app_shell_low_text"
    assert "weak_text_extraction" in page.limitations


def test_http_provider_classifies_link_heavy_or_title_only_pages_as_partial() -> None:
    def opener(_request, timeout):
        return _Response(
            b"<html><head><title>Links</title></head><body>"
            b"<a href='/a'>A</a><a href='/b'>B</a><a href='/c'>C</a></body></html>"
        )

    provider = HttpWebRetrievalProvider(WebRetrievalConfig(), opener=opener)
    page = provider.retrieve(WebRetrievalRequest(urls=["https://example.com/links"], intent="extract_links"), "https://example.com/links")

    assert page.status == "partial"
    assert page.confidence == "low"
    assert page.error_code == "links_only_extraction"
    assert page.link_count == 3


def test_http_provider_detects_error_pages_and_unsupported_content_types() -> None:
    def error_opener(_request, timeout):
        return _Response(
            b"<html><head><title>404 Not Found</title></head><body>Not Found</body></html>",
            status=200,
        )

    error_page = HttpWebRetrievalProvider(WebRetrievalConfig(), opener=error_opener).retrieve(
        WebRetrievalRequest(urls=["https://example.com/missing"], intent="read_page"),
        "https://example.com/missing",
    )
    assert error_page.status == "partial"
    assert error_page.error_code == "probable_error_page"

    def pdf_opener(_request, timeout):
        return _Response(b"%PDF-1.7", headers={"content-type": "application/pdf"})

    unsupported = HttpWebRetrievalProvider(WebRetrievalConfig(), opener=pdf_opener).retrieve(
        WebRetrievalRequest(urls=["https://example.com/file.pdf"], intent="read_page"),
        "https://example.com/file.pdf",
    )
    assert unsupported.status == "unsupported"
    assert unsupported.error_code == "unsupported_content_type"


def test_http_provider_maps_socket_timeout_to_typed_timeout() -> None:
    def opener(_request, timeout):
        raise socket.timeout("timed out")

    provider = HttpWebRetrievalProvider(WebRetrievalConfig(), opener=opener)
    page = provider.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="read_page"), "https://example.com")

    assert page.status == "timeout"
    assert page.error_code == "timeout"


def test_http_provider_maps_network_errors_to_typed_failure() -> None:
    def opener(_request, timeout):
        raise URLError("network unreachable")

    provider = HttpWebRetrievalProvider(WebRetrievalConfig(), opener=opener)
    page = provider.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="read_page"), "https://example.com")

    assert page.status == "failed"
    assert page.error_code == "http_error"
    assert "network unreachable" in page.error_message


def test_obscura_provider_reports_disabled_and_missing_binary_readiness() -> None:
    disabled = ObscuraCliProvider(WebRetrievalObscuraConfig(enabled=False), which=lambda _binary: None)
    missing = ObscuraCliProvider(WebRetrievalObscuraConfig(enabled=True, binary_path="obscura"), which=lambda _binary: None)

    assert disabled.readiness().status == "disabled"
    assert missing.readiness().status == "binary_missing"

    disabled_page = disabled.retrieve(
        WebRetrievalRequest(urls=["https://example.com"], intent="render_page"),
        "https://example.com",
    )
    missing_page = missing.retrieve(
        WebRetrievalRequest(urls=["https://example.com"], intent="render_page"),
        "https://example.com",
    )
    assert disabled_page.status == "provider_unavailable"
    assert disabled_page.error_code == "obscura_disabled"
    assert missing_page.status == "provider_unavailable"
    assert missing_page.error_code == "binary_missing"


def test_obscura_provider_runs_bounded_cli_and_extracts_links() -> None:
    calls: list[list[str]] = []
    kwargs_seen: list[dict[str, object]] = []

    def runner(command, **kwargs):
        calls.append(list(command))
        kwargs_seen.append(dict(kwargs))
        if "--dump" in command and command[command.index("--dump") + 1] == "links":
            return subprocess.CompletedProcess(command, 0, stdout="https://example.com/a\n/about\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="Rendered headline\n\nRendered body", stderr="")

    provider = ObscuraCliProvider(
        WebRetrievalObscuraConfig(enabled=True, binary_path="obscura", wait_until="networkidle0"),
        runner=runner,
        which=lambda binary: binary,
    )
    page = provider.retrieve(WebRetrievalRequest(urls=["https://example.com"], intent="render_page"), "https://example.com")

    assert page.status == "success"
    assert page.provider == "obscura"
    assert page.rendered_javascript is True
    assert page.text.startswith("Rendered headline")
    assert [link.url for link in page.links] == ["https://example.com/a", "https://example.com/about"]
    assert calls[0][:3] == ["obscura", "fetch", "https://example.com"]
    assert kwargs_seen[0]["encoding"] == "utf-8"
    assert kwargs_seen[0]["errors"] == "replace"


def test_obscura_provider_maps_timeout_nonzero_and_empty_stdout() -> None:
    base = WebRetrievalObscuraConfig(enabled=True, binary_path="obscura")

    def timeout_runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=1)

    timed_out = ObscuraCliProvider(base, runner=timeout_runner, which=lambda binary: binary).retrieve(
        WebRetrievalRequest(urls=["https://example.com"], intent="render_page"),
        "https://example.com",
    )
    assert timed_out.status == "timeout"
    assert timed_out.error_code == "timeout"

    def error_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="failed https://user:secret@example.com")

    failed = ObscuraCliProvider(base, runner=error_runner, which=lambda binary: binary).retrieve(
        WebRetrievalRequest(urls=["https://example.com"], intent="render_page"),
        "https://example.com",
    )
    assert failed.status == "failed"
    assert failed.error_code == "process_error"
    assert "secret" not in failed.error_message

    def empty_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    empty = ObscuraCliProvider(base, runner=empty_runner, which=lambda binary: binary).retrieve(
        WebRetrievalRequest(urls=["https://example.com"], intent="render_page"),
        "https://example.com",
    )
    assert empty.status == "partial"
    assert empty.error_code == "empty_extraction"


def test_obscura_provider_bounds_huge_and_weird_output_without_fake_success() -> None:
    base = WebRetrievalObscuraConfig(enabled=True, binary_path="obscura")

    def huge_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="A" * 200, stderr="")

    huge = ObscuraCliProvider(base, runner=huge_runner, which=lambda binary: binary).retrieve(
        WebRetrievalRequest(urls=["https://example.com"], intent="render_page", max_text_chars=50),
        "https://example.com",
    )
    assert huge.status == "partial"
    assert huge.error_code == "output_truncated"
    assert huge.truncated is True

    def bytes_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=b"\xff\xfeRendered text", stderr=b"")

    weird = ObscuraCliProvider(base, runner=bytes_runner, which=lambda binary: binary).retrieve(
        WebRetrievalRequest(urls=["https://example.com"], intent="render_page"),
        "https://example.com",
    )
    assert weird.status in {"success", "partial"}
    assert "Rendered text" in weird.text
    assert not weird.text.startswith("b'")
