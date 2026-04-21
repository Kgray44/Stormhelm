from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from stormhelm.config.models import AppConfig
from stormhelm.core.environment.models import (
    ActivitySummary,
    AttentionPriority,
    BrowserContextItem,
    BrowserReferenceCandidate,
    BrowserReuseDecision,
    EnvironmentContinuitySnapshot,
    MissedActivityWindow,
    NotificationPolicy,
    SurfaceLinkReason,
)
from stormhelm.core.events import EventBuffer
from stormhelm.core.intelligence.language import fuzzy_ratio, normalize_lookup_phrase, normalize_phrase, token_overlap
from stormhelm.core.operations.service import OperationalAwarenessService
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.workspace.models import WorkspaceInclusionReason
from stormhelm.core.workspace.service import WorkspaceService


_BROWSER_PROCESSES = {"brave", "chrome", "firefox", "iexplore", "msedge", "opera", "vivaldi"}
_BROWSER_SUFFIXES = (
    " - Google Chrome",
    " - Microsoft Edge",
    " - Mozilla Firefox",
    " - Brave",
    " - Opera",
    " - Vivaldi",
)
_CURRENT_BROWSER_HINTS = {
    "current article",
    "current page",
    "just reading",
    "recent page",
    "source i was just reading",
    "that page",
    "this article",
    "this page",
}
_BROWSER_STOP_TOKENS = {
    "a",
    "about",
    "article",
    "bring",
    "browser",
    "find",
    "forward",
    "page",
    "show",
    "source",
    "tab",
    "that",
    "the",
    "this",
    "up",
    "with",
}


class EnvironmentIntelligenceService:
    def __init__(
        self,
        *,
        config: AppConfig,
        session_state: ConversationStateStore,
        workspace_service: WorkspaceService | None,
        system_probe: Any,
        events: EventBuffer,
    ) -> None:
        self.config = config
        self.session_state = session_state
        self.workspace_service = workspace_service
        self.system_probe = system_probe
        self.events = events
        self.persona = PersonaContract(config)
        self.operational_awareness = OperationalAwarenessService()

    def handle_browser_request(
        self,
        *,
        operation: str,
        query: str,
        session_id: str,
    ) -> dict[str, Any]:
        normalized_operation = str(operation or "find").strip().lower() or "find"
        capabilities = self._browser_capabilities()
        context_items = self._browser_context_items(session_id=session_id)
        continuity = self._environment_continuity(session_id=session_id, context_items=context_items, capabilities=capabilities)

        if normalized_operation in {"find", "recent_page"}:
            return self._find_browser_item(
                session_id=session_id,
                query=query,
                items=context_items,
                capabilities=capabilities,
                continuity=continuity,
            )
        if normalized_operation == "summarize":
            return self._summarize_browser_item(
                query=query,
                items=context_items,
                capabilities=capabilities,
                continuity=continuity,
                session_id=session_id,
            )
        if normalized_operation == "add_to_workspace":
            return self._add_browser_item_to_workspace(
                session_id=session_id,
                query=query,
                items=context_items,
                capabilities=capabilities,
                continuity=continuity,
            )
        if normalized_operation == "collect_references":
            return self._collect_browser_references(
                session_id=session_id,
                query=query,
                items=context_items,
                capabilities=capabilities,
                continuity=continuity,
            )

        summary = self.persona.error("browser context action is not supported")
        return {
            "summary": summary,
            "action": {
                "type": "browser_context",
                "bearing_title": "Browser action unavailable",
                "micro_response": "That browser action is not available.",
                "full_response": summary,
            },
            "browserContext": {
                "capabilities": capabilities,
                "items": [item.to_dict() for item in context_items],
                "continuity": continuity.to_dict(),
            },
            "error": "unsupported_operation",
        }

    def summarize_recent_activity(
        self,
        *,
        session_id: str,
        query: str,
        lookback_minutes: int = 15,
    ) -> dict[str, Any]:
        del query, session_id
        window = self._missed_activity_window(lookback_minutes)
        recent_events = self._recent_events(window)
        system_state = self._system_state_snapshot()
        signals = [
            signal.to_dict()
            for signal in self.operational_awareness.build_signals(
                events=recent_events,
                jobs=[],
                system_state=system_state,
            )
        ]
        policy = self._notification_policy()
        high_priority: list[dict[str, Any]] = []
        summary_worthy: list[dict[str, Any]] = []
        suppressed_count = 0

        for event in recent_events:
            classified = self._classify_event_attention(event, system_state=system_state)
            if classified["priority"] == AttentionPriority.INTERRUPT.value:
                high_priority.append(classified)
            elif classified["priority"] == AttentionPriority.SUMMARY.value:
                summary_worthy.append(classified)
            else:
                suppressed_count += 1

        for signal in signals:
            classified = self._classify_signal_attention(signal, system_state=system_state)
            if classified["priority"] == AttentionPriority.INTERRUPT.value:
                if classified not in high_priority:
                    high_priority.append(classified)
            elif classified["priority"] == AttentionPriority.SUMMARY.value:
                if classified not in summary_worthy:
                    summary_worthy.append(classified)

        summary_text = self._activity_summary_text(
            high_priority=high_priority,
            summary_worthy=summary_worthy,
            suppressed_count=suppressed_count,
        )
        activity_summary = ActivitySummary(
            headline="Recent activity summarized",
            summary=summary_text,
            window=window,
            high_priority=high_priority[:6],
            summary_worthy=summary_worthy[:6],
            suppressed_count=suppressed_count,
            policy=policy,
            limitations=["Full browser-history and external app-notification ingestion are not available in this build."],
        )
        summary = self.persona.report(summary_text)
        return {
            "summary": summary,
            "activitySummary": activity_summary.to_dict(),
            "action": {
                "type": "activity_summary",
                "bearing_title": "Recent activity summarized",
                "micro_response": "Summarized the recent important changes.",
                "full_response": summary,
            },
        }

    def _find_browser_item(
        self,
        *,
        session_id: str,
        query: str,
        items: list[BrowserContextItem],
        capabilities: dict[str, Any],
        continuity: EnvironmentContinuitySnapshot,
    ) -> dict[str, Any]:
        candidate = self._resolve_browser_candidate(items=items, query=query, session_id=session_id)
        if candidate is None:
            summary = self.persona.report(
                "I could not match that against the visible browser pages here. Full browser-history search is not available in this build."
            )
            reuse = BrowserReuseDecision(
                reused_existing=False,
                reasons=["No visible browser page matched the request."],
                capability_limits=["Only visible browser windows and retained workspace page context are searchable here."],
            )
            return {
                "summary": summary,
                "match": {},
                "browserContext": {
                    "capabilities": capabilities,
                    "items": [item.to_dict() for item in items],
                    "reuseDecision": reuse.to_dict(),
                    "continuity": continuity.to_dict(),
                },
                "action": {
                    "type": "browser_context",
                    "bearing_title": "Browser page not found",
                    "micro_response": "Couldn't find a matching browser page.",
                    "full_response": summary,
                },
                "error": "browser_page_not_found",
            }

        focus_result = self._focus_browser_candidate(candidate, capabilities=capabilities)
        limits = []
        if not capabilities.get("inspect_open_browser_tabs", False):
            limits.append("Searching full browser tabs is not available; Stormhelm matched the visible browser context instead.")
        reuse = BrowserReuseDecision(
            reused_existing=True,
            chosen=candidate.item.to_dict(),
            reasons=[
                "Matched the strongest open browser context for the request.",
                "Reused the existing browser page instead of opening a duplicate.",
            ],
            duplicate_candidates=self._duplicate_browser_candidates(candidate.item, items),
            capability_limits=limits,
        )
        summary = self.persona.report(
            "Found the matching open browser page and brought it forward."
            if focus_result.get("success")
            else "Found the matching browser page in the current environment."
        )
        return {
            "summary": summary,
            "match": candidate.item.to_dict(),
            "browserContext": {
                "capabilities": capabilities,
                "items": [item.to_dict() for item in items],
                "reuseDecision": reuse.to_dict(),
                "continuity": continuity.to_dict(),
            },
            "action": {
                "type": "browser_context",
                "bearing_title": f"{candidate.item.title or 'Browser page'} found",
                "micro_response": "Found the matching browser page.",
                "full_response": summary,
            },
        }

    def _summarize_browser_item(
        self,
        *,
        query: str,
        items: list[BrowserContextItem],
        capabilities: dict[str, Any],
        continuity: EnvironmentContinuitySnapshot,
        session_id: str,
    ) -> dict[str, Any]:
        candidate = self._resolve_browser_candidate(items=items, query=query, session_id=session_id)
        if candidate is None:
            summary = self.persona.report("There is no strong current browser page context to summarize here.")
            return {
                "summary": summary,
                "action": {
                    "type": "browser_context",
                    "bearing_title": "Browser summary unavailable",
                    "micro_response": "Couldn't summarize a current browser page.",
                    "full_response": summary,
                },
                "browserContext": {
                    "capabilities": capabilities,
                    "items": [item.to_dict() for item in items],
                    "continuity": continuity.to_dict(),
                },
                "error": "browser_page_not_found",
            }

        detail = candidate.item.summary or f"{candidate.item.title} is part of the current browser context."
        if not capabilities.get("extract_page_content", False):
            detail = f"{detail.rstrip('.')} Full article extraction is not available in this build."
        summary = self.persona.report(detail)
        return {
            "summary": summary,
            "match": candidate.item.to_dict(),
            "browserContext": {
                "capabilities": capabilities,
                "items": [item.to_dict() for item in items],
                "continuity": continuity.to_dict(),
            },
            "action": {
                "type": "browser_context",
                "bearing_title": "Browser page summarized",
                "micro_response": "Summarized the current browser page context.",
                "full_response": summary,
            },
        }

    def _add_browser_item_to_workspace(
        self,
        *,
        session_id: str,
        query: str,
        items: list[BrowserContextItem],
        capabilities: dict[str, Any],
        continuity: EnvironmentContinuitySnapshot,
    ) -> dict[str, Any]:
        candidate = self._resolve_browser_candidate(items=items, query=query, session_id=session_id)
        if candidate is None:
            summary = self.persona.report("I could not identify a current browser page to add into the workspace.")
            return {
                "summary": summary,
                "action": {
                    "type": "browser_context",
                    "bearing_title": "Page not added to workspace",
                    "micro_response": "Couldn't add a browser page to the workspace.",
                    "full_response": summary,
                },
                "browserContext": {
                    "capabilities": capabilities,
                    "items": [item.to_dict() for item in items],
                    "continuity": continuity.to_dict(),
                },
                "error": "browser_page_not_found",
            }
        if self.workspace_service is None:
            summary = self.persona.report("Workspace linking is not available in this build.")
            return {
                "summary": summary,
                "action": {
                    "type": "browser_context",
                    "bearing_title": "Workspace linking unavailable",
                    "micro_response": "Workspace linking isn't available.",
                    "full_response": summary,
                },
                "error": "workspace_linking_unavailable",
            }

        active_workspace = self.workspace_service.active_workspace_summary(session_id)
        workspace_name = str(((active_workspace.get("workspace") or {}).get("name") if isinstance(active_workspace, dict) else "") or "").strip()
        if not workspace_name:
            summary = self.persona.report("No workspace is active right now, so there is nowhere to attach the browser page.")
            return {
                "summary": summary,
                "action": {
                    "type": "browser_context",
                    "bearing_title": "No active workspace",
                    "micro_response": "No workspace is active.",
                    "full_response": summary,
                },
                "error": "workspace_unavailable",
            }

        reasons = self._browser_workspace_reasons(candidate, session_id=session_id)
        link = self.workspace_service.link_material_into_active_workspace(
            session_id=session_id,
            item=candidate.item.to_workspace_item(),
            target_surface="references",
            reasons=[WorkspaceInclusionReason(code=reason.code, label=reason.label, detail=reason.detail, score=reason.score) for reason in reasons],
            source_surface="browser",
            activity_description=f"Linked browser context '{candidate.item.title}' into workspace references.",
        )
        summary = self.persona.report(
            "Added the current page to workspace References because it supports the active topic."
            if not link.get("already_linked")
            else "That browser page is already held in workspace References."
        )
        action = dict(link.get("action") or {})
        action.update(
            {
                "bearing_title": "Page added to workspace" if not link.get("already_linked") else "Page already in workspace",
                "micro_response": "Added the page to References." if not link.get("already_linked") else "The page is already in References.",
                "full_response": summary,
            }
        )
        return {
            "summary": summary,
            "match": candidate.item.to_dict(),
            "workspace": link.get("workspace", {}),
            "browserContext": {
                "capabilities": capabilities,
                "items": [item.to_dict() for item in items],
                "continuity": continuity.to_dict(),
                "referenceCandidate": BrowserReferenceCandidate(item=candidate.item, score=candidate.score, reasons=reasons).to_dict(),
            },
            "action": action,
        }

    def _collect_browser_references(
        self,
        *,
        session_id: str,
        query: str,
        items: list[BrowserContextItem],
        capabilities: dict[str, Any],
        continuity: EnvironmentContinuitySnapshot,
    ) -> dict[str, Any]:
        if self.workspace_service is None:
            summary = self.persona.report("Workspace linking is not available in this build.")
            return {
                "summary": summary,
                "action": {
                    "type": "browser_context",
                    "bearing_title": "Workspace linking unavailable",
                    "micro_response": "Workspace linking isn't available.",
                    "full_response": summary,
                },
                "error": "workspace_linking_unavailable",
            }

        ranked = self._rank_browser_candidates(items=items, query=query, session_id=session_id)
        linked_count = 0
        latest_link: dict[str, Any] = {}
        for candidate in ranked[:3]:
            latest_link = self.workspace_service.link_material_into_active_workspace(
                session_id=session_id,
                item=candidate.item.to_workspace_item(),
                target_surface="references",
                reasons=[WorkspaceInclusionReason(code=reason.code, label=reason.label, detail=reason.detail, score=reason.score) for reason in candidate.reasons],
                source_surface="browser",
                activity_description=f"Collected browser context '{candidate.item.title}' into workspace references.",
            )
            if not latest_link.get("already_linked"):
                linked_count += 1
        summary = self.persona.report(
            f"Collected {linked_count} relevant browser reference{'s' if linked_count != 1 else ''} into the workspace."
            if linked_count
            else "The strongest browser references were already present in the workspace."
        )
        action = dict(latest_link.get("action") or {})
        action.update(
            {
                "bearing_title": "Browser references collected",
                "micro_response": "Collected browser references for the workspace.",
                "full_response": summary,
            }
        )
        return {
            "summary": summary,
            "browserContext": {
                "capabilities": capabilities,
                "items": [item.to_dict() for item in items],
                "continuity": continuity.to_dict(),
                "references": [candidate.to_dict() for candidate in ranked[:3]],
            },
            "action": action,
        }

    def _browser_capabilities(self) -> dict[str, Any]:
        raw = self._control_capabilities()
        search_caps = raw.get("search", {}) if isinstance(raw.get("search"), dict) else {}
        window_caps = raw.get("window", {}) if isinstance(raw.get("window"), dict) else {}
        can_inspect_windows = bool(search_caps.get("windows", False) and hasattr(self.system_probe, "window_status"))
        return {
            "inspect_open_browser_tabs": bool(search_caps.get("browser_tabs", False)),
            "inspect_open_browser_windows": can_inspect_windows,
            "search_open_browser_context": bool(can_inspect_windows),
            "reuse_existing_tabs": bool(can_inspect_windows),
            "focus_browser_window": bool(window_caps.get("focus", False) and hasattr(self.system_probe, "window_control")),
            "browser_history_search": False,
            "summarize_page_context": True,
            "extract_page_content": False,
            "add_page_to_workspace": self.workspace_service is not None,
            "collect_references": self.workspace_service is not None,
        }

    def _control_capabilities(self) -> dict[str, Any]:
        if self.system_probe is None or not hasattr(self.system_probe, "control_capabilities"):
            return {}
        capabilities = self.system_probe.control_capabilities()
        return capabilities if isinstance(capabilities, dict) else {}

    def _browser_context_items(self, *, session_id: str) -> list[BrowserContextItem]:
        items: list[BrowserContextItem] = []
        seen: set[str] = set()

        for item in self._browser_window_items():
            if item.context_id not in seen:
                seen.add(item.context_id)
                items.append(item)

        workspace_summary = self.workspace_service.active_workspace_summary(session_id) if self.workspace_service is not None else {}
        active_item = workspace_summary.get("active_item") if isinstance(workspace_summary.get("active_item"), dict) else {}
        opened_items = workspace_summary.get("opened_items") if isinstance(workspace_summary.get("opened_items"), list) else []
        references = workspace_summary.get("references") if isinstance(workspace_summary.get("references"), list) else []
        for source_name, bucket, role in [
            ("workspace_active_item", [active_item] if active_item else [], "opened_item"),
            ("workspace_opened_item", opened_items, "opened_item"),
            ("workspace_reference", references, "reference"),
        ]:
            for raw_item in bucket:
                browser_item = self._browser_item_from_workspace_item(raw_item, source=source_name, role=role)
                if browser_item is not None and browser_item.context_id not in seen:
                    seen.add(browser_item.context_id)
                    items.append(browser_item)

        active_context = self.session_state.get_active_context(session_id)
        for source_name in ("selection", "clipboard"):
            descriptor = active_context.get(source_name) if isinstance(active_context.get(source_name), dict) else {}
            browser_item = self._browser_item_from_context_descriptor(descriptor, source=source_name)
            if browser_item is not None and browser_item.context_id not in seen:
                seen.add(browser_item.context_id)
                items.append(browser_item)

        recent_entities = active_context.get("recent_entities") if isinstance(active_context.get("recent_entities"), list) else []
        for entity in recent_entities:
            browser_item = self._browser_item_from_recent_entity(entity)
            if browser_item is not None and browser_item.context_id not in seen:
                seen.add(browser_item.context_id)
                items.append(browser_item)

        workspace_topic = str(((workspace_summary.get("workspace") or {}).get("topic") if isinstance(workspace_summary, dict) else "") or "").strip()
        active_goal = str(workspace_summary.get("active_goal") or "").strip()
        return self._rank_context_items(items=items, workspace_topic=workspace_topic, active_goal=active_goal)[:8]

    def _browser_window_items(self) -> list[BrowserContextItem]:
        if self.system_probe is None or not hasattr(self.system_probe, "window_status"):
            return []
        status = self.system_probe.window_status()
        windows = status.get("windows") if isinstance(status.get("windows"), list) else []
        results: list[BrowserContextItem] = []
        for window in windows:
            if not isinstance(window, dict):
                continue
            process_name = str(window.get("process_name") or "").strip().lower()
            path = str(window.get("path") or "").strip().lower()
            if process_name not in _BROWSER_PROCESSES and not any(name in path for name in _BROWSER_PROCESSES):
                continue
            raw_title = str(window.get("window_title") or "").strip()
            title = self._clean_browser_title(raw_title)
            results.append(
                BrowserContextItem(
                    context_id=f"window:{int(window.get('window_handle') or 0)}:{title.lower()}",
                    title=title or raw_title,
                    process_name=process_name,
                    window_handle=int(window.get("window_handle") or 0),
                    pid=int(window.get("pid") or 0),
                    source="open_browser_window",
                    role="active" if bool(window.get("is_focused", False)) else "supporting",
                    summary="Visible browser page.",
                    active=bool(window.get("is_focused", False)),
                    metadata={
                        "windowTitle": raw_title,
                        "monitorIndex": int(window.get("monitor_index") or 0),
                    },
                )
            )
        return results

    def _browser_item_from_workspace_item(self, item: object, *, source: str, role: str) -> BrowserContextItem | None:
        if not isinstance(item, dict):
            return None
        url = str(item.get("url") or "").strip()
        viewer = str(item.get("viewer") or item.get("kind") or "").strip().lower()
        if viewer != "browser" and not url:
            return None
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title and not url:
            return None
        parsed = urlparse(url) if url else None
        return BrowserContextItem(
            context_id=str(item.get("itemId") or url or title).strip(),
            title=title or (parsed.netloc if parsed is not None else "Browser page"),
            url=url,
            domain=(parsed.netloc if parsed is not None else ""),
            source=source,
            role=role,
            summary=str(item.get("summary") or item.get("subtitle") or "").strip(),
            active=source == "workspace_active_item",
            metadata={"workspaceItem": True},
        )

    def _browser_item_from_context_descriptor(self, descriptor: object, *, source: str) -> BrowserContextItem | None:
        if not isinstance(descriptor, dict):
            return None
        kind = str(descriptor.get("kind") or "").strip().lower()
        value = descriptor.get("value")
        if kind != "url" or not isinstance(value, str):
            return None
        url = value.strip()
        if not url:
            return None
        parsed = urlparse(url)
        title = str(descriptor.get("preview") or parsed.netloc or url).strip()
        return BrowserContextItem(
            context_id=f"{source}:{url}",
            title=title,
            url=url,
            domain=parsed.netloc,
            source=source,
            role="context",
            summary=f"Captured from {source}.",
            metadata={"descriptorKind": kind},
        )

    def _browser_item_from_recent_entity(self, entity: object) -> BrowserContextItem | None:
        if not isinstance(entity, dict):
            return None
        url = str(entity.get("url") or "").strip()
        if not url:
            return None
        parsed = urlparse(url)
        title = str(entity.get("title") or parsed.netloc or url).strip()
        return BrowserContextItem(
            context_id=str(entity.get("item_id") or url),
            title=title,
            url=url,
            domain=parsed.netloc,
            source="recent_entity",
            role="recent",
            summary="Recent browser context.",
        )

    def _resolve_browser_candidate(
        self,
        *,
        items: list[BrowserContextItem],
        query: str,
        session_id: str,
    ) -> BrowserReferenceCandidate | None:
        ranked = self._rank_browser_candidates(items=items, query=query, session_id=session_id)
        return ranked[0] if ranked else None

    def _rank_browser_candidates(
        self,
        *,
        items: list[BrowserContextItem],
        query: str,
        session_id: str,
    ) -> list[BrowserReferenceCandidate]:
        workspace_summary = self.workspace_service.active_workspace_summary(session_id) if self.workspace_service is not None else {}
        workspace_topic = str(((workspace_summary.get("workspace") or {}).get("topic") if isinstance(workspace_summary, dict) else "") or "").strip()
        active_goal = str(workspace_summary.get("active_goal") or "").strip()
        normalized_query = normalize_phrase(query)
        prefer_current = any(phrase in normalized_query for phrase in _CURRENT_BROWSER_HINTS)
        results: list[BrowserReferenceCandidate] = []
        for item in items:
            reasons: list[SurfaceLinkReason] = []
            score = 0.0
            if prefer_current and item.active:
                score += 4.5
                reasons.append(SurfaceLinkReason(code="current_browser_page", label="Current browser page", detail="This is the active browser context.", score=4.5))
            title_match = token_overlap(self._meaningful_browser_query(query), normalize_phrase(item.title))
            if title_match > 0:
                match_score = round(title_match * 4.0, 3)
                score += match_score
                reasons.append(SurfaceLinkReason(code="title_match", label="Title match", detail="Title strongly matches the requested browser topic.", score=match_score))
            fuzzy = fuzzy_ratio(normalized_query, normalize_phrase(item.title)) / 100.0 if normalized_query else 0.0
            if fuzzy >= 0.55:
                fuzzy_score = round(fuzzy * 2.0, 3)
                score += fuzzy_score
                reasons.append(SurfaceLinkReason(code="fuzzy_match", label="Meaning match", detail="Browser title is a close match for the request.", score=fuzzy_score))
            if workspace_topic and token_overlap(normalize_phrase(workspace_topic), normalize_phrase(item.title)) > 0:
                score += 1.1
                reasons.append(SurfaceLinkReason(code="active_workspace_match", label="Workspace topic match", detail="The browser page overlaps the active workspace topic.", score=1.1))
            if active_goal and token_overlap(normalize_phrase(active_goal), normalize_phrase(item.title)) > 0:
                score += 0.9
                reasons.append(SurfaceLinkReason(code="active_goal_match", label="Active goal match", detail="The page supports the current active goal.", score=0.9))
            if item.active:
                score += 0.6
            if item.source in {"workspace_active_item", "workspace_reference", "selection", "clipboard"}:
                score += 0.45
            if score <= 0 and prefer_current and item.active:
                score = 1.5
            if score > 0:
                results.append(BrowserReferenceCandidate(item=item, score=score, reasons=reasons))
        return sorted(results, key=lambda candidate: candidate.score, reverse=True)

    def _rank_context_items(
        self,
        *,
        items: list[BrowserContextItem],
        workspace_topic: str,
        active_goal: str,
    ) -> list[BrowserContextItem]:
        if not items:
            return []

        def sort_key(item: BrowserContextItem) -> tuple[float, str]:
            total = 0.0
            if item.active:
                total += 1.5
            if item.source in {"workspace_active_item", "workspace_reference"}:
                total += 1.2
            if workspace_topic and token_overlap(normalize_phrase(workspace_topic), normalize_phrase(item.title)) > 0:
                total += 0.8
            if active_goal and token_overlap(normalize_phrase(active_goal), normalize_phrase(item.title)) > 0:
                total += 0.6
            return total, item.title.lower()

        return sorted(items, key=sort_key, reverse=True)

    def _focus_browser_candidate(self, candidate: BrowserReferenceCandidate, *, capabilities: dict[str, Any]) -> dict[str, Any]:
        if not capabilities.get("focus_browser_window", False):
            return {"success": False, "reason": "focus_unavailable"}
        if self.system_probe is None or not hasattr(self.system_probe, "window_control"):
            return {"success": False, "reason": "probe_unavailable"}
        window_title = str(candidate.item.metadata.get("windowTitle") or candidate.item.title).strip()
        return self.system_probe.window_control(action="focus", app_name=window_title, target_mode="app")

    def _duplicate_browser_candidates(self, chosen: BrowserContextItem, items: list[BrowserContextItem]) -> list[dict[str, Any]]:
        normalized = normalize_lookup_phrase(chosen.title)
        duplicates: list[dict[str, Any]] = []
        for item in items:
            if item.context_id == chosen.context_id:
                continue
            if normalize_lookup_phrase(item.title) == normalized:
                duplicates.append(item.to_dict())
        return duplicates[:3]

    def _browser_workspace_reasons(self, candidate: BrowserReferenceCandidate, *, session_id: str) -> list[SurfaceLinkReason]:
        workspace_summary = self.workspace_service.active_workspace_summary(session_id) if self.workspace_service is not None else {}
        workspace_topic = str(((workspace_summary.get("workspace") or {}).get("topic") if isinstance(workspace_summary, dict) else "") or "").strip()
        reasons = [SurfaceLinkReason(code="active_browser_context", label="Current browser context", detail="Added from the active browser context.", score=1.0)]
        if workspace_topic:
            reasons.append(
                SurfaceLinkReason(
                    code="active_workspace_match",
                    label="Workspace topic match",
                    detail="The page supports the active workspace topic.",
                    score=0.9,
                )
            )
        reasons.extend(candidate.reasons[:2])
        return reasons

    def _notification_policy(self) -> NotificationPolicy:
        return NotificationPolicy(
            high_priority_rules=[
                "Failed workflows or repairs are interrupt-worthy.",
                "Critical battery, disk, or severe active network issues are interrupt-worthy.",
            ],
            summary_rules=[
                "Completed high-value workflows and warning-level signals belong in summaries.",
                "Recoveries and diagnostics completions are summary-worthy instead of interrupting live work.",
            ],
            background_rules=[
                "Queued jobs, repeated low-value status changes, and trivial opens stay in the background log.",
            ],
            capabilities={
                "external_app_notifications": False,
                "watch_signal_summary": True,
                "job_event_summary": True,
            },
        )

    def _classify_event_attention(self, event: dict[str, Any], *, system_state: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        source = str(event.get("source") or "").strip().lower()
        message = str(event.get("message") or "").strip()
        level = str(event.get("level") or "").strip().lower()
        tool_name = str(payload.get("tool_name") or "").strip().lower()
        status = str(payload.get("status") or "").strip().lower()
        title = message or source.title()
        detail = message
        priority = AttentionPriority.BACKGROUND

        if source == "job_manager" and status in {"failed", "timed_out"}:
            priority = AttentionPriority.INTERRUPT
            title = f"{self._tool_label(tool_name)} failed"
            detail = str(payload.get("error") or message or "The task failed.").replace("_", " ")
        elif source == "job_manager" and status == "completed":
            if tool_name in {"workflow_execute", "repair_action", "maintenance_action", "file_operation", "workspace_restore", "workspace_assemble"}:
                priority = AttentionPriority.SUMMARY
                title = f"{self._tool_label(tool_name)} completed"
                detail = str(payload.get("result_summary") or "Completed successfully.").strip()
            else:
                priority = AttentionPriority.BACKGROUND
        elif source == "network":
            priority = AttentionPriority.SUMMARY if level in {"warning", "info"} else AttentionPriority.BACKGROUND
            detail = str(payload.get("detail") or message).strip()
        elif source in {"assistant", "core"} and "failed" in normalize_phrase(message):
            priority = AttentionPriority.INTERRUPT

        power = system_state.get("power", {}) if isinstance(system_state, dict) else {}
        battery_percent = power.get("battery_percent")
        if battery_percent is not None and int(battery_percent) <= 10:
            priority = AttentionPriority.INTERRUPT

        return {
            "priority": priority.value,
            "title": title,
            "detail": detail,
            "source": source,
            "timestamp": str(event.get("timestamp") or ""),
        }

    def _classify_signal_attention(self, signal: dict[str, Any], *, system_state: dict[str, Any]) -> dict[str, Any]:
        severity = str(signal.get("severity") or "").strip().lower()
        category = str(signal.get("category") or "").strip().lower()
        priority = AttentionPriority.SUMMARY
        power = system_state.get("power", {}) if isinstance(system_state, dict) else {}
        battery_percent = power.get("battery_percent")
        if category == "power" and battery_percent is not None and int(battery_percent) <= 10:
            priority = AttentionPriority.INTERRUPT
        elif severity == "warning" and category in {"network", "workflow"}:
            priority = AttentionPriority.INTERRUPT
        elif severity in {"warning", "attention"}:
            priority = AttentionPriority.SUMMARY
        else:
            priority = AttentionPriority.BACKGROUND
        return {
            "priority": priority.value,
            "title": str(signal.get("title") or "Signal"),
            "detail": str(signal.get("detail") or ""),
            "source": str(signal.get("source") or "signals"),
        }

    def _activity_summary_text(
        self,
        *,
        high_priority: list[dict[str, Any]],
        summary_worthy: list[dict[str, Any]],
        suppressed_count: int,
    ) -> str:
        if high_priority:
            first = high_priority[0]
            if summary_worthy:
                return f"{first['title']} needs attention. Also summarized {len(summary_worthy)} other recent change{'s' if len(summary_worthy) != 1 else ''}."
            return f"{first['title']} needs attention."
        if summary_worthy:
            first = summary_worthy[0]
            return f"{first['title']} was the highest-signal recent change. {suppressed_count} lower-value update{'s' if suppressed_count != 1 else ''} stayed in the background log."
        if suppressed_count:
            return f"No interrupt-worthy change stood out. {suppressed_count} lower-value update{'s' if suppressed_count != 1 else ''} stayed in the background log."
        return "No important recent change stood out."

    def _environment_continuity(
        self,
        *,
        session_id: str,
        context_items: list[BrowserContextItem],
        capabilities: dict[str, Any],
    ) -> EnvironmentContinuitySnapshot:
        workspace_summary = self.workspace_service.active_workspace_summary(session_id) if self.workspace_service is not None else {}
        workspace = workspace_summary.get("workspace") if isinstance(workspace_summary.get("workspace"), dict) else {}
        signals = [
            signal.to_dict()
            for signal in self.operational_awareness.build_signals(
                events=self.events.recent(limit=24),
                jobs=[],
                system_state=self._system_state_snapshot(),
            )
        ]
        limitations = []
        if not capabilities.get("inspect_open_browser_tabs", False):
            limitations.append("Stormhelm can search visible browser windows here, but not full tab or browser history state.")
        if not capabilities.get("extract_page_content", False):
            limitations.append("Full article extraction is not available in this build.")
        return EnvironmentContinuitySnapshot(
            workspace=workspace,
            browser_context=[item.to_dict() for item in context_items],
            operational_signals=signals,
            capabilities=capabilities,
            limitations=limitations,
        )

    def _missed_activity_window(self, lookback_minutes: int) -> MissedActivityWindow:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=max(int(lookback_minutes), 1))
        return MissedActivityWindow(
            lookback_minutes=max(int(lookback_minutes), 1),
            started_at=start.isoformat(),
            ended_at=end.isoformat(),
        )

    def _recent_events(self, window: MissedActivityWindow) -> list[dict[str, Any]]:
        recent = self.events.recent(limit=96)
        try:
            started = datetime.fromisoformat(window.started_at)
        except ValueError:
            return recent
        filtered = []
        for event in recent:
            timestamp = str(event.get("timestamp") or "").strip()
            try:
                captured = datetime.fromisoformat(timestamp)
            except ValueError:
                captured = None
            if captured is None or captured >= started:
                filtered.append(event)
        return filtered

    def _system_state_snapshot(self) -> dict[str, Any]:
        probe = self.system_probe
        if probe is None:
            return {}
        snapshot: dict[str, Any] = {}
        if hasattr(probe, "machine_status"):
            snapshot["machine"] = probe.machine_status()
        if hasattr(probe, "power_status"):
            snapshot["power"] = probe.power_status()
        if hasattr(probe, "resource_status"):
            snapshot["resources"] = probe.resource_status()
        if hasattr(probe, "storage_status"):
            snapshot["storage"] = probe.storage_status()
        if hasattr(probe, "network_status"):
            snapshot["network"] = probe.network_status()
        if hasattr(probe, "resolve_location"):
            snapshot["location"] = probe.resolve_location()
        return snapshot

    def _meaningful_browser_query(self, query: str) -> str:
        tokens = [
            token
            for token in normalize_phrase(query).split()
            if token and token not in _BROWSER_STOP_TOKENS
        ]
        return " ".join(tokens)

    def _clean_browser_title(self, title: str) -> str:
        cleaned = title.strip()
        for suffix in _BROWSER_SUFFIXES:
            if cleaned.endswith(suffix):
                return cleaned[: -len(suffix)].strip()
        return cleaned

    def _tool_label(self, tool_name: str) -> str:
        label = " ".join(str(tool_name or "operation").replace("_", " ").split()).strip()
        return label.title() if label else "Operation"
