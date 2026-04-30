from __future__ import annotations

from time import perf_counter
from typing import Any

from stormhelm.config.models import WebRetrievalConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.events import EventFamily
from stormhelm.core.events import EventRetentionClass
from stormhelm.core.events import EventSeverity
from stormhelm.core.events import EventVisibilityScope
from stormhelm.core.web_retrieval.http_provider import HttpWebRetrievalProvider
from stormhelm.core.web_retrieval.cdp_provider import ObscuraCDPProvider
from stormhelm.core.web_retrieval.models import CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE
from stormhelm.core.web_retrieval.models import CLAIM_CEILING_RENDERED_PAGE_EVIDENCE
from stormhelm.core.web_retrieval.models import ProviderReadiness
from stormhelm.core.web_retrieval.models import RenderedWebPage
from stormhelm.core.web_retrieval.models import WebEvidenceBundle
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.models import WebRetrievalTrace
from stormhelm.core.web_retrieval.obscura_provider import ObscuraCliProvider
from stormhelm.core.web_retrieval.safety import UrlSafetyResult
from stormhelm.core.web_retrieval.safety import bounded_text
from stormhelm.core.web_retrieval.safety import safe_url_display
from stormhelm.core.web_retrieval.safety import validate_public_url


class WebRetrievalService:
    def __init__(
        self,
        config: WebRetrievalConfig,
        *,
        events: EventBuffer | None = None,
        http_provider: Any | None = None,
        obscura_provider: Any | None = None,
        cdp_provider: Any | None = None,
    ) -> None:
        self.config = config
        self.events = events
        self.http_provider = http_provider if http_provider is not None else HttpWebRetrievalProvider(config)
        self.obscura_provider = (
            obscura_provider
            if obscura_provider is not None
            else ObscuraCliProvider(config.obscura)
        )
        self.cdp_provider = cdp_provider if cdp_provider is not None else ObscuraCDPProvider(config)

    def retrieve(self, request: WebRetrievalRequest) -> WebEvidenceBundle:
        started = perf_counter()
        urls = self._dedupe_urls(list(request.urls or []))[: max(1, int(self.config.max_url_count or 1))]
        attempted: list[str] = []
        provider_attempts: list[dict[str, str | bool | float]] = []
        provider_chain: list[str] = []
        pages: list[RenderedWebPage] = []
        limitations: list[str] = []
        errors: list[dict[str, str]] = []
        readiness_payload: dict[str, Any] = {}
        trace_safety: dict[str, Any] = {}
        trace_final_url = ""
        extraction_confidence = ""
        fallback_reason = ""
        fallback_outcome = ""
        fallback_used = False
        trace_cdp: dict[str, Any] = {}
        self._publish(
            "web_retrieval.requested",
            "Web retrieval requested.",
            {"url_count": len(urls), "intent": request.intent, "claim_ceiling": CLAIM_CEILING_RENDERED_PAGE_EVIDENCE},
        )
        if not self.config.enabled:
            page = RenderedWebPage(
                requested_url="",
                final_url="",
                provider="none",
                status="unsupported",
                error_code="web_retrieval_disabled",
                error_message="Web retrieval is disabled.",
            )
            trace = WebRetrievalTrace(request_id=request.request_id, result_state="unsupported", errors=[{"code": "web_retrieval_disabled", "message": page.error_message}])
            return WebEvidenceBundle(request=request, pages=[page], trace=trace, result_state="unsupported", limitations=["web_retrieval_disabled"])

        for raw_url in urls:
            safety = validate_public_url(raw_url, self.config)
            if not trace_safety:
                trace_safety["initial"] = safety.to_dict()
            if not safety.allowed:
                page = RenderedWebPage(
                    requested_url=raw_url,
                    final_url=safety.normalized_url or raw_url,
                    provider="safety",
                    status="blocked",
                    error_code=safety.reason_code,
                    error_message=safety.message,
                    limitations=["public_url_safety_gate"],
                )
                pages.append(page)
                errors.append({"code": safety.reason_code, "message": safety.message})
                if not trace_safety.get("final"):
                    trace_safety["final"] = safety.to_dict()
                self._publish(
                    "web_retrieval.blocked",
                    "Web retrieval blocked by public URL safety policy.",
                    {
                        "safe_url_display": safety.safe_url_display,
                        "status": "blocked",
                        "error_code": safety.reason_code,
                        "claim_ceiling": CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
                    },
                    severity=EventSeverity.WARNING,
                    visibility=EventVisibilityScope.GHOST_HINT,
                )
                continue
            normalized_url = safety.normalized_url
            providers = self._provider_order(request)
            selected_provider = providers[0] if providers else ""
            self._publish(
                "web_retrieval.provider_selected",
                "Web retrieval provider selected.",
                {
                    "safe_url_display": safety.safe_url_display,
                    "provider": selected_provider,
                    "mode": request.intent,
                    "claim_ceiling": CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
                },
            )
            first_failure: RenderedWebPage | None = None
            selected_page: RenderedWebPage | None = None
            selected_attempt_status = ""
            for index, provider_name in enumerate(providers):
                provider = self._provider(provider_name)
                if provider is None:
                    continue
                attempted.append(provider_name)
                if provider_name not in provider_chain:
                    provider_chain.append(provider_name)
                readiness = self._readiness(provider)
                readiness_payload[provider_name] = readiness.to_dict()
                if not readiness.available:
                    if provider_name == "obscura_cdp":
                        self._publish_cdp_event(
                            "web_retrieval.obscura_cdp_start_failed",
                            "CDP inspection failed.",
                            {
                                "safe_url_display": safety.safe_url_display,
                                "provider": provider_name,
                                "status": readiness.status,
                                "error_code": readiness.reason or readiness.status,
                                "claim_ceiling": CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                            },
                            severity=EventSeverity.WARNING,
                            visibility=EventVisibilityScope.GHOST_HINT,
                        )
                    unavailable = RenderedWebPage(
                        requested_url=normalized_url,
                        final_url=normalized_url,
                        provider=provider_name,
                        status="provider_unavailable",
                        error_code=readiness.status,
                        error_message=readiness.reason or readiness.status,
                    )
                    self._record_attempt(provider_attempts, unavailable, readiness=readiness.status)
                    errors.append(_error_payload(unavailable))
                    first_failure = first_failure or unavailable
                    limitations.append(f"{provider_name}_unavailable")
                    continue
                if provider_name == "obscura_cdp":
                    self._publish_cdp_event(
                        "web_retrieval.obscura_cdp_start_requested",
                        "CDP page inspection started.",
                        {
                            "safe_url_display": safety.safe_url_display,
                            "provider": provider_name,
                            "claim_ceiling": CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                        },
                    )
                    self._publish_cdp_event(
                        "web_retrieval.obscura_cdp_navigation_started",
                        "CDP page navigation started.",
                        {
                            "safe_url_display": safety.safe_url_display,
                            "provider": provider_name,
                            "claim_ceiling": CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                        },
                    )
                page = provider.retrieve(request, normalized_url)
                if provider_name == "obscura_cdp":
                    cdp_attempt = self._cdp_attempt(provider, page)
                    if cdp_attempt:
                        trace_cdp = cdp_attempt
                    self._publish_cdp_result(page, cdp_attempt)
                page, final_safety = self._enforce_final_url_safety(page)
                if not trace_safety.get("final"):
                    trace_safety["final"] = final_safety.to_dict()
                trace_final_url = page.final_url or trace_final_url
                extraction_confidence = page.confidence or extraction_confidence
                self._record_attempt(provider_attempts, page, readiness=readiness.status)
                if page.status not in {"success"} and page.error_code:
                    errors.append(_error_payload(page))
                if page.status in {"success", "partial"} and (page.text or page.links or page.title):
                    selected_page = page
                    selected_attempt_status = page.status
                    fallback_used = fallback_used or index > 0 or first_failure is not None
                    if first_failure is not None:
                        limitations.append(f"{first_failure.provider}_failed")
                        fallback_reason = f"{first_failure.provider}:{first_failure.error_code or first_failure.status}"
                        fallback_outcome = f"{provider_name}:{page.status}"
                        self._publish(
                            "web_retrieval.fallback_used",
                            "Web retrieval fallback provider used.",
                            {
                                "safe_url_display": safety.safe_url_display,
                                "from_provider": first_failure.provider,
                                "to_provider": provider_name,
                                "fallback_reason": fallback_reason,
                                "fallback_outcome": fallback_outcome,
                                "fallback": True,
                                "claim_ceiling": CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
                            },
                        )
                    break
                first_failure = first_failure or page
                if page.error_code:
                    fallback_reason = fallback_reason or f"{page.provider}:{page.error_code}"
            page = selected_page or first_failure or RenderedWebPage(
                requested_url=normalized_url,
                final_url=normalized_url,
                provider="none",
                status="failed",
                error_code="provider_unavailable",
                error_message="No web retrieval provider was available.",
            )
            pages.append(page)
            event_type = (
                "web_retrieval.page_rendered"
                if page.status == "success"
                else "web_retrieval.page_partial"
                if page.status == "partial"
                else "web_retrieval.page_failed"
            )
            self._publish_page(event_type, page)
            if selected_page is not None and not fallback_outcome:
                fallback_outcome = f"{selected_page.provider}:{selected_attempt_status or selected_page.status}"

        result_state = _bundle_state(pages)
        first_error = next((error for error in errors if error.get("code")), {})
        trace = WebRetrievalTrace(
            request_id=request.request_id,
            selected_provider=_selected_provider(pages) or (provider_chain[-1] if provider_chain else ""),
            attempted_providers=list(dict.fromkeys(attempted)),
            provider_attempts=provider_attempts,
            result_state=result_state,
            elapsed_ms=(perf_counter() - started) * 1000,
            page_count=len(pages),
            text_chars=sum(page.text_chars for page in pages),
            link_count=sum(page.link_count for page in pages),
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            fallback_outcome=fallback_outcome,
            url_safety=trace_safety,
            final_url=trace_final_url or next((page.final_url for page in pages if page.final_url), ""),
            extraction_confidence=extraction_confidence or next((page.confidence for page in pages if page.confidence), ""),
            limitations=list(dict.fromkeys(limitations)),
            provider_readiness=readiness_payload,
            errors=errors,
            error_code=str(first_error.get("code") or ""),
            error_message=str(first_error.get("message") or ""),
            claim_ceiling=CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
            cdp=trace_cdp,
        )
        if any(page.provider == "obscura_cdp" for page in pages):
            trace.claim_ceiling = CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE
        return WebEvidenceBundle(
            request=request,
            pages=pages,
            trace=trace,
            result_state=result_state,
            provider_chain=provider_chain,
            fallback_used=fallback_used,
            limitations=list(dict.fromkeys(limitations)),
            summary_ready=result_state in {"extracted", "partial"},
            claim_ceiling=trace.claim_ceiling,
        )

    def _provider_order(self, request: WebRetrievalRequest) -> list[str]:
        preferred = str(request.preferred_provider or self.config.default_provider or "auto").strip().lower()
        cdp_requested = preferred in {"obscura_cdp", "obscura.cdp", "cdp"} or str(request.intent or "").startswith("cdp_")
        rendering = bool(request.require_rendering or request.intent in {"render_page", "compare_pages"})
        if cdp_requested:
            order = ["obscura_cdp"]
        elif preferred == "obscura" or rendering:
            order = ["obscura", "http"]
        elif preferred == "http":
            order = ["http", "obscura"]
        elif preferred in {"browser_renderer", "headless"}:
            order = ["obscura_cdp", "obscura", "http"]
        else:
            order = ["http", "obscura"]
        if not self.config.http.enabled:
            order = [item for item in order if item != "http"]
        if not self.config.obscura.enabled and not rendering and preferred != "obscura":
            order = [item for item in order if item != "obscura"]
        if "obscura_cdp" in order and not (self.config.obscura.cdp.enabled or cdp_requested):
            order = [item for item in order if item != "obscura_cdp"]
        return list(dict.fromkeys(order))

    def _provider(self, provider_name: str) -> Any | None:
        if provider_name == "http":
            return self.http_provider
        if provider_name == "obscura":
            return self.obscura_provider
        if provider_name == "obscura_cdp":
            return self.cdp_provider
        return None

    def _dedupe_urls(self, raw_urls: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for raw_url in raw_urls:
            candidate = str(raw_url or "").strip()
            if not candidate:
                continue
            safety = validate_public_url(candidate, self.config)
            key = safety.normalized_url or candidate
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _readiness(self, provider: Any) -> ProviderReadiness:
        raw = provider.readiness() if hasattr(provider, "readiness") else {"status": "available", "provider": getattr(provider, "name", "provider")}
        if isinstance(raw, ProviderReadiness):
            return raw
        if isinstance(raw, dict):
            status = str(raw.get("status") or "available").strip()
            return ProviderReadiness(
                provider=str(raw.get("provider") or getattr(provider, "name", "provider")),
                status=status,
                available=status == "available" or bool(raw.get("available", False)),
                reason=str(raw.get("reason") or ""),
                detail=str(raw.get("detail") or ""),
            )
        return ProviderReadiness(provider=getattr(provider, "name", "provider"), status="available", available=True)

    def _enforce_final_url_safety(self, page: RenderedWebPage) -> tuple[RenderedWebPage, UrlSafetyResult]:
        final_url = page.final_url or page.requested_url
        final_safety = validate_public_url(final_url, self.config)
        if final_safety.allowed:
            return page, final_safety
        blocked = RenderedWebPage(
            requested_url=page.requested_url,
            final_url=final_url,
            provider=page.provider,
            status="blocked",
            elapsed_ms=page.elapsed_ms,
            confidence="low",
            error_code="redirect_target_blocked",
            error_message=f"Final redirected URL blocked by safety policy: {final_safety.reason_code}.",
            limitations=list(dict.fromkeys([*page.limitations, "public_url_safety_gate", "redirect_target_blocked"])),
            cdp_session_id=page.cdp_session_id,
            process_id=page.process_id,
            active_port=page.active_port,
            page_id=page.page_id,
            load_state=page.load_state,
            claim_ceiling=page.claim_ceiling,
        )
        return blocked, final_safety

    def _record_attempt(
        self,
        attempts: list[dict[str, str | bool | float]],
        page: RenderedWebPage,
        *,
        readiness: str,
    ) -> None:
        attempts.append(
            {
                "provider": page.provider,
                "readiness": readiness,
                "status": page.status,
                "error_code": page.error_code,
                "error_message": _bounded_message(page.error_message),
                "elapsed_ms": round(float(page.elapsed_ms or 0.0), 3),
                "text_chars": page.text_chars,
                "link_count": page.link_count,
                "confidence": page.confidence,
            }
        )
        if page.provider == "obscura_cdp":
            attempts[-1].update(
                {
                    "cdp_session_id": page.cdp_session_id,
                    "process_id": page.process_id,
                    "active_port": page.active_port,
                    "page_id": page.page_id,
                    "load_state": page.load_state,
                    "network_request_count": _summary_count(page.network_summary, "request_count"),
                    "console_error_count": _summary_count(page.console_summary, "error_count"),
                    "claim_ceiling": CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                }
            )

    def _publish_page(self, event_type: str, page: RenderedWebPage) -> None:
        self._publish(
            event_type,
            "Web retrieval page result.",
            {
                "safe_url_display": safe_url_display(page.final_url or page.requested_url),
                "provider": page.provider,
                "status": page.status,
                "elapsed_ms": round(float(page.elapsed_ms or 0.0), 3),
                "text_chars": page.text_chars,
                "links": page.link_count,
                "fallback": False,
                "claim_ceiling": page.claim_ceiling or CLAIM_CEILING_RENDERED_PAGE_EVIDENCE,
                "limitations": list(page.limitations),
                "error_code": page.error_code,
                "error_message": _bounded_message(page.error_message),
                "extraction_confidence": page.confidence,
            },
            severity=EventSeverity.WARNING if page.status in {"failed", "timeout", "blocked", "provider_unavailable", "unsupported"} else EventSeverity.INFO,
            visibility=EventVisibilityScope.GHOST_HINT if page.status in {"failed", "timeout", "blocked", "provider_unavailable", "unsupported"} else EventVisibilityScope.DECK_CONTEXT,
        )

    def _publish_cdp_result(self, page: RenderedWebPage, cdp_attempt: dict[str, Any]) -> None:
        base_payload = {
            "safe_url_display": safe_url_display(page.final_url or page.requested_url),
            "provider": page.provider,
            "status": page.status,
            "cdp_session_id": page.cdp_session_id,
            "process_id": page.process_id,
            "active_port": page.active_port,
            "page_id": page.page_id,
            "load_state": page.load_state,
            "title_present": bool(page.title),
            "dom_text_chars": page.text_chars,
            "links_found": page.link_count,
            "html_excerpt_chars": page.html_chars,
            "network_request_count": _summary_count(page.network_summary, "request_count"),
            "console_error_count": _summary_count(page.console_summary, "error_count"),
            "elapsed_ms": round(float(page.elapsed_ms or 0.0), 3),
            "claim_ceiling": CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
            "limitations": list(page.limitations),
            "error_code": page.error_code,
            "error_message": _bounded_message(page.error_message),
        }
        if page.status == "blocked":
            self._publish_cdp_event(
                "web_retrieval.obscura_cdp_blocked",
                "Blocked by safety policy.",
                base_payload,
                severity=EventSeverity.WARNING,
                visibility=EventVisibilityScope.GHOST_HINT,
            )
            return
        if page.status in {"success", "partial"}:
            self._publish_cdp_event(
                "web_retrieval.obscura_cdp_started",
                "Obscura CDP session started.",
                {
                    "cdp_session_id": page.cdp_session_id,
                    "process_id": page.process_id,
                    "active_port": page.active_port,
                    "claim_ceiling": CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                },
            )
            self._publish_cdp_event(
                "web_retrieval.obscura_cdp_connected",
                "Obscura CDP session connected.",
                {
                    "cdp_session_id": page.cdp_session_id,
                    "active_port": page.active_port,
                    "claim_ceiling": CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                },
            )
            self._publish_cdp_event(
                "web_retrieval.obscura_cdp_navigation_completed",
                "CDP page navigation completed.",
                base_payload,
            )
            self._publish_cdp_event(
                "web_retrieval.obscura_cdp_extraction_completed",
                "Page inspected.",
                base_payload,
                visibility=EventVisibilityScope.DECK_CONTEXT,
            )
            self._publish_cdp_event(
                "web_retrieval.obscura_cdp_stopped",
                "Obscura CDP session stopped.",
                {
                    "cdp_session_id": page.cdp_session_id,
                    "active_port": page.active_port,
                    "claim_ceiling": CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE,
                },
            )
            return
        self._publish_cdp_event(
            "web_retrieval.obscura_cdp_failed",
            "CDP inspection failed.",
            base_payload,
            severity=EventSeverity.WARNING,
            visibility=EventVisibilityScope.GHOST_HINT,
        )

    def _publish_cdp_event(
        self,
        event_type: str,
        message: str,
        payload: dict[str, Any],
        *,
        severity: EventSeverity = EventSeverity.INFO,
        visibility: EventVisibilityScope = EventVisibilityScope.DECK_CONTEXT,
    ) -> None:
        if not bool(getattr(self.config.obscura.cdp, "debug_events_enabled", True)):
            return
        self._publish(event_type, message, payload, severity=severity, visibility=visibility)

    def _cdp_attempt(self, provider: Any, page: RenderedWebPage) -> dict[str, Any]:
        attempt = getattr(provider, "last_attempt", None)
        if attempt is not None and hasattr(attempt, "to_dict"):
            payload = attempt.to_dict()
        else:
            payload = {}
        payload.setdefault("cdp_session_id", page.cdp_session_id)
        payload.setdefault("session_id", payload.get("cdp_session_id") or page.cdp_session_id)
        payload.setdefault("process_id", page.process_id)
        payload.setdefault("active_port", page.active_port)
        payload.setdefault("page_id", page.page_id)
        payload.setdefault("requested_url", page.requested_url)
        payload.setdefault("final_url", page.final_url)
        payload.setdefault("title", page.title)
        payload.setdefault("load_state", page.load_state)
        payload.setdefault("dom_text_chars", page.text_chars)
        payload.setdefault("links_found", page.link_count)
        payload.setdefault("html_excerpt_chars", page.html_chars)
        payload.setdefault("network_request_count", _summary_count(page.network_summary, "request_count"))
        payload.setdefault("console_error_count", _summary_count(page.console_summary, "error_count"))
        payload.setdefault("provider_attempt_status", page.status)
        payload.setdefault("claim_ceiling", CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE)
        return payload

    def _publish(
        self,
        event_type: str,
        message: str,
        payload: dict[str, Any],
        *,
        severity: EventSeverity = EventSeverity.INFO,
        visibility: EventVisibilityScope = EventVisibilityScope.DECK_CONTEXT,
    ) -> None:
        if self.events is None or not self.config.debug_events_enabled:
            return
        self.events.publish(
            event_family=EventFamily.WEB_RETRIEVAL,
            event_type=event_type,
            severity=severity,
            subsystem="web_retrieval",
            visibility_scope=visibility,
            retention_class=EventRetentionClass.BOUNDED_RECENT,
            provenance={"channel": "web_retrieval", "kind": "subsystem_interpretation"},
            message=message,
            payload=dict(payload),
        )


def _bundle_state(pages: list[RenderedWebPage]) -> str:
    if not pages:
        return "failed"
    statuses = {page.status for page in pages}
    if statuses <= {"blocked"}:
        return "blocked"
    if statuses <= {"provider_unavailable"}:
        return "provider_unavailable"
    if statuses <= {"unsupported"}:
        return "unsupported"
    if statuses <= {"timeout"}:
        return "timeout"
    if any(status == "success" for status in statuses):
        return "partial" if any(status in {"failed", "timeout", "blocked", "partial"} for status in statuses) else "extracted"
    if any(status == "partial" for status in statuses):
        return "partial"
    if any(status == "timeout" for status in statuses):
        return "failed"
    return "failed"


def _error_payload(page: RenderedWebPage) -> dict[str, str]:
    return {
        "provider": page.provider,
        "status": page.status,
        "code": page.error_code or page.status,
        "message": _bounded_message(page.error_message or page.status),
    }


def _bounded_message(message: str) -> str:
    bounded, _ = bounded_text(str(message or ""), 500)
    return bounded


def _selected_provider(pages: list[RenderedWebPage]) -> str:
    for page in pages:
        if page.status in {"success", "partial"} and page.provider not in {"safety", "none"}:
            return page.provider
    return ""


def _summary_count(summary: dict[str, Any], key: str) -> int:
    if not isinstance(summary, dict):
        return 0
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0
