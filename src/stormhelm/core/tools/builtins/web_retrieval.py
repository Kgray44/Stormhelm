from __future__ import annotations

from typing import Any

from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import build_execution_report
from stormhelm.core.web_retrieval.models import CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.core.web_retrieval.models import CLAIM_CEILING_RENDERED_PAGE_EVIDENCE
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.service import WebRetrievalService
from stormhelm.shared.result import SafetyClassification, ToolResult


class WebRetrievalFetchTool(BaseTool):
    name = "web_retrieval_fetch"
    display_name = "Web Retrieval Fetch"
    description = "Extract public webpage text, links, and optional rendered evidence through Stormhelm's web retrieval providers."
    category = "web_retrieval"
    classification = SafetyClassification.READ_ONLY

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}},
                "intent": {"type": "string"},
                "preferred_provider": {"type": "string"},
                "require_rendering": {"type": "boolean"},
                "include_html": {"type": "boolean"},
                "include_links": {"type": "boolean"},
                "provider": {"type": "string"},
            },
            "required": ["urls"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_urls = arguments.get("urls")
        if isinstance(raw_urls, str):
            urls = [raw_urls]
        elif isinstance(raw_urls, list):
            urls = [str(url).strip() for url in raw_urls if str(url).strip()]
        else:
            urls = []
        if not urls:
            raise ValueError("At least one public URL is required.")
        return {
            "urls": urls,
            "intent": str(arguments.get("intent") or "read_page").strip() or "read_page",
            "preferred_provider": str(arguments.get("preferred_provider") or "auto").strip().lower() or "auto",
            "provider": str(arguments.get("provider") or arguments.get("preferred_provider") or "auto").strip().lower() or "auto",
            "require_rendering": bool(arguments.get("require_rendering", False)),
            "include_html": bool(arguments.get("include_html", False)),
            "include_links": bool(arguments.get("include_links", True)),
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        request = WebRetrievalRequest(
            urls=list(arguments["urls"]),
            intent=str(arguments.get("intent") or "read_page"),
            preferred_provider=str(arguments.get("preferred_provider") or "auto"),
            require_rendering=bool(arguments.get("require_rendering", False)),
            include_html=bool(arguments.get("include_html", False)),
            include_links=bool(arguments.get("include_links", True)),
            max_text_chars=context.config.web_retrieval.max_text_chars,
            max_html_chars=context.config.web_retrieval.max_html_chars,
        )
        bundle = WebRetrievalService(context.config.web_retrieval, events=context.events).retrieve(request)
        contract = self.resolve_adapter_contract(arguments)
        success = bundle.result_state in {"extracted", "partial"}
        execution = (
            build_execution_report(
                contract,
                success=success,
                observed_outcome=ClaimOutcome.OBSERVED if success else ClaimOutcome.NONE,
                evidence=["Public webpage evidence extraction result."],
                failure_kind=None if success else bundle.result_state,
            )
            if contract is not None
            else None
        )
        page = bundle.pages[0] if bundle.pages else None
        title = page.title if page and page.title else "Page"
        trace = bundle.trace.to_dict() if bundle.trace is not None else {}
        action_result_state = "fallback_used" if success and bundle.fallback_used else bundle.result_state
        claim_ceiling = bundle.claim_ceiling or CLAIM_CEILING_RENDERED_PAGE_EVIDENCE
        summary = _summary(
            action_result_state,
            title=title,
            page_count=bundle.page_count,
            link_count=bundle.link_count,
            trace=trace,
        )
        payload = bundle.to_dict(include_raw_html=bool(arguments.get("include_html")), include_text=True)
        bearing = "Page Inspected" if trace.get("selected_provider") == "obscura_cdp" and success else _bearing(action_result_state)
        return ToolResult(
            success=success,
            summary=summary,
            data={
                "action": {
                    "type": "web_retrieval_evidence",
                    "target": "deck",
                    "module": "browser",
                    "section": "web-evidence",
                    "bearing_title": bearing,
                    "micro_response": summary,
                    "full_response": (
                        f"{summary} Claim ceiling: {claim_ceiling}; "
                        "this is extracted public page evidence. I did not verify the source's claims independently, "
                        "and this is not the user's visible screen."
                    ),
                    "result_state": action_result_state,
                    "evidence_bundle": payload,
                    "trace": payload.get("trace", {}),
                    "claim_ceiling": claim_ceiling,
                },
                "evidence_bundle": payload,
            },
            error=None if success else bundle.result_state,
            adapter_contract=contract.to_dict() if contract is not None else {},
            adapter_execution=execution.to_dict() if execution is not None else {},
        )


def _bearing(result_state: str) -> str:
    return {
        "extracted": "Page Extracted",
        "partial": "Page Partially Extracted",
        "blocked": "Page Retrieval Blocked",
        "fallback_used": "HTTP Fallback Used",
        "provider_unavailable": "Provider Unavailable",
        "timeout": "Page Retrieval Timed Out",
        "unsupported": "Page Retrieval Unsupported",
        "failed": "Page Retrieval Failed",
    }.get(result_state, "Web Evidence")


def _summary(result_state: str, *, title: str, page_count: int, link_count: int, trace: dict[str, Any] | None = None) -> str:
    trace = trace or {}
    if result_state == "blocked":
        return "The URL was blocked by safety policy."
    if result_state == "provider_unavailable":
        return "The configured web retrieval provider was unavailable."
    if result_state == "timeout":
        return "The page extraction timed out."
    if result_state == "unsupported":
        return "The page could not be extracted by the configured providers for that content type."
    if result_state == "failed":
        return "The page could not be extracted by the configured providers."
    if result_state == "fallback_used":
        reason = str(trace.get("fallback_reason") or "").strip()
        if reason.startswith("obscura:"):
            return "Obscura was unavailable, so I used the HTTP fallback."
        return "I used the HTTP fallback for the public page extraction."
    link_phrase = f" and {link_count} links" if link_count else ""
    if trace.get("selected_provider") == "obscura_cdp" or trace.get("claim_ceiling") == CLAIM_CEILING_HEADLESS_CDP_PAGE_EVIDENCE:
        if result_state == "partial":
            return f"Headless page partially inspected for {title}{link_phrase}."
        return f"Headless page inspected for {title}{link_phrase}."
    if result_state == "partial":
        return f"Partial extraction for {title}{link_phrase}."
    return f"Page extracted for {title}{link_phrase}."
