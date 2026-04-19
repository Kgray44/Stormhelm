from __future__ import annotations

import asyncio
import json
from typing import Any

from stormhelm.config.models import AppConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.memory.repositories import ConversationRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.providers.base import AssistantProvider, ProviderToolCall
from stormhelm.core.tools.registry import ToolRegistry
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
        self.provider = provider

    async def handle_message(
        self,
        message: str,
        session_id: str = "default",
        *,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
        workspace_context: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        self.conversations.ensure_session(session_id)
        user_message = self.conversations.add_message(
            session_id,
            "user",
            message,
            metadata={
                "surface_mode": surface_mode,
                "active_module": active_module,
                "workspace_context": workspace_context or {},
            },
        )
        routed = self.router.route(message, surface_mode=surface_mode)
        actions: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        assistant_text = routed.assistant_message

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
                    workspace_context=workspace_context,
                )
                if planned.tool_requests:
                    assistant_text, jobs, actions = await self._execute_tool_requests(
                        planned.tool_requests,
                        session_id=session_id,
                        prompt=message,
                        surface_mode=surface_mode,
                        active_module=active_module,
                    )
                    self.session_state.clear_previous_response_id(session_id, role="planner")
                    self.session_state.clear_previous_response_id(session_id, role="reasoner")
                elif planned.assistant_message:
                    assistant_text = self.persona.report(planned.assistant_message)
                elif self.provider is not None and self.config.openai.enabled:
                    assistant_text, jobs, actions = await self._handle_provider_turn(
                        message=message,
                        session_id=session_id,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        workspace_context=workspace_context,
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

        assistant_message = self.conversations.add_message(
            session_id,
            "assistant",
            assistant_text,
            metadata={"actions": actions, "jobs": jobs, "surface_mode": surface_mode, "active_module": active_module},
        )
        self.events.publish(
            level="INFO",
            source="assistant",
            message=f"Handled message in session '{session_id}'.",
            payload={"job_count": len(jobs), "action_count": len(actions), "surface_mode": surface_mode},
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
            elif job.error:
                summaries.append(job.error)

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

    async def _handle_provider_turn(
        self,
        *,
        message: str,
        session_id: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
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
        input_items: str | list[dict[str, Any]] = message
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
                    message=message,
                    jobs=all_jobs,
                    actions=all_actions,
                    workspace_context=resolved_workspace_context,
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
        ]
        return "\n\n".join(part for part in [instructions, "\n".join(dynamic_rules)] if part)

    def _build_reasoning_payload(
        self,
        *,
        message: str,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        workspace_context: dict[str, Any] | None,
    ) -> str:
        payload = {
            "operator_message": message,
            "workspace_context": workspace_context or {},
            "tool_jobs": jobs,
            "actions": actions,
        }
        return json.dumps(payload)

    def _merge_job_summaries(self, completed_jobs: list[dict[str, Any]] | list[Any], summaries: list[str]) -> str:
        cleaned = [summary.strip() for summary in summaries if summary and summary.strip()]
        if cleaned:
            if len(cleaned) == 1:
                return cleaned[0]
            return " | ".join(cleaned)
        if completed_jobs:
            return "Stormhelm completed the requested work."
        return "Standing by."
