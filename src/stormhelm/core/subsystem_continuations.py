from __future__ import annotations

import inspect
import asyncio
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from time import perf_counter
from typing import TYPE_CHECKING
from typing import Any
from typing import Awaitable
from typing import Callable
from uuid import uuid4

from stormhelm.core.events import EventBuffer
from stormhelm.core.latency import safe_latency_value
from stormhelm.shared.time import utc_now_iso

if TYPE_CHECKING:
    from stormhelm.core.tools.base import ToolContext


ContinuationHandler = Callable[
    ["SubsystemContinuationRequest", "ToolContext"],
    "SubsystemContinuationResult | dict[str, Any] | Awaitable[SubsystemContinuationResult | dict[str, Any]]",
]


INLINE_OPERATION_KINDS = {
    "calculations.evaluate",
    "trust_approval.bind",
    "trust_approvals.bind",
    "voice.stop_speaking",
    "voice_control.stop_speaking",
    "playback.stop",
    "browser.open_url",
    "browser_destination.open_url",
    "clarification.request",
    "workspace.clear",
    "workspace.save",
    "workspace.archive",
    "workspace.rename",
    "workspace.tag",
    "workspace.list",
    "workspace.where_left_off",
    "workspace.next_steps",
    "software_control.plan_operation",
    "discord_relay.preview",
    "screen_awareness.clarify_target",
}

CONTINUATION_OPERATION_KINDS = {
    "software_control.execute_approved_operation",
    "software_control.verify_operation",
    "software_recovery.run_recovery_plan",
    "discord_relay.dispatch_approved_preview",
    "screen_awareness.verify_change",
    "screen_awareness.run_action",
    "screen_awareness.run_workflow",
    "workspace.assemble_deep",
    "workspace.restore_deep",
    "network.run_live_diagnosis",
}

COMPLETED_STATES = {"completed", "completed_unverified", "verified"}
VERIFIED_STATES = {"verified"}


@dataclass(frozen=True, slots=True)
class SubsystemContinuationPolicy:
    route_family: str
    subsystem: str
    operation_kind: str
    worker_continuation_expected: bool
    reason: str
    worker_lane: str = "normal"
    priority_level: str = "normal"
    background_ok: bool = False
    approval_required_before_worker: bool = False
    verification_required: bool = False
    inline_required: bool = False
    async_conversion_missing_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return safe_latency_value(asdict(self))


@dataclass(frozen=True, slots=True)
class SubsystemContinuationHandlerStatus:
    operation_kind: str
    route_family: str
    subsystem: str
    implemented: bool
    worker_lane: str = "normal"
    priority_level: str = "normal"
    requires_approval: bool = False
    requires_fresh_binding: bool = False
    supports_progress: bool = True
    supports_cancellation: bool = False
    supports_verification: bool = False
    safe_for_background: bool = False
    max_runtime_ms: int = 30_000
    redaction_policy: str = "safe_latency_value"
    missing_reason: str = ""
    handler_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return safe_latency_value(asdict(self))


@dataclass(slots=True)
class SubsystemContinuationRequest:
    continuation_id: str
    route_family: str
    subsystem: str
    operation_kind: str
    stage: str = "queued"
    request_id: str = ""
    session_id: str = "default"
    task_id: str = ""
    job_id: str = ""
    latency_trace_id: str = ""
    source_surface: str = ""
    active_module: str = ""
    result_state: str = "queued"
    approval_state: str = "not_required"
    verification_required: bool = False
    verification_state: str = "not_verified"
    worker_lane: str = "normal"
    priority_level: str = "normal"
    payload_summary: dict[str, Any] = field(default_factory=dict)
    payload_ref: str = ""
    plan_ref: str = ""
    operator_text_preview: str = ""
    trust_scope_id: str = ""
    preview_fingerprint: str = ""
    freshness_warnings: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    completion_claimed: bool = False
    verification_claimed: bool = False

    @classmethod
    def create(
        cls,
        *,
        route_family: str,
        subsystem: str,
        operation_kind: str,
        continuation_id: str | None = None,
        **kwargs: Any,
    ) -> "SubsystemContinuationRequest":
        return cls(
            continuation_id=continuation_id or f"subcont-{uuid4().hex}",
            route_family=str(route_family or "unknown"),
            subsystem=str(subsystem or "unknown"),
            operation_kind=str(operation_kind or "unknown"),
            **kwargs,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SubsystemContinuationRequest":
        allowed = set(cls.__dataclass_fields__)
        values = {key: value for key, value in dict(payload).items() if key in allowed}
        if "continuation_id" not in values:
            values["continuation_id"] = f"subcont-{uuid4().hex}"
        if "route_family" not in values:
            values["route_family"] = "unknown"
        if "subsystem" not in values:
            values["subsystem"] = "unknown"
        if "operation_kind" not in values:
            values["operation_kind"] = "unknown"
        return cls(**values)

    def with_job(self, *, job_id: str) -> "SubsystemContinuationRequest":
        values = asdict(self)
        values["job_id"] = str(job_id or "")
        return SubsystemContinuationRequest(**values)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["completion_claimed"] = False
        payload["verification_claimed"] = False
        return safe_latency_value(payload)


@dataclass(slots=True)
class SubsystemContinuationResult:
    continuation_id: str
    route_family: str
    subsystem: str
    operation_kind: str
    status: str
    result_state: str
    verification_state: str
    summary: str
    stage: str = ""
    request_id: str = ""
    session_id: str = "default"
    task_id: str = ""
    job_id: str = ""
    latency_trace_id: str = ""
    worker_lane: str = "normal"
    priority_level: str = "normal"
    queue_wait_ms: float = 0.0
    run_ms: float = 0.0
    total_ms: float = 0.0
    progress_event_count: int = 0
    completion_claimed: bool = False
    verification_claimed: bool = False
    result_summary: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    warnings: list[str] = field(default_factory=list)
    subsystem_continuation_handler: str = ""
    subsystem_continuation_handler_implemented: bool = False
    subsystem_continuation_handler_missing_reason: str = ""
    continuation_progress_stages: list[str] = field(default_factory=list)
    continuation_verification_required: bool = False
    continuation_verification_attempted: bool = False
    continuation_verification_evidence_count: int = 0
    continuation_result_limitations: list[str] = field(default_factory=list)
    continuation_truth_clamps_applied: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SubsystemContinuationResult":
        allowed = set(cls.__dataclass_fields__)
        values = {key: value for key, value in dict(payload).items() if key in allowed}
        for key in (
            "continuation_id",
            "route_family",
            "subsystem",
            "operation_kind",
            "status",
            "result_state",
            "verification_state",
            "summary",
        ):
            values.setdefault(key, "")
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        result_state = str(payload.get("result_state") or "")
        verification_state = str(payload.get("verification_state") or "")
        payload["completion_claimed"] = bool(payload.get("completion_claimed")) and result_state in COMPLETED_STATES
        payload["verification_claimed"] = (
            bool(payload.get("verification_claimed"))
            and result_state in VERIFIED_STATES
            and verification_state == "verified"
        )
        return safe_latency_value(payload)


def _handler_status_for(
    *,
    operation_kind: str,
    implemented: bool,
    route_family: str | None = None,
    subsystem: str | None = None,
    worker_lane: str = "normal",
    priority_level: str = "normal",
    requires_approval: bool | None = None,
    requires_fresh_binding: bool = False,
    supports_progress: bool = True,
    supports_cancellation: bool = False,
    supports_verification: bool | None = None,
    safe_for_background: bool = False,
    max_runtime_ms: int = 30_000,
    redaction_policy: str = "safe_latency_value",
    missing_reason: str = "",
    handler_name: str = "",
) -> SubsystemContinuationHandlerStatus:
    operation = str(operation_kind or "").strip()
    resolved_route = str(route_family or _route_family_for_operation(operation)).strip() or "unknown"
    resolved_subsystem = str(subsystem or _subsystem_for_operation(operation)).strip() or resolved_route
    approval_required = bool(
        requires_approval
        if requires_approval is not None
        else operation in {"software_control.execute_approved_operation", "discord_relay.dispatch_approved_preview"}
    )
    verification = bool(
        supports_verification
        if supports_verification is not None
        else operation
        in {
            "software_control.verify_operation",
            "software_recovery.run_recovery_plan",
            "discord_relay.dispatch_approved_preview",
            "screen_awareness.verify_change",
            "network.run_live_diagnosis",
        }
    )
    return SubsystemContinuationHandlerStatus(
        operation_kind=operation,
        route_family=resolved_route,
        subsystem=resolved_subsystem,
        implemented=bool(implemented),
        worker_lane=worker_lane,
        priority_level=priority_level,
        requires_approval=approval_required,
        requires_fresh_binding=bool(requires_fresh_binding),
        supports_progress=bool(supports_progress),
        supports_cancellation=bool(supports_cancellation),
        supports_verification=verification,
        safe_for_background=bool(safe_for_background),
        max_runtime_ms=int(max_runtime_ms or 0),
        redaction_policy=redaction_policy,
        missing_reason="" if implemented else (missing_reason or "not_wired_l43"),
        handler_name=handler_name or operation,
    )


def _route_family_for_operation(operation_kind: str) -> str:
    if operation_kind.startswith("workspace."):
        return "workspace_operations"
    return operation_kind.split(".", 1)[0] if "." in operation_kind else "unknown"


def _subsystem_for_operation(operation_kind: str) -> str:
    return operation_kind.split(".", 1)[0] if "." in operation_kind else "unknown"


class SubsystemContinuationRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ContinuationHandler] = {}
        self._statuses: dict[str, SubsystemContinuationHandlerStatus] = {}

    def register(
        self,
        operation_kind: str,
        handler: ContinuationHandler,
        *,
        status: SubsystemContinuationHandlerStatus | None = None,
        **metadata: Any,
    ) -> None:
        key = str(operation_kind or "").strip()
        if not key:
            raise ValueError("operation_kind is required")
        self._handlers[key] = handler
        self._statuses[key] = status or _handler_status_for(
            operation_kind=key,
            implemented=True,
            handler_name=getattr(handler, "__name__", handler.__class__.__name__),
            **metadata,
        )

    def get(self, operation_kind: str) -> ContinuationHandler | None:
        return self._handlers.get(str(operation_kind or "").strip())

    def has_handler(self, operation_kind: str) -> bool:
        return self.get(operation_kind) is not None

    def operation_kinds(self) -> list[str]:
        return sorted(self._handlers)

    def describe(self, operation_kind: str) -> dict[str, Any]:
        key = str(operation_kind or "").strip()
        status = self._statuses.get(key)
        if status is None:
            status = _handler_status_for(
                operation_kind=key,
                implemented=False,
                missing_reason="handler_not_registered",
            )
        return status.to_dict()

    def describe_all(self) -> list[dict[str, Any]]:
        keys = set(CONTINUATION_OPERATION_KINDS) | set(self._statuses)
        return [self.describe(key) for key in sorted(keys)]


class SubsystemContinuationRunner:
    def __init__(self, *, registry: SubsystemContinuationRegistry | None = None, events: EventBuffer | None = None) -> None:
        self.registry = registry or default_subsystem_continuation_registry()
        self.events = events

    async def run(
        self,
        request: SubsystemContinuationRequest,
        context: ToolContext,
    ) -> SubsystemContinuationResult:
        started = perf_counter()
        active_request = request.with_job(job_id=context.job_id)
        self._publish(
            "subsystem.continuation.started",
            active_request,
            message=f"Started subsystem continuation {active_request.continuation_id}.",
        )
        handler = self.registry.get(active_request.operation_kind)
        handler_status = self.registry.describe(active_request.operation_kind)
        if handler is None:
            result = SubsystemContinuationResult(
                continuation_id=active_request.continuation_id,
                request_id=active_request.request_id,
                session_id=active_request.session_id,
                task_id=active_request.task_id,
                job_id=context.job_id,
                latency_trace_id=active_request.latency_trace_id,
                route_family=active_request.route_family,
                subsystem=active_request.subsystem,
                operation_kind=active_request.operation_kind,
                stage="blocked",
                status="blocked",
                result_state="blocked",
                verification_state=active_request.verification_state,
                summary="Continuation handler is unavailable.",
                worker_lane=active_request.worker_lane,
                priority_level=active_request.priority_level,
                run_ms=_elapsed_ms(started),
                total_ms=_elapsed_ms(started),
                error_code="handler_unavailable",
                error_message="No subsystem continuation handler is registered for this operation.",
                subsystem_continuation_handler=str(handler_status.get("handler_name") or active_request.operation_kind),
                subsystem_continuation_handler_implemented=False,
                subsystem_continuation_handler_missing_reason=str(
                    handler_status.get("missing_reason") or "handler_unavailable"
                ),
                continuation_verification_required=active_request.verification_required,
                continuation_truth_clamps_applied=["handler_unavailable"],
            )
            self._publish_result(result)
            return result

        try:
            handler_result = handler(active_request, context)
            if inspect.isawaitable(handler_result):
                handler_result = await handler_result
            result = _coerce_result(handler_result, request=active_request, context=context)
            _apply_handler_status(result, handler_status)
            result.run_ms = result.run_ms or _elapsed_ms(started)
            result.total_ms = result.total_ms or result.run_ms
            self._publish_result(result)
            return result
        except Exception as error:
            result = SubsystemContinuationResult(
                continuation_id=active_request.continuation_id,
                request_id=active_request.request_id,
                session_id=active_request.session_id,
                task_id=active_request.task_id,
                job_id=context.job_id,
                latency_trace_id=active_request.latency_trace_id,
                route_family=active_request.route_family,
                subsystem=active_request.subsystem,
                operation_kind=active_request.operation_kind,
                stage="failed",
                status="failed",
                result_state="failed",
                verification_state=active_request.verification_state,
                summary="Continuation failed before verified completion.",
                worker_lane=active_request.worker_lane,
                priority_level=active_request.priority_level,
                run_ms=_elapsed_ms(started),
                total_ms=_elapsed_ms(started),
                error_code="continuation_exception",
                error_message=str(error),
                subsystem_continuation_handler=str(handler_status.get("handler_name") or active_request.operation_kind),
                subsystem_continuation_handler_implemented=bool(handler_status.get("implemented")),
                subsystem_continuation_handler_missing_reason="",
                continuation_verification_required=active_request.verification_required,
                continuation_truth_clamps_applied=["exception_prevented_verified_completion"],
            )
            self._publish_result(result)
            return result

    def _publish(self, event_type: str, request: SubsystemContinuationRequest, *, message: str) -> None:
        if self.events is None:
            return
        self.events.publish(
            event_family="runtime",
            event_type=event_type,
            severity="info",
            subsystem=request.subsystem or "subsystem_continuation",
            session_id=request.session_id,
            subject=request.continuation_id,
            visibility_scope="watch_surface",
            retention_class="bounded_recent",
            provenance={"channel": "subsystem_continuation", "kind": "direct_system_fact"},
            message=message,
            payload=request.to_dict(),
        )

    def _publish_result(self, result: SubsystemContinuationResult) -> None:
        if self.events is None:
            return
        result_payload = result.to_dict()
        state = str(result_payload.get("result_state") or result_payload.get("status") or "progress")
        if state == "completed_unverified":
            event_type = "subsystem.continuation.completed_unverified"
        elif state == "verified":
            event_type = "subsystem.continuation.verified"
        elif state in {"failed", "blocked", "cancelled"}:
            event_type = f"subsystem.continuation.{state}"
        else:
            event_type = "subsystem.continuation.progress"
        self.events.publish(
            event_family="runtime",
            event_type=event_type,
            severity="info" if state not in {"failed", "blocked"} else "warning",
            subsystem=result.subsystem or "subsystem_continuation",
            session_id=result.session_id,
            subject=result.continuation_id,
            visibility_scope="watch_surface",
            retention_class="bounded_recent",
            provenance={"channel": "subsystem_continuation", "kind": "direct_system_fact"},
            message=str(result.summary or "Subsystem continuation updated."),
            payload=result_payload,
        )


def classify_subsystem_continuation(
    *,
    route_family: str,
    subsystem: str = "",
    operation_kind: str = "",
    approved: bool = False,
    verification_required: bool | None = None,
) -> SubsystemContinuationPolicy:
    route = str(route_family or "").strip() or "unknown"
    resolved_subsystem = str(subsystem or route).strip() or route
    operation = str(operation_kind or "").strip()
    if operation in INLINE_OPERATION_KINDS:
        return SubsystemContinuationPolicy(
            route_family=route,
            subsystem=resolved_subsystem,
            operation_kind=operation,
            worker_continuation_expected=False,
            reason="cheap_or_authority_stage_stays_inline",
            inline_required=True,
        )
    if operation in CONTINUATION_OPERATION_KINDS:
        needs_approval = operation in {
            "software_control.execute_approved_operation",
            "discord_relay.dispatch_approved_preview",
            "screen_awareness.run_action",
            "screen_awareness.run_workflow",
        }
        if needs_approval and not approved:
            return SubsystemContinuationPolicy(
                route_family=route,
                subsystem=resolved_subsystem,
                operation_kind=operation,
                worker_continuation_expected=False,
                reason="approval_required_before_worker",
                approval_required_before_worker=True,
                inline_required=True,
                async_conversion_missing_reason="approval_required",
                verification_required=bool(verification_required),
            )
        return SubsystemContinuationPolicy(
            route_family=route,
            subsystem=resolved_subsystem,
            operation_kind=operation,
            worker_continuation_expected=True,
            reason="slow_external_or_verification_back_half",
            worker_lane="normal",
            priority_level="normal",
            approval_required_before_worker=needs_approval,
            verification_required=bool(
                verification_required
                if verification_required is not None
                else operation
                in {
                    "software_control.verify_operation",
                    "screen_awareness.verify_change",
                    "screen_awareness.run_action",
                    "screen_awareness.run_workflow",
                    "network.run_live_diagnosis",
                }
            ),
        )
    return SubsystemContinuationPolicy(
        route_family=route,
        subsystem=resolved_subsystem,
        operation_kind=operation,
        worker_continuation_expected=False,
        reason="no_continuation_policy",
        inline_required=True,
        async_conversion_missing_reason="unsupported_operation",
    )


def default_subsystem_continuation_registry() -> SubsystemContinuationRegistry:
    registry = SubsystemContinuationRegistry()
    registry.register(
        "workspace.assemble_deep",
        _run_workspace_assemble,
        supports_verification=False,
    )
    registry.register(
        "workspace.restore_deep",
        _run_workspace_restore,
        supports_verification=False,
    )
    registry.register(
        "software_control.verify_operation",
        _run_software_verify_operation,
        route_family="software_control",
        subsystem="software_control",
        supports_verification=True,
        max_runtime_ms=20_000,
    )
    registry.register(
        "software_recovery.run_recovery_plan",
        _run_software_recovery_plan,
        route_family="software_recovery",
        subsystem="software_recovery",
        supports_verification=True,
        max_runtime_ms=25_000,
    )
    registry.register(
        "discord_relay.dispatch_approved_preview",
        _run_discord_dispatch_approved_preview,
        route_family="discord_relay",
        subsystem="discord_relay",
        requires_approval=True,
        requires_fresh_binding=True,
        supports_verification=True,
        max_runtime_ms=30_000,
    )
    registry.register(
        "network.run_live_diagnosis",
        _run_network_live_diagnosis,
        route_family="network",
        subsystem="network",
        supports_verification=True,
        max_runtime_ms=20_000,
    )
    return registry


async def _run_workspace_assemble(
    request: SubsystemContinuationRequest,
    context: ToolContext,
) -> SubsystemContinuationResult:
    service = context.workspace_service
    if service is None:
        return _blocked_result(
            request,
            context=context,
            error_code="workspace_service_unavailable",
            summary="Workspace service is unavailable for the continuation.",
        )
    context.report_progress(_progress_payload(request, "running", "Assembling workspace."))
    await asyncio.sleep(0)
    query = str(request.payload_summary.get("query") or request.operator_text_preview or "")
    compact = bool(request.payload_summary.get("compact", True))
    data = await _maybe_async(lambda: service.assemble_workspace(query, session_id=request.session_id, compact=compact))
    summary = str(data.get("summary") or "Workspace assembly completed but is not separately verified.") if isinstance(data, dict) else "Workspace assembly completed but is not separately verified."
    return SubsystemContinuationResult(
        continuation_id=request.continuation_id,
        request_id=request.request_id,
        session_id=request.session_id,
        task_id=request.task_id,
        job_id=context.job_id,
        latency_trace_id=request.latency_trace_id,
        route_family=request.route_family,
        subsystem=request.subsystem,
        operation_kind=request.operation_kind,
        stage="completed_unverified",
        status="completed",
        result_state="completed_unverified",
        verification_state="not_verified",
        summary=summary,
        worker_lane=request.worker_lane,
        priority_level=request.priority_level,
        progress_event_count=1,
        completion_claimed=True,
        verification_claimed=False,
        result_summary={"data": data} if isinstance(data, dict) else {},
    )


async def _run_workspace_restore(
    request: SubsystemContinuationRequest,
    context: ToolContext,
) -> SubsystemContinuationResult:
    service = context.workspace_service
    if service is None:
        return _blocked_result(
            request,
            context=context,
            error_code="workspace_service_unavailable",
            summary="Workspace service is unavailable for the continuation.",
        )
    context.report_progress(_progress_payload(request, "running", "Restoring workspace."))
    await asyncio.sleep(0)
    query = str(request.payload_summary.get("query") or request.operator_text_preview or "")
    compact = bool(request.payload_summary.get("compact", True))
    data = await _maybe_async(lambda: service.restore_workspace(query, session_id=request.session_id, compact=compact))
    summary = str(data.get("summary") or "Workspace restore completed but is not separately verified.") if isinstance(data, dict) else "Workspace restore completed but is not separately verified."
    return SubsystemContinuationResult(
        continuation_id=request.continuation_id,
        request_id=request.request_id,
        session_id=request.session_id,
        task_id=request.task_id,
        job_id=context.job_id,
        latency_trace_id=request.latency_trace_id,
        route_family=request.route_family,
        subsystem=request.subsystem,
        operation_kind=request.operation_kind,
        stage="completed_unverified",
        status="completed",
        result_state="completed_unverified",
        verification_state="not_verified",
        summary=summary,
        worker_lane=request.worker_lane,
        priority_level=request.priority_level,
        progress_event_count=1,
        completion_claimed=True,
        verification_claimed=False,
        result_summary={"data": data} if isinstance(data, dict) else {},
    )


async def _run_software_verify_operation(
    request: SubsystemContinuationRequest,
    context: ToolContext,
) -> SubsystemContinuationResult:
    service = getattr(context, "software_control", None)
    if service is None:
        return _blocked_result(
            request,
            context=context,
            error_code="software_control_unavailable",
            summary="Software control is unavailable for the verification continuation.",
            truth_clamps=["service_unavailable"],
        )
    _report_progress(request, context, "resolving_target", "Resolving software verification target.")
    await asyncio.sleep(0)
    payload = dict(request.payload_summary or {})
    target_name = str(payload.get("target_name") or payload.get("target") or request.operator_text_preview or "").strip()
    if not target_name:
        return _blocked_result(
            request,
            context=context,
            error_code="software_target_missing",
            summary="Software verification needs a resolved target from the inline planner.",
            truth_clamps=["missing_resolved_target"],
        )
    _report_progress(request, context, "checking_install_state", "Checking local software install state.")
    response_payload: dict[str, Any]
    if callable(getattr(service, "execute_software_operation", None)):
        response_payload = await _maybe_async(
            lambda: service.execute_software_operation(
                session_id=request.session_id,
                active_module=request.active_module or request.source_surface or "ghost",
                request=_software_verification_request(request, target_name),
            )
        )
        response_payload = _as_dict(response_payload)
    elif callable(getattr(service, "verify_operation", None)):
        response_payload = _as_dict(await _maybe_async(lambda: service.verify_operation(payload)))
    else:
        return _blocked_result(
            request,
            context=context,
            error_code="software_verification_handler_unavailable",
            summary="Software control does not expose a safe verification handler yet.",
            truth_clamps=["handler_method_unavailable"],
        )

    verification = _first_dict(
        response_payload.get("verification"),
        response_payload.get("debug", {}).get("verification") if isinstance(response_payload.get("debug"), dict) else None,
        response_payload.get("result"),
    )
    result_payload = _first_dict(response_payload.get("result"), response_payload)
    evidence = _string_list(verification.get("evidence") or result_payload.get("evidence"), limit=12)
    verification_status = str(
        verification.get("status")
        or result_payload.get("verification_status")
        or result_payload.get("status")
        or ""
    ).lower()
    stale_or_cache_only = bool(
        payload.get("cache_only")
        or payload.get("stale_verification_cache")
        or any("cache_expired" in warning or "verification_cache_expired" in warning for warning in request.freshness_warnings)
        or all("cache" in item.lower() or "catalog" in item.lower() for item in evidence)
    )
    truth_clamps: list[str] = []
    verified = verification_status == "verified" and bool(evidence) and not stale_or_cache_only
    if verification_status == "verified" and stale_or_cache_only:
        truth_clamps.append("stale_or_cache_only_evidence")
    if verification_status == "verified" and not evidence:
        truth_clamps.append("missing_verification_evidence")
    result_state = "verified" if verified else "completed_unverified"
    verification_state = "verified" if verified else "not_verified"
    if str(result_payload.get("status") or "").lower() in {"failed", "blocked"}:
        result_state = str(result_payload.get("status")).lower()
        verification_state = "not_verified"
        truth_clamps.append("terminal_state_not_verified")
    _report_progress(request, context, "verification_complete", "Software verification continuation completed.")
    summary = str(
        verification.get("detail")
        or result_payload.get("detail")
        or response_payload.get("assistant_response")
        or "Software verification completed without verified evidence."
    )
    return _continuation_result(
        request,
        context=context,
        stage=result_state,
        status="completed" if result_state in COMPLETED_STATES else result_state,
        result_state=result_state,
        verification_state=verification_state,
        summary=summary,
        progress_stages=["resolving_target", "checking_install_state", "verification_complete"],
        verification_required=True,
        verification_attempted=True,
        evidence_count=len(evidence),
        truth_clamps=truth_clamps,
        completion_claimed=result_state in COMPLETED_STATES,
        verification_claimed=verified,
        result_summary={
            "target_name": target_name,
            "verification_status": verification_status or verification_state,
            "evidence_count": len(evidence),
            "detail": summary,
        },
    )


async def _run_software_recovery_plan(
    request: SubsystemContinuationRequest,
    context: ToolContext,
) -> SubsystemContinuationResult:
    service = getattr(context, "software_recovery", None)
    if service is None:
        return _blocked_result(
            request,
            context=context,
            error_code="software_recovery_unavailable",
            summary="Software recovery is unavailable for the continuation.",
            truth_clamps=["service_unavailable"],
        )
    payload = dict(request.payload_summary or {})
    _report_progress(request, context, "classifying_failure", "Classifying the software failure.")
    await asyncio.sleep(0)
    if callable(getattr(service, "run_recovery_plan", None)):
        recovery_payload = _as_dict(await _maybe_async(lambda: service.run_recovery_plan(payload)))
    else:
        recovery_payload = await _run_structured_recovery_service(service, payload)
    _report_progress(request, context, "running_recovery_step", "Running bounded software recovery continuation.")
    await asyncio.sleep(0)
    _report_progress(request, context, "checking_recovery_result", "Checking recovery result without claiming repair.")
    verification_payload = recovery_payload.get("verification") if isinstance(recovery_payload.get("verification"), dict) else {}
    verification_status = str(
        recovery_payload.get("verification_status")
        or verification_payload.get("status")
        or recovery_payload.get("status")
        or ""
    ).lower()
    evidence = _string_list(recovery_payload.get("evidence"), limit=12)
    verified = verification_status == "verified" and bool(evidence)
    truth_clamps = [] if verified else ["recovery_attempted_not_fixed"]
    summary = str(recovery_payload.get("summary") or "Recovery attempted a bounded route but did not verify a fix.")
    return _continuation_result(
        request,
        context=context,
        stage="verified" if verified else "completed_unverified",
        status="completed",
        result_state="verified" if verified else "completed_unverified",
        verification_state="verified" if verified else "not_verified",
        summary=summary,
        progress_stages=["classifying_failure", "running_recovery_step", "checking_recovery_result"],
        verification_required=True,
        verification_attempted=True,
        evidence_count=len(evidence),
        truth_clamps=truth_clamps,
        completion_claimed=True,
        verification_claimed=verified,
        result_summary={
            "status": recovery_payload.get("status"),
            "route_switched_to": recovery_payload.get("route_switched_to"),
            "retry_performed": recovery_payload.get("retry_performed"),
            "verification_status": verification_status or "unverified",
        },
    )


async def _run_discord_dispatch_approved_preview(
    request: SubsystemContinuationRequest,
    context: ToolContext,
) -> SubsystemContinuationResult:
    service = getattr(context, "discord_relay", None)
    if service is None:
        return _blocked_result(
            request,
            context=context,
            error_code="discord_relay_unavailable",
            summary="Discord relay is unavailable for the dispatch continuation.",
            truth_clamps=["service_unavailable"],
        )
    if str(request.approval_state or "").lower() not in {"approved", "approved_once", "approved_scoped", "allowed", "granted"}:
        return _blocked_result(
            request,
            context=context,
            error_code="approval_required_before_dispatch",
            summary="Discord dispatch needs fresh scoped approval before worker continuation.",
            truth_clamps=["approval_required_before_dispatch"],
        )
    payload = dict(request.payload_summary or {})
    pending_preview = payload.get("pending_preview") if isinstance(payload.get("pending_preview"), dict) else {}
    if not pending_preview:
        return _blocked_result(
            request,
            context=context,
            error_code="pending_preview_missing",
            summary="Discord dispatch needs the approved preview produced inline.",
            truth_clamps=["preview_missing"],
        )
    preview_fingerprint = _preview_fingerprint(pending_preview)
    if request.preview_fingerprint and preview_fingerprint and request.preview_fingerprint != preview_fingerprint:
        return _blocked_result(
            request,
            context=context,
            error_code="preview_fingerprint_mismatch",
            summary="Discord preview fingerprint changed before dispatch.",
            truth_clamps=["preview_fingerprint_mismatch"],
        )
    _report_progress(request, context, "validating_preview", "Validating approved Discord preview.")
    await asyncio.sleep(0)
    if not callable(getattr(service, "handle_request", None)):
        return _blocked_result(
            request,
            context=context,
            error_code="discord_dispatch_handler_unavailable",
            summary="Discord relay does not expose a safe dispatch handler yet.",
            truth_clamps=["handler_method_unavailable"],
        )
    _report_progress(request, context, "focusing_client", "Preparing local Discord dispatch route.")
    response_payload = _as_dict(
        await _maybe_async(
            lambda: service.handle_request(
                session_id=request.session_id,
                operator_text=request.operator_text_preview or "send approved Discord preview",
                surface_mode=request.source_surface or "ghost",
                active_module=request.active_module or "",
                active_context=payload.get("active_context") if isinstance(payload.get("active_context"), dict) else {},
                workspace_context=payload.get("workspace_context") if isinstance(payload.get("workspace_context"), dict) else {},
                request_slots={
                    "request_stage": "dispatch",
                    "pending_preview": pending_preview,
                    "approval_outcome": "approve",
                    "approval_scope": payload.get("approval_scope") or "once",
                    "trust_request_id": request.trust_scope_id or payload.get("trust_request_id"),
                },
            )
        )
    )
    _report_progress(request, context, "send_attempted", "Discord dispatch attempt returned from relay subsystem.")
    attempt = _first_dict(response_payload.get("attempt"), response_payload)
    state = str(response_payload.get("state") or attempt.get("state") or "").lower()
    evidence = _string_list(attempt.get("verification_evidence"), limit=12)
    verification_strength = str(attempt.get("verification_strength") or "").lower()
    verified = state == "verified" and bool(evidence) and verification_strength not in {"", "none", "weak"}
    truth_clamps = [] if verified else ["delivery_not_verified"]
    _report_progress(request, context, "limited_verification", "Recording bounded Discord delivery evidence.")
    summary = str(
        response_payload.get("assistant_response")
        or attempt.get("send_summary")
        or "Discord dispatch attempted, but delivery is not verified."
    )
    return _continuation_result(
        request,
        context=context,
        stage="verified" if verified else "completed_unverified",
        status="completed",
        result_state="verified" if verified else "completed_unverified",
        verification_state="verified" if verified else "not_verified",
        summary=summary,
        progress_stages=["validating_preview", "focusing_client", "send_attempted", "limited_verification"],
        verification_required=True,
        verification_attempted=True,
        evidence_count=len(evidence),
        truth_clamps=truth_clamps,
        completion_claimed=True,
        verification_claimed=verified,
        result_summary={
            "state": state or "unknown",
            "verification_strength": verification_strength or "none",
            "evidence_count": len(evidence),
            "preview_fingerprint": preview_fingerprint,
        },
    )


async def _run_network_live_diagnosis(
    request: SubsystemContinuationRequest,
    context: ToolContext,
) -> SubsystemContinuationResult:
    probe = context.system_probe
    if probe is None or not callable(getattr(probe, "network_diagnosis", None)):
        return _blocked_result(
            request,
            context=context,
            error_code="network_diagnosis_unavailable",
            summary="Network live diagnosis is unavailable in this runtime.",
            truth_clamps=["service_unavailable"],
        )
    payload = dict(request.payload_summary or {})
    focus = str(payload.get("focus") or "overview")
    diagnostic_burst = bool(payload.get("diagnostic_burst", False))
    _report_progress(request, context, "checking_adapter", "Checking local network adapter state.")
    await asyncio.sleep(0)
    _report_progress(request, context, "running_connectivity_probe", "Running bounded network connectivity diagnosis.")
    data = _as_dict(
        await _maybe_async(lambda: probe.network_diagnosis(focus=focus, diagnostic_burst=diagnostic_burst))
    )
    evidence = _string_list(data.get("evidence") or data.get("signals"), limit=12)
    limitations = _string_list(data.get("limitations") or data.get("warnings"), limit=12)
    _report_progress(request, context, "classifying_diagnosis", "Classifying network diagnosis with evidence limits.")
    summary = str(data.get("summary") or data.get("status") or "Network live diagnosis completed with bounded evidence.")
    return _continuation_result(
        request,
        context=context,
        stage="completed_unverified",
        status="completed",
        result_state="completed_unverified",
        verification_state="not_verified",
        summary=summary,
        progress_stages=["checking_adapter", "running_connectivity_probe", "classifying_diagnosis"],
        verification_required=bool(request.verification_required),
        verification_attempted=True,
        evidence_count=len(evidence),
        result_limitations=limitations,
        truth_clamps=["diagnosis_is_not_repair"],
        completion_claimed=True,
        verification_claimed=False,
        result_summary={
            "focus": focus,
            "diagnostic_burst": diagnostic_burst,
            "status": data.get("status"),
            "evidence_count": len(evidence),
            "limitation_count": len(limitations),
        },
    )


async def _maybe_async(callback: Callable[[], Any]) -> Any:
    result = callback()
    if inspect.isawaitable(result):
        return await result
    return result


def _software_verification_request(request: SubsystemContinuationRequest, target_name: str) -> Any:
    from stormhelm.core.software_control.models import SoftwareOperationRequest
    from stormhelm.core.software_control.models import SoftwareOperationType

    return SoftwareOperationRequest(
        request_id=request.request_id or request.continuation_id,
        source_surface=request.source_surface or "ghost",
        raw_input=str(request.payload_summary.get("raw_input") or request.operator_text_preview or f"verify {target_name}"),
        user_visible_text=str(request.payload_summary.get("user_visible_text") or request.operator_text_preview or f"verify {target_name}"),
        operation_type=SoftwareOperationType.VERIFY,
        target_name=target_name,
        request_stage=str(request.payload_summary.get("request_stage") or "prepare_plan"),
        task_id=request.task_id or None,
    )


async def _run_structured_recovery_service(service: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if not (
        callable(getattr(service, "build_troubleshooting_context", None))
        and callable(getattr(service, "diagnose_failure", None))
        and callable(getattr(service, "execute_recovery_plan", None))
    ):
        return {
            "status": "blocked",
            "summary": "Software recovery does not expose a safe recovery-plan execution handler yet.",
            "verification_status": "unverified",
            "error_code": "software_recovery_handler_unavailable",
        }
    from stormhelm.core.software_recovery.models import FailureEvent

    failure_payload = payload.get("failure_event") if isinstance(payload.get("failure_event"), dict) else {}
    failure = FailureEvent(
        failure_id=str(failure_payload.get("failure_id") or payload.get("failure_id") or "failure"),
        operation_type=str(failure_payload.get("operation_type") or payload.get("operation_type") or "unknown"),
        target_name=str(failure_payload.get("target_name") or payload.get("target_name") or "unknown"),
        stage=str(failure_payload.get("stage") or "execution"),
        category=str(failure_payload.get("category") or payload.get("failure_category") or "unknown_failure"),
        message=str(failure_payload.get("message") or payload.get("message") or "Software operation needs recovery."),
        details=dict(failure_payload.get("details") or {}) if isinstance(failure_payload.get("details"), dict) else {},
    )
    context = await _maybe_async(
        lambda: service.build_troubleshooting_context(
            failure_event=failure,
            operation_plan=dict(payload.get("operation_plan") or {}),
            verification=payload.get("verification") if isinstance(payload.get("verification"), dict) else None,
            local_signals=dict(payload.get("local_signals") or {}),
        )
    )
    plan = await _maybe_async(lambda: service.diagnose_failure(context))
    result = await _maybe_async(lambda: service.execute_recovery_plan(plan))
    verification = (
        await _maybe_async(lambda: service.verify_recovery_result(result))
        if callable(getattr(service, "verify_recovery_result", None))
        else {}
    )
    data = _as_dict(result)
    data["plan"] = _as_dict(plan)
    data["verification"] = _as_dict(verification)
    return data


def _report_progress(request: SubsystemContinuationRequest, context: ToolContext, stage: str, message: str) -> None:
    payload = _progress_payload(request, stage, message)
    context.report_progress(payload)
    events = getattr(context, "events", None)
    if events is None:
        return
    events.publish(
        event_family="runtime",
        event_type="subsystem.continuation.progress",
        severity="info",
        subsystem=request.subsystem or "subsystem_continuation",
        session_id=request.session_id,
        subject=request.continuation_id,
        visibility_scope="watch_surface",
        retention_class="bounded_recent",
        provenance={"channel": "subsystem_continuation", "kind": "direct_system_fact"},
        message=message,
        payload=payload,
    )


def _continuation_result(
    request: SubsystemContinuationRequest,
    *,
    context: ToolContext,
    stage: str,
    status: str,
    result_state: str,
    verification_state: str,
    summary: str,
    progress_stages: list[str],
    verification_required: bool,
    verification_attempted: bool,
    evidence_count: int,
    truth_clamps: list[str] | None = None,
    result_limitations: list[str] | None = None,
    completion_claimed: bool = False,
    verification_claimed: bool = False,
    result_summary: dict[str, Any] | None = None,
) -> SubsystemContinuationResult:
    truth_clamps = list(truth_clamps or [])
    limitations = list(result_limitations or [])
    debug = {
        "subsystem_continuation_handler": request.operation_kind,
        "continuation_progress_stages": list(progress_stages),
        "continuation_verification_required": bool(verification_required),
        "continuation_verification_attempted": bool(verification_attempted),
        "continuation_verification_evidence_count": int(evidence_count or 0),
        "continuation_result_limitations": list(limitations),
        "continuation_truth_clamps_applied": list(truth_clamps),
    }
    return SubsystemContinuationResult(
        continuation_id=request.continuation_id,
        request_id=request.request_id,
        session_id=request.session_id,
        task_id=request.task_id,
        job_id=context.job_id,
        latency_trace_id=request.latency_trace_id,
        route_family=request.route_family,
        subsystem=request.subsystem,
        operation_kind=request.operation_kind,
        stage=stage,
        status=status,
        result_state=result_state,
        verification_state=verification_state,
        summary=summary,
        worker_lane=request.worker_lane,
        priority_level=request.priority_level,
        progress_event_count=len(progress_stages),
        completion_claimed=completion_claimed,
        verification_claimed=verification_claimed,
        result_summary=safe_latency_value(result_summary or {}),
        subsystem_continuation_handler=request.operation_kind,
        subsystem_continuation_handler_implemented=True,
        continuation_progress_stages=list(progress_stages),
        continuation_verification_required=bool(verification_required),
        continuation_verification_attempted=bool(verification_attempted),
        continuation_verification_evidence_count=int(evidence_count or 0),
        continuation_result_limitations=list(limitations),
        continuation_truth_clamps_applied=list(truth_clamps),
        debug=debug,
    )


def _apply_handler_status(result: SubsystemContinuationResult, status: dict[str, Any]) -> None:
    if not result.subsystem_continuation_handler:
        result.subsystem_continuation_handler = str(status.get("operation_kind") or result.operation_kind)
    result.subsystem_continuation_handler_implemented = bool(status.get("implemented"))
    if not result.subsystem_continuation_handler_missing_reason:
        result.subsystem_continuation_handler_missing_reason = str(status.get("missing_reason") or "")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        converted = value.to_dict()
        return dict(converted) if isinstance(converted, dict) else {}
    if hasattr(value, "__dataclass_fields__"):
        converted = safe_latency_value(asdict(value))
        return dict(converted) if isinstance(converted, dict) else {}
    return {}


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return {}


def _string_list(value: Any, *, limit: int = 24) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in list(value)[:limit] if str(item or "").strip()]


def _preview_fingerprint(preview: dict[str, Any]) -> str:
    fingerprint = preview.get("fingerprint") if isinstance(preview.get("fingerprint"), dict) else {}
    return str(fingerprint.get("fingerprint_id") or preview.get("preview_fingerprint") or "")


def _progress_payload(
    request: SubsystemContinuationRequest,
    stage: str,
    message: str,
) -> dict[str, Any]:
    return {
        "continuation_id": request.continuation_id,
        "route_family": request.route_family,
        "subsystem": request.subsystem,
        "operation_kind": request.operation_kind,
        "stage": stage,
        "result_state": stage,
        "message": message,
        "completion_claimed": False,
        "verification_claimed": False,
    }


def _blocked_result(
    request: SubsystemContinuationRequest,
    *,
    context: ToolContext,
    error_code: str,
    summary: str,
    truth_clamps: list[str] | None = None,
) -> SubsystemContinuationResult:
    truth_clamps = list(truth_clamps or [])
    handler_missing_reason = error_code if "handler" in error_code else ""
    return SubsystemContinuationResult(
        continuation_id=request.continuation_id,
        request_id=request.request_id,
        session_id=request.session_id,
        task_id=request.task_id,
        job_id=context.job_id,
        latency_trace_id=request.latency_trace_id,
        route_family=request.route_family,
        subsystem=request.subsystem,
        operation_kind=request.operation_kind,
        stage="blocked",
        status="blocked",
        result_state="blocked",
        verification_state=request.verification_state,
        summary=summary,
        worker_lane=request.worker_lane,
        priority_level=request.priority_level,
        error_code=error_code,
        error_message=summary,
        subsystem_continuation_handler=request.operation_kind,
        subsystem_continuation_handler_implemented=False,
        subsystem_continuation_handler_missing_reason=handler_missing_reason,
        continuation_verification_required=bool(request.verification_required),
        continuation_truth_clamps_applied=truth_clamps,
        debug={
            "subsystem_continuation_handler": request.operation_kind,
            "continuation_progress_stages": [],
            "continuation_verification_required": bool(request.verification_required),
            "continuation_verification_attempted": False,
            "continuation_verification_evidence_count": 0,
            "continuation_result_limitations": [],
            "continuation_truth_clamps_applied": truth_clamps,
        },
    )


def _coerce_result(
    value: SubsystemContinuationResult | dict[str, Any],
    *,
    request: SubsystemContinuationRequest,
    context: ToolContext,
) -> SubsystemContinuationResult:
    if isinstance(value, SubsystemContinuationResult):
        result = value
    elif isinstance(value, dict):
        result = SubsystemContinuationResult.from_dict(value)
    else:
        result = _blocked_result(
            request,
            context=context,
            error_code="invalid_handler_result",
            summary="Continuation handler returned an invalid result.",
        )
    if not result.continuation_id:
        result.continuation_id = request.continuation_id
    if not result.request_id:
        result.request_id = request.request_id
    if not result.session_id:
        result.session_id = request.session_id
    if not result.job_id:
        result.job_id = context.job_id
    if not result.route_family:
        result.route_family = request.route_family
    if not result.subsystem:
        result.subsystem = request.subsystem
    if not result.operation_kind:
        result.operation_kind = request.operation_kind
    if not result.worker_lane:
        result.worker_lane = request.worker_lane
    if not result.priority_level:
        result.priority_level = request.priority_level
    return result


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, (perf_counter() - started) * 1000), 3)
