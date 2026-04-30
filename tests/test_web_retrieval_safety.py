from __future__ import annotations

import pytest

from stormhelm.config.models import WebRetrievalConfig
from stormhelm.core.web_retrieval.safety import safe_url_display
from stormhelm.core.web_retrieval.safety import validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/path?x=1",
        "http://example.com",
        "www.example.com/docs",
    ],
)
def test_validate_public_url_accepts_public_http_urls(url: str) -> None:
    result = validate_public_url(url, WebRetrievalConfig())

    assert result.allowed is True
    assert result.normalized_url.startswith(("http://", "https://"))
    assert result.reason_code == "allowed_public_url"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("file:///C:/Users/kkids/secrets.txt", "file_urls_disabled"),
        ("http://localhost:8765/health", "private_network_url_blocked"),
        ("http://127.0.0.1:8765/health", "private_network_url_blocked"),
        ("http://10.0.0.12/", "private_network_url_blocked"),
        ("http://172.16.1.4/", "private_network_url_blocked"),
        ("http://192.168.1.1/", "private_network_url_blocked"),
        ("http://[::1]/", "private_network_url_blocked"),
        ("ftp://example.com/file", "unsupported_scheme"),
        ("https://user:secret@example.com/path", "credentials_in_url_blocked"),
    ],
)
def test_validate_public_url_blocks_non_public_or_credentialed_targets(url: str, reason: str) -> None:
    result = validate_public_url(url, WebRetrievalConfig())

    assert result.allowed is False
    assert result.reason_code == reason


def test_safe_url_display_redacts_credentials_and_fragments() -> None:
    assert safe_url_display("https://user:secret@example.com/path?q=1#token") == "https://example.com/path?q=1"


def test_validate_public_url_normalizes_scheme_and_blocks_control_characters() -> None:
    accepted = validate_public_url("HTTPS://Example.COM/Docs", WebRetrievalConfig())

    assert accepted.allowed is True
    assert accepted.normalized_url == "https://example.com/Docs"

    blocked = validate_public_url("https://example.com/\n@127.0.0.1/admin", WebRetrievalConfig())

    assert blocked.allowed is False
    assert blocked.reason_code == "control_characters_in_url"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://example.com:999999/path", "invalid_url"),
        ("https://example.com/" + ("a" * 5000), "url_too_long"),
        ("http://LOCALHOST./health", "private_network_url_blocked"),
        ("http://127.1/admin", "private_network_url_blocked"),
        ("http://2130706433/admin", "private_network_url_blocked"),
        ("http://0x7f000001/admin", "private_network_url_blocked"),
        ("http://0177.0.0.1/admin", "private_network_url_blocked"),
        ("http://127.000.000.001/admin", "private_network_url_blocked"),
        ("http://169.254.169.254/latest/meta-data", "private_network_url_blocked"),
        ("http://[fe80::1]/", "private_network_url_blocked"),
        ("http://[fc00::1]/", "private_network_url_blocked"),
        ("http://[::ffff:127.0.0.1]/", "private_network_url_blocked"),
        ("gopher://example.com/", "unsupported_scheme"),
    ],
)
def test_validate_public_url_blocks_adversarial_public_looking_urls(url: str, reason: str) -> None:
    result = validate_public_url(url, WebRetrievalConfig())

    assert result.allowed is False
    assert result.reason_code == reason
