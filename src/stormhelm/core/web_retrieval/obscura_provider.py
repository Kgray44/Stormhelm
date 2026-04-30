from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from time import perf_counter
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from stormhelm.config.models import WebRetrievalObscuraConfig
from stormhelm.core.web_retrieval.models import ExtractedLink
from stormhelm.core.web_retrieval.models import ProviderReadiness
from stormhelm.core.web_retrieval.models import RenderedWebPage
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.safety import bounded_text
from stormhelm.core.web_retrieval.safety import redact_url_credentials


class ObscuraCliProvider:
    name = "obscura"

    def __init__(
        self,
        config: WebRetrievalObscuraConfig,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        which: Callable[[str], str | None] | None = None,
    ) -> None:
        self.config = config
        self._runner = runner or subprocess.run
        self._which = which or shutil.which

    def readiness(self) -> ProviderReadiness:
        if not self.config.enabled:
            return ProviderReadiness(provider=self.name, status="disabled", available=False, reason="obscura_disabled")
        binary = self._resolved_binary()
        if not binary:
            return ProviderReadiness(provider=self.name, status="binary_missing", available=False, reason="binary_missing")
        return ProviderReadiness(provider=self.name, status="available", available=True, detail=binary)

    def retrieve(self, request: WebRetrievalRequest, url: str) -> RenderedWebPage:
        started = perf_counter()
        readiness = self.readiness()
        if not readiness.available:
            code = readiness.reason or readiness.status
            return self._failure(url, "provider_unavailable", code, readiness.reason or readiness.status, started)
        timeout_seconds = float(getattr(self.config, "timeout_seconds", 12.0) or 12.0)
        text_result = self._run_dump(url, "text", timeout=request_timeout(request, timeout_seconds))
        if text_result["status"] != "ok":
            return self._failure(
                url,
                str(text_result["page_status"]),
                str(text_result["error_code"]),
                str(text_result["error_message"]),
                started,
            )
        text, text_truncated = bounded_text(_output_text(text_result["stdout"]), request.max_text_chars or 60000)
        if not text.strip():
            return self._failure(url, "partial", "empty_extraction", "Obscura returned no extracted text.", started)
        links: list[ExtractedLink] = []
        limitations = ["public_pages_only", "no_logged_in_context", "not_truth_verified", "not_user_visible_screen"]
        if request.include_links:
            link_result = self._run_dump(url, "links", timeout=request_timeout(request, timeout_seconds))
            if link_result["status"] == "ok":
                links = _parse_links(_output_text(link_result["stdout"]), base_url=url)
            else:
                limitations.append("link_extraction_failed")
        html = ""
        html_truncated = False
        if request.include_html:
            html_result = self._run_dump(url, "html", timeout=request_timeout(request, timeout_seconds))
            if html_result["status"] == "ok":
                html, html_truncated = bounded_text(_output_text(html_result["stdout"]), request.max_html_chars or 250000)
            else:
                limitations.append("html_extraction_failed")
        title = text.strip().splitlines()[0].strip()[:180] if text.strip() else ""
        truncated = text_truncated or html_truncated
        if truncated:
            limitations.append("output_truncated")
        weak_text = len(" ".join(text.split())) < 20
        if weak_text:
            limitations.append("weak_text_extraction")
        return RenderedWebPage(
            requested_url=url,
            final_url=url,
            provider=self.name,
            status="partial" if truncated or weak_text else "success",
            title=title,
            text=text,
            html=html,
            links=links,
            elapsed_ms=(perf_counter() - started) * 1000,
            rendered_javascript=True,
            confidence="low" if weak_text else "medium",
            error_code="output_truncated" if truncated else "weak_text_extraction" if weak_text else "",
            error_message="Output was truncated at the configured limit." if truncated else "Only a small amount of readable page text was extracted." if weak_text else "",
            limitations=limitations,
            truncated=truncated,
        )

    def _run_dump(self, url: str, dump_format: str, *, timeout: float) -> dict[str, Any]:
        binary = self._resolved_binary()
        if not binary:
            return {
                "status": "error",
                "page_status": "failed",
                "error_code": "binary_missing",
                "error_message": "Obscura binary was not found.",
            }
        command = [
            binary,
            "fetch",
            url,
            "--dump",
            dump_format,
            "--wait-until",
            self.config.wait_until,
            "--quiet",
        ]
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "page_status": "timeout",
                "error_code": "timeout",
                "error_message": "Obscura retrieval timed out.",
            }
        except Exception as error:
            return {
                "status": "error",
                "page_status": "failed",
                "error_code": "process_error",
                "error_message": redact_url_credentials(str(error))[:500],
            }
        if int(getattr(completed, "returncode", 1) or 0) != 0:
            stderr = redact_url_credentials(str(getattr(completed, "stderr", "") or "Obscura process failed."))
            return {
                "status": "error",
                "page_status": "failed",
                "error_code": "process_error",
                "error_message": stderr[:500],
            }
        return {"status": "ok", "stdout": getattr(completed, "stdout", "") or ""}

    def _resolved_binary(self) -> str:
        binary = str(self.config.binary_path or "obscura").strip() or "obscura"
        if any(sep in binary for sep in ("/", "\\")) or (len(binary) > 1 and binary[1] == ":"):
            return binary if Path(binary).exists() else ""
        return self._which(binary) or ""

    def _failure(self, url: str, status: str, code: str, message: str, started: float) -> RenderedWebPage:
        return RenderedWebPage(
            requested_url=url,
            final_url=url,
            provider=self.name,
            status=status,
            error_code=code,
            error_message=message[:500],
            elapsed_ms=(perf_counter() - started) * 1000,
            rendered_javascript=True,
            confidence="low",
            limitations=["public_pages_only", "not_truth_verified", "not_user_visible_screen"],
        )


def request_timeout(request: WebRetrievalRequest, fallback: float) -> float:
    del request
    return max(0.1, float(fallback or 12.0))


def _parse_links(output: str, *, base_url: str) -> list[ExtractedLink]:
    links: list[ExtractedLink] = []
    base_host = urlparse(base_url).netloc.lower()
    seen: set[str] = set()
    for raw in str(output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        url = line.split()[0].strip()
        absolute = urljoin(base_url, url)
        if absolute in seen or not urlparse(absolute).scheme.startswith("http"):
            continue
        seen.add(absolute)
        links.append(
            ExtractedLink(
                url=absolute,
                text=line if line != url else "",
                same_origin=urlparse(absolute).netloc.lower() == base_host,
            )
        )
    return links


def _output_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")
