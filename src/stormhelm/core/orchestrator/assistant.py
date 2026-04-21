from __future__ import annotations

import asyncio
import json
from typing import Any

from stormhelm.config.models import AppConfig
from stormhelm.core.context.service import ActiveContextService
from stormhelm.core.events import EventBuffer
from stormhelm.core.judgment.service import JudgmentService
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.providers.base import AssistantProvider, ProviderToolCall
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService


class AssistantOrchestrator:
    def __init__(
        self,
        *,
        config: AppConfig,
        conversations: ConversationRepository,
        jobs: JobManager,
        router: IntentRouter,
        events: EventBuffer,
        tool_registry: ToolRegistry,
        session_state: ConversationStateStore,
        planner: DeterministicPlanner,
        persona: PersonaContract,
        workspace_service: WorkspaceService | None = None,
        provider: AssistantProvider | None = None,
    ) -> None:
        self.config = config
        self.conversations = conversations
        self.jobs = jobs
        self.router = router
        self.events = events
        self.tool_registry = tool_registry
        self.session_state = session_state
        self.planner = planner
        self.persona = persona
        self.workspace_service = workspace_service
        self._fallback_workspace_service: WorkspaceService | None = None
        self.provider = provider
        self.active_context_service = ActiveContextService(session_state)
        self.judgment = JudgmentService(config=config, session_state=session_state)

    def _workspace_service_for_tools(self) -> WorkspaceService:
        if self.workspace_service is not None:
            return self.workspace_service
        if self._fallback_workspace_service is None:
            database = SQLiteDatabase(self.config.storage.database_path)
            database.initialize()
            self._fallback_workspace_service = WorkspaceService(
                config=self.config,
                repository=WorkspaceRepository(database),
                notes=NotesRepository(database),
                conversations=ConversationRepository(database),
                preferences=PreferencesRepository(database),
                session_state=self.session_state,
                indexer=WorkspaceIndexer(self.config),
                events=self.events,
                persona=self.persona,
            )
        return self._fallback_workspace_service

    async def _maybe_execute_workspace_requests_directly(
        self,
        requests: list[ToolRequest] | list[ProviderToolCall],
        *,
        session_id: str,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]] | None:
        normalized_requests = [
            (
                request.tool_name if isinstance(request, ToolRequest) else request.name,
                request.arguments,
            )
            for request in requests
        ]
        workspace_tools = {
            "workspace_restore",
            "workspace_assemble",
            "workspace_save",
            "workspace_clear",
            "workspace_archive",
            "workspace_rename",
            "workspace_tag",
            "workspace_list",
            "workspace_where_left_off",
            "workspace_next_steps",
        }
        if not normalized_requests or any(tool_name not in workspace_tools for tool_name, _ in normalized_requests):
            return None

        service = self._workspace_service_for_tools()
        jobs: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        summaries: list[str] = []

        for tool_name, arguments in normalized_requests:
            arguments = dict(arguments)
            if tool_name == "workspace_restore":
                data = service.restore_workspace(str(arguments.get("query", "")), session_id=session_id)
            elif tool_name == "workspace_assemble":
                data = service.assemble_workspace(str(arguments.get("query", "")), session_id=session_id)
            elif tool_name == "workspace_save":
                data = service.save_workspace(session_id=session_id)
            elif tool_name == "workspace_clear":
                data = service.clear_workspace(session_id=session_id)
            elif tool_name == "workspace_archive":
                data = service.archive_workspace(session_id=session_id, query=str(arguments.get("query", "")) or None)
            elif tool_name == "workspace_rename":
                data = service.rename_workspace(session_id=session_id, new_name=str(arguments.get("new_name", "")))
            elif tool_name == "workspace_tag":
                tags = arguments.get("tags", [])
                data = service.tag_workspace(session_id=session_id, tags=list(tags) if isinstance(tags, list) else [])
            elif tool_name == "workspace_list":
                data = service.list_workspaces(
                    session_id=session_id,
                    query=str(arguments.get("query", "")),
                    include_archived=bool(arguments.get("include_archived", False)),
                    archived_only=bool(arguments.get("archived_only", False)),
                )
            elif tool_name == "workspace_where_left_off":
                data = service.where_we_left_off(session_id=session_id)
            else:
                data = service.next_steps(session_id=session_id)

            summary = str(data.get("summary", "")).strip() if isinstance(data, dict) else ""
            if summary:
                summaries.append(summary)
            if isinstance(data, dict):
                action = data.get("action")
                if isinstance(action, dict):
                    actions.append(action)
                action_list = data.get("actions")
                if isinstance(action_list, list):
                    actions.extend(item for item in action_list if isinstance(item, dict))
            jobs.append(
                {
                    "job_id": f"direct-{tool_name}",
                    "tool_name": tool_name,
                    "arguments": dict(arguments),
                    "status": "completed",
                    "created_at": "",
                    "started_at": "",
                    "finished_at": "",
                    "result": {
                        "summary": summary,
                        "data": data,
                    },
                    "error": "",
                }
            )
            self.session_state.remember_tool_result(
                session_id,
                tool_name=tool_name,
                arguments=dict(arguments),
                result={"summary": summary, "data": data},
                captured_at="",
            )

        assistant_text = self.persona.report(self._merge_job_summaries([], summaries))
        return assistant_text, jobs, actions

    async def handle_message(
        self,
        message: str,
        session_id: str = "default",
        *,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
        workspace_context: dict[str, Any] | None = None,
        input_context: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        self.conversations.ensure_session(session_id)
        self.judgment.observe_operator_turn(session_id, message)
        if self.workspace_service is not None:
            self.workspace_service.capture_workspace_context(
                session_id=session_id,
                prompt=message,
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=workspace_context,
            )
        user_message = self.conversations.add_message(
            session_id,
            "user",
            message,
            metadata={
                "surface_mode": surface_mode,
                "active_module": active_module,
                "workspace_context": workspace_context or {},
                "input_context": input_context or {},
            },
        )
        routed = self.router.route(message, surface_mode=surface_mode)
        actions: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        assistant_text = routed.assistant_message
        resolved_workspace_context = workspace_context or (
            self.workspace_service.active_workspace_summary(session_id) if self.workspace_service is not None else {}
        )
        active_posture = self.session_state.get_active_posture(session_id)
        active_request_state = self.session_state.get_active_request_state(session_id)
        recent_tool_results = self.session_state.get_recent_tool_results(session_id, max_age_seconds=900)
        learned_preferences = self.session_state.get_learned_preferences()
        active_context = self.active_context_service.update_from_turn(
            session_id=session_id,
            workspace_context=resolved_workspace_context,
            active_posture=active_posture,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
            input_context=input_context,
        )
        response_judgment: dict[str, Any] = {}

        try:
            if routed.tool_calls:
                assistant_text, jobs, actions = await self._execute_tool_requests(
                    routed.tool_calls,
                    session_id=session_id,
                    prompt=message,
                    surface_mode=surface_mode,
                    active_module=active_module,
                )
                self.session_state.clear_previous_response_id(session_id, role="planner")
                self.session_state.clear_previous_response_id(session_id, role="reasoner")
            elif assistant_text is not None:
                assistant_text = self.persona.report(assistant_text)
            else:
                planned = self.planner.plan(
                    message,
                    session_id=session_id,
                    surface_mode=surface_mode,
                    active_module=active_module,
                    workspace_context=resolved_workspace_context,
                    active_posture=active_posture,
                    active_request_state=active_request_state,
                    recent_tool_results=recent_tool_results,
                    learned_preferences=learned_preferences,
                    active_context=active_context,
                )
                if planned.tool_requests:
                    pre_action = self.judgment.assess_pre_action(
                        session_id=session_id,
                        message=message,
                        tool_requests=planned.tool_requests,
                        active_context=active_context,
                    )
                    assistant_text, jobs, actions = await self._execute_tool_requests(
                        planned.tool_requests,
                        session_id=session_id,
                        prompt=message,
                        surface_mode=surface_mode,
                        active_module=active_module,
                    )
                    post_action = self.judgment.evaluate_post_action(
                        session_id=session_id,
                        message=message,
                        jobs=jobs,
                        actions=actions,
                        active_context=active_context,
                        active_request_state=planned.active_request_state,
                        pre_action=pre_action,
                    )
                    response_judgment = {
                        "risk_tier": pre_action.risk_tier.value,
                        "decision": pre_action.outcome,
                        "debug": dict(post_action.debug),
                    }
                    if post_action.suppressed_reason:
                        response_judgment["suppressed_reason"] = post_action.suppressed_reason
                    if post_action.next_suggestion is not None:
                        response_judgment["next_suggestion"] = dict(post_action.next_suggestion)
                    if post_action.recovery:
                        response_judgment["recovery"] = True
                    if planned.active_request_state:
                        self.session_state.set_active_request_state(session_id, planned.active_request_state)
                        self._learn_from_message(session_id=session_id, message=message, request_state=planned.active_request_state)
                    if self.provider is not None and self.config.openai.enabled and self.planner.should_escalate(
                        message,
                        tool_job_count=len(jobs),
                        actions=actions,
                        planner_text=assistant_text,
                        request_type=planned.request_type,
                        requires_reasoner=planned.requires_reasoner,
                    ):
                        assistant_text = await self._run_reasoner_summary(
                            message=message,
                            session_id=session_id,
                            surface_mode=surface_mode,
                            active_module=active_module,
                            workspace_context=resolved_workspace_context,
                            active_context=active_context,
                            jobs=jobs,
                            actions=actions,
                        )
                    self.session_state.clear_previous_response_id(session_id, role="planner")
                    self.session_state.clear_previous_response_id(session_id, role="reasoner")
                elif planned.assistant_message:
                    if planned.active_request_state:
                        self.session_state.set_active_request_state(session_id, planned.active_request_state)
                        self._learn_from_message(session_id=session_id, message=message, request_state=planned.active_request_state)
                    assistant_text = self.persona.report(planned.assistant_message)
                elif self.provider is not None and self.config.openai.enabled:
                    assistant_text, jobs, actions = await self._handle_provider_turn(
                        message=message,
                        session_id=session_id,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        workspace_context=resolved_workspace_context,
                        active_context=active_context,
                    )
                else:
                    assistant_text = self.persona.report(
                        "OpenAI integration is not configured. Set OPENAI_API_KEY in .env or your environment "
                        "and enable [openai].enabled for natural-language assistance, or use explicit safe commands "
                        "like /time, /battery, /storage, /open, or /recent."
                    )
        except Exception as error:
            assistant_text = self.persona.error(str(error))
            self.events.publish(
                level="WARNING",
                source="assistant",
                message="Failed to handle assistant request.",
                payload={"error": str(error), "surface_mode": surface_mode, "active_module": active_module},
            )
            jobs = []
            actions = []

        response_metadata = self._build_response_metadata(
            text=assistant_text,
            jobs=jobs,
            actions=actions,
            active_module=active_module,
            judgment=response_judgment,
        )
        assistant_message = self.conversations.add_message(
            session_id,
            "assistant",
            assistant_text,
            metadata={
                "actions": actions,
                "jobs": jobs,
                "surface_mode": surface_mode,
                "active_module": active_module,
                **response_metadata,
            },
        )
        self.events.publish(
            level="INFO",
            source="assistant",
            message=f"Handled message in session '{session_id}'.",
            payload={"job_count": len(jobs), "action_count": len(actions), "surface_mode": surface_mode},
        )
        judgment_metadata = response_metadata.get("judgment") if isinstance(response_metadata.get("judgment"), dict) else {}
        next_suggestion = response_metadata.get("next_suggestion") if isinstance(response_metadata.get("next_suggestion"), dict) else {}
        if judgment_metadata or next_suggestion:
            self.events.publish(
                level="DEBUG",
                source="judgment",
                message="Evaluated post-action judgment.",
                payload={
                    "session_id": session_id,
                    "risk_tier": str(judgment_metadata.get("risk_tier", "")),
                    "decision": str(judgment_metadata.get("decision", "")),
                    "suppressed_reason": str(judgment_metadata.get("suppressed_reason", "")),
                    "next_suggestion": dict(next_suggestion),
                },
            )
        return {
            "session_id": session_id,
            "user_message": user_message.to_dict(),
            "assistant_message": assistant_message.to_dict(),
            "job": jobs[0] if jobs else None,
            "jobs": jobs,
            "actions": actions,
        }

    async def _execute_tool_requests(
        self,
        requests: list[ToolRequest] | list[ProviderToolCall],
        *,
        session_id: str,
        prompt: str,
        surface_mode: str,
        active_module: str,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        direct_workspace_result = await self._maybe_execute_workspace_requests_directly(
            requests,
            session_id=session_id,
        )
        if direct_workspace_result is not None:
            return direct_workspace_result
        submitted_jobs = await asyncio.gather(
            *[
                self.jobs.submit(
                    request.tool_name if isinstance(request, ToolRequest) else request.name,
                    request.arguments,
                )
                for request in requests
            ]
        )
        completed_jobs = await asyncio.gather(*[self.jobs.wait(job.job_id) for job in submitted_jobs])
        actions: list[dict[str, Any]] = []
        summaries: list[str] = []

        for job in completed_jobs:
            if isinstance(job.result, dict):
                summaries.append(str(job.result.get("summary") or ""))
                data = job.result.get("data")
                if isinstance(data, dict):
                    action = data.get("action")
                    if isinstance(action, dict):
                        actions.append(action)
                    action_list = data.get("actions")
                    if isinstance(action_list, list):
                        actions.extend(item for item in action_list if isinstance(item, dict))
            elif job.error:
                summaries.append(job.error)

            if isinstance(job.result, dict):
                self.session_state.remember_tool_result(
                    session_id,
                    tool_name=job.tool_name,
                    arguments=job.arguments,
                    result=job.result,
                    captured_at=job.finished_at or job.created_at,
                )

        if self.workspace_service is not None:
            self.workspace_service.remember_actions(
                session_id=session_id,
                prompt=prompt,
                actions=actions,
                surface_mode=surface_mode,
                active_module=active_module,
            )
        assistant_text = self.persona.report(self._merge_job_summaries(completed_jobs, summaries))
        return assistant_text, [job.to_dict() for job in completed_jobs], actions

    async def _run_reasoner_summary(
        self,
        *,
        message: str,
        session_id: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
        active_context: dict[str, Any] | None,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> str:
        if self.provider is None or not self.config.openai.enabled:
            return self.persona.report(self._merge_job_summaries([], [action.get("type", "") for action in actions]))
        reasoning_response = await self.provider.generate(
            instructions=self._build_provider_instructions(
                role="reasoner",
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=workspace_context,
            ),
            input_items=self._build_reasoning_payload(
                session_id=session_id,
                message=message,
                jobs=jobs,
                actions=actions,
                workspace_context=workspace_context,
                active_context=active_context,
            ),
            previous_response_id=self.session_state.get_previous_response_id(session_id, role="reasoner"),
            tools=[],
            model=self.config.openai.reasoning_model,
            max_output_tokens=self.config.openai.reasoning_max_output_tokens,
        )
        if reasoning_response.response_id:
            self.session_state.set_previous_response_id(session_id, reasoning_response.response_id, role="reasoner")
        if reasoning_response.output_text:
            return self.persona.report(reasoning_response.output_text)
        return self.persona.report(self._merge_job_summaries([], [action.get("type", "") for action in actions]))

    async def _handle_provider_turn(
        self,
        *,
        message: str,
        session_id: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
        active_context: dict[str, Any] | None,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        tool_definitions = [
            tool.response_tool_definition()
            for tool in self.tool_registry.all_tools()
            if self.config.tools.enabled.is_enabled(tool.name)
        ]
        resolved_workspace_context = workspace_context or (
            self.workspace_service.active_workspace_summary(session_id) if self.workspace_service is not None else {}
        )
        instructions = self._build_provider_instructions(
            role="planner",
            surface_mode=surface_mode,
            active_module=active_module,
            workspace_context=resolved_workspace_context,
        )
        previous_response_id = self.session_state.get_previous_response_id(session_id, role="planner")
        input_items: str | list[dict[str, Any]] = self._build_provider_input_items(
            session_id=session_id,
            message=message,
            active_context=active_context,
        )
        all_actions: list[dict[str, Any]] = []
        all_jobs: list[dict[str, Any]] = []
        final_text = ""
        latest_response_id = previous_response_id

        for _ in range(max(1, self.config.openai.max_tool_rounds)):
            result = await self.provider.generate(
                instructions=instructions,
                input_items=input_items,
                previous_response_id=previous_response_id,
                tools=tool_definitions,
                model=self.config.openai.planner_model,
                max_output_tokens=self.config.openai.planner_max_output_tokens,
            )
            latest_response_id = result.response_id or latest_response_id
            if result.output_text:
                final_text = result.output_text

            if not result.tool_calls:
                break

            tool_text, jobs, actions = await self._execute_tool_requests(
                result.tool_calls,
                session_id=session_id,
                prompt=message,
                surface_mode=surface_mode,
                active_module=active_module,
            )
            all_jobs.extend(jobs)
            all_actions.extend(actions)
            input_items = [
                {
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": json.dumps(job.get("result") or {"success": False, "error": job.get("error", "unknown_tool_failure")}),
                }
                for tool_call, job in zip(result.tool_calls, jobs, strict=False)
            ]
            previous_response_id = result.response_id
            if not final_text:
                final_text = tool_text
        else:
            if not final_text:
                final_text = self.persona.report("Stormhelm reached the current tool round limit before finalizing a response.")

        self.session_state.set_previous_response_id(session_id, latest_response_id, role="planner")
        if self.planner.should_escalate(message, tool_job_count=len(all_jobs), actions=all_actions, planner_text=final_text):
            reasoning_response = await self.provider.generate(
                instructions=self._build_provider_instructions(
                    role="reasoner",
                    surface_mode=surface_mode,
                    active_module=active_module,
                    workspace_context=resolved_workspace_context,
                ),
                input_items=self._build_reasoning_payload(
                    session_id=session_id,
                    message=message,
                    jobs=all_jobs,
                    actions=all_actions,
                    workspace_context=resolved_workspace_context,
                    active_context=active_context,
                ),
                previous_response_id=self.session_state.get_previous_response_id(session_id, role="reasoner"),
                tools=[],
                model=self.config.openai.reasoning_model,
                max_output_tokens=self.config.openai.reasoning_max_output_tokens,
            )
            if reasoning_response.response_id:
                self.session_state.set_previous_response_id(
                    session_id,
                    reasoning_response.response_id,
                    role="reasoner",
                )
            if reasoning_response.output_text:
                final_text = reasoning_response.output_text
        if not final_text:
            final_text = self._merge_job_summaries([], [action.get("type", "") for action in all_actions]) or "Standing by."
        return self.persona.report(final_text), all_jobs, all_actions

    def _build_provider_instructions(
        self,
        *,
        role: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
    ) -> str:
        instructions = self.persona.build_provider_instructions(
            role=role,
            surface_mode=surface_mode,
            active_module=active_module,
            workspace_context=workspace_context,
        )
        dynamic_rules = [
            "Use deck_open_url and deck_open_file when the operator explicitly asks to open content inside Stormhelm or when the current surface is Deck.",
            "Use external_open_url and external_open_file when Ghost is active unless the operator explicitly asks for internal Deck viewing.",
            "Stormhelm's own bounded 8-worker scheduler is the authority for concurrency, timeouts, cancellation, and result merging.",
            "You may request multiple specialized tools in one response when that materially improves the result.",
            "Keep visible replies concise and information-dense.",
        ]
        return "\n\n".join(part for part in [instructions, "\n".join(dynamic_rules)] if part)

    def _build_reasoning_payload(
        self,
        *,
        session_id: str,
        message: str,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        workspace_context: dict[str, Any] | None,
        active_context: dict[str, Any] | None,
    ) -> str:
        payload = {
            "previous_user_message": self._previous_user_message(session_id=session_id, current_message=message),
            "operator_message": message,
            "workspace_context": workspace_context or {},
            "active_context": active_context or {},
            "tool_jobs": jobs,
            "actions": actions,
        }
        return json.dumps(payload)

    def _build_provider_input_items(
        self,
        *,
        session_id: str,
        message: str,
        active_context: dict[str, Any] | None,
    ) -> str | list[dict[str, Any]]:
        current_message = (message or "").strip()
        previous_user_message = self._previous_user_message(session_id=session_id, current_message=current_message)
        context_items = self._build_context_input_items(active_context)
        if not previous_user_message and not context_items:
            return current_message
        items: list[dict[str, Any]] = []
        if previous_user_message:
            items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Previous user message: {previous_user_message}",
                        }
                    ],
                }
            )
        items.extend(context_items)
        items.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": current_message,
                    }
                ],
            }
        )
        return items

    def _build_context_input_items(self, active_context: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(active_context, dict):
            return []
        items: list[dict[str, Any]] = []
        for source_name in ("selection", "clipboard"):
            descriptor = active_context.get(source_name)
            if not isinstance(descriptor, dict):
                continue
            value = descriptor.get("value")
            if value in (None, ""):
                continue
            kind = str(descriptor.get("kind") or "text").strip() or "text"
            items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Resolved context source: {source_name} ({kind})\n{value}",
                        }
                    ],
                }
            )
        return items

    def _previous_user_message(self, *, session_id: str, current_message: str) -> str | None:
        list_messages = getattr(self.conversations, "list_messages", None)
        if not callable(list_messages):
            return None
        try:
            messages = list_messages(session_id=session_id, limit=8)
        except Exception:
            return None
        user_messages: list[str] = []
        for record in messages:
            role = getattr(record, "role", None)
            content = getattr(record, "content", None)
            if role != "user":
                continue
            normalized = " ".join(str(content or "").split()).strip()
            if normalized:
                user_messages.append(normalized)
        if not user_messages:
            return None
        current_normalized = " ".join(current_message.split()).strip()
        if len(user_messages) >= 2 and user_messages[-1] == current_normalized:
            return user_messages[-2]
        if user_messages[-1] != current_normalized:
            return user_messages[-1]
        return None

    def _merge_job_summaries(self, completed_jobs: list[dict[str, Any]] | list[Any], summaries: list[str]) -> str:
        cleaned = [summary.strip() for summary in summaries if summary and summary.strip()]
        if cleaned:
            if len(cleaned) == 1:
                return cleaned[0]
            return " ".join(cleaned[:2])
        if completed_jobs:
            return "Stormhelm completed the requested work."
        return "Standing by."

    def _build_response_metadata(
        self,
        *,
        text: str,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        active_module: str,
        judgment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action_contract = next(
            (
                action
                for action in actions
                if isinstance(action, dict)
                and (
                    action.get("bearing_title")
                    or action.get("micro_response")
                    or action.get("full_response")
                )
            ),
            {},
        )
        full_response = str(action_contract.get("full_response") or self.persona.report(text)).strip()
        metadata: dict[str, Any] = {
            "bearing_title": str(
                action_contract.get("bearing_title")
                or self._bearing_title(jobs=jobs, actions=actions, active_module=active_module, text=full_response)
            ).strip(),
            "micro_response": str(action_contract.get("micro_response") or self._micro_response(full_response)).strip(),
            "full_response": full_response,
        }
        judgment = judgment or {}
        next_suggestion = judgment.get("next_suggestion")
        if isinstance(next_suggestion, dict):
            metadata["next_suggestion"] = dict(next_suggestion)
        if judgment:
            metadata["judgment"] = {
                "risk_tier": str(judgment.get("risk_tier", "")),
                "decision": str(judgment.get("decision", "")),
                "suppressed_reason": str(judgment.get("suppressed_reason", "")),
                "recovery": bool(judgment.get("recovery", False)),
                "debug": dict(judgment.get("debug") or {}) if isinstance(judgment.get("debug"), dict) else {},
            }
        return metadata

    def _micro_response(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return "Standing by."
        stop = len(cleaned)
        for marker in (". ", "! ", "? "):
            index = cleaned.find(marker)
            if index != -1:
                stop = min(stop, index + 1)
        micro = cleaned[:stop].strip()
        if len(micro) > 96:
            micro = micro[:95].rstrip(" ,;:") + "…"
        return micro or cleaned[:96]

    def _bearing_title(
        self,
        *,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        active_module: str,
        text: str,
    ) -> str:
        tool_name = str(jobs[0].get("tool_name", "")).strip().lower() if jobs else ""
        action_type = str(actions[0].get("type", "")).strip().lower() if actions else ""
        if tool_name or action_type:
            title_map = {
                "power_status": "Power",
                "power_projection": "Power",
                "power_diagnosis": "Power",
                "machine_status": "Machine",
                "resource_status": "Resources",
                "resource_diagnosis": "Resources",
                "storage_status": "Storage",
                "storage_diagnosis": "Storage",
                "network_status": "Network",
                "network_diagnosis": "Network",
                "weather_current": "Weather",
                "location_status": "Location",
                "saved_locations": "Location",
                "save_location": "Location",
                "active_apps": "Applications",
                "browser_context": "Browser",
                "activity_summary": "Activity",
                "app_control": "Applications",
                "context_action": "Context",
                "desktop_search": "Search",
                "workflow_execute": "Workflow",
                "repair_action": "Repair",
                "routine_execute": "Routine",
                "routine_save": "Routine",
                "trusted_hook_register": "Hook",
                "trusted_hook_execute": "Hook",
                "file_operation": "Files",
                "maintenance_action": "Maintenance",
                "recent_files": "Files",
                "workspace_restore": "Workspace",
                "workspace_assemble": "Workspace",
                "workspace_save": "Workspace",
                "workspace_clear": "Workspace",
                "workspace_archive": "Workspace",
                "workspace_rename": "Workspace",
                "workspace_tag": "Workspace",
                "workspace_list": "Workspace",
                "workspace_where_left_off": "Workspace",
                "workspace_next_steps": "Workspace",
                "workspace_open": "Reference",
                "workspace_focus": "Systems" if active_module == "systems" else "Deck",
                "open_external": "External",
            }
            title = title_map.get(tool_name) or title_map.get(action_type)
            if title:
                return title
        lowered = text.lower()
        if "weather" in lowered or "forecast" in lowered:
            return "Weather"
        if "battery" in lowered or "power" in lowered:
            return "Power"
        if "network" in lowered or "wi-fi" in lowered or "wifi" in lowered:
            return "Network"
        if "workspace" in lowered:
            return "Workspace"
        if "location" in lowered:
            return "Location"
        if active_module == "systems":
            return "Systems"
        return "Bearing"

    def _learn_from_message(
        self,
        *,
        session_id: str,
        message: str,
        request_state: dict[str, Any],
    ) -> None:
        lower = normalize_phrase(message)
        family = str(request_state.get("family") or "").strip().lower()
        if family not in {"weather", "location"} and not any(token in lower for token in {"weather", "forecast", "location"}):
            return
        open_target = self._explicit_open_target(lower)
        if open_target is not None:
            self.session_state.remember_preference("weather", "open_target", open_target)
        location_mode = self._explicit_location_mode(lower)
        if location_mode is not None:
            self.session_state.remember_preference("weather", "location_mode", location_mode)

    def _explicit_open_target(self, lower: str) -> str | None:
        if any(phrase in lower for phrase in {"do not open", "don't open", "just answer", "without opening"}):
            return "none"
        if any(phrase in lower for phrase in {"in the deck", "inside the deck", "show it in the deck", "show it internally"}):
            return "deck"
        if any(phrase in lower for phrase in {"open externally", "open it externally", "in the browser"}):
            return "external"
        return None

    def _explicit_location_mode(self, lower: str) -> str | None:
        if any(token in lower for token in {"use my home location", "home location", "saved home"}):
            return "home"
        if any(token in lower for token in {"use my current location", "current location"}):
            return "current"
        return None
