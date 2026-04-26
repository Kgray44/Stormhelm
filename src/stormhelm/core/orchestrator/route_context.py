from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


DEICTIC_TERMS = {"this", "that", "it", "these", "those", "there"}
UI_ACTION_VERBS = {"click", "press", "tap", "select", "focus", "scroll", "open"}
UI_TARGET_TERMS = {
    "button",
    "menu",
    "dropdown",
    "field",
    "panel",
    "tab",
    "icon",
    "submit",
    "save",
    "ok",
    "okay",
    "next",
    "continue",
    "cancel",
}


def _looks_like_placeholder_routine_request(lower: str) -> bool:
    return bool(re.fullmatch(r"(?:run|execute|do)\s+(?:(?:the)\s+)?(?:thing|this|that|it)", lower))


@dataclass(frozen=True, slots=True)
class RouteContextBinding:
    context_type: str
    context_source: str
    route_family: str
    label: str
    value: Any | None = None
    freshness: str = "current"
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RouteContextArbitration:
    context_available: bool
    context_type: str = "none"
    context_source: str = "none"
    freshness: str = "missing"
    ambiguity: str = "none"
    candidate_bindings: tuple[RouteContextBinding, ...] = ()
    selected_binding: RouteContextBinding | None = None
    missing_preconditions: tuple[str, ...] = ()
    route_family_owners: tuple[str, ...] = ()
    clarification_recommended: bool = False
    clarification_text: str = ""
    generic_provider_allowed: bool = True
    reason: str = ""
    intent: str = ""
    requested_action: str = ""
    tool_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_available": self.context_available,
            "context_type": self.context_type,
            "context_source": self.context_source,
            "freshness": self.freshness,
            "ambiguity": self.ambiguity,
            "candidate_bindings": [binding.to_dict() for binding in self.candidate_bindings],
            "selected_binding": self.selected_binding.to_dict() if self.selected_binding is not None else None,
            "missing_preconditions": list(self.missing_preconditions),
            "route_family_owners": list(self.route_family_owners),
            "clarification_recommended": self.clarification_recommended,
            "clarification_text": self.clarification_text,
            "generic_provider_allowed": self.generic_provider_allowed,
            "reason": self.reason,
            "intent": self.intent,
            "requested_action": self.requested_action,
            "tool_hint": self.tool_hint,
        }


class RouteContextArbitrator:
    """Small shared owner/context resolver for deictic and follow-up command routing."""

    def evaluate(
        self,
        *,
        normalized_text: str,
        active_context: dict[str, Any] | None,
        active_request_state: dict[str, Any] | None,
        recent_tool_results: list[dict[str, Any]] | None,
    ) -> RouteContextArbitration | None:
        lower = " ".join(str(normalized_text or "").lower().split())
        if not lower:
            return None
        bindings = self._bindings(
            active_context=active_context or {},
            active_request_state=active_request_state or {},
            recent_tool_results=recent_tool_results or [],
        )

        explicit_path = self.explicit_file_path(lower)
        if explicit_path and self._looks_like_file_read(lower):
            return self._owned(
                "file",
                bindings,
                intent="explicit_file_read",
                requested_action="read_file",
                tool_hint="file_reader",
                reason="filesystem path read request outranks app-control open matching",
            )
        if explicit_path and self._looks_like_file_open(lower):
            explicit_binding = RouteContextBinding(
                context_type="file_path",
                context_source="operator_text",
                route_family="file",
                label=explicit_path,
                value=explicit_path,
                confidence=0.98,
            )
            return self._owned(
                "file",
                (*bindings, explicit_binding),
                selected=explicit_binding,
                intent="explicit_file_open",
                requested_action="open_file",
                tool_hint="open_file",
                reason="filesystem path open request outranks app-control matching",
            )

        if self._looks_like_status_over_app_open(lower):
            return self._owned(
                "network",
                bindings,
                intent="network_status",
                requested_action="network_status",
                tool_hint="network_status",
                reason="status/diagnosis wording around wifi should not launch an app",
            )

        if self._looks_like_activity_catchup(lower):
            return self._owned(
                "watch_runtime",
                bindings,
                intent="activity_summary",
                requested_action="summarize_activity",
                tool_hint="activity_summary",
                reason="away/catch-up wording belongs to runtime activity summary",
            )

        if self._looks_like_system_settings(lower):
            return self._owned(
                "system_control",
                bindings,
                intent="system_settings",
                requested_action="open_settings_page",
                tool_hint="system_control",
                reason="settings target should use system-control rather than app launch",
            )

        if self._looks_like_browser_open(lower):
            binding = self._best_binding(bindings, {"browser_destination"})
            if binding is not None:
                return self._owned(
                    "browser_destination",
                    bindings,
                    selected=binding,
                    intent="deictic_browser_open",
                    requested_action="open_browser_destination",
                    tool_hint="external_open_url",
                    reason="deictic browser open bound to recent page/url context",
                )
            return self._missing(
                "browser_destination",
                bindings,
                missing=("destination_context",),
                intent="deictic_browser_open",
                requested_action="open_browser_destination",
                text="Which website or page should I open? I need a URL, current page, or recent browser reference first.",
                reason="browser destination intent is native but lacks a bound website/page context",
            )

        if self._looks_like_file_open_or_read(lower):
            binding = self._best_binding(bindings, {"file"})
            if binding is not None:
                return self._owned(
                    "file",
                    bindings,
                    selected=binding,
                    intent="deictic_file_open",
                    requested_action="open_file",
                    tool_hint="external_open_file",
                    reason="deictic file request bound to recent file context",
                )
            return self._missing(
                "file",
                bindings,
                missing=("file_context",),
                intent="deictic_file_open",
                requested_action="open_file",
                text="Which file should I use? I need a current file, selected file, or recent file reference first.",
                reason="file route owns the deictic request but lacks a bound file context",
            )

        if self._looks_like_context_action(lower):
            binding = self._best_binding(bindings, {"context_action"})
            if binding is not None:
                return self._owned(
                    "context_action",
                    bindings,
                    selected=binding,
                    intent="selected_context_action",
                    requested_action=self._context_action(lower),
                    tool_hint="context_action",
                    reason="selected/highlighted context request bound to active context",
                )
            return self._missing(
                "context_action",
                bindings,
                missing=("context",),
                intent="selected_context_action",
                requested_action=self._context_action(lower),
                text="Which selected or highlighted context should I use? I need an active selection or clipboard first.",
                reason="context-action intent is native but the selected/highlighted context is missing",
            )

        if self._looks_like_screen_action(lower):
            return self._missing(
                "screen_awareness",
                bindings,
                missing=("visible_screen",),
                intent="visible_ui_action",
                requested_action="ground_screen_action",
                text="Which visible control should I use? I need screen grounding before I can guide that action.",
                reason="visible UI action wording needs screen grounding and must not execute blindly",
            )

        if self._looks_like_relay_missing_context(lower):
            return self._missing(
                "discord_relay",
                bindings,
                missing=("payload", "destination"),
                intent="relay_missing_context",
                requested_action="preview",
                text="What should I send, and where should it go?",
                reason="relay intent is native but lacks payload and destination bindings",
            )

        if self._looks_like_trust_missing_context(lower):
            return self._missing(
                "trust_approvals",
                bindings,
                missing=("approval_object",),
                intent="approval_missing_context",
                requested_action="explain_approval",
                text="Which approval request should I use?",
                reason="trust approval wording is native but lacks an active approval object",
            )

        if self._looks_like_file_operation_missing_context(lower):
            return self._missing(
                "file_operation",
                bindings,
                missing=("file_context",),
                intent="file_operation_missing_context",
                requested_action="file_operation",
                text="Which file should I rename or change?",
                reason="file operation intent is native but lacks a bound file target",
            )

        if self._looks_like_routine_missing_context(lower):
            return self._missing(
                "routine",
                bindings,
                missing=("routine_context",),
                intent="routine_missing_context",
                requested_action="execute_routine",
                text="Which routine or saved workflow should I run?",
                reason="routine execution intent is native but lacks a routine binding",
            )

        return None

    def explicit_file_path(self, normalized_text: str) -> str | None:
        match = re.search(r"(?<![A-Za-z])(?P<path>[A-Za-z]:[\\/][^\r\n,;]+)", normalized_text)
        if not match:
            return None
        path = str(match.group("path") or "").strip(" .,:;!?\"'")
        path = re.sub(
            r"\s+(?:without\s+opening(?:\s+an?\s+app)?|do\s+not\s+open(?:\s+an?\s+app)?|don't\s+open(?:\s+an?\s+app)?)$",
            "",
            path,
            flags=re.IGNORECASE,
        ).strip(" .,:;!?\"'")
        return path

    def _bindings(
        self,
        *,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> tuple[RouteContextBinding, ...]:
        bindings: list[RouteContextBinding] = []
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        if selection.get("value"):
            bindings.append(
                RouteContextBinding(
                    context_type=str(selection.get("kind") or "selected_text"),
                    context_source="selection",
                    route_family="context_action",
                    label=str(selection.get("preview") or "selected text"),
                    value=selection.get("value"),
                    confidence=0.9,
                )
            )
        clipboard = active_context.get("clipboard") if isinstance(active_context.get("clipboard"), dict) else {}
        if clipboard.get("value"):
            bindings.append(
                RouteContextBinding(
                    context_type=str(clipboard.get("kind") or "clipboard"),
                    context_source="clipboard",
                    route_family="context_action",
                    label=str(clipboard.get("preview") or "clipboard"),
                    value=clipboard.get("value"),
                    confidence=0.84,
                )
            )
        recent_entities = active_context.get("recent_entities")
        if isinstance(recent_entities, list):
            for index, entity in enumerate(recent_entities):
                if not isinstance(entity, dict):
                    continue
                url = str(entity.get("url") or "").strip()
                path = str(entity.get("path") or "").strip()
                if not url and not path:
                    continue
                freshness = str(entity.get("freshness") or ("current" if index == 0 else "recent")).strip() or "recent"
                bindings.append(
                    RouteContextBinding(
                        context_type=str(entity.get("kind") or ("page" if url else "file")),
                        context_source="recent_entity",
                        route_family="browser_destination" if url else "file",
                        label=str(entity.get("title") or entity.get("name") or url or path),
                        value=url or path,
                        freshness=freshness,
                        confidence=0.88 if freshness in {"current", "recent"} else 0.42,
                    )
                )
        recent_context = active_context.get("recent_context_resolutions")
        if isinstance(recent_context, list):
            for item in recent_context:
                if not isinstance(item, dict):
                    continue
                if str(item.get("kind") or "").strip() == "calculation":
                    result = item.get("result") if isinstance(item.get("result"), dict) else {}
                    trace = item.get("trace") if isinstance(item.get("trace"), dict) else {}
                    expression = str(trace.get("extracted_expression") or result.get("expression") or "").strip()
                    bindings.append(
                        RouteContextBinding(
                            context_type="calculation",
                            context_source="recent_context_resolution",
                            route_family="calculations",
                            label=expression or "recent calculation",
                            value=item,
                            confidence=0.9,
                        )
                    )
        family = str(active_request_state.get("family") or "").strip()
        subject = str(active_request_state.get("subject") or "").strip()
        if family and subject:
            bindings.append(
                RouteContextBinding(
                    context_type=family,
                    context_source="active_request_state",
                    route_family=family,
                    label=subject,
                    value=active_request_state,
                    freshness="recent",
                    confidence=0.72,
                )
            )
        if recent_tool_results:
            latest = recent_tool_results[0]
            if isinstance(latest, dict):
                family = str(latest.get("family") or "").strip()
                if family:
                    bindings.append(
                        RouteContextBinding(
                            context_type=str(latest.get("tool_name") or family),
                            context_source="recent_tool_result",
                            route_family=family,
                            label=str(latest.get("tool_name") or family),
                            value=latest,
                            freshness="recent",
                            confidence=0.64,
                        )
                    )
        return tuple(sorted(bindings, key=lambda binding: binding.confidence, reverse=True))

    def _best_binding(
        self,
        bindings: tuple[RouteContextBinding, ...],
        owners: set[str],
    ) -> RouteContextBinding | None:
        for binding in bindings:
            if binding.route_family in owners:
                return binding
        return None

    def _owned(
        self,
        owner: str,
        bindings: tuple[RouteContextBinding, ...],
        *,
        selected: RouteContextBinding | None = None,
        intent: str,
        requested_action: str,
        tool_hint: str,
        reason: str,
    ) -> RouteContextArbitration:
        selected = selected or self._best_binding(bindings, {owner})
        return RouteContextArbitration(
            context_available=selected is not None or not bindings,
            context_type=selected.context_type if selected is not None else "explicit",
            context_source=selected.context_source if selected is not None else "operator_text",
            freshness=selected.freshness if selected is not None else "current",
            candidate_bindings=bindings,
            selected_binding=selected,
            route_family_owners=(owner,),
            generic_provider_allowed=False,
            reason=reason,
            intent=intent,
            requested_action=requested_action,
            tool_hint=tool_hint,
        )

    def _missing(
        self,
        owner: str,
        bindings: tuple[RouteContextBinding, ...],
        *,
        missing: tuple[str, ...],
        intent: str,
        requested_action: str,
        text: str,
        reason: str,
    ) -> RouteContextArbitration:
        return RouteContextArbitration(
            context_available=False,
            context_type="none",
            context_source="none",
            freshness="missing",
            ambiguity="missing_context",
            candidate_bindings=bindings,
            missing_preconditions=missing,
            route_family_owners=(owner,),
            clarification_recommended=True,
            clarification_text=text,
            generic_provider_allowed=False,
            reason=reason,
            intent=intent,
            requested_action=requested_action,
        )

    def _looks_like_file_read(self, lower: str) -> bool:
        return lower.startswith(("read ", "summarize ", "show me the contents of ", "show contents of ", "inspect "))

    def _looks_like_file_open(self, lower: str) -> bool:
        return bool(re.match(r"^(?:open|show|bring\s+up|pull\s+up)\b", lower))

    def _looks_like_status_over_app_open(self, lower: str) -> bool:
        return bool(
            re.search(r"\b(?:open\s+or\s+diagnose|diagnose|status)\b", lower)
            and re.search(r"\b(?:wi\s*fi|wifi|wi-fi|network|connection)\b", lower)
        )

    def _looks_like_activity_catchup(self, lower: str) -> bool:
        return bool(
            re.search(r"\bwhat\b.{0,24}\b(?:miss|happened|changed)\b", lower)
            and re.search(r"\b(?:away|stepped away|while i was away|while we were away)\b", lower)
        )

    def _looks_like_system_settings(self, lower: str) -> bool:
        return bool(re.match(r"^(?:open|show|bring\s+up)\s+.+\s+settings?$", lower)) and "website" not in lower

    def _looks_like_browser_open(self, lower: str) -> bool:
        opener = re.match(r"^(?:open|show|bring\s+up|pull\s+up|go\s+to)\b", lower)
        if opener is None:
            return False
        return bool(
            re.search(r"\b(?:website|web\s+site|site|page|link|url)\b", lower)
            and re.search(r"\b(?:this|that|previous|last|earlier|before|we\s+just\s+used)\b", lower)
        )

    def _looks_like_file_open_or_read(self, lower: str) -> bool:
        return bool(
            re.match(r"^(?:open|show|bring\s+up|pull\s+up|read|summarize)\b", lower)
            and re.search(r"\b(?:file|document|doc|pdf|readme|from before|previous|earlier)\b", lower)
        )

    def _looks_like_context_action(self, lower: str) -> bool:
        if any(phrase in lower for phrase in {"selection bias", "selection criteria"}):
            return False
        if re.match(r"^(?:send|share|message|post|relay|forward|dm|pass)\b", lower) and (
            "discord" in lower or re.search(r"\bto\s+\w+", lower)
        ):
            return False
        action = r"(?:use|summarize|open|turn|make|read|copy|extract)"
        explicit_context = r"(?:selected|selection|highlighted|clipboard)"
        return bool(
            re.search(rf"\b{action}\b.{{0,36}}\b{explicit_context}\b", lower)
            or re.search(r"\b(?:use|summarize|open|turn|make)\b.{0,24}\b(?:bit|text)\b", lower)
        )

    def _context_action(self, lower: str) -> str:
        if any(phrase in lower for phrase in {"task", "tasks"}):
            return "extract_tasks"
        if lower.startswith(("open ", "show ", "bring ")):
            return "open"
        return "inspect"

    def _looks_like_screen_action(self, lower: str) -> bool:
        tokens = lower.split()
        if not tokens or tokens[0] not in UI_ACTION_VERBS:
            return False
        return bool(any(term in lower for term in UI_TARGET_TERMS))

    def _looks_like_relay_missing_context(self, lower: str) -> bool:
        return bool(
            re.match(r"^(?:send|share|message|post|relay|forward|dm)\b", lower)
            and any(term in lower.split() for term in {"this", "that", "there", "it"})
        )

    def _looks_like_trust_missing_context(self, lower: str) -> bool:
        return bool(
            re.match(r"^(?:approve|allow|deny|reject|confirm)\b", lower)
            or "why do you need permission" in lower
            or "why are you asking" in lower
        ) and bool(DEICTIC_TERMS.intersection(lower.split()) or "trusted hook" in lower or "permission" in lower)

    def _looks_like_file_operation_missing_context(self, lower: str) -> bool:
        return bool(re.match(r"^(?:rename|move|copy|archive|tag)\s+(?:it|this|that|those|these)\b", lower))

    def _looks_like_routine_missing_context(self, lower: str) -> bool:
        return _looks_like_placeholder_routine_request(lower)
