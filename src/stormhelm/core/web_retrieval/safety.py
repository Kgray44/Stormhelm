from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import ParseResult
from urllib.parse import urlparse
from urllib.parse import urlunparse

from stormhelm.config.models import WebRetrievalConfig


@dataclass(slots=True)
class UrlSafetyResult:
    allowed: bool
    original_url: str
    normalized_url: str = ""
    safe_url_display: str = ""
    reason_code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "allowed": self.allowed,
            "original_url": self.original_url,
            "normalized_url": self.normalized_url,
            "safe_url_display": self.safe_url_display,
            "reason_code": self.reason_code,
            "message": self.message,
        }


def validate_public_url(raw_url: str, config: WebRetrievalConfig) -> UrlSafetyResult:
    original = str(raw_url or "").strip()
    if not original:
        return _blocked(original, "missing_url", "A non-empty public URL is required.")
    if len(original) > int(getattr(config, "max_url_chars", 4096) or 4096):
        return _blocked(original, "url_too_long", "The URL is too long for public web retrieval.")
    if re.search(r"[\x00-\x20\x7f]", original):
        return _blocked(original, "control_characters_in_url", "Whitespace and control characters are blocked in URLs.")
    candidate = f"https://{original}" if original.lower().startswith("www.") else original
    try:
        parsed = urlparse(candidate)
        _ = parsed.hostname
        _ = parsed.port
    except ValueError:
        return _blocked(original, "invalid_url", "The URL could not be parsed.")
    display = safe_url_display(candidate)
    scheme = parsed.scheme.lower()
    if scheme == "file":
        if not config.allow_file_urls:
            return _blocked(original, "file_urls_disabled", "Local file URLs are outside public web retrieval.", display)
        return _blocked(original, "unsupported_scheme", "File URL retrieval is not supported by public web providers.", display)
    if scheme not in {"http", "https"}:
        return _blocked(original, "unsupported_scheme", "Only http and https public URLs are supported.", display)
    if not parsed.netloc or not parsed.hostname:
        return _blocked(original, "missing_host", "The URL must include a host.", display)
    if parsed.username or parsed.password:
        return _blocked(original, "credentials_in_url_blocked", "Credential-bearing URLs are blocked.", display)
    if _is_private_or_local_host(parsed.hostname) and not config.allow_private_network_urls:
        return _blocked(original, "private_network_url_blocked", "Private, local, and loopback network URLs are blocked.", display)
    normalized = _normalize_public_url(parsed)
    return UrlSafetyResult(
        allowed=True,
        original_url=original,
        normalized_url=normalized,
        safe_url_display=safe_url_display(normalized),
        reason_code="allowed_public_url",
        message="Public URL accepted for retrieval.",
    )


def safe_url_display(raw_url: str) -> str:
    try:
        parsed = urlparse(str(raw_url or "").strip())
    except ValueError:
        return str(raw_url or "").strip()
    if not parsed.scheme and str(raw_url or "").strip().lower().startswith("www."):
        parsed = urlparse(f"https://{raw_url}")
    try:
        host = parsed.hostname or ""
    except ValueError:
        host = ""
    netloc = host
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port:
        netloc = f"{netloc}:{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", parsed.query, ""))


def redact_url_credentials(text: str) -> str:
    words = str(text or "")
    try:
        parsed = urlparse(words)
    except ValueError:
        parsed = None
    if parsed and parsed.scheme and parsed.hostname and (parsed.username or parsed.password):
        return safe_url_display(words)
    return _CREDENTIAL_URL_RE.sub(lambda match: safe_url_display(match.group(0)), words)


def bounded_text(value: str, limit: int) -> tuple[str, bool]:
    text = str(value or "")
    if limit <= 0 or len(text) <= limit:
        return text, False
    return text[:limit], True


def _blocked(original: str, reason: str, message: str, display: str = "") -> UrlSafetyResult:
    return UrlSafetyResult(
        allowed=False,
        original_url=original,
        safe_url_display=display or safe_url_display(original),
        reason_code=reason,
        message=message,
    )


def _normalize_public_url(parsed: ParseResult) -> str:
    path = "" if parsed.path == "/" else parsed.path or ""
    hostname = (parsed.hostname or "").lower().rstrip(".")
    netloc = hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def _is_private_or_local_host(hostname: str) -> bool:
    host = hostname.strip("[]").rstrip(".").lower()
    if host in {"localhost", "0.0.0.0"} or host.endswith(".localhost") or host.endswith(".local"):
        return True
    weird_ipv4 = _parse_ipv4_loose(host)
    if weird_ipv4 is not None:
        return _is_blocked_ip(weird_ipv4)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_blocked_ip(ip.ipv4_mapped)
    return _is_blocked_ip(ip)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _parse_ipv4_loose(host: str) -> ipaddress.IPv4Address | None:
    if not re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+)){0,3}", host):
        return None
    try:
        parts = [_parse_ipv4_component(part) for part in host.split(".")]
    except ValueError:
        return None
    if not parts:
        return None
    total = 0
    if len(parts) == 1:
        total = parts[0]
        if total > 0xFFFFFFFF:
            return None
    elif len(parts) == 2:
        if parts[0] > 0xFF or parts[1] > 0xFFFFFF:
            return None
        total = (parts[0] << 24) | parts[1]
    elif len(parts) == 3:
        if parts[0] > 0xFF or parts[1] > 0xFF or parts[2] > 0xFFFF:
            return None
        total = (parts[0] << 24) | (parts[1] << 16) | parts[2]
    elif len(parts) == 4:
        if any(part > 0xFF for part in parts):
            return None
        total = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]
    else:
        return None
    try:
        return ipaddress.IPv4Address(total)
    except ipaddress.AddressValueError:
        return None


def _parse_ipv4_component(part: str) -> int:
    lowered = part.lower()
    if lowered.startswith("0x"):
        return int(lowered, 16)
    if len(lowered) > 1 and lowered.startswith("0"):
        return int(lowered, 8)
    return int(lowered, 10)

_CREDENTIAL_URL_RE = re.compile(r"https?://[^/\s:@]+:[^/\s@]+@[^/\s]+[^\s]*", re.IGNORECASE)
