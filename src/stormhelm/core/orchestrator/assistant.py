from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlparse

from stormhelm.config.models import AppConfig
from stormhelm.core.calculations import CalculationCallerContext
from stormhelm.core.calculations import CalculationInputOrigin
from stormhelm.core.calculations import CalculationOutputMode
from stormhelm.core.calculations import CalculationRequest
from stormhelm.core.calculations import CalculationResultVisibility
from stormhelm.core.calculations import CalculationsSubsystem
from stormhelm.core.context.service import ActiveContextService
from stormhelm.core.discord_relay import DiscordRelaySubsystem
from stormhelm.core.events import EventBuffer
from stormhelm.core.judgment.service import JudgmentService
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner import PlannerDecision
from stormhelm.core.orchestrator.planner_models import QueryShape
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.screen_awareness import ScreenAwarenessSubsystem
from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.providers.base import AssistantProvider, ProviderToolCall
from stormhelm.core.software_control import SoftwareExecutionStatus
from stormhelm.core.software_control import SoftwareOperationRequest
from stormhelm.core.software_control import SoftwareOperationType
from stormhelm.core.software_control import SoftwareControlSubsystem
from stormhelm.core.software_recovery import SoftwareRecoverySubsystem
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.core.tasks import DurableTaskService
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
        task_service: DurableTaskService | None = None,
        provider: AssistantProvider | None = None,
        calculations: CalculationsSubsystem | None = None,
        software_control: SoftwareControlSubsystem | None = None,
        software_recovery: SoftwareRecoverySubsystem | None = None,
        screen_awareness: ScreenAwarenessSubsystem | None = None,
        discord_relay: DiscordRelaySubsystem | None = None,
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
        self.task_service = task_service
        self._fallback_workspace_service: WorkspaceService | None = None
        self.provider = provider
        self.calculations = calculations
        self.software_control = software_control
        self.software_recovery = software_recovery
        self.screen_awareness = screen_awareness
        self.discord_relay = discord_relay
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
        prompt: str,
        surface_mode: str,
        active_module: str,
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
        task_plan = None
        if self.task_service is not None:
            task_plan = self.task_service.begin_execution(
                session_id=session_id,
                prompt=prompt,
                requests=requests,
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=service.active_workspace_summary(session_id),
            )
        jobs: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        summaries: list[str] = []

        for index, (tool_name, arguments) in enumerate(normalized_requests):
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
                data = (
                    self.task_service.where_we_left_off(session_id=session_id)
                    if self.task_service is not None
                    else None
                ) or service.where_we_left_off(session_id=session_id)
            else:
                data = (
                    self.task_service.next_steps(session_id=session_id)
                    if self.task_service is not None
                    else None
                ) or service.next_steps(session_id=session_id)

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
            if task_plan is not None and index < len(task_plan.step_ids) and self.task_service is not None:
                self.task_service.record_direct_tool_result(
                    task_id=task_plan.task_id,
                    step_id=task_plan.step_ids[index],
                    tool_name=tool_name,
                    arguments=dict(arguments),
                    result={"summary": summary, "data": data} if isinstance(data, dict) else {"summary": summary},
                    success=True,
                )
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
        planner_debug: dict[str, Any] = {}
        planned_decision: PlannerDecision | None = None
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
                    available_tools={
                        tool.name
                        for tool in self.tool_registry.all_tools()
                        if self.config.tools.enabled.is_enabled(tool.name)
                    },
                )
                planned = await self._maybe_apply_browser_search_fallback(
                    planned=planned,
                    message=message,
                    session_id=session_id,
                    surface_mode=surface_mode,
                    active_module=active_module,
                    workspace_context=resolved_workspace_context,
                    active_context=active_context,
                )
                planned_decision = planned
                planner_debug = dict(planned.debug)
                self._publish_calculation_event(
                    session_id=session_id,
                    calculation_debug=planner_debug.get("calculations"),
                )
                self._publish_screen_awareness_event(
                    session_id=session_id,
                    screen_awareness_debug=planner_debug.get("screen_awareness"),
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
                elif (
                    planned.execution_plan is not None
                    and planned.structured_query is not None
                    and planned.structured_query.query_shape == QueryShape.CALCULATION_REQUEST
                    and planned.execution_plan.plan_type == "calculation_evaluate"
                    and self.calculations is not None
                ):
                    calculation_slots = (
                        planned.structured_query.slots if isinstance(planned.structured_query.slots, dict) else {}
                    )
                    calculation_request_payload = (
                        calculation_slots.get("calculation_request")
                        if isinstance(calculation_slots.get("calculation_request"), dict)
                        else {}
                    )
                    requested_mode = str(
                        calculation_request_payload.get("requested_mode")
                        or calculation_slots.get("requested_mode")
                        or CalculationOutputMode.ANSWER_ONLY.value
                    ).strip()
                    try:
                        calculation_mode = CalculationOutputMode(requested_mode)
                    except ValueError:
                        calculation_mode = CalculationOutputMode.ANSWER_ONLY
                    calculation_request = CalculationRequest(
                        request_id=f"calc-{session_id}",
                        source_surface=surface_mode,
                        raw_input=message,
                        user_visible_text=message,
                        extracted_expression=str(calculation_request_payload.get("extracted_expression") or "").strip() or None,
                        requested_mode=calculation_mode,
                        helper_name=str(calculation_request_payload.get("helper_name") or "").strip() or None,
                        arguments=(
                            dict(calculation_request_payload.get("arguments") or {})
                            if isinstance(calculation_request_payload.get("arguments"), dict)
                            else {}
                        ),
                        missing_arguments=(
                            list(calculation_request_payload.get("missing_arguments") or [])
                            if isinstance(calculation_request_payload.get("missing_arguments"), list)
                            else []
                        ),
                        follow_up_reuse=bool(calculation_request_payload.get("follow_up_reuse", False)),
                        verification_claim=str(calculation_request_payload.get("verification_claim") or "").strip() or None,
                        caller=CalculationCallerContext(
                            subsystem="assistant",
                            caller_intent="planner_direct_calculation",
                            input_origin=(
                                CalculationInputOrigin.REUSED_CONTEXT
                                if bool(calculation_request_payload.get("follow_up_reuse", False))
                                else CalculationInputOrigin.USER_TEXT
                            ),
                            visual_extraction_dependency=False,
                            internal_validation=False,
                            result_visibility=CalculationResultVisibility.USER_FACING,
                            reuse_path="assistant_orchestrator.calculation_request",
                            provenance_stack=[
                                "assistant_orchestrator",
                                "recent_context_reuse"
                                if bool(calculation_request_payload.get("follow_up_reuse", False))
                                else "direct_user_request",
                            ],
                        ),
                    )
                    calculation_response = self.calculations.execute(
                        session_id=session_id,
                        active_module=active_module,
                        request=calculation_request,
                    )
                    assistant_text = calculation_response.assistant_response
                    self.active_context_service.remember_resolution(
                        session_id,
                        {
                            "kind": "calculation",
                            "query": message,
                            "result": calculation_response.result.to_dict()
                            if calculation_response.result is not None
                            else None,
                            "failure": calculation_response.failure.to_dict()
                            if calculation_response.failure is not None
                            else None,
                            "trace": calculation_response.trace.to_dict(),
                        },
                    )
                    planned.structured_query.slots["response_contract"] = dict(calculation_response.response_contract)
                    calculation_debug = dict(planner_debug.get("calculations") or {})
                    calculation_debug["trace"] = calculation_response.trace.to_dict()
                    calculation_debug["result"] = (
                        calculation_response.result.to_dict() if calculation_response.result is not None else None
                    )
                    calculation_debug["failure"] = (
                        calculation_response.failure.to_dict() if calculation_response.failure is not None else None
                    )
                    planner_debug["calculations"] = calculation_debug
                    self._publish_calculation_event(
                        session_id=session_id,
                        calculation_debug=calculation_debug,
                    )
                elif (
                    planned.execution_plan is not None
                    and planned.structured_query is not None
                    and planned.structured_query.query_shape == QueryShape.SOFTWARE_CONTROL_REQUEST
                    and planned.execution_plan.plan_type == "software_control_execute"
                    and self.software_control is not None
                ):
                    software_slots = (
                        planned.structured_query.slots if isinstance(planned.structured_query.slots, dict) else {}
                    )
                    operation_value = str(software_slots.get("operation_type") or "install").strip().lower()
                    try:
                        operation_type = SoftwareOperationType(operation_value)
                    except ValueError:
                        operation_type = SoftwareOperationType.INSTALL
                    sensitive_task_id = ""
                    if self.task_service is not None:
                        resolver = getattr(self.task_service, "current_sensitive_task_id", None)
                        if callable(resolver):
                            sensitive_task_id = str(resolver(session_id=session_id) or "").strip()
                    if not sensitive_task_id:
                        sensitive_task_id = str(self.session_state.get_active_task_id(session_id) or "").strip()
                    software_request = SoftwareOperationRequest(
                        request_id=f"software-{session_id}",
                        source_surface=surface_mode,
                        raw_input=message,
                        user_visible_text=message,
                        operation_type=operation_type,
                        target_name=str(software_slots.get("target_name") or "").strip() or "software",
                        request_stage=str(software_slots.get("request_stage") or "prepare_plan").strip() or "prepare_plan",
                        follow_up_reuse=bool(software_slots.get("follow_up_reuse", False)),
                        selected_source_route=str(software_slots.get("selected_source_route") or "").strip() or None,
                        task_id=sensitive_task_id or None,
                        trust_request_id=str(software_slots.get("trust_request_id") or "").strip() or None,
                        approval_scope=str(software_slots.get("approval_scope") or "").strip() or None,
                        approval_outcome=str(software_slots.get("approval_outcome") or "").strip() or None,
                    )
                    software_response = self.software_control.execute_software_operation(
                        session_id=session_id,
                        active_module=active_module,
                        request=software_request,
                    )
                    assistant_text = self.persona.report(software_response.assistant_response)
                    self.active_context_service.remember_resolution(
                        session_id,
                        {
                            "kind": "software_control",
                            "query": message,
                            "result": software_response.result.to_dict()
                            if software_response.result is not None
                            else None,
                            "verification": software_response.verification.to_dict()
                            if software_response.verification is not None
                            else None,
                            "recovery_plan": software_response.recovery_plan.to_dict()
                            if software_response.recovery_plan is not None
                            else None,
                            "recovery_result": software_response.recovery_result.to_dict()
                            if software_response.recovery_result is not None
                            else None,
                            "trace": software_response.trace.to_dict(),
                        },
                    )
                    planned.structured_query.slots["response_contract"] = dict(software_response.response_contract)
                    if software_response.active_request_state is not None:
                        if software_response.active_request_state:
                            self.session_state.set_active_request_state(session_id, software_response.active_request_state)
                        else:
                            self.session_state.clear_active_request_state(session_id)
                    software_debug = dict(planner_debug.get("software_control") or {})
                    software_debug["result"] = (
                        software_response.result.to_dict() if software_response.result is not None else None
                    )
                    software_debug["trace"] = software_response.trace.to_dict()
                    software_debug["verification"] = (
                        software_response.verification.to_dict() if software_response.verification is not None else None
                    )
                    if software_response.recovery_plan is not None:
                        software_debug["recovery_plan"] = software_response.recovery_plan.to_dict()
                    if software_response.recovery_result is not None:
                        software_debug["recovery_result"] = software_response.recovery_result.to_dict()
                    planner_debug["software_control"] = software_debug
                    self._publish_software_control_event(
                        session_id=session_id,
                        software_debug=software_debug,
                    )
                    if software_response.trace.recovery_invoked:
                        self._publish_software_recovery_event(
                            session_id=session_id,
                            recovery_debug=software_debug,
                        )
                elif (
                    planned.execution_plan is not None
                    and planned.structured_query is not None
                    and planned.structured_query.query_shape == QueryShape.SCREEN_AWARENESS_REQUEST
                    and planned.execution_plan.plan_type in {
                        "screen_awareness_analyze",
                        "screen_awareness_act",
                        "screen_awareness_continue",
                        "screen_awareness_workflow",
                        "screen_awareness_brain",
                        "screen_awareness_power",
                    }
                    and self.screen_awareness is not None
                ):
                    screen_debug = planned.structured_query.slots.get("screen_awareness")
                    debug_payload = dict(screen_debug) if isinstance(screen_debug, dict) else {}
                    intent_value = str(
                        debug_payload.get("intent")
                        or planned.structured_query.requested_action
                        or ScreenIntentType.INSPECT_VISIBLE_STATE.value
                    ).strip()
                    try:
                        screen_intent = ScreenIntentType(intent_value)
                    except ValueError:
                        screen_intent = ScreenIntentType.INSPECT_VISIBLE_STATE
                    screen_response = self.screen_awareness.handle_request(
                        session_id=session_id,
                        operator_text=message,
                        intent=screen_intent,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        active_context=active_context,
                        workspace_context=resolved_workspace_context,
                    )
                    assistant_text = self.persona.report(screen_response.assistant_response)
                    self.active_context_service.remember_resolution(
                        session_id,
                        {
                            "kind": "screen_awareness",
                            "intent": screen_intent.value,
                            "query": message,
                            "analysis_result": screen_response.analysis.to_dict(),
                            "telemetry": dict(screen_response.telemetry),
                        },
                    )
                    planned.structured_query.slots["response_contract"] = dict(screen_response.response_contract)
                    if planned.active_request_state:
                        self.session_state.set_active_request_state(session_id, planned.active_request_state)
                    screen_awareness_debug = dict(planner_debug.get("screen_awareness") or {})
                    screen_awareness_debug["analysis_result"] = screen_response.analysis.to_dict()
                    screen_awareness_debug["telemetry"] = dict(screen_response.telemetry)
                    planner_debug["screen_awareness"] = screen_awareness_debug
                    self._publish_screen_awareness_event(
                        session_id=session_id,
                        screen_awareness_debug=screen_awareness_debug,
                    )
                elif (
                    planned.execution_plan is not None
                    and planned.structured_query is not None
                    and planned.structured_query.query_shape == QueryShape.DISCORD_RELAY_REQUEST
                    and planned.execution_plan.plan_type in {"discord_relay_preview", "discord_relay_dispatch"}
                    and self.discord_relay is not None
                ):
                    relay_response = self.discord_relay.handle_request(
                        session_id=session_id,
                        operator_text=message,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        active_context=active_context,
                        workspace_context=resolved_workspace_context,
                        request_slots=planned.structured_query.slots,
                    )
                    assistant_text = self.persona.report(relay_response.assistant_response)
                    self.active_context_service.remember_resolution(
                        session_id,
                        {
                            "kind": "discord_relay",
                            "query": message,
                            "state": relay_response.state.value,
                            "preview": relay_response.preview.to_dict() if relay_response.preview is not None else None,
                            "attempt": relay_response.attempt.to_dict() if relay_response.attempt is not None else None,
                            "trace": relay_response.trace.to_dict() if relay_response.trace is not None else None,
                        },
                    )
                    planned.structured_query.slots["response_contract"] = dict(relay_response.response_contract)
                    if relay_response.active_request_state is not None:
                        if relay_response.active_request_state:
                            self.session_state.set_active_request_state(session_id, relay_response.active_request_state)
                        else:
                            self.session_state.clear_active_request_state(session_id)
                    relay_debug = dict(relay_response.debug)
                    if relay_response.trace is not None:
                        relay_debug["trace"] = relay_response.trace.to_dict()
                    if relay_response.preview is not None:
                        relay_debug["preview"] = relay_response.preview.to_dict()
                    if relay_response.attempt is not None:
                        relay_debug["attempt"] = relay_response.attempt.to_dict()
                    planner_debug["discord_relay"] = relay_debug
                    self._publish_discord_relay_event(
                        session_id=session_id,
                        relay_debug=relay_debug,
                    )
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
                event_family="runtime",
                event_type="runtime.assistant_request_failed",
                severity="warning",
                subsystem="assistant",
                session_id=session_id,
                visibility_scope="ghost_hint",
                retention_class="operator_relevant",
                provenance={"channel": "assistant", "kind": "operator_summary"},
                message="Failed to handle assistant request.",
                payload={"error": str(error), "surface_mode": surface_mode, "active_module": active_module},
            )
            jobs = []
            actions = []

        planner_obedience = self._planner_obedience_metadata(
            planned_decision=planned_decision,
            jobs=jobs,
            actions=actions,
            text=assistant_text,
        )
        if planner_obedience:
            planner_debug.update(
                {
                    "actual_tool_names": list(planner_obedience.get("actual_tool_names") or []),
                    "actual_result_mode": str(planner_obedience.get("actual_result_mode") or ""),
                    "planner_authority": dict(planner_obedience),
                }
            )

        response_metadata = self._build_response_metadata(
            text=assistant_text,
            jobs=jobs,
            actions=actions,
            active_module=active_module,
            judgment=response_judgment,
            planner_obedience=planner_obedience,
            planned_decision=planned_decision,
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
                "planner_debug": planner_debug,
                **response_metadata,
            },
        )
        self.events.publish(
            event_family="runtime",
            event_type="runtime.assistant_response_ready",
            severity="info",
            subsystem="assistant",
            session_id=session_id,
            visibility_scope="internal_only",
            retention_class="bounded_recent",
            provenance={"channel": "assistant", "kind": "operator_summary"},
            message=f"Handled message in session '{session_id}'.",
            payload={
                "job_count": len(jobs),
                "action_count": len(actions),
                "surface_mode": surface_mode,
                "active_module": active_module,
            },
        )
        if planner_obedience:
            self.events.publish(
                event_family="runtime",
                event_type="runtime.planner_obedience_evaluated",
                severity="debug",
                subsystem="planner",
                session_id=session_id,
                visibility_scope="internal_only",
                retention_class="ephemeral",
                provenance={"channel": "planner", "kind": "heuristic_status"},
                message="Verified planner obedience for handled message.",
                payload={
                    "session_id": session_id,
                    "query_shape": str(planner_obedience.get("query_shape", "")),
                    "execution_plan_type": str(planner_obedience.get("execution_plan_type", "")),
                    "planned_tool_names": list(planner_obedience.get("planned_tool_names") or []),
                    "actual_tool_names": list(planner_obedience.get("actual_tool_names") or []),
                    "expected_response_mode": str(planner_obedience.get("expected_response_mode", "")),
                    "actual_result_mode": str(planner_obedience.get("actual_result_mode", "")),
                    "authority_enforced": bool(planner_obedience.get("authority_enforced", False)),
                    "compatibility_shim_used": bool(planner_obedience.get("compatibility_shim_used", False)),
                    "legacy_fallback_used": str(planner_obedience.get("legacy_fallback_used", "")),
                },
            )
        judgment_metadata = response_metadata.get("judgment") if isinstance(response_metadata.get("judgment"), dict) else {}
        next_suggestion = response_metadata.get("next_suggestion") if isinstance(response_metadata.get("next_suggestion"), dict) else {}
        if judgment_metadata or next_suggestion:
            self.events.publish(
                event_family="verification",
                event_type="verification.response_judgment",
                severity="debug",
                subsystem="judgment",
                session_id=session_id,
                visibility_scope="internal_only",
                retention_class="ephemeral",
                provenance={"channel": "judgment", "kind": "subsystem_interpretation"},
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
            "active_request_state": self.session_state.get_active_request_state(session_id),
            "recent_context_resolutions": self.session_state.get_recent_context_resolutions(session_id),
            "active_task": self.task_service.active_task_summary(session_id) if self.task_service is not None else {},
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
            prompt=prompt,
            surface_mode=surface_mode,
            active_module=active_module,
        )
        if direct_workspace_result is not None:
            return direct_workspace_result
        task_plan = None
        if self.task_service is not None:
            task_plan = self.task_service.begin_execution(
                session_id=session_id,
                prompt=prompt,
                requests=requests,
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=self.workspace_service.active_workspace_summary(session_id) if self.workspace_service is not None else {},
            )
        submitted_jobs = await asyncio.gather(
            *[
                self.jobs.submit(
                    request.tool_name if isinstance(request, ToolRequest) else request.name,
                    request.arguments,
                    session_id=session_id,
                    task_id=task_plan.task_id if task_plan is not None else None,
                    task_step_id=task_plan.step_ids[index] if task_plan is not None and index < len(task_plan.step_ids) else None,
                )
                for index, request in enumerate(requests)
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

    async def _maybe_apply_browser_search_fallback(
        self,
        *,
        planned: PlannerDecision,
        message: str,
        session_id: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
        active_context: dict[str, Any] | None,
    ) -> PlannerDecision:
        del session_id, message, surface_mode, active_module, workspace_context, active_context
        if self.provider is None or not self.config.openai.enabled:
            return planned
        if planned.structured_query is None or planned.execution_plan is None:
            return planned
        if planned.structured_query.query_shape.value != "search_browser_destination":
            return planned
        if planned.request_type != "browser_search" or planned.tool_requests:
            return planned
        slots = planned.structured_query.slots if isinstance(planned.structured_query.slots, dict) else {}
        if str(slots.get("browser_search_failure_reason") or "").strip() != "search_provider_unresolved":
            return planned
        if not planned.assistant_message:
            return planned

        provider_phrase = str(
            slots.get("search_provider")
            or slots.get("requested_search_provider_phrase")
            or slots.get("browser_search_request", {}).get("provider_phrase")
            or ""
        ).strip()
        search_query = str(slots.get("search_query") or "").strip()
        browser_target = str(slots.get("browser_preference") or "").strip()
        open_target = str(slots.get("open_target") or "external").strip() or "external"
        fallback_model = self._browser_search_fallback_model()
        fallback_metadata: dict[str, Any] = {
            "attempted": True,
            "used": False,
            "model": fallback_model,
            "provider_phrase": provider_phrase,
        }

        result = await self.provider.generate(
            instructions=(
                "Resolve an unresolved browser-search provider into one credible http or https URL. "
                "Return exactly one browser_search_fallback_resolve function call. "
                "Prefer a native search URL when obvious; otherwise return a Google site: search URL. "
                "If no credible URL can be inferred, return resolved_url as an empty string."
            ),
            input_items=json.dumps(
                {
                    "provider_phrase": provider_phrase,
                    "search_query": search_query,
                    "browser_target": browser_target,
                    "open_target": open_target,
                }
            ),
            previous_response_id=None,
            tools=[self._browser_search_fallback_tool_definition()],
            model=fallback_model,
            max_output_tokens=self.config.openai.planner_max_output_tokens,
        )

        tool_call = next((call for call in result.tool_calls if call.name == "browser_search_fallback_resolve"), None)
        if tool_call is None:
            fallback_metadata["failure"] = "no_tool_call"
            slots["browser_search_fallback"] = fallback_metadata
            self._refresh_planned_debug(planned)
            return planned

        arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
        resolved_url = str(arguments.get("resolved_url") or "").strip()
        if not self._is_http_url(resolved_url):
            fallback_metadata["failure"] = "invalid_url"
            fallback_metadata["reason"] = str(arguments.get("reason") or "").strip()
            slots["browser_search_fallback"] = fallback_metadata
            self._refresh_planned_debug(planned)
            return planned

        title = str(arguments.get("title") or self._default_browser_search_title(provider_phrase)).strip()
        resolution_kind = str(arguments.get("resolution_kind") or "fallback_url").strip() or "fallback_url"
        fallback_provider_phrase = str(arguments.get("provider_phrase") or provider_phrase).strip() or provider_phrase
        reason = str(arguments.get("reason") or "").strip()
        resolver = getattr(self.planner, "_browser_destination_resolver", None)
        if resolver is not None and hasattr(resolver, "response_contract_for_search_title"):
            response_contract = resolver.response_contract_for_search_title(title, open_target=open_target)
        else:
            if open_target == "deck":
                response_contract = {
                    "bearing_title": f"{title} queued",
                    "micro_response": f"Queued {title} for the Deck browser.",
                    "full_response": f"Queued {title} for the Deck browser.",
                }
            else:
                response_contract = {
                    "bearing_title": f"{title} requested",
                    "micro_response": f"Requested that {title} open externally.",
                    "full_response": f"Requested that {title} open externally.",
                }
        tool_name = "deck_open_url" if open_target == "deck" else "external_open_url"
        tool_arguments: dict[str, Any] = {
            "url": resolved_url,
            "label": title,
            "response_contract": dict(response_contract),
        }
        if tool_name == "external_open_url" and browser_target and browser_target != "default":
            tool_arguments["browser_target"] = browser_target

        planned.tool_requests = [ToolRequest(tool_name, dict(tool_arguments))]
        planned.assistant_message = None
        planned.execution_plan.tool_name = tool_name
        planned.execution_plan.tool_arguments = dict(tool_arguments)
        planned.execution_plan.assistant_message = None

        slots["response_contract"] = dict(response_contract)
        slots["browser_open_plan"] = {
            "tool_name": tool_name,
            "tool_arguments": dict(tool_arguments),
            "response_contract": dict(response_contract),
            "open_target": open_target,
        }
        slots["browser_search_fallback"] = {
            **fallback_metadata,
            "used": True,
            "resolution_kind": resolution_kind,
            "provider_phrase": fallback_provider_phrase,
            "resolved_url": resolved_url,
            "reason": reason,
        }

        if hasattr(self.planner, "_active_request_state_from_structured_query"):
            planned.active_request_state = self.planner._active_request_state_from_structured_query(
                planned.structured_query,
                planned.execution_plan,
            )
        self._refresh_planned_debug(planned)
        return planned

    def _browser_search_fallback_model(self) -> str:
        return "gpt-5.4-nano"

    def _browser_search_fallback_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": "browser_search_fallback_resolve",
            "description": "Resolve a browser-search provider phrase into a credible URL to open.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resolved_url": {"type": "string"},
                    "title": {"type": "string"},
                    "resolution_kind": {"type": "string"},
                    "provider_phrase": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["resolved_url", "title", "resolution_kind", "provider_phrase", "reason"],
                "additionalProperties": False,
            },
        }

    def _refresh_planned_debug(self, planned: PlannerDecision) -> None:
        if planned.structured_query is not None:
            planned.debug["structured_query"] = planned.structured_query.to_dict()
        if planned.execution_plan is not None:
            planned.debug["execution_plan"] = planned.execution_plan.to_dict()

    def _default_browser_search_title(self, provider_phrase: str) -> str:
        phrase = " ".join(str(provider_phrase or "").split()).strip()
        if not phrase:
            return "Search"
        if "." in phrase:
            return f"{phrase} search"
        return f"{phrase[:1].upper()}{phrase[1:]} search"

    def _is_http_url(self, candidate: str) -> bool:
        parsed = urlparse(str(candidate or "").strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

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
        planner_obedience: dict[str, Any] | None = None,
        planned_decision: PlannerDecision | None = None,
    ) -> dict[str, Any]:
        planner_contract = self._planner_response_contract(planned_decision)
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
            planner_contract,
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
        action_adapter_contract = action_contract.get("adapter_contract")
        action_adapter_execution = action_contract.get("adapter_execution")
        job_adapter_contract = next(
            (
                (job.get("result") or {}).get("adapter_contract")
                for job in jobs
                if isinstance(job, dict)
                and isinstance(job.get("result"), dict)
                and isinstance((job.get("result") or {}).get("adapter_contract"), dict)
            ),
            {},
        )
        job_adapter_execution = next(
            (
                (job.get("result") or {}).get("adapter_execution")
                for job in jobs
                if isinstance(job, dict)
                and isinstance(job.get("result"), dict)
                and isinstance((job.get("result") or {}).get("adapter_execution"), dict)
            ),
            {},
        )
        if isinstance(action_adapter_contract, dict):
            metadata["adapter_contract"] = dict(action_adapter_contract)
        elif isinstance(job_adapter_contract, dict) and job_adapter_contract:
            metadata["adapter_contract"] = dict(job_adapter_contract)
        elif (
            planned_decision is not None
            and planned_decision.capability_plan is not None
            and isinstance(planned_decision.capability_plan.selected_adapter, dict)
        ):
            metadata["adapter_contract"] = dict(planned_decision.capability_plan.selected_adapter)
        if isinstance(action_adapter_execution, dict):
            metadata["adapter_execution"] = dict(action_adapter_execution)
        elif isinstance(job_adapter_execution, dict) and job_adapter_execution:
            metadata["adapter_execution"] = dict(job_adapter_execution)
        elif (
            planned_decision is not None
            and planned_decision.capability_plan is not None
            and planned_decision.capability_plan.max_claimable_outcome
        ):
            metadata["adapter_execution"] = {
                "claim_ceiling": planned_decision.capability_plan.max_claimable_outcome,
                "approval_required": planned_decision.capability_plan.approval_required,
                "preview_required": False,
                "rollback_available": planned_decision.capability_plan.rollback_available,
            }
        if (
            planned_decision is not None
            and planned_decision.capability_plan is not None
            and planned_decision.capability_plan.candidate_adapters
        ):
            metadata["candidate_adapters"] = list(planned_decision.capability_plan.candidate_adapters)
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
        if planner_obedience:
            metadata["planner_obedience"] = dict(planner_obedience)
        return metadata

    def _publish_screen_awareness_event(
        self,
        *,
        session_id: str,
        screen_awareness_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.screen_awareness is not None:
            debug_events_enabled = self.screen_awareness.config.debug_events_enabled
        elif hasattr(self.config, "screen_awareness"):
            debug_events_enabled = bool(self.config.screen_awareness.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(screen_awareness_debug, dict) or not screen_awareness_debug.get("candidate"):
            return
        disposition = str(screen_awareness_debug.get("disposition") or "").strip()
        message = "Screen-awareness request detected."
        if disposition == "phase0_scaffold":
            message = "Screen-awareness request routed to the Phase 0 scaffold."
        elif disposition == "phase1_analyze":
            message = "Screen-awareness request routed to Phase 1 observe-and-describe analysis."
        elif disposition == "phase2_ground":
            message = "Screen-awareness request routed to Phase 2 grounding and disambiguation."
        elif disposition == "phase3_guide":
            message = "Screen-awareness request routed to Phase 3 guided navigation."
        elif disposition == "phase4_verify":
            message = "Screen-awareness request routed to Phase 4 verification and change intelligence."
        elif disposition == "phase5_act":
            message = "Screen-awareness request routed to Phase 5 direct UI action execution."
        elif disposition == "phase6_continue":
            message = "Screen-awareness request routed to Phase 6 workflow continuity and recovery."
        elif disposition == "phase8_problem_solve":
            message = "Screen-awareness request routed to Phase 8 problem solving and teaching."
        elif disposition == "phase9_workflow_reuse":
            message = "Screen-awareness request routed to Phase 9 workflow learning and reuse."
        elif disposition == "phase10_brain_integration":
            message = "Screen-awareness request routed to Phase 10 brain integration and long-term intelligence."
        elif disposition == "phase11_power":
            message = "Screen-awareness request routed to Phase 11 multi-monitor, accessibility, and power features."
        elif disposition in {"feature_disabled", "routing_disabled"}:
            message = "Screen-awareness request detected but not activated."
        self.events.publish(
            event_family="screen_awareness",
            event_type=f"screen_awareness.{disposition or 'routed'}",
            severity="debug",
            subsystem="screen_awareness",
            session_id=session_id,
            visibility_scope="deck_context",
            retention_class="bounded_recent",
            provenance={"channel": "screen_awareness", "kind": "subsystem_interpretation"},
            message=message,
            payload={
                "session_id": session_id,
                "disposition": disposition,
                "intent": str(screen_awareness_debug.get("intent") or ""),
                "route_confidence": float(screen_awareness_debug.get("route_confidence") or 0.0),
                "feature_enabled": bool(screen_awareness_debug.get("feature_enabled", False)),
                "planner_routing_enabled": bool(screen_awareness_debug.get("planner_routing_enabled", False)),
                "input_signals": dict(screen_awareness_debug.get("input_signals") or {})
                if isinstance(screen_awareness_debug.get("input_signals"), dict)
                else {},
                "analysis_result": dict(screen_awareness_debug.get("analysis_result") or {})
                if isinstance(screen_awareness_debug.get("analysis_result"), dict)
                else {},
                "telemetry": dict(screen_awareness_debug.get("telemetry") or {})
                if isinstance(screen_awareness_debug.get("telemetry"), dict)
                else {},
            },
        )

    def _publish_software_control_event(
        self,
        *,
        session_id: str,
        software_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.software_control is not None:
            debug_events_enabled = self.software_control.config.debug_events_enabled
        elif hasattr(self.config, "software_control"):
            debug_events_enabled = bool(self.config.software_control.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(software_debug, dict) or not software_debug.get("candidate"):
            return
        result = software_debug.get("result") if isinstance(software_debug.get("result"), dict) else {}
        trace = software_debug.get("trace") if isinstance(software_debug.get("trace"), dict) else {}
        self.events.publish(
            event_family="tool",
            event_type="tool.software_control_routed",
            severity="debug",
            subsystem="software_control",
            session_id=session_id,
            visibility_scope="internal_only",
            retention_class="ephemeral",
            provenance={"channel": "software_control", "kind": "subsystem_interpretation"},
            message="Software-control request handled.",
            payload={
                "session_id": session_id,
                "operation_type": str(software_debug.get("operation_type") or ""),
                "target_name": str(software_debug.get("target_name") or ""),
                "status": str((result.get("status") or trace.get("execution_status") or "")).strip(),
                "route_selected": str(trace.get("route_selected") or ""),
                "recovery_invoked": bool(trace.get("recovery_invoked", False)),
                "trace": dict(trace),
            },
        )

    def _publish_software_recovery_event(
        self,
        *,
        session_id: str,
        recovery_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.software_recovery is not None:
            debug_events_enabled = self.software_recovery.config.debug_events_enabled
        elif hasattr(self.config, "software_recovery"):
            debug_events_enabled = bool(self.config.software_recovery.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(recovery_debug, dict):
            return
        recovery_plan = recovery_debug.get("recovery_plan") if isinstance(recovery_debug.get("recovery_plan"), dict) else {}
        recovery_result = recovery_debug.get("recovery_result") if isinstance(recovery_debug.get("recovery_result"), dict) else {}
        if not recovery_plan and not recovery_result:
            return
        self.events.publish(
            event_family="runtime",
            event_type="runtime.software_recovery_engaged",
            severity="debug",
            subsystem="software_recovery",
            session_id=session_id,
            visibility_scope="internal_only",
            retention_class="ephemeral",
            provenance={"channel": "software_recovery", "kind": "subsystem_interpretation"},
            message="Software recovery route engaged.",
            payload={
                "session_id": session_id,
                "failure_category": str((recovery_plan.get("failure_category") or recovery_debug.get("failure_category") or "")).strip(),
                "cloud_fallback_disposition": str(recovery_plan.get("cloud_fallback_disposition") or "").strip(),
                "route_switched_to": str(recovery_result.get("route_switched_to") or "").strip(),
                "recovery_plan": dict(recovery_plan),
                "recovery_result": dict(recovery_result),
            },
        )

    def _publish_discord_relay_event(
        self,
        *,
        session_id: str,
        relay_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.discord_relay is not None:
            debug_events_enabled = self.discord_relay.config.debug_events_enabled
        elif hasattr(self.config, "discord_relay"):
            debug_events_enabled = bool(self.config.discord_relay.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(relay_debug, dict):
            return
        trace = relay_debug.get("trace") if isinstance(relay_debug.get("trace"), dict) else {}
        preview = relay_debug.get("preview") if isinstance(relay_debug.get("preview"), dict) else {}
        attempt = relay_debug.get("attempt") if isinstance(relay_debug.get("attempt"), dict) else {}
        if not trace and not preview and not attempt:
            return
        self.events.publish(
            event_family="discord_relay",
            event_type=f"discord_relay.{str((attempt.get('state') or trace.get('state') or 'updated')).strip().lower() or 'updated'}",
            severity="debug",
            subsystem="discord_relay",
            session_id=session_id,
            visibility_scope="deck_context",
            retention_class="bounded_recent",
            provenance={"channel": "discord_relay", "kind": "subsystem_interpretation"},
            message="Discord relay request handled.",
            payload={
                "session_id": session_id,
                "state": str((attempt.get("state") or trace.get("state") or "")).strip(),
                "route_mode": str((attempt.get("route_mode") or preview.get("route_mode") or trace.get("route_mode") or "")).strip(),
                "payload_kind": str((preview.get("payload") or {}).get("kind") if isinstance(preview.get("payload"), dict) else trace.get("payload_kind") or "").strip(),
                "destination_alias": str((preview.get("destination") or {}).get("alias") if isinstance(preview.get("destination"), dict) else trace.get("destination_alias") or "").strip(),
                "preview": dict(preview),
                "attempt": dict(attempt),
            },
        )

    def _publish_calculation_event(
        self,
        *,
        session_id: str,
        calculation_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.calculations is not None:
            debug_events_enabled = self.calculations.config.debug_events_enabled
        elif hasattr(self.config, "calculations"):
            debug_events_enabled = bool(self.config.calculations.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(calculation_debug, dict) or not calculation_debug.get("candidate"):
            return
        trace = calculation_debug.get("trace") if isinstance(calculation_debug.get("trace"), dict) else {}
        failure = calculation_debug.get("failure") if isinstance(calculation_debug.get("failure"), dict) else {}
        message = "Calculation request detected."
        if trace.get("parse_success") is True and trace.get("result"):
            message = "Calculation request resolved through the deterministic local lane."
        elif failure:
            message = "Calculation request failed honestly in the deterministic local lane."
        self.events.publish(
            event_family="verification",
            event_type=(
                "verification.calculation_succeeded"
                if trace.get("parse_success") is True and trace.get("result")
                else "verification.calculation_failed"
                if failure
                else "verification.calculation_detected"
            ),
            severity="debug",
            subsystem="calculations",
            session_id=session_id,
            visibility_scope="deck_context",
            retention_class="bounded_recent",
            provenance={"channel": "calculations", "kind": "subsystem_interpretation"},
            message=message,
            payload={
                "session_id": session_id,
                "disposition": str(calculation_debug.get("disposition") or ""),
                "route_confidence": float(calculation_debug.get("route_confidence") or 0.0),
                "extracted_expression": str(calculation_debug.get("extracted_expression") or ""),
                "trace": dict(trace),
                "failure": dict(failure),
                "result": dict(calculation_debug.get("result") or {})
                if isinstance(calculation_debug.get("result"), dict)
                else {},
            },
        )

    def _planner_response_contract(self, planned_decision: PlannerDecision | None) -> dict[str, Any]:
        if planned_decision is None or planned_decision.structured_query is None:
            return {}
        slots = planned_decision.structured_query.slots if isinstance(planned_decision.structured_query.slots, dict) else {}
        if planned_decision.unsupported_reason is not None:
            contract = slots.get("unsupported_response_contract")
            if isinstance(contract, dict):
                return dict(contract)
        contract = slots.get("response_contract")
        if isinstance(contract, dict):
            return dict(contract)
        return {}

    def _planner_obedience_metadata(
        self,
        *,
        planned_decision: PlannerDecision | None,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        text: str,
    ) -> dict[str, Any]:
        if planned_decision is None:
            return {}
        planned_tool_names = [request.tool_name for request in planned_decision.tool_requests]
        actual_tool_names = [
            str(job.get("tool_name", "")).strip()
            for job in jobs
            if isinstance(job, dict) and str(job.get("tool_name", "")).strip()
        ]
        expected_response_mode = str(planned_decision.response_mode or "").strip()
        actual_result_mode = self._actual_result_mode(
            planned_decision=planned_decision,
            jobs=jobs,
            actions=actions,
            text=text,
        )
        legacy_fallback = ""
        semantic_debug = planned_decision.debug.get("semantic_parse_proposal") if isinstance(planned_decision.debug, dict) else {}
        if isinstance(semantic_debug, dict):
            legacy_fallback = str(semantic_debug.get("fallback_path") or "").strip()
        compatibility_shim_used = bool(
            planned_decision.execution_plan is not None and planned_decision.execution_plan.plan_type == "compatibility_shim"
        )
        tool_dispatch_match = planned_tool_names == actual_tool_names if (planned_tool_names or actual_tool_names) else True
        response_mode_match = expected_response_mode == actual_result_mode if expected_response_mode else not actual_result_mode

        final_result_type = "assistant_message"
        if actual_tool_names:
            final_result_type = "tool_result"
        if expected_response_mode == "unsupported":
            final_result_type = "unsupported"
        elif expected_response_mode == "clarification":
            final_result_type = "clarification"
        elif expected_response_mode == "workspace_result":
            final_result_type = "workspace_result"
        elif expected_response_mode == "search_result":
            final_result_type = "search_result"
        elif expected_response_mode == "action_result":
            final_result_type = "action_result"
        elif expected_response_mode == "calculation_result":
            final_result_type = "calculation_result"
        elif expected_response_mode in {"numeric_metric", "status_summary", "identity_summary", "diagnostic_summary", "history_summary", "forecast_summary"}:
            final_result_type = expected_response_mode

        return {
            "query_shape": planned_decision.structured_query.query_shape.value if planned_decision.structured_query is not None else "",
            "execution_plan_type": str(planned_decision.execution_plan.plan_type if planned_decision.execution_plan is not None else ""),
            "planned_tool_names": planned_tool_names,
            "actual_tool_names": actual_tool_names,
            "expected_response_mode": expected_response_mode,
            "actual_result_mode": actual_result_mode,
            "final_result_type": final_result_type,
            "tool_dispatch_match": tool_dispatch_match,
            "response_mode_match": response_mode_match,
            "authority_enforced": tool_dispatch_match and response_mode_match,
            "compatibility_shim_used": compatibility_shim_used,
            "legacy_fallback_used": legacy_fallback,
        }

    def _actual_result_mode(
        self,
        *,
        planned_decision: PlannerDecision,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        text: str,
    ) -> str:
        del actions, text
        if not jobs:
            return str(planned_decision.response_mode or "").strip()
        primary_job = jobs[0] if isinstance(jobs[0], dict) else {}
        tool_name = str(primary_job.get("tool_name", "")).strip().lower()
        arguments = primary_job.get("arguments") if isinstance(primary_job.get("arguments"), dict) else {}

        if tool_name in {"network_status", "power_status", "storage_status", "location_status", "saved_locations", "active_apps", "recent_files"}:
            return "status_summary"
        if tool_name == "network_throughput":
            return "numeric_metric"
        if tool_name == "machine_status":
            focus = str(arguments.get("focus", "")).strip().lower()
            return "identity_summary" if focus == "identity" else "status_summary"
        if tool_name in {"network_diagnosis", "power_diagnosis", "resource_diagnosis", "storage_diagnosis"}:
            return str(planned_decision.response_mode or "diagnostic_summary")
        if tool_name == "resource_status":
            query_kind = str(arguments.get("query_kind", "")).strip().lower()
            if query_kind == "identity":
                return "identity_summary"
            if query_kind == "diagnostic":
                return "diagnostic_summary"
            return "numeric_metric"
        if tool_name == "weather_current":
            return str(planned_decision.response_mode or "forecast_summary")
        if tool_name == "desktop_search":
            return "search_result"
        if tool_name in {
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
        }:
            return "workspace_result"
        if tool_name in {
            "app_control",
            "window_control",
            "system_control",
            "workflow_execute",
            "repair_action",
            "routine_execute",
            "routine_save",
            "trusted_hook_execute",
            "trusted_hook_register",
            "maintenance_action",
            "file_operation",
            "browser_context",
            "activity_summary",
            "context_action",
            "save_location",
            "external_open_url",
            "deck_open_url",
            "external_open_file",
            "deck_open_file",
        }:
            return str(planned_decision.response_mode or "action_result")
        return str(planned_decision.response_mode or "").strip()

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
                "network_throughput": "Network",
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
