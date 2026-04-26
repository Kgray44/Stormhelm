from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from stormhelm.core.intelligence.language import normalize_phrase


DEICTIC_TERMS = {"this", "that", "it", "these", "those"}
FOLLOWUP_TERMS = {"previous", "prior", "last", "again", "same", "before", "earlier", "reuse"}
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
CONCEPTUAL_GUARDS = {
    "architecture",
    "concept",
    "principle",
    "principles",
    "philosophy",
    "ideas",
    "essay",
    "theory",
    "teaching",
    "workshop",
}


def _placeholder_routine_request(text: str) -> bool:
    return bool(re.fullmatch(r"(?:run|execute|do)\s+(?:(?:the)\s+)?(?:thing|this|that|it)", text))


@dataclass(slots=True)
class IntentFrame:
    raw_text: str
    normalized_text: str
    invocation_prefix_removed: bool = False
    speech_act: str = "ambiguous"
    operation: str = "unknown"
    target_type: str = "unknown"
    target_text: str = ""
    extracted_entities: dict[str, Any] = field(default_factory=dict)
    context_reference: str = "none"
    context_status: str = "missing"
    risk_class: str = "read_only"
    candidate_route_families: list[str] = field(default_factory=list)
    native_owner_hint: str | None = None
    clarification_needed: bool = False
    clarification_reason: str = ""
    generic_provider_allowed: bool = True
    generic_provider_reason: str = "no_native_route_family_meaningfully_owns_request"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IntentFrameExtractor:
    """Build a typed intent frame before route-family scoring."""

    def extract(
        self,
        raw_text: str,
        *,
        active_context: dict[str, Any] | None = None,
        active_request_state: dict[str, Any] | None = None,
        recent_tool_results: list[dict[str, Any]] | None = None,
    ) -> IntentFrame:
        active_context = active_context or {}
        active_request_state = active_request_state or {}
        recent_tool_results = recent_tool_results or []
        stripped = self._strip_invocation_prefix(raw_text)
        normalized = normalize_phrase(stripped)
        tokens = [token for token in normalized.split() if token]
        operation = self._operation(normalized, tokens)
        if (
            operation == "unknown"
            and self._has_calculation_context(
                active_context=active_context,
                active_request_state=active_request_state,
                recent_tool_results=recent_tool_results,
            )
            and self._calculation_contextual_followup_signal(normalized)
        ):
            operation = "calculate"
        speech_act = self._speech_act(normalized, tokens, operation)
        target_type, target_text, entities = self._target(
            stripped,
            normalized,
            tokens,
            operation=operation,
            active_context=active_context,
        )
        context_reference = self._context_reference(normalized, tokens, target_type)
        context_status, selected_context = self._context_status(
            context_reference=context_reference,
            target_type=target_type,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        if selected_context:
            entities["selected_context"] = selected_context
        risk_class = self._risk_class(operation, target_type, normalized)
        native_owner = self._native_owner(
            normalized,
            operation=operation,
            target_type=target_type,
            speech_act=speech_act,
            context_reference=context_reference,
        )
        clarification_reason = self._clarification_reason(
            owner=native_owner,
            context_reference=context_reference,
            context_status=context_status,
            normalized=normalized,
        )
        candidate_families = [native_owner] if native_owner else []
        return IntentFrame(
            raw_text=stripped,
            normalized_text=normalized,
            invocation_prefix_removed=stripped != str(raw_text or "").strip(),
            speech_act=speech_act,
            operation=operation,
            target_type=target_type,
            target_text=target_text,
            extracted_entities=entities,
            context_reference=context_reference,
            context_status=context_status,
            risk_class=risk_class,
            candidate_route_families=candidate_families,
            native_owner_hint=native_owner,
            clarification_needed=bool(clarification_reason),
            clarification_reason=clarification_reason,
            generic_provider_allowed=native_owner is None,
            generic_provider_reason=(
                "no_native_route_family_meaningfully_owns_request"
                if native_owner is None
                else "native_route_candidate_present"
            ),
        )

    def _strip_invocation_prefix(self, raw_text: str) -> str:
        text = " ".join(str(raw_text or "").split()).strip()
        text = re.sub(r"^\s*stormhelm\s*[,:\-]\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"^\s*(?:hey\s+)?(?:can|could)\s+you\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*(?:please|pls|yo)\s+", "", text, flags=re.IGNORECASE)
        return text.strip(" ?")

    def _speech_act(self, normalized: str, tokens: list[str], operation: str) -> str:
        if any(term in tokens for term in FOLLOWUP_TERMS) or any(term in tokens for term in DEICTIC_TERMS):
            if operation in {"calculate", "open", "inspect", "compare"}:
                return "followup"
        if "not " in normalized or normalized.startswith(("no ", "nah ")):
            return "correction"
        if operation == "compare" or re.search(r"\b(?:better|versus|vs)\b", normalized):
            return "comparison"
        if operation == "status" or self._looks_like_status(normalized):
            return "status_check"
        if operation == "explain":
            return "explanation_request"
        if tokens and tokens[0] in {"what", "which", "how", "why", "is", "are", "am"}:
            return "question"
        if operation != "unknown":
            return "command"
        return "ambiguous"

    def _operation(self, normalized: str, tokens: list[str]) -> str:
        if self._looks_like_calculation(normalized):
            return "calculate"
        if self._software_recovery_signal(normalized):
            return "repair"
        if self._trust_approval_signal(normalized):
            return "verify"
        if self._workflow_signal(normalized):
            return "assemble"
        if self._maintenance_signal(normalized):
            return "repair"
        if self._terminal_signal(normalized):
            return "open" if any(token in tokens for token in {"open", "show", "launch", "start"}) else "launch"
        if self._task_continuity_signal(normalized):
            return "assemble"
        if any(token in tokens for token in {"quit", "close"}) and re.search(r"\bnot\s+(?:uninstall|remove|update)\b", normalized):
            return "quit" if "quit" in tokens else "close"
        if any(token in tokens for token in {"install", "download", "setup"}) or "set up" in normalized:
            if "environment" not in normalized and "workspace" not in normalized and "workflow" not in normalized:
                return "install"
        if (any(token in tokens for token in {"uninstall", "remove"}) or "get rid of" in normalized) and self._software_target(normalized):
            return "uninstall"
        if any(token in tokens for token in {"update", "upgrade"}):
            return "update"
        if any(token in tokens for token in {"rename", "move", "delete", "tag", "archive"}):
            return "update"
        if any(token in tokens for token in {"repair", "fix"}):
            return "repair"
        if any(token in tokens for token in {"read", "inspect", "summarize"}) or "contents of" in normalized:
            return "inspect"
        if any(token in tokens for token in {"quit", "close"}):
            return "quit" if "quit" in tokens else "close"
        if self._weather_status_signal(normalized):
            return "status"
        if tokens and tokens[0] in {"explain", "why", "what"} and not self._looks_like_status(normalized):
            return "explain"
        if "focus" in tokens:
            return "open"
        if any(token in tokens for token in {"send", "share", "message", "post", "relay", "forward", "dm"}) or "pass this along" in normalized:
            return "send"
        if self._looks_like_routine_save(normalized):
            return "save"
        if any(token in tokens for token in {"assemble", "restore", "resume"}):
            return "assemble"
        if any(token in tokens for token in {"search", "find"}):
            return "search"
        if self._network_status_signal(normalized):
            return "status"
        if any(token in tokens for token in {"verify", "check"}):
            return "verify"
        if any(token in tokens for token in {"approve", "deny", "allow"}) or "permission" in normalized or "confirmation" in normalized:
            return "verify"
        if any(token in tokens for token in {"compare", "diff"}) or re.search(r"\b(?:versus|vs|better)\b", normalized):
            return "compare"
        if any(token in tokens for token in {"read", "inspect", "summarize"}) and self._file_signal(normalized):
            return "inspect"
        if self._looks_like_status(normalized):
            return "status"
        if any(token in tokens for token in {"open", "show", "launch", "start", "bring", "pull"}):
            return "launch" if "launch" in tokens or "start" in tokens else "open"
        if "run" in tokens:
            return "launch"
        return "unknown"

    def _target(
        self,
        raw_text: str,
        normalized: str,
        tokens: list[str],
        *,
        operation: str,
        active_context: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        del active_context
        entities: dict[str, Any] = {}
        url_match = re.search(r"https?://[^\s]+", raw_text, flags=re.IGNORECASE)
        if url_match:
            url = url_match.group(0).strip(" .,:;!?\"'")
            entities["url"] = url
            return "url", url, entities
        path_match = re.search(r"(?<![A-Za-z])(?P<path>[A-Za-z]:[\\/][^\r\n,;]+)", raw_text)
        if path_match:
            path = str(path_match.group("path") or "").strip(" .,:;!?\"'")
            path = re.split(r"\s+without\s+", path, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .,:;!?\"'")
            entities["path"] = path
            return "file", path, entities
        domain = self._domain_like_destination(raw_text, normalized)
        if domain:
            entities["url"] = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
            return "website", domain, entities
        if self._selected_signal(normalized):
            return "selected_text", "selected text", entities
        if self._visible_ui_signal(normalized):
            return "visible_ui", "visible UI", entities
        if self._website_signal(normalized):
            return "website", self._extract_after_open(raw_text), entities
        if self._maintenance_signal(normalized):
            return "folder", self._extract_after_open(raw_text) or "maintenance target", entities
        if self._terminal_signal(normalized):
            return "folder", self._extract_after_open(raw_text) or "working directory", entities
        if self._desktop_search_signal(normalized):
            return "file" if self._file_signal(normalized) else "unknown", self._extract_after_open(raw_text), entities
        if self._workflow_signal(normalized):
            return "workspace", self._extract_after_open(raw_text) or "workflow", entities
        if self._workspace_signal(normalized):
            return "workspace", self._extract_after_open(raw_text), entities
        if self._file_signal(normalized):
            return "file", self._extract_after_open(raw_text), entities
        if operation == "update" and any(term in tokens for term in {"it", "this", "that"}):
            return "file", "current file", entities
        if operation == "update" and self._file_operation_signal(normalized):
            return "file", self._extract_after_open(raw_text), entities
        if operation == "repair" and self._software_recovery_signal(normalized):
            return "system_resource", self._system_resource(normalized), entities
        if operation in {"install", "uninstall", "update", "repair"} and self._software_target(normalized):
            return "software_package", self._software_target_text(raw_text), entities
        if operation in {"quit", "close", "launch", "open"} and self._app_control_signal(normalized):
            return "app", self._app_target_text(raw_text), entities
        if operation == "status" and self._app_status_signal(normalized):
            return "app", "active applications", entities
        if operation == "status" and self._window_status_signal(normalized):
            return "current_app", "windows", entities
        if self._routine_signal(normalized):
            return "routine", self._extract_after_open(raw_text), entities
        if self._discord_signal(normalized):
            return "discord_recipient", self._extract_after_open(raw_text), entities
        if self._weather_status_signal(normalized):
            return "system_resource", "weather", entities
        if self._software_recovery_signal(normalized):
            return "system_resource", self._system_resource(normalized), entities
        if self._system_resource_signal(normalized):
            return "system_resource", self._system_resource(normalized), entities
        if self._calculation_followup_signal(normalized) or (
            operation == "calculate" and self._calculation_contextual_followup_signal(normalized)
        ):
            return "prior_calculation", "previous calculation", entities
        if operation == "calculate":
            return "unknown", "", entities
        return "unknown", "", entities

    def _context_reference(self, normalized: str, tokens: list[str], target_type: str) -> str:
        if "selected" in tokens:
            return "selected"
        if "highlighted" in tokens:
            return "highlighted"
        if "current page" in normalized:
            return "current_page"
        if target_type == "file" and any(
            phrase in normalized
            for phrase in {"from before", "previous file", "previous document", "earlier file", "earlier document"}
        ):
            return "current_file"
        if any(phrase in normalized for phrase in {"we just used", "from before", "moment ago", "previous website", "previous page", "earlier page"}):
            return "current_page"
        if "current file" in normalized:
            return "current_file"
        if "previous calculation" in normalized or target_type == "prior_calculation":
            return "previous_calculation"
        if "previous result" in normalized or "last answer" in normalized or "previous answer" in normalized:
            return "previous_result"
        if any(phrase in normalized for phrase in {"this computer", "this machine", "this pc"}):
            return "none"
        for term in ("this", "that", "it"):
            if term in tokens:
                return term
        for term in ("here", "there"):
            if term in tokens:
                return term
        if any(term in tokens for term in FOLLOWUP_TERMS):
            if target_type in {"website", "url"}:
                return "current_page"
            if target_type == "file":
                return "current_file"
            if target_type in {"prior_calculation", "prior_result"}:
                return "previous_calculation"
            return "previous_result"
        return "none"

    def _context_status(
        self,
        *,
        context_reference: str,
        target_type: str,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any] | None]:
        if context_reference == "none":
            return "available", None
        compatible = self._compatible_context(
            target_type=target_type,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        if compatible:
            if len(compatible) > 1:
                compatible = sorted(compatible, key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
                if abs(float(compatible[0].get("confidence", 0.0)) - float(compatible[1].get("confidence", 0.0))) < 0.05:
                    return "ambiguous", None
            return "available", compatible[0]
        return "missing", None

    def _compatible_context(
        self,
        *,
        target_type: str,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        workspace = active_context.get("workspace") if isinstance(active_context.get("workspace"), dict) else {}
        if target_type == "workspace" and workspace:
            candidates.append(
                {
                    "type": "workspace",
                    "source": "workspace_context",
                    "label": str(workspace.get("name") or workspace.get("workspaceId") or "current workspace"),
                    "value": workspace,
                    "confidence": 0.93,
                }
            )
        if target_type == "selected_text" and selection.get("value"):
            candidates.append(
                {
                    "type": "selected_text",
                    "source": "selection",
                    "label": str(selection.get("preview") or "selected text"),
                    "value": selection.get("value"),
                    "confidence": 0.94,
                }
            )
        for entity in self._recent_entities(active_context, recent_tool_results):
            kind = str(entity.get("kind") or "").lower()
            if target_type in {"website", "url"} and (kind in {"page", "url", "website", "link"} or entity.get("url")):
                candidates.append(
                    {
                        "type": "website",
                        "source": "recent_entities",
                        "label": str(entity.get("title") or entity.get("url") or "recent page"),
                        "value": entity.get("url") or entity.get("value"),
                        "confidence": 0.9,
                    }
                )
            if target_type == "file" and (kind in {"file", "document"} or entity.get("path")):
                candidates.append(
                    {
                        "type": "file",
                        "source": "recent_entities",
                        "label": str(entity.get("title") or entity.get("path") or "recent file"),
                        "value": entity.get("path") or entity.get("value"),
                        "confidence": 0.9,
                    }
                )
        for item in active_context.get("recent_context_resolutions", []) if isinstance(active_context.get("recent_context_resolutions"), list) else []:
            if isinstance(item, dict) and target_type in {"prior_calculation", "prior_result"} and str(item.get("kind") or "") == "calculation":
                candidates.append(
                    {
                        "type": "prior_calculation",
                        "source": "recent_context_resolutions",
                        "label": "recent calculation",
                        "value": item.get("result") or item,
                        "confidence": 0.92,
                    }
                )
        family = str(active_request_state.get("family") or "").lower()
        if family == "calculations" and target_type in {"prior_calculation", "prior_result"} and candidates:
            candidates[0]["confidence"] = max(float(candidates[0].get("confidence", 0.0)), 0.94)
        return candidates

    def _recent_entities(self, active_context: dict[str, Any], recent_tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        raw_entities = active_context.get("recent_entities")
        if isinstance(raw_entities, list):
            entities.extend(item for item in raw_entities if isinstance(item, dict))
        for result in recent_tool_results:
            if not isinstance(result, dict):
                continue
            entity = result.get("entity")
            if isinstance(entity, dict):
                entities.append(entity)
        return entities

    def _risk_class(self, operation: str, target_type: str, normalized: str) -> str:
        if operation in {"install", "uninstall", "update", "repair"} and target_type == "software_package":
            return "software_lifecycle"
        if operation == "send":
            return "external_send"
        if operation in {"quit", "close", "launch"} and target_type == "app":
            return "external_app_open"
        if operation == "open" and target_type in {"url", "website"}:
            return "external_browser_open"
        if operation == "open" and target_type in {"file", "folder"}:
            return "internal_surface_open"
        if operation in {"save", "assemble"} or any(token in normalized for token in {"rename", "move", "delete"}):
            return "dry_run_plan"
        return "read_only"

    def _native_owner(
        self,
        normalized: str,
        *,
        operation: str,
        target_type: str,
        speech_act: str,
        context_reference: str,
    ) -> str | None:
        if self._conceptual_near_miss(normalized):
            return None
        if self._external_commitment_signal(normalized):
            return "unsupported"
        if operation == "calculate" or self._calculation_followup_signal(normalized):
            return "calculations"
        if self._software_recovery_signal(normalized):
            return "software_recovery"
        if operation in {"install", "uninstall", "update", "repair"} and target_type == "software_package":
            return "software_control"
        if self._weather_status_signal(normalized):
            return "weather"
        if target_type == "system_resource" and self._system_resource(normalized) == "power":
            return "power"
        if operation == "compare" and target_type in {"file", "selected_text"}:
            return "comparison"
        if target_type in {"url", "website"}:
            return "browser_destination"
        if self._maintenance_signal(normalized):
            return "maintenance"
        if self._desktop_search_signal(normalized):
            return "desktop_search"
        if self._workflow_signal(normalized):
            return "workflow"
        if self._terminal_signal(normalized):
            return "terminal"
        if target_type == "file":
            if operation in {"open", "inspect"}:
                return "file"
            if operation in {"save", "update", "repair"}:
                return "file_operation"
            return None
        if target_type == "selected_text":
            return "context_action"
        if target_type == "visible_ui":
            return "screen_awareness"
        if operation == "send" and (target_type == "discord_recipient" or self._discord_signal(normalized)):
            return "discord_relay"
        if operation == "send" and any(term in normalized.split() for term in {"this", "that", "there", "it"}):
            return "discord_relay"
        if self._trust_approval_signal(normalized):
            return "trust_approvals"
        if operation == "save" and self._routine_signal(normalized):
            return "routine"
        if self._routine_signal(normalized):
            return "routine"
        if operation == "launch" and _placeholder_routine_request(normalized):
            return "routine"
        if self._task_continuity_signal(normalized):
            return "task_continuity"
        if self._workspace_signal(normalized):
            return "workspace_operations"
        if operation in {"quit", "close", "launch", "open"} and target_type == "app":
            return "app_control"
        if self._app_status_signal(normalized):
            return "app_control"
        if self._window_status_signal(normalized):
            return "window_control"
        if self._resource_status_signal(normalized):
            return "resources"
        if self._status_runtime_signal(normalized):
            return "watch_runtime"
        if self._network_status_signal(normalized):
            return "network"
        if operation == "search" and self._file_signal(normalized):
            return "desktop_search"
        if operation == "compare" and context_reference != "none" and target_type in {"file", "selected_text", "prior_result"}:
            return "context_action"
        if speech_act in {"explanation_request", "comparison"}:
            return None
        return None

    def _clarification_reason(
        self,
        *,
        owner: str | None,
        context_reference: str,
        context_status: str,
        normalized: str,
    ) -> str:
        if owner is None:
            return ""
        if owner == "network":
            return ""
        if owner == "screen_awareness" and context_status != "available":
            return "visible_screen"
        if owner == "discord_relay" and self._relay_missing_context(normalized):
            return "payload"
        if owner == "routine" and self._looks_like_routine_save(normalized):
            return "steps_or_recent_action"
        if owner == "routine" and _placeholder_routine_request(normalized):
            return "routine_context"
        if owner == "trust_approvals" and context_status != "available":
            return "approval_object"
        if owner == "terminal" and context_status != "available":
            return "folder_context"
        if owner == "workflow" and context_status != "available":
            return "workflow_context"
        if owner == "desktop_search" and context_status != "available":
            return "search_context"
        if owner == "file_operation" and context_status != "available":
            return "file_context"
        if context_reference != "none" and context_status != "available":
            return {
                "calculations": "calculation_context",
                "browser_destination": "destination_context",
                "file": "file_context",
                "context_action": "context",
                "task_continuity": "context",
                "routine": "routine_context",
                "app_control": "app_context",
            }.get(owner, "context")
        return ""

    def _looks_like_calculation(self, normalized: str) -> bool:
        if self._calculation_followup_signal(normalized):
            return True
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:\+|\-|\*|/|x|times|plus|minus|over|divided by|multiplied by)\s*\d+", normalized):
            return True
        return bool(re.search(r"\b(?:compute|calculate|solve|answer)\b.{0,24}\b\d+", normalized))

    def _calculation_followup_signal(self, normalized: str) -> bool:
        return any(
            phrase in normalized
            for phrase in {
                "that answer",
                "last answer",
                "previous answer",
                "that result",
                "last result",
                "same equation",
                "same math",
                "same setup",
                "redo it",
                "that number",
                "that calculation",
                "walk through",
                "walk me through",
                "show arithmetic",
                "show me the arithmetic",
                "show the steps",
                "divide the last answer",
                "multiply that",
                "doubled",
                "swap in",
            }
        )

    def _calculation_contextual_followup_signal(self, normalized: str) -> bool:
        if self._calculation_followup_signal(normalized):
            return True
        if self._generic_deictic_followup_signal(normalized):
            return True
        if re.search(r"\bcontinue\b.{0,24}\b(?:this|that|the)\b.{0,16}\bcalculation\b", normalized):
            return True
        return bool(
            any(
                phrase in normalized
                for phrase in {
                    "same calculation",
                    "same thing as before",
                    "same thing again",
                    "use that result",
                    "go ahead with that preview",
                    "use the other one",
                    "show the steps",
                }
            )
            or normalized in {"yes", "yes go ahead", "no use the other one"}
        )

    def _generic_deictic_followup_signal(self, normalized: str) -> bool:
        if not any(term in normalized.split() for term in DEICTIC_TERMS):
            return False
        return bool(
            re.search(r"\b(?:use|reuse|continue|redo|apply|show|explain)\b.{0,36}\b(?:this|that|it|these|those)\b", normalized)
            or re.search(r"\b(?:this|that|it|these|those)\b.{0,36}\b(?:again|instead|next|same|other)\b", normalized)
        )

    def _has_calculation_context(
        self,
        *,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> bool:
        if str(active_request_state.get("family") or "").lower() == "calculations":
            return True
        for item in active_context.get("recent_context_resolutions", []) if isinstance(active_context.get("recent_context_resolutions"), list) else []:
            if isinstance(item, dict) and str(item.get("kind") or "").lower() == "calculation":
                return True
        for result in recent_tool_results:
            if isinstance(result, dict) and str(result.get("family") or result.get("kind") or "").lower() == "calculations":
                return True
        return False

    def _looks_like_status(self, normalized: str) -> bool:
        return self._network_status_signal(normalized) or self._weather_status_signal(normalized) or self._status_runtime_signal(normalized) or self._app_status_signal(normalized) or self._window_status_signal(normalized) or any(
            phrase in normalized
            for phrase in {"battery", "storage status", "machine name", "os version", "current time"}
        )

    def _network_status_signal(self, normalized: str) -> bool:
        if (
            "neural network" in normalized
            or "network architecture" in normalized
            or any(term in normalized for term in {"network design", "network effects", "networking advice", "network graph concept"})
        ):
            return False
        return bool(
            re.search(r"\b(?:which|what|tell|show|check)\b.{0,28}\b(?:wifi|wi-fi|wireless|network|connection|ssid|internet)\b", normalized)
            or re.search(r"\bcheck\b.{0,32}\b(?:online|connected)\b", normalized)
            or re.search(r"\b(?:am i|are we|is my|is this|is the)\b.{0,32}\b(?:online|connected|on wifi|on wi-fi)\b", normalized)
            or re.search(r"\b(?:open|diagnose|show|check)\b.{0,24}\b(?:wifi|wi-fi|network|connection)\b.{0,16}\bstatus\b", normalized)
            or re.search(r"\b(?:wifi|wi-fi|wireless)\b.{0,20}\b(?:signal|name|ssid|network)\b", normalized)
            or any(phrase in normalized for phrase in {"wifi status", "wi-fi status", "network status", "connection status", "internet connected"})
        )

    def _status_runtime_signal(self, normalized: str) -> bool:
        if self._conceptual_near_miss(normalized):
            return False
        return bool(
            self._browser_context_status_signal(normalized)
            or "what did i miss" in normalized
            or "while i was away" in normalized
            or "what happened while" in normalized
            or "what changed while" in normalized
            or "stepped away" in normalized
        )

    def _app_status_signal(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in {"app design", "app principles", "app architecture", "app marketing", "apps should i build", "apps concept", "mobile ux"}):
            return False
        return bool(
            re.search(r"\b(?:which|what|show|list)\b.{0,24}\b(?:apps?|applications?|programs?)\b.{0,24}\b(?:running|open|active)\b", normalized)
            or re.search(r"\b(?:apps?|applications?|programs?)\b.{0,24}\b(?:running|open|active)\b", normalized)
            or re.search(r"\b(?:running|active|open)\b.{0,24}\b(?:apps?|applications?|programs?)\b", normalized)
        )

    def _window_status_signal(self, normalized: str) -> bool:
        if "window pattern" in normalized or "application window pattern" in normalized:
            return False
        return bool(
            re.search(r"\b(?:what|which|show|list)\b.{0,24}\bwindows?\b.{0,24}\b(?:open|active|focused|running)\b", normalized)
            or re.search(r"\b(?:open|active|focused)\b.{0,24}\bwindows?\b", normalized)
        )

    def _resource_status_signal(self, normalized: str) -> bool:
        return bool(re.search(r"\b(?:cpu|memory|ram)\b.{0,24}\b(?:usage|use|load)\b", normalized) or "cpu and memory" in normalized)

    def _weather_status_signal(self, normalized: str) -> bool:
        return bool(
            re.search(r"\b(?:weather|forecast)\b", normalized)
            or re.search(r"\b(?:temperature|outside)\b.{0,24}\b(?:now|right now|today|tonight|tomorrow)\b", normalized)
            or re.search(r"\b(?:what|how)\b.{0,16}\b(?:outside|temperature)\b", normalized)
        )

    def _browser_context_status_signal(self, normalized: str) -> bool:
        return bool(
            re.search(r"\b(?:what|which)\b.{0,24}\b(?:browser\s+)?(?:page|tab)\b.{0,24}\bam i on\b", normalized)
            or re.search(r"\bcurrent\b.{0,16}\b(?:browser\s+)?(?:page|tab)\b", normalized)
        )

    def _selected_signal(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in {"selected text in html", "selection bias", "selection criteria", "highlighted text typography ideas"}):
            return False
        return bool(re.search(r"\b(?:selected|highlighted|clipboard|selection)\b", normalized))

    def _visible_ui_signal(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in {"coverage summary", "buttoned up", "press release"}):
            return False
        has_action = bool(re.search(r"\b(?:click|press|tap|select|focus|scroll|open)\b", normalized))
        has_target = any(re.search(rf"\b{re.escape(term)}\b", normalized) for term in UI_TARGET_TERMS)
        return has_action and has_target

    def _website_signal(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in {"what is a website", "website design ideas", "website design principles", "website app ideas"}):
            return False
        if "not exactly" in normalized and "almost" in normalized:
            return False
        if re.search(r"\b(?:open|show|bring|pull)\b.{0,32}\bin\s+(?:a\s+)?browser\b", normalized):
            return True
        return any(term in normalized for term in {"website", "site", "page", "link", "url"}) and any(
            verb in normalized for verb in {"open", "show", "bring", "pull"}
        )

    def _domain_like_destination(self, raw_text: str, normalized: str) -> str:
        if any(phrase in normalized for phrase in {"what is a website", "website design", "app ideas"}):
            return ""
        if "not exactly" in normalized and "almost" in normalized:
            return ""
        match = re.search(r"\b(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?\b", raw_text, flags=re.IGNORECASE)
        if match and re.search(r"\b(?:open|show|bring|pull)\b", normalized):
            return str(match.group(0)).strip(" .,:;!?\"'")
        browser_target = re.search(
            r"\b(?:open|show|bring\s+up|pull\s+up)\s+(?P<target>[a-z0-9-]{3,})\s+(?:in|with)\s+(?:a\s+)?browser\b",
            raw_text,
            flags=re.IGNORECASE,
        )
        if browser_target:
            return str(browser_target.group("target") or "").strip(" .,:;!?\"'")
        return ""

    def _file_signal(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in {"what is a file", "file naming philosophy"}):
            return False
        return bool(re.search(r"\b(?:file|document|doc|pdf|readme|folder|screenshot|screenshots)\b", normalized)) and not self._website_signal(normalized)

    def _file_operation_signal(self, normalized: str) -> bool:
        return bool(
            re.search(r"\b(?:rename|move|delete|tag|archive)\b.{0,40}\b(?:file|files|folder|screenshots?|documents?|docs?)\b", normalized)
            or re.search(r"\b(?:file|files|folder|screenshots?|documents?|docs?)\b.{0,40}\b(?:rename|move|delete|tag|archive)\b", normalized)
        )

    def _app_control_signal(self, normalized: str) -> bool:
        if self._website_signal(normalized) or self._file_signal(normalized):
            return False
        if any(phrase in normalized for phrase in {"app design", "app architecture", "app principles", "app idea", "app ideas", "apps concept", "mobile ux"}):
            return False
        return bool(re.search(r"\b(?:app|apps|app\d+|notepad|chrome|slack|discord|calculator|window)\b", normalized))

    def _software_target(self, normalized: str) -> bool:
        return bool(re.search(r"\b(?:app|apps|notepad|chrome|slack|discord|zoom|software|package|program|pc|computer|machine)\b", normalized))

    def _software_target_text(self, raw_text: str) -> str:
        return re.sub(r"^(?:install|uninstall|update|upgrade|repair|fix|remove)\s+", "", raw_text, flags=re.IGNORECASE).strip(" .,:;!?")

    def _app_target_text(self, raw_text: str) -> str:
        return re.sub(r"^(?:open|launch|start|quit|close|focus)\s+", "", raw_text, flags=re.IGNORECASE).strip(" .,:;!?")

    def _routine_signal(self, normalized: str) -> bool:
        return "routine" in normalized or "saved workflow" in normalized

    def _looks_like_routine_save(self, normalized: str) -> bool:
        return self._routine_signal(normalized) and any(
            phrase in normalized
            for phrase in {"save this", "save that", "make this", "make that", "turn this", "turn that", "remember this"}
        )

    def _workspace_signal(self, normalized: str) -> bool:
        return "workspace" in normalized or "where left off" in normalized or "writing environment" in normalized

    def _task_continuity_signal(self, normalized: str) -> bool:
        return any(
            phrase in normalized
            for phrase in {
                "where left off",
                "where i left off",
                "continue where i left off",
                "resume where i left off",
                "next steps",
                "do next",
                "what should i do next",
            }
        )

    def _workflow_signal(self, normalized: str) -> bool:
        if self._conceptual_near_miss(normalized):
            return False
        return bool(
            re.search(r"\b(?:set up|setup|prepare|open|restore)\b.{0,36}\b(?:workflow|environment|setup|work context)\b", normalized)
            or re.search(r"\b(?:writing|research|project|diagnostics)\b.{0,24}\b(?:environment|setup|workflow|context)\b", normalized)
            or re.search(r"\brun\b.{0,24}\b(?:workflow|setup)\b", normalized)
        )

    def _maintenance_signal(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in {"clean up this paragraph", "clean writing style", "cleanup advice", "clean workspace ideas", "clean workspace"}):
            return False
        if "workspace" in normalized and any(phrase in normalized for phrase in {"current workspace", "this workspace", "workspace inspiration"}):
            return False
        return bool(
            re.search(r"\b(?:clean up|cleanup|clean|archive|tidy)\b.{0,36}\b(?:downloads?|screenshots?|files?|folder|workspace)\b", normalized)
            or re.search(r"\b(?:find|show)\b.{0,24}\b(?:stale|large|old)\b.{0,24}\bfiles?\b", normalized)
        )

    def _terminal_signal(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in {"terminal velocity", "terminal illness", "terminal value"}):
            return False
        return bool(re.search(r"\b(?:terminal|powershell|command shell|shell)\b", normalized))

    def _desktop_search_signal(self, normalized: str) -> bool:
        if any(phrase in normalized for phrase in {"search algorithms", "search theory", "search engine", "search the web", "research online"}):
            return False
        return bool(
            re.search(r"\b(?:find|locate|search|pull up)\b.{0,48}\b(?:file|files|folder|document|doc|readme|pdf|downloads?|desktop|computer|machine)\b", normalized)
            or re.search(r"\b(?:find|locate|search)\b.{0,36}\b(?:on|from|under)\s+(?:this\s+)?(?:computer|machine|pc|desktop)\b", normalized)
        )

    def _software_recovery_signal(self, normalized: str) -> bool:
        if "status" in normalized and not re.search(r"\b(?:fix|repair|flush|restart)\b", normalized):
            return False
        if re.search(r"\b(?:fix|repair|diagnose|flush|restart)\b.{0,32}\b(?:wifi|wi-fi|wi fi|network|connection|dns|explorer)\b", normalized):
            return True
        return bool(re.search(r"\b(?:run)\b.{0,24}\b(?:connectivity checks?|network checks?)\b", normalized))

    def _trust_approval_signal(self, normalized: str) -> bool:
        return bool(
            re.search(r"\b(?:approve|deny|allow)\b", normalized)
            or "permission" in normalized
            or "confirmation" in normalized
            or re.search(r"\bwhy\b.{0,24}\b(?:approval|approve|permission|confirm|confirmation)\b", normalized)
            or re.search(r"\bwhat\b.{0,24}\b(?:approving|approval|permission)\b", normalized)
        )

    def _external_commitment_signal(self, normalized: str) -> bool:
        return bool(
            re.search(r"\b(?:book|buy|purchase|order)\b", normalized)
            and re.search(r"\b(?:pay|paid|reservation|ticket|flight|hotel)\b", normalized)
        )

    def _discord_signal(self, normalized: str) -> bool:
        return bool(re.search(r"\bdiscord\b", normalized) or re.search(r"\brelay\b", normalized))

    def _system_resource_signal(self, normalized: str) -> bool:
        return (
            self._network_status_signal(normalized)
            or self._status_runtime_signal(normalized)
            or self._app_status_signal(normalized)
            or self._resource_status_signal(normalized)
            or any(term in normalized for term in {"battery", "charging", "machine name", "os version"})
        )

    def _system_resource(self, normalized: str) -> str:
        if "wifi" in normalized or "wi-fi" in normalized or "network" in normalized:
            return "network"
        if "apps" in normalized or "applications" in normalized:
            return "apps"
        if "battery" in normalized or "charging" in normalized:
            return "power"
        if "cpu" in normalized or "memory" in normalized:
            return "resources"
        return "system"

    def _relay_missing_context(self, normalized: str) -> bool:
        return any(term in normalized for term in {"this", "that", "there"}) or "discord" not in normalized

    def _conceptual_near_miss(self, normalized: str) -> bool:
        if "neural network" in normalized or "machine learning" in normalized:
            return True
        if any(term in normalized for term in CONCEPTUAL_GUARDS) and not re.search(r"\b(?:open|run|save|send|install|uninstall|update|quit|close)\b", normalized):
            return True
        if any(phrase in normalized for phrase in {"selected text in html", "terminal velocity", "daily routine", "what is a website", "what is a file"}):
            return True
        return False

    def _extract_after_open(self, raw_text: str) -> str:
        return re.sub(r"^(?:open|show|bring up|pull up|read|inspect|summarize|run|save)\s+", "", raw_text, flags=re.IGNORECASE).strip(" .,:;!?")
