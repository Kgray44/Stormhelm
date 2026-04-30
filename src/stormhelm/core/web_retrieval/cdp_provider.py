from __future__ import annotations

from time import perf_counter
from typing import Any

from stormhelm.config.models import WebRetrievalConfig
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

    def readiness(self) -> ProviderReadiness:
        readiness = self.manager.readiness()
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
        weak_text = len(" ".join(text.split())) < 20
        if weak_text:
            limitations.append("weak_text_extraction")
        return RenderedWebPage(
            requested_url=url,
            final_url=inspection.final_url or url,
            provider=self.name,
            status="partial" if truncated or weak_text else "success",
            title=inspection.title[:180],
            text=text,
            html=html,
            links=links,
            elapsed_ms=inspection.elapsed_ms or ((perf_counter() - started) * 1000),
            rendered_javascript=True,
            confidence="low" if weak_text else "medium",
            error_code="output_truncated" if truncated else "weak_text_extraction" if weak_text else "",
            error_message="Output was truncated at the configured limit." if truncated else "Only a small amount of readable page text was extracted." if weak_text else "",
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
    ) -> RenderedWebPage:
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
            limitations=["headless_cdp_page_evidence", "public_pages_only", "not_truth_verified", "not_user_visible_screen"],
            cdp_session_id=str(getattr(session, "session_id", "") or ""),
            process_id=int(getattr(session, "process_id", 0) or 0),
            active_port=int(getattr(session, "active_port", 0) or 0),
            claim_ceiling=CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
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
