from __future__ import annotations

from time import perf_counter
from typing import Any

from stormhelm.config.models import WebRetrievalConfig
from stormhelm.core.web_retrieval.cdp import CDPCompatibilityError
from stormhelm.core.web_retrieval.cdp import ObscuraCDPClient
from stormhelm.core.web_retrieval.cdp import ObscuraCDPManager
from stormhelm.core.web_retrieval.models import CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE
from stormhelm.core.web_retrieval.models import ExtractedLink
from stormhelm.core.web_retrieval.models import ObscuraCDPPageInspection
from stormhelm.core.web_retrieval.models import ObscuraCDPProviderAttempt
from stormhelm.core.web_retrieval.models import ProviderReadiness
from stormhelm.core.web_retrieval.models import RenderedWebPage
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.safety import bounded_text
from stormhelm.core.web_retrieval.safety import redact_url_credentials
from stormhelm.core.web_retrieval.safety import validate_public_url


class ObscuraCDPProvider:
    name = "obscura_cdp"

    def __init__(
        self,
        config: WebRetrievalConfig,
        *,
        manager: ObscuraCDPManager | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self.cdp_config = config.obscura.cdp
        self.manager = manager or ObscuraCDPManager(self.cdp_config)
        self.client = client or ObscuraCDPClient(self.cdp_config)
        self.last_attempt: ObscuraCDPProviderAttempt | None = None

    @property
    def compatibility_report(self) -> dict[str, Any]:
        report = getattr(self.manager, "_last_compatibility_report", None)
        if report is not None and hasattr(report, "to_dict"):
            return report.to_dict()
        return {}

    def readiness(self) -> ProviderReadiness:
        readiness = self.manager.readiness()
        if readiness.status == "diagnostic_only" or readiness.diagnostic_only:
            return ProviderReadiness(
                provider=self.name,
                status="diagnostic_only",
                available=False,
                reason="cdp_navigation_unsupported",
                detail=readiness.status_message or "CDP endpoint detected; page navigation unsupported. Use Obscura CLI for page extraction.",
            )
        if readiness.status == "active":
            return ProviderReadiness(provider=self.name, status="active", available=True, detail=readiness.cdp_endpoint_url)
        if readiness.status == "ready":
            return ProviderReadiness(provider=self.name, status="ready", available=True, detail=readiness.binary_path)
        reason = readiness.blocking_reasons[0] if readiness.blocking_reasons else readiness.status
        return ProviderReadiness(provider=self.name, status=readiness.status, available=False, reason=reason, detail=readiness.binary_path)

    def retrieve(self, request: WebRetrievalRequest, url: str) -> RenderedWebPage:
        started = perf_counter()
        readiness = self.readiness()
        if not readiness.available:
            return self._failure(url, "provider_unavailable", readiness.reason or readiness.status, readiness.reason or readiness.status, started)
        session = None
        try:
            session = self.manager.start()
            self.manager.register_page_use()
            inspection = self.client.inspect_url(session, url)
            mark_supported = getattr(self.manager, "mark_page_inspection_supported", None)
            if callable(mark_supported):
                mark_supported()
            final_safety = validate_public_url(inspection.final_url or url, self.config)
            if not final_safety.allowed:
                page = RenderedWebPage(
                    requested_url=url,
                    final_url=inspection.final_url or url,
                    provider=self.name,
                    status="blocked",
                    elapsed_ms=(perf_counter() - started) * 1000,
                    confidence="low",
                    error_code="redirect_target_blocked",
                    error_message=f"Final redirected URL blocked by safety policy: {final_safety.reason_code}.",
                    limitations=["public_url_safety_gate", "redirect_target_blocked"],
                    cdp_session_id=session.session_id,
                    process_id=session.process_id,
                    active_port=session.active_port,
                    page_id=inspection.page_id,
                    load_state=inspection.load_state,
                    claim_ceiling=CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                )
                self._remember_attempt(page, session=session, inspection=inspection, safety_status="blocked")
                return page
            page = self._page_from_inspection(request, url, inspection, started, session=session)
            self._remember_attempt(page, session=session, inspection=inspection, safety_status="allowed")
            return page
        except TimeoutError as error:
            return self._failure(url, "timeout", "timeout", str(error), started, session=session)
        except CDPCompatibilityError as error:
            if error.code == "cdp_navigation_unsupported":
                mark_unsupported = getattr(self.manager, "mark_navigation_unsupported", None)
                if callable(mark_unsupported):
                    mark_unsupported(error.message)
                return self._failure(
                    url,
                    "unsupported",
                    error.code,
                    "CDP endpoint detected; page navigation unsupported. Use Obscura CLI for page extraction.",
                    started,
                    session=session,
                    fallback_provider="obscura",
                )
            return self._failure(url, "failed", error.code, error.message, started, session=session)
        except Exception as error:
            return self._failure(url, "failed", "cdp_error", redact_url_credentials(str(error)), started, session=session)
        finally:
            try:
                close = getattr(self.client, "close", None)
                if callable(close):
                    close()
            finally:
                self.manager.stop()

    def _page_from_inspection(
        self,
        request: WebRetrievalRequest,
        url: str,
        inspection: ObscuraCDPPageInspection,
        started: float,
        *,
        session: Any,
    ) -> RenderedWebPage:
        text, text_truncated = bounded_text(inspection.dom_text, request.max_text_chars or self.cdp_config.max_dom_text_chars)
        html = ""
        html_truncated = False
        if request.include_html:
            html, html_truncated = bounded_text(inspection.html_excerpt, request.max_html_chars or self.cdp_config.max_html_chars)
        links = _links_from_inspection(inspection, max_links=int(self.cdp_config.max_links or 500)) if request.include_links else []
        limitations = list(
            dict.fromkeys(
                [
                    "headless_cdp_page_evidence",
                    "public_pages_only",
                    "not_user_visible_screen",
                    "not_truth_verified",
                    "no_input_domain",
                    "no_logged_in_context",
                    *inspection.limitations,
                ]
            )
        )
        truncated = text_truncated or html_truncated or len(inspection.links) > len(links)
        if truncated:
            limitations.append("output_truncated")
        optional_unavailable = _summary_unavailable(inspection.network_summary) or _summary_unavailable(inspection.console_summary)
        if optional_unavailable:
            limitations.append("optional_cdp_domain_unavailable")
        weak_text = len(" ".join(text.split())) < 20
        if weak_text:
            limitations.append("weak_text_extraction")
        status = "partial" if truncated or weak_text or optional_unavailable else "success"
        error_code = (
            "output_truncated"
            if truncated
            else "optional_cdp_domain_unavailable"
            if optional_unavailable
            else "weak_text_extraction"
            if weak_text
            else ""
        )
        error_message = (
            "Output was truncated at the configured limit."
            if truncated
            else "Optional CDP domains were unavailable; core page evidence was still extracted."
            if optional_unavailable
            else "Only a small amount of readable page text was extracted."
            if weak_text
            else ""
        )
        return RenderedWebPage(
            requested_url=url,
            final_url=inspection.final_url or url,
            provider=self.name,
            status=status,
            title=inspection.title[:180],
            text=text,
            html=html,
            links=links,
            elapsed_ms=inspection.elapsed_ms or ((perf_counter() - started) * 1000),
            rendered_javascript=True,
            confidence="low" if weak_text else "medium",
            error_code=error_code,
            error_message=error_message,
            limitations=list(dict.fromkeys(limitations)),
            truncated=truncated,
            load_state=inspection.load_state,
            cdp_session_id=session.session_id,
            process_id=session.process_id,
            active_port=session.active_port,
            page_id=inspection.page_id,
            network_summary=dict(inspection.network_summary),
            console_summary=dict(inspection.console_summary),
            claim_ceiling=CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
        )

    def _failure(
        self,
        url: str,
        status: str,
        code: str,
        message: str,
        started: float,
        *,
        session: Any | None = None,
        fallback_provider: str = "",
    ) -> RenderedWebPage:
        limitations = ["headless_cdp_page_evidence", "public_pages_only", "not_truth_verified", "not_user_visible_screen"]
        if code == "cdp_navigation_unsupported":
            limitations = [*limitations, "cdp_diagnostic_only", "page_inspection_unsupported"]
        page = RenderedWebPage(
            requested_url=url,
            final_url=url,
            provider=self.name,
            status=status,
            error_code=code,
            error_message=redact_url_credentials(message)[:500],
            elapsed_ms=(perf_counter() - started) * 1000,
            rendered_javascript=True,
            confidence="low",
            limitations=list(dict.fromkeys(limitations)),
            cdp_session_id=str(getattr(session, "session_id", "") or ""),
            process_id=int(getattr(session, "process_id", 0) or 0),
            active_port=int(getattr(session, "active_port", 0) or 0),
            claim_ceiling=CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
            fallback_provider=fallback_provider,
        )
        self._remember_attempt(page, session=session, inspection=None, safety_status="failed")
        return page

    def _remember_attempt(
        self,
        page: RenderedWebPage,
        *,
        session: Any | None,
        inspection: ObscuraCDPPageInspection | None,
        safety_status: str,
    ) -> None:
        network = page.network_summary or (inspection.network_summary if inspection is not None else {})
        console = page.console_summary or (inspection.console_summary if inspection is not None else {})
        self.last_attempt = ObscuraCDPProviderAttempt(
            cdp_session_id=page.cdp_session_id,
            process_id=page.process_id,
            active_port=page.active_port,
            endpoint_url=str(getattr(session, "endpoint_url", "") or ""),
            page_id=page.page_id,
            requested_url=page.requested_url,
            final_url=page.final_url,
            title=page.title,
            load_state=page.load_state,
            dom_text_chars=page.text_chars,
            links_found=page.link_count,
            html_excerpt_chars=page.html_chars,
            network_request_count=int(network.get("request_count") or 0) if isinstance(network, dict) else 0,
            console_error_count=int(console.get("error_count") or 0) if isinstance(console, dict) else 0,
            elapsed_ms=page.elapsed_ms,
            provider_attempt_status=page.status,
            safety_status=safety_status,
            limitations=list(page.limitations),
            error_code=page.error_code,
            bounded_error_message=page.error_message[:500],
        )


def _links_from_inspection(inspection: ObscuraCDPPageInspection, *, max_links: int) -> list[ExtractedLink]:
    links: list[ExtractedLink] = []
    seen: set[str] = set()
    for item in inspection.links:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        links.append(
            ExtractedLink(
                url=url,
                text=str(item.get("text") or "")[:500],
                title=str(item.get("title") or "")[:500],
                rel=str(item.get("rel") or "")[:120],
                same_origin=bool(item.get("same_origin", False)),
            )
        )
        if len(links) >= max(0, max_links):
            break
    return links


def _summary_unavailable(summary: dict[str, Any]) -> bool:
    return isinstance(summary, dict) and summary.get("available") is False
