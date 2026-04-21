from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stormhelm.config.models import AppConfig
from stormhelm.core.intelligence.language import normalize_phrase, token_overlap
from stormhelm.core.judgment.models import ActionRiskTier, GuardrailDecision, PostActionJudgmentResult, SuggestionCandidate
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.orchestrator.session_state import ConversationStateStore


class JudgmentService:
    def __init__(self, *, config: AppConfig, session_state: ConversationStateStore) -> None:
        self.config = config
        self.session_state = session_state

    def observe_operator_turn(self, session_id: str, message: str) -> None:
        state = self.session_state.get_suggestion_state(session_id)
        if not state:
            return
        normalized_message = normalize_phrase(message)
        command = normalize_phrase(str(state.get("command") or ""))
        title = normalize_phrase(str(state.get("title") or ""))
        if command and (command in normalized_message or token_overlap(normalized_message, command) >= 0.72):
            self.session_state.clear_suggestion_state(session_id)
            return
        if title and token_overlap(normalized_message, title) >= 0.72:
            self.session_state.clear_suggestion_state(session_id)
            return
        updated = dict(state)
        updated["ignore_count"] = int(updated.get("ignore_count", 0) or 0) + 1
        updated["last_ignored_at"] = datetime.now(timezone.utc).isoformat()
        self.session_state.set_suggestion_state(session_id, updated)

    def assess_pre_action(
        self,
        *,
        session_id: str,
        message: str,
        tool_requests: list[ToolRequest],
        active_context: dict[str, Any] | None,
    ) -> GuardrailDecision:
        del session_id, message, active_context
        risk_tier = ActionRiskTier.SAFE
        debug: dict[str, Any] = {"considered_tools": [request.tool_name for request in tool_requests]}
        for request in tool_requests:
            candidate = self._risk_for_request(request)
            if candidate is ActionRiskTier.HIGH:
                risk_tier = ActionRiskTier.HIGH
                break
            if candidate is ActionRiskTier.CAUTION:
                risk_tier = ActionRiskTier.CAUTION
        outcome = "act_direct"
        if risk_tier is ActionRiskTier.CAUTION:
            outcome = "act_with_guardrail_notice"
        elif risk_tier is ActionRiskTier.HIGH:
            outcome = "act_direct"
        return GuardrailDecision(
            risk_tier=risk_tier,
            outcome=outcome,
            debug=debug,
        )

    def evaluate_post_action(
        self,
        *,
        session_id: str,
        message: str,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        active_context: dict[str, Any] | None,
        active_request_state: dict[str, Any] | None,
        pre_action: GuardrailDecision,
    ) -> PostActionJudgmentResult:
        del message, actions, active_context
        candidate, recovery = self._suggestion_candidate(jobs=jobs, active_request_state=active_request_state or {})
        debug = {
            "risk_tier": pre_action.risk_tier.value,
            "guardrail_outcome": pre_action.outcome,
            "candidate": candidate.to_dict() if candidate is not None else None,
        }
        if candidate is None:
            self.session_state.clear_suggestion_state(session_id)
            return PostActionJudgmentResult(debug=debug)
        state = self.session_state.get_suggestion_state(session_id)
        if state and str(state.get("key") or "") == candidate.key and int(state.get("ignore_count", 0) or 0) >= 1:
            debug["suppressed_reason"] = "recently_ignored"
            return PostActionJudgmentResult(suppressed_reason="recently_ignored", recovery=recovery, debug=debug)
        payload = candidate.to_dict()
        payload["label"] = f"Next: {candidate.title}"
        self.session_state.set_suggestion_state(
            session_id,
            {
                "key": candidate.key,
                "title": candidate.title,
                "command": candidate.command,
                "shown_at": datetime.now(timezone.utc).isoformat(),
                "ignore_count": 0,
            },
        )
        return PostActionJudgmentResult(next_suggestion=payload, recovery=recovery, debug=debug)

    def _risk_for_request(self, request: ToolRequest) -> ActionRiskTier:
        name = str(request.tool_name or "").strip().lower()
        arguments = request.arguments if isinstance(request.arguments, dict) else {}
        if name == "app_control":
            action = str(arguments.get("action") or "").strip().lower()
            if action == "force_quit":
                return ActionRiskTier.HIGH
            if action in {"close", "quit", "restart"}:
                return ActionRiskTier.CAUTION
            return ActionRiskTier.SAFE
        if name == "trusted_hook_execute":
            return ActionRiskTier.HIGH
        if name in {"maintenance_action", "routine_execute"}:
            return ActionRiskTier.CAUTION
        if name == "repair_action":
            repair_kind = str(arguments.get("repair_kind") or "").strip().lower()
            if repair_kind in {"network_repair", "restart_network_adapter", "restart_explorer", "relaunch_app"}:
                return ActionRiskTier.CAUTION
            return ActionRiskTier.SAFE
        if name == "file_operation":
            operation = str(arguments.get("operation") or "").strip().lower()
            if operation in {"rename_by_date", "move", "copy", "archive", "group_by_type"}:
                return ActionRiskTier.CAUTION
            if operation in {"delete", "remove"}:
                return ActionRiskTier.HIGH
            return ActionRiskTier.SAFE
        return ActionRiskTier.SAFE

    def _suggestion_candidate(
        self,
        *,
        jobs: list[dict[str, Any]],
        active_request_state: dict[str, Any],
    ) -> tuple[SuggestionCandidate | None, bool]:
        latest = jobs[0] if jobs else None
        if not isinstance(latest, dict):
            return None, False
        tool_name = str(latest.get("tool_name") or "").strip().lower()
        arguments = latest.get("arguments") if isinstance(latest.get("arguments"), dict) else {}
        result = latest.get("result") if isinstance(latest.get("result"), dict) else {}

        if tool_name == "app_control" and bool(result.get("success")):
            action = str(arguments.get("action") or result.get("action") or "").strip().lower()
            app_name = self._display_label(arguments.get("app_name") or result.get("process_name") or "app")
            if action == "force_quit":
                normalized = normalize_phrase(app_name)
                return (
                    SuggestionCandidate(
                        key=f"app:relaunch:{normalized}",
                        title=f"Relaunch {app_name}",
                        command=f"relaunch {normalized}",
                        reason="force_quit_follow_up",
                    ),
                    False,
                )

        if tool_name == "desktop_search" and bool(result.get("success")):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            results = data.get("results") if isinstance(data.get("results"), list) else []
            search_action = str(arguments.get("action") or "search").strip().lower()
            if search_action == "search" and results:
                return (
                    SuggestionCandidate(
                        key="search:open_top_result",
                        title="Open it",
                        command="open it",
                        reason="search_follow_up",
                    ),
                    False,
                )
            if search_action == "open" and results:
                kind = str(((results[0] or {}).get("kind") if isinstance(results[0], dict) else "") or "").strip().lower()
                if kind in {"pdf", "markdown", "text", "txt"}:
                    return (
                        SuggestionCandidate(
                            key=f"search:summarize:{kind}",
                            title="Summarize this",
                            command="summarize this",
                            reason="opened_document_follow_up",
                        ),
                        False,
                    )

        if tool_name == "repair_action" and bool(result.get("success")):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            workflow = data.get("workflow") if isinstance(data.get("workflow"), dict) else {}
            kind = str(workflow.get("kind") or arguments.get("repair_kind") or active_request_state.get("subject") or "").strip().lower()
            partial = bool(workflow.get("partial"))
            steps = workflow.get("steps") if isinstance(workflow.get("steps"), list) else []
            if partial:
                failed_titles = [
                    str(step.get("title") or "").strip().lower()
                    for step in steps
                    if isinstance(step, dict) and str(step.get("status") or "").strip().lower() == "failed"
                ]
                if any("network adapter" in title for title in failed_titles):
                    return (
                        SuggestionCandidate(
                            key="repair:device_manager",
                            title="Open Device Manager",
                            command="open device manager",
                            reason="partial_network_repair",
                        ),
                        True,
                    )
            if kind in {"network_repair", "connectivity_checks"}:
                return (
                    SuggestionCandidate(
                        key=f"repair:network_check:{kind}",
                        title="Run a 60-second network check",
                        command="run a 60-second network check",
                        reason="network_follow_up",
                    ),
                    False,
                )
        return None, False

    def _display_label(self, value: Any) -> str:
        normalized = " ".join(str(value or "").replace("_", " ").split()).strip()
        return normalized.title() if normalized else "App"
