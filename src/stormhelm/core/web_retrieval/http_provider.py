from __future__ import annotations

from html.parser import HTMLParser
import re
import socket
from time import perf_counter
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from stormhelm.config.models import WebRetrievalConfig
from stormhelm.core.web_retrieval.models import ExtractedLink
from stormhelm.core.web_retrieval.models import ProviderReadiness
from stormhelm.core.web_retrieval.models import RenderedWebPage
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.safety import bounded_text


class _TextAndLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._current_anchor: dict[str, str] | None = None
        self._anchor_text: list[str] = []
        self.text_parts: list[str] = []
        self.non_link_text_parts: list[str] = []
        self.links: list[ExtractedLink] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if lowered in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if lowered == "title":
            self._in_title = True
        if lowered == "a" and attr_map.get("href"):
            self._current_anchor = attr_map
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if lowered == "title":
            self._in_title = False
        if lowered == "a" and self._current_anchor is not None:
            href = self._current_anchor.get("href", "").strip()
            absolute = urljoin(self.base_url, href)
            text = " ".join(" ".join(self._anchor_text).split())
            title = self._current_anchor.get("title", "")
            rel = self._current_anchor.get("rel", "")
            base_host = urlparse(self.base_url).netloc.lower()
            link_host = urlparse(absolute).netloc.lower()
            self.links.append(
                ExtractedLink(
                    url=absolute,
                    text=text,
                    title=title,
                    rel=rel,
                    same_origin=bool(base_host and base_host == link_host),
                )
            )
            self._current_anchor = None
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        text = " ".join(str(data or "").split())
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
            return
        if self._skip_depth:
            return
        self.text_parts.append(text)
        if self._current_anchor is not None:
            self._anchor_text.append(text)
        else:
            self.non_link_text_parts.append(text)

    @property
    def text(self) -> str:
        return " ".join(self.text_parts).strip()

    @property
    def non_link_text(self) -> str:
        return " ".join(self.non_link_text_parts).strip()


class HttpWebRetrievalProvider:
    name = "http"

    def __init__(
        self,
        config: WebRetrievalConfig,
        *,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self._opener = opener or urlopen

    def readiness(self) -> ProviderReadiness:
        return ProviderReadiness(
            provider=self.name,
            status="available" if self.config.http.enabled else "disabled",
            available=bool(self.config.http.enabled),
            reason="" if self.config.http.enabled else "http_provider_disabled",
        )

    def retrieve(self, request: WebRetrievalRequest, url: str) -> RenderedWebPage:
        started = perf_counter()
        if not self.config.http.enabled:
            return self._failure(url, "unsupported", "http_provider_disabled", "HTTP retrieval is disabled.", started)
        http_request = Request(
            url,
            headers={
                "User-Agent": "Stormhelm-WebRetrieval/1.0 (+public-page-evidence)",
                "Accept": "text/html, text/plain;q=0.9, */*;q=0.5",
            },
        )
        try:
            with self._opener(http_request, timeout=float(self.config.http.timeout_seconds)) as response:
                body = response.read()
                final_url = response.geturl() if hasattr(response, "geturl") else url
                status_code = response.getcode() if hasattr(response, "getcode") else getattr(response, "status", 200)
                content_type = _header(response, "content-type")
        except HTTPError as error:
            return self._failure(url, "failed", "http_status_error", f"HTTP {error.code}", started)
        except URLError as error:
            if isinstance(getattr(error, "reason", None), (TimeoutError, socket.timeout)):
                return self._failure(url, "timeout", "timeout", "HTTP retrieval timed out.", started)
            return self._failure(url, "failed", "http_error", str(error.reason or error), started)
        except (TimeoutError, socket.timeout):
            return self._failure(url, "timeout", "timeout", "HTTP retrieval timed out.", started)
        except Exception as error:
            return self._failure(url, "failed", "http_error", str(error), started)

        encoding = _encoding_from_content_type(content_type) or "utf-8"
        html, html_truncated = bounded_text(body.decode(encoding, errors="replace"), request.max_html_chars or self.config.max_html_chars)
        title = ""
        links: list[ExtractedLink] = []
        non_link_text = ""
        if int(status_code or 0) >= 400:
            return self._failure(url, "failed", "http_status_error", f"HTTP {status_code}", started)
        if _unsupported_content_type(content_type, html):
            return self._failure(
                url,
                "unsupported",
                "unsupported_content_type",
                f"Unsupported content type: {content_type or 'unknown'}",
                started,
            )
        if _looks_like_html(content_type, html):
            parser = _TextAndLinkParser(final_url)
            parser.feed(html)
            text = parser.text
            non_link_text = parser.non_link_text
            title = parser.title
            links = parser.links if request.include_links else []
        else:
            text = html
            non_link_text = text
        text, text_truncated = bounded_text(text, request.max_text_chars or self.config.max_text_chars)
        limitations = ["static_http_only", "no_javascript_rendering", "not_truth_verified"]
        status, confidence, code, message, extra_limitations = _classify_extraction(
            title=title,
            text=text,
            html=html,
            links=links,
            non_link_text=non_link_text,
            truncated=html_truncated or text_truncated,
        )
        limitations.extend(extra_limitations)
        return RenderedWebPage(
            requested_url=url,
            final_url=final_url,
            provider=self.name,
            status=status,
            title=title,
            text=text,
            html=html if request.include_html else "",
            links=links,
            elapsed_ms=(perf_counter() - started) * 1000,
            rendered_javascript=False,
            confidence=confidence,
            error_code=code,
            error_message=message,
            limitations=limitations,
            truncated=html_truncated or text_truncated,
        )

    def _failure(self, url: str, status: str, code: str, message: str, started: float) -> RenderedWebPage:
        return RenderedWebPage(
            requested_url=url,
            final_url=url,
            provider=self.name,
            status=status,
            error_code=code,
            error_message=message[:500],
            elapsed_ms=(perf_counter() - started) * 1000,
            confidence="low",
            limitations=["static_http_only", "not_truth_verified"],
        )


def _header(response: Any, name: str) -> str:
    headers = getattr(response, "headers", {})
    if isinstance(headers, dict):
        return str(headers.get(name) or headers.get(name.title()) or "")
    getter = getattr(headers, "get", None)
    return str(getter(name, "") if callable(getter) else "")


def _encoding_from_content_type(value: str) -> str:
    lowered = str(value or "").lower()
    if "charset=" not in lowered:
        return ""
    return lowered.split("charset=", 1)[1].split(";", 1)[0].strip()


def _looks_like_html(content_type: str, html: str) -> bool:
    lowered_type = str(content_type or "").lower()
    return "html" in lowered_type or "<html" in html[:500].lower() or "<!doctype html" in html[:500].lower()


def _unsupported_content_type(content_type: str, body: str) -> bool:
    lowered = str(content_type or "").split(";", 1)[0].strip().lower()
    if not lowered:
        return not _looks_like_html(content_type, body)
    if lowered in {"text/html", "application/xhtml+xml", "text/plain"}:
        return False
    return not _looks_like_html(content_type, body)


def _classify_extraction(
    *,
    title: str,
    text: str,
    html: str,
    links: list[ExtractedLink],
    non_link_text: str,
    truncated: bool,
) -> tuple[str, str, str, str, list[str]]:
    clean_text = " ".join(str(text or "").split()).strip()
    clean_title = " ".join(str(title or "").split()).strip()
    clean_non_link = " ".join(str(non_link_text or "").split()).strip()
    lowered = f"{clean_title} {clean_text}".lower()
    limitations: list[str] = []
    if truncated:
        limitations.append("output_truncated")
        return "partial", "medium" if clean_text else "low", "output_truncated", "Output was truncated at the configured limit.", limitations
    if _probable_error_page(lowered):
        limitations.append("probable_error_page")
        return "partial", "low", "probable_error_page", "The extracted page looks like an error page.", limitations
    if not clean_text:
        if links:
            limitations.extend(["weak_text_extraction", "links_only_extraction"])
            return "partial", "low", "links_only_extraction", "The page exposed links but little readable body text.", limitations
        if clean_title:
            limitations.extend(["weak_text_extraction", "title_only_extraction"])
            return "partial", "low", "title_only_extraction", "The page exposed a title but no readable body text.", limitations
        limitations.append("empty_extraction")
        return "partial", "low", "empty_extraction", "No readable page text was extracted.", limitations
    word_count = len(re.findall(r"[A-Za-z0-9]+", clean_text))
    if len(links) >= 3 and len(re.findall(r"[A-Za-z0-9]+", clean_non_link)) <= 2:
        limitations.extend(["weak_text_extraction", "links_only_extraction"])
        return "partial", "low", "links_only_extraction", "The page is mostly links with little readable body text.", limitations
    if _looks_like_app_shell(clean_text, html):
        limitations.extend(["weak_text_extraction", "app_shell_low_text"])
        return "partial", "low", "app_shell_low_text", "The page looks like an app shell with little readable text.", limitations
    if _boilerplate_only(clean_text):
        limitations.extend(["weak_text_extraction", "boilerplate_only"])
        return "partial", "low", "boilerplate_only", "The extracted text looks like boilerplate rather than page evidence.", limitations
    if word_count < 12 or len(clean_text) < 80:
        limitations.append("weak_text_extraction")
        return "partial", "low", "weak_text_extraction", "Only a small amount of readable page text was extracted.", limitations
    return "success", "medium", "", "", limitations


def _probable_error_page(lowered_text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:404|403|500|not found|access denied|forbidden|service unavailable|error page|page unavailable)\b",
            lowered_text,
        )
        and len(lowered_text) < 500
    )


def _looks_like_app_shell(text: str, html: str) -> bool:
    lowered = f"{text} {html[:1000]}".lower()
    return bool(
        len(text) < 240
        and (
            "enable javascript" in lowered
            or "loading..." in lowered
            or 'id="root"' in lowered
            or 'id="app"' in lowered
            or "data-reactroot" in lowered
        )
    )


def _boilerplate_only(text: str) -> bool:
    words = re.findall(r"[a-z]+", text.lower())
    if not words or len(words) > 40:
        return False
    boilerplate = {"cookie", "cookies", "privacy", "terms", "copyright", "rights", "reserved", "accept", "preferences"}
    return sum(1 for word in words if word in boilerplate) >= max(3, len(words) // 2)
