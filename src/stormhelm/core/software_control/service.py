from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import shutil
from typing import Any

from stormhelm.config.models import SoftwareControlConfig
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.software_control.catalog import resolve_catalog_target
from stormhelm.core.software_control.models import SoftwareCheckpointStatus
from stormhelm.core.software_control.models import SoftwareControlResponse
from stormhelm.core.software_control.models import SoftwareControlTrace
from stormhelm.core.software_control.models import SoftwareExecutionStatus
from stormhelm.core.software_control.models import SoftwareInstallState
from stormhelm.core.software_control.models import SoftwareOperationPlan
from stormhelm.core.software_control.models import SoftwareOperationRequest
from stormhelm.core.software_control.models import SoftwareOperationResult
from stormhelm.core.software_control.models import SoftwareOperationType
from stormhelm.core.software_control.models import SoftwarePlanStep
from stormhelm.core.software_control.models import SoftwareSource
from stormhelm.core.software_control.models import SoftwareSourceKind
from stormhelm.core.software_control.models import SoftwareTarget
from stormhelm.core.software_control.models import SoftwareTrustLevel
from stormhelm.core.software_control.models import SoftwareVerificationResult
from stormhelm.core.software_control.models import SoftwareVerificationStatus
from stormhelm.core.software_control.planner import SoftwareControlPlannerSeam
from stormhelm.core.software_recovery import FailureEvent
from stormhelm.core.software_recovery import SoftwareRecoverySubsystem
from stormhelm.core.trust import PermissionGrant
from stormhelm.core.trust import PermissionScope
from stormhelm.core.trust import TrustActionKind
from stormhelm.core.trust import TrustActionRequest
from stormhelm.core.trust import TrustDecision
from stormhelm.core.trust import TrustDecisionOutcome
from stormhelm.shared.result import SafetyDecision


@dataclass(slots=True)
class _NullSafetyPolicy:
    def authorize_software_route(self, route_kind: str, *, requires_elevation: bool = False):  # type: ignore[no-untyped-def]
        payload = {"route_kind": route_kind, "requires_elevation": requires_elevation}
        return SafetyDecision(True, "No safety policy attached.", details=payload)


@dataclass(slots=True)
class SoftwareControlSubsystem:
    config: SoftwareControlConfig
    recovery: SoftwareRecoverySubsystem
    safety: SafetyPolicy | _NullSafetyPolicy = field(default_factory=_NullSafetyPolicy)
    system_probe: Any | None = None
    trust_service: Any | None = None
    planner_seam: SoftwareControlPlannerSeam = field(init=False)
    _recent_traces: deque[SoftwareControlTrace] = field(default_factory=lambda: deque(maxlen=24), init=False)

    def __post_init__(self) -> None:
        self.planner_seam = SoftwareControlPlannerSeam(self.config)

    def status_snapshot(self) -> dict[str, object]:
        last_trace = self._recent_traces[-1].to_dict() if self._recent_traces else None
        return {
            "phase": "software1",
            "enabled": self.config.enabled,
            "planner_routing_enabled": self.config.planner_routing_enabled,
            "package_manager_routes_enabled": self.config.package_manager_routes_enabled,
            "browser_guided_routes_enabled": self.config.browser_guided_routes_enabled,
            "privileged_operations_allowed": self.config.privileged_operations_allowed,
            "capabilities": {
                "package_manager_routing": self.config.package_manager_routes_enabled,
                "vendor_installer_routing": self.config.vendor_installer_routes_enabled,
                "browser_guided_acquisition": self.config.browser_guided_routes_enabled,
                "typed_operation_planning": True,
                "typed_verification": True,
                "source_resolution": True,
            },
            "truthfulness_contract": {
                "status_discipline": "explicit_checkpoints",
                "planned_vs_attempted": "separate",
                "verification_required_for_success": True,
            },
            "runtime_hooks": {
                "catalog_ready": True,
                "planner_seam_ready": True,
                "recovery_handoff_ready": True,
                "launch_adapter_ready": callable(getattr(self.system_probe, "app_control", None)),
            },
            "recent_trace_count": len(self._recent_traces),
            "last_trace": last_trace,
        }

    def resolve_software_target(self, operator_text: str) -> SoftwareTarget | None:
        evaluation = self.planner_seam.evaluate(
            raw_text=operator_text,
            normalized_text=operator_text,
            surface_mode="ghost",
            active_module="chartroom",
            active_request_state={},
            active_context={},
        )
        if not evaluation.target_name:
            return None
        return resolve_catalog_target(evaluation.target_name)

    def discover_software_sources(self, target: SoftwareTarget | None) -> list[SoftwareSource]:
        if target is None:
            return []
        sources: list[SoftwareSource] = []
        if self.config.package_manager_routes_enabled:
            winget_id = target.package_ids.get("winget")
            if winget_id:
                sources.append(
                    SoftwareSource(
                        kind=SoftwareSourceKind.PACKAGE_MANAGER,
                        route="winget",
                        label=f"{target.display_name} via winget",
                        locator=winget_id,
                        trust_level=SoftwareTrustLevel.TRUSTED,
                    )
                )
            chocolatey_id = target.package_ids.get("chocolatey")
            if chocolatey_id:
                sources.append(
                    SoftwareSource(
                        kind=SoftwareSourceKind.PACKAGE_MANAGER,
                        route="chocolatey",
                        label=f"{target.display_name} via Chocolatey",
                        locator=chocolatey_id,
                        trust_level=SoftwareTrustLevel.TRUSTED,
                    )
                )
        if self.config.vendor_installer_routes_enabled and target.vendor_url:
            sources.append(
                SoftwareSource(
                    kind=SoftwareSourceKind.VENDOR_INSTALLER,
                    route="vendor_installer",
                    label=f"{target.display_name} trusted vendor installer",
                    locator=target.vendor_url,
                    trust_level=SoftwareTrustLevel.TRUSTED,
                    requires_browser=True,
                )
            )
        if self.config.browser_guided_routes_enabled:
            browser_locator = target.vendor_url or f"https://www.google.com/search?q={target.browser_query or target.display_name}"
            browser_source = SoftwareSource(
                kind=SoftwareSourceKind.BROWSER_GUIDED,
                route="browser_guided",
                label=f"{target.display_name} browser-guided acquisition",
                locator=browser_locator,
                trust_level=SoftwareTrustLevel.KNOWN if target.vendor_url else SoftwareTrustLevel.UNVERIFIED,
                requires_browser=True,
            )
            if self._allow_source(browser_source):
                sources.append(browser_source)
        return [source for source in sources if self._allow_source(source)]

    def plan_software_operation(
        self,
        *,
        operation_type: SoftwareOperationType,
        target: SoftwareTarget,
        sources: list[SoftwareSource],
    ) -> SoftwareOperationPlan:
        selected_source = self.select_software_source(sources)
        requires_confirmation = self._requires_confirmation(operation_type)
        steps = [
            SoftwarePlanStep(
                title="Target resolved",
                status=SoftwareCheckpointStatus.FOUND,
                detail=f"Identified {target.display_name} as the requested software target.",
            ),
            SoftwarePlanStep(
                title="Install state",
                status=SoftwareCheckpointStatus.UNCERTAIN,
                detail="The local install state has not been verified yet in this pass.",
            ),
            SoftwarePlanStep(
                title="Route prepared",
                status=SoftwareCheckpointStatus.PREPARED,
                detail=(
                    f"Prepared the {selected_source.route} route as the preferred local source."
                    if selected_source is not None
                    else (
                        "Prepared the local verification lane."
                        if operation_type == SoftwareOperationType.VERIFY
                        else "Prepared a software workflow shell, but no trusted source is selected yet."
                    )
                ),
            ),
        ]
        if requires_confirmation:
            steps.append(
                SoftwarePlanStep(
                    title="Execution gate",
                    status=SoftwareCheckpointStatus.WAITING_CONFIRMATION,
                    detail="Waiting for operator confirmation before any install, update, uninstall, or repair attempt.",
                )
            )
        response_contract = {
            "bearing_title": "Software Plan",
            "micro_response": f"Prepared a local {operation_type.value} plan for {target.display_name}.",
            "full_response": (
                f"Prepared a local {operation_type.value} plan for {target.display_name}. "
                f"Source: {selected_source.route}. I have not {self._completion_verb(operation_type)} anything yet."
                if selected_source is not None
                else f"Prepared a local {operation_type.value} plan for {target.display_name}. "
                "I have not attempted anything yet because no trusted route is selected."
            ),
        }
        return SoftwareOperationPlan(
            operation_type=operation_type,
            target=target,
            sources=list(sources),
            selected_source=selected_source,
            presentation_depth="deck" if operation_type in {SoftwareOperationType.UPDATE, SoftwareOperationType.UNINSTALL, SoftwareOperationType.REPAIR} else "ghost",
            requires_command_deck=operation_type in {SoftwareOperationType.UPDATE, SoftwareOperationType.UNINSTALL, SoftwareOperationType.REPAIR},
            steps=steps,
            response_contract=response_contract,
        )

    def execute_software_operation(
        self,
        *,
        session_id: str,
        active_module: str,
        request: SoftwareOperationRequest,
    ) -> SoftwareControlResponse:
        del active_module
        target = resolve_catalog_target(request.target_name)
        if target is None:
            return self._blocked_response(
                request=request,
                message="Stormhelm could not resolve that software target into a typed local record yet.",
                failure_category="unresolved_target",
            )
        sources = self.discover_software_sources(target)
        plan = self.plan_software_operation(
            operation_type=request.operation_type,
            target=target,
            sources=sources,
        )
        if request.operation_type == SoftwareOperationType.VERIFY and request.request_stage != "confirm_execution":
            return self._execute_verification(request=request, target=target)

        if request.operation_type == SoftwareOperationType.LAUNCH and request.request_stage != "confirm_execution":
            return self._execute_launch(request=request, target=target, sources=sources, plan=plan)

        trust_grant: PermissionGrant | None = None
        trust_decision = None
        trust_required = self._requires_confirmation(request.operation_type) and self.trust_service is not None
        if trust_required:
            trust_request = self._trust_request(
                session_id=session_id,
                request=request,
                target=target,
                plan=plan,
            )
            if request.request_stage == "confirm_execution" and request.trust_request_id:
                trust_decision = self.trust_service.respond_to_request(
                    approval_request_id=request.trust_request_id,
                    decision=str(request.approval_outcome or "approve"),
                    session_id=session_id,
                    scope=self._trust_scope(request.approval_scope),
                    task_id=str((trust_request.task_id or "")),
                )
            else:
                trust_decision = self.trust_service.evaluate_action(trust_request)
            trust_grant = trust_decision.grant
            if (
                request.request_stage == "confirm_execution"
                and trust_decision is not None
                and not trust_decision.allowed
                and trust_decision.outcome != TrustDecisionOutcome.BLOCKED
            ):
                trust_decision = self.trust_service.evaluate_action(trust_request)
                trust_grant = trust_decision.grant
            if request.request_stage == "confirm_execution" and trust_decision.outcome == "blocked":
                return self._denied_response(request=request, target=target, decision=trust_decision)

        if (request.request_stage != "confirm_execution" or (trust_decision is not None and not trust_decision.allowed)) and (
            trust_decision is None or not trust_decision.allowed
        ):
            trace = SoftwareControlTrace(
                operation_type=request.operation_type.value,
                target_name=target.canonical_name,
                route_selected=plan.selected_source.route if plan.selected_source is not None else None,
                execution_status=SoftwareExecutionStatus.PREPARED.value,
                presentation_depth=plan.presentation_depth,
                follow_up_reuse=request.follow_up_reuse,
                source_candidates=[source.to_dict() for source in sources],
                checkpoints=[step.status.value for step in plan.steps],
                uncertain_points=["install_state_unverified"],
            )
            result = SoftwareOperationResult(
                status=SoftwareExecutionStatus.PREPARED,
                operation_type=request.operation_type,
                target_name=target.canonical_name,
                selected_source=plan.selected_source,
                install_state=SoftwareInstallState.UNKNOWN,
                verification_status=SoftwareVerificationStatus.UNVERIFIED,
                checkpoints=[step.status.value for step in plan.steps],
                evidence=["prepared_plan_only", "execution_not_started"],
                detail="Execution has not started yet.",
            )
            verification = self.verify_software_operation(
                request=request,
                target=target,
                result=result,
            )
            self._remember_trace(trace)
            active_request_state = (
                self._awaiting_confirmation_state(request=request, target=target, plan=plan)
                if self._requires_confirmation(request.operation_type)
                else {}
            )
            if trust_decision is not None and self.trust_service is not None:
                active_request_state = self.trust_service.attach_request_state(active_request_state, decision=trust_decision)
            return SoftwareControlResponse(
                assistant_response=self._merge_trust_prompt(
                    plan.response_contract["full_response"],
                    trust_decision.operator_message if trust_decision is not None else "",
                ),
                response_contract=dict(plan.response_contract),
                trace=trace,
                result=result,
                verification=verification,
                active_request_state=active_request_state,
                debug={
                    "operation_type": request.operation_type.value,
                    "target_name": target.canonical_name,
                    "plan": plan.to_dict(),
                    "result": result.to_dict(),
                    "trace": trace.to_dict(),
                    "verification": verification.to_dict(),
                    "trust": trust_decision.to_dict() if trust_decision is not None else {},
                },
            )

        selected_source = plan.selected_source
        route_policy = self.safety.authorize_software_route(
            selected_source.route if selected_source is not None else "unresolved",
            requires_elevation=bool(selected_source and selected_source.requires_elevation),
        )
        if not route_policy.allowed:
            return self._blocked_response(
                request=request,
                message=route_policy.reason,
                failure_category="policy_block",
            )

        return self._handoff_to_recovery(
            request=request,
            target=target,
            sources=sources,
            selected_source=selected_source,
            failure_category="adapter_mismatch",
            failure_message="The preferred package-manager execution lane is not wired into this pass yet.",
            local_signals={
                "route": selected_source.route if selected_source is not None else "",
                "supported_runtime": False,
                "browser_guided_available": self.config.browser_guided_routes_enabled,
                "vendor_installer_available": self.config.vendor_installer_routes_enabled,
            },
            policy_decisions=[
                {
                    "allowed": bool(route_policy.allowed),
                    "reason": str(route_policy.reason),
                    "context": dict(route_policy.details or {}),
                }
            ],
            uncertain_points=["execution_adapter_unavailable"],
            trust_decision=trust_decision,
        )

    def verify_software_operation(
        self,
        *,
        request: SoftwareOperationRequest,
        target: SoftwareTarget,
        result: SoftwareOperationResult,
    ) -> SoftwareVerificationResult:
        del request
        if result.status == SoftwareExecutionStatus.PREPARED:
            return SoftwareVerificationResult(
                status=SoftwareVerificationStatus.UNVERIFIED,
                install_state=target.install_state,
                detail="No installation, repair, or launch attempt has been executed yet.",
                evidence=["prepared_only"],
            )
        if result.status == SoftwareExecutionStatus.VERIFIED:
            return SoftwareVerificationResult(
                status=result.verification_status,
                install_state=result.install_state,
                detail=result.detail or "Verification confirmed the software state.",
                evidence=list(result.evidence),
            )
        return SoftwareVerificationResult(
            status=SoftwareVerificationStatus.UNCERTAIN,
            install_state=SoftwareInstallState.UNKNOWN,
            detail="Stormhelm cannot verify the software state yet from the current evidence.",
            evidence=["verification_incomplete"],
        )

    def select_software_source(
        self,
        sources: list[SoftwareSource],
        *,
        preferred_route: str | None = None,
    ) -> SoftwareSource | None:
        allowed_sources = [source for source in sources if self._allow_source(source)]
        if preferred_route:
            for source in allowed_sources:
                if source.route == preferred_route:
                    return source
        return allowed_sources[0] if allowed_sources else None

    def _allow_source(self, source: SoftwareSource) -> bool:
        if not self.config.trusted_sources_only:
            return True
        return source.trust_level != SoftwareTrustLevel.UNVERIFIED

    def _requires_confirmation(self, operation_type: SoftwareOperationType) -> bool:
        return operation_type in {
            SoftwareOperationType.INSTALL,
            SoftwareOperationType.UPDATE,
            SoftwareOperationType.UNINSTALL,
            SoftwareOperationType.REPAIR,
        }

    def _execute_verification(
        self,
        *,
        request: SoftwareOperationRequest,
        target: SoftwareTarget,
    ) -> SoftwareControlResponse:
        local_probe = self._local_install_probe(target)
        if local_probe is not None:
            detail = f"{target.display_name} appears to be installed at {local_probe['path']}."
            verification_status = SoftwareVerificationStatus.VERIFIED
            install_state = SoftwareInstallState.INSTALLED
            evidence = [f"executable:{local_probe['launch_name']}", f"path:{local_probe['path']}"]
            micro_response = f"{target.display_name} appears to be installed."
        else:
            detail = f"Stormhelm could not verify {target.display_name} locally from executable paths in this pass."
            verification_status = SoftwareVerificationStatus.UNCERTAIN
            install_state = SoftwareInstallState.UNKNOWN
            evidence = ["executable_probe_incomplete"]
            micro_response = f"Stormhelm could not verify {target.display_name} locally yet."

        status = (
            SoftwareExecutionStatus.VERIFIED
            if verification_status == SoftwareVerificationStatus.VERIFIED
            else SoftwareExecutionStatus.UNCERTAIN
        )
        checkpoints = ["found", "verified"] if status == SoftwareExecutionStatus.VERIFIED else ["found", "uncertain"]
        trace = SoftwareControlTrace(
            operation_type=request.operation_type.value,
            target_name=target.canonical_name,
            execution_status=status.value,
            verification_status=verification_status.value,
            presentation_depth="ghost",
            follow_up_reuse=request.follow_up_reuse,
            checkpoints=checkpoints,
            uncertain_points=[] if status == SoftwareExecutionStatus.VERIFIED else ["local_verification_incomplete"],
        )
        result = SoftwareOperationResult(
            status=status,
            operation_type=request.operation_type,
            target_name=target.canonical_name,
            install_state=install_state,
            verification_status=verification_status,
            checkpoints=checkpoints,
            evidence=evidence,
            detail=detail,
        )
        verification = SoftwareVerificationResult(
            status=verification_status,
            install_state=install_state,
            detail=detail,
            evidence=evidence,
        )
        self._remember_trace(trace)
        response_contract = {
            "bearing_title": "Software Verification",
            "micro_response": micro_response,
            "full_response": detail,
        }
        return SoftwareControlResponse(
            assistant_response=detail,
            response_contract=response_contract,
            trace=trace,
            result=result,
            verification=verification,
            active_request_state={},
            debug={
                "operation_type": request.operation_type.value,
                "target_name": target.canonical_name,
                "result": result.to_dict(),
                "trace": trace.to_dict(),
                "verification": verification.to_dict(),
            },
        )

    def _execute_launch(
        self,
        *,
        request: SoftwareOperationRequest,
        target: SoftwareTarget,
        sources: list[SoftwareSource],
        plan: SoftwareOperationPlan,
    ) -> SoftwareControlResponse:
        app_control = getattr(self.system_probe, "app_control", None) if self.system_probe is not None else None
        if not callable(app_control):
            return self._handoff_to_recovery(
                request=request,
                target=target,
                sources=sources,
                selected_source=plan.selected_source,
                failure_category="adapter_mismatch",
                failure_message="The native app launch adapter is unavailable in this pass.",
                local_signals={
                    "launch_candidates": list(target.launch_names),
                    "launch_adapter_ready": False,
                },
                uncertain_points=["launch_adapter_unavailable"],
            )

        last_failure: dict[str, Any] | None = None
        for launch_name in target.launch_names or [target.display_name]:
            payload = app_control(action="launch", app_name=launch_name)
            if isinstance(payload, dict) and bool(payload.get("success")):
                detail = f"Launched {target.display_name} through native app control."
                evidence = [f"launch_target:{launch_name}"]
                if payload.get("pid"):
                    evidence.append(f"pid:{payload['pid']}")
                trace = SoftwareControlTrace(
                    operation_type=request.operation_type.value,
                    target_name=target.canonical_name,
                    execution_status=SoftwareExecutionStatus.COMPLETED.value,
                    verification_status=SoftwareVerificationStatus.VERIFIED.value,
                    presentation_depth="ghost",
                    follow_up_reuse=request.follow_up_reuse,
                    checkpoints=["found", "attempted", "launched", "completed"],
                )
                result = SoftwareOperationResult(
                    status=SoftwareExecutionStatus.COMPLETED,
                    operation_type=request.operation_type,
                    target_name=target.canonical_name,
                    install_state=SoftwareInstallState.UNKNOWN,
                    verification_status=SoftwareVerificationStatus.VERIFIED,
                    checkpoints=["found", "attempted", "launched", "completed"],
                    evidence=evidence,
                    detail=detail,
                )
                verification = SoftwareVerificationResult(
                    status=SoftwareVerificationStatus.VERIFIED,
                    install_state=SoftwareInstallState.UNKNOWN,
                    detail=detail,
                    evidence=evidence,
                )
                self._remember_trace(trace)
                response_contract = {
                    "bearing_title": "Software Launch",
                    "micro_response": f"Launched {target.display_name}.",
                    "full_response": detail,
                }
                return SoftwareControlResponse(
                    assistant_response=detail,
                    response_contract=response_contract,
                    trace=trace,
                    result=result,
                    verification=verification,
                    active_request_state={},
                    debug={
                        "operation_type": request.operation_type.value,
                        "target_name": target.canonical_name,
                        "result": result.to_dict(),
                        "trace": trace.to_dict(),
                        "verification": verification.to_dict(),
                        "launch_payload": dict(payload),
                    },
                )
            last_failure = dict(payload) if isinstance(payload, dict) else {"reason": "launch_failed"}

        return self._handoff_to_recovery(
            request=request,
            target=target,
            sources=sources,
            selected_source=plan.selected_source,
            failure_category="launch_failed",
            failure_message=str((last_failure or {}).get("reason") or "The launch attempt did not complete successfully."),
            local_signals={
                "launch_candidates": list(target.launch_names),
                "launch_adapter_ready": True,
                "launch_failure": dict(last_failure or {}),
            },
            uncertain_points=["launch_verification_incomplete"],
        )

    def _local_install_probe(self, target: SoftwareTarget) -> dict[str, str] | None:
        for launch_name in target.launch_names:
            path = shutil.which(launch_name)
            if path:
                return {"launch_name": launch_name, "path": path}
        return None

    def _handoff_to_recovery(
        self,
        *,
        request: SoftwareOperationRequest,
        target: SoftwareTarget,
        sources: list[SoftwareSource],
        selected_source: SoftwareSource | None,
        failure_category: str,
        failure_message: str,
        local_signals: dict[str, Any],
        policy_decisions: list[dict[str, Any]] | None = None,
        uncertain_points: list[str] | None = None,
        trust_decision: TrustDecision | None = None,
    ) -> SoftwareControlResponse:
        failure = FailureEvent(
            failure_id=request.request_id,
            operation_type=request.operation_type.value,
            target_name=target.canonical_name,
            stage="execution",
            category=failure_category,
            message=failure_message,
            details={
                "selected_route": selected_source.route if selected_source is not None else "",
                "request_stage": request.request_stage,
            },
        )
        recovery_context = self.recovery.build_troubleshooting_context(
            failure_event=failure,
            operation_plan={
                "target": target.to_dict(),
                "request": request.to_dict(),
                "selected_source": selected_source.to_dict() if selected_source is not None else None,
            },
            verification=None,
            local_signals=dict(local_signals),
        )
        recovery_plan = self.recovery.diagnose_failure(recovery_context)
        recovery_result = self.recovery.execute_recovery_plan(recovery_plan)
        trace = SoftwareControlTrace(
            operation_type=request.operation_type.value,
            target_name=target.canonical_name,
            route_selected=selected_source.route if selected_source is not None else None,
            execution_status=SoftwareExecutionStatus.RECOVERY_IN_PROGRESS.value,
            verification_status=SoftwareVerificationStatus.UNVERIFIED.value,
            recovery_invoked=True,
            presentation_depth="deck",
            follow_up_reuse=request.follow_up_reuse,
            source_candidates=[source.to_dict() for source in sources],
            policy_decisions=list(policy_decisions or []),
            checkpoints=["found", "prepared", "attempted", "recovery_in_progress"],
            uncertain_points=list(uncertain_points or ["execution_adapter_unavailable"]),
            failure_category=failure.category,
        )
        result = SoftwareOperationResult(
            status=SoftwareExecutionStatus.RECOVERY_IN_PROGRESS,
            operation_type=request.operation_type,
            target_name=target.canonical_name,
            selected_source=selected_source,
            install_state=SoftwareInstallState.UNKNOWN,
            verification_status=SoftwareVerificationStatus.UNVERIFIED,
            checkpoints=list(trace.checkpoints),
            evidence=["route_attempt_blocked", "recovery_invoked"],
            detail="Execution did not complete; Stormhelm switched into a bounded recovery route.",
        )
        self._remember_trace(trace)
        response_contract = {
            "bearing_title": "Software Recovery",
            "micro_response": (
                f"Recovery switched {target.display_name} toward the trusted "
                f"{recovery_result.route_switched_to.replace('_', ' ')} route."
                if recovery_result.route_switched_to
                else f"Recovery prepared the next safe route for {target.display_name}."
            ),
            "full_response": (
                f"The preferred {selected_source.route if selected_source is not None else 'local'} route is not executable in this pass. "
                f"Stormhelm kept the install state truthful and moved recovery toward "
                f"{recovery_result.route_switched_to.replace('_', ' ') if recovery_result.route_switched_to else 'the next safe route'}."
            ),
        }
        active_request_state = {
            "family": "software_control",
            "subject": target.canonical_name,
            "task_id": str(request.task_id or ""),
            "request_type": "software_control_response",
            "parameters": {
                "operation_type": request.operation_type.value,
                "target_name": target.canonical_name,
                "request_stage": "recovery_ready",
                "route_switched_to": recovery_result.route_switched_to,
                "task_id": str(request.task_id or ""),
            },
        }
        if trust_decision is not None and self.trust_service is not None:
            active_request_state = self.trust_service.attach_request_state(
                active_request_state,
                decision=trust_decision,
            )
        return SoftwareControlResponse(
            assistant_response=response_contract["full_response"],
            response_contract=response_contract,
            trace=trace,
            result=result,
            recovery_plan=recovery_plan,
            recovery_result=recovery_result,
            active_request_state=active_request_state,
            debug={
                "operation_type": request.operation_type.value,
                "target_name": target.canonical_name,
                "result": result.to_dict(),
                "trace": trace.to_dict(),
                "recovery_plan": recovery_plan.to_dict(),
                "recovery_result": recovery_result.to_dict(),
                "trust": trust_decision.to_dict() if trust_decision is not None else {},
            },
        )

    def _awaiting_confirmation_state(
        self,
        *,
        request: SoftwareOperationRequest,
        target: SoftwareTarget,
        plan: SoftwareOperationPlan,
    ) -> dict[str, object]:
        return {
            "family": "software_control",
            "subject": target.canonical_name,
            "task_id": str(request.task_id or ""),
            "request_type": "software_control_response",
            "query_shape": "software_control_request",
            "route": {
                "tool_name": "",
                "response_mode": "action_result",
            },
            "parameters": {
                "operation_type": request.operation_type.value,
                "target_name": target.canonical_name,
                "request_stage": "awaiting_confirmation",
                "selected_source_route": plan.selected_source.route if plan.selected_source is not None else "",
                "presentation_depth": plan.presentation_depth,
                "task_id": str(request.task_id or ""),
                "trust_request_id": request.trust_request_id,
            },
        }

    def _trust_request(
        self,
        *,
        session_id: str,
        request: SoftwareOperationRequest,
        target: SoftwareTarget,
        plan: SoftwareOperationPlan,
    ) -> TrustActionRequest:
        task_scope = PermissionScope.TASK if str(request.task_id or "").strip() else PermissionScope.ONCE
        task_id = str(request.task_id or "")
        return TrustActionRequest(
            request_id=request.request_id,
            family="software_control",
            action_key=f"software_control.{request.operation_type.value}",
            subject=target.canonical_name,
            session_id=session_id,
            task_id=task_id,
            action_kind=TrustActionKind.SOFTWARE_CONTROL,
            approval_required=self._requires_confirmation(request.operation_type),
            preview_allowed=True,
            suggested_scope=task_scope,
            available_scopes=[
                PermissionScope.ONCE,
                PermissionScope.TASK,
                PermissionScope.SESSION,
            ],
            operator_justification=(
                f"{request.operation_type.value.title()} may change local software state for {target.display_name} "
                f"through the {plan.selected_source.route if plan.selected_source is not None else 'selected'} route."
            ),
            operator_message=(
                f"Approval is required before Stormhelm can {request.operation_type.value} {target.display_name}. "
                "Choose once, task, or session."
            ),
            verification_label="Software verification remains explicit after any attempt.",
            recovery_label="Recovery will re-check trust before carrying a route switch forward.",
            task_binding_label="Software grants stay bound to the active request context.",
            details={
                "operation_type": request.operation_type.value,
                "target_name": target.canonical_name,
                "selected_source_route": plan.selected_source.route if plan.selected_source is not None else "",
                "presentation_depth": plan.presentation_depth,
            },
        )

    def _trust_scope(self, value: str | None) -> PermissionScope | None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        if normalized == PermissionScope.SESSION.value:
            return PermissionScope.SESSION
        if normalized == PermissionScope.TASK.value:
            return PermissionScope.TASK
        if normalized == PermissionScope.ONCE.value:
            return PermissionScope.ONCE
        return None

    def _merge_trust_prompt(self, message: str, trust_prompt: str) -> str:
        text = str(message or "").strip()
        prompt = str(trust_prompt or "").strip()
        if not prompt or prompt in text:
            return text
        return f"{text} {prompt}".strip()

    def _denied_response(
        self,
        *,
        request: SoftwareOperationRequest,
        target: SoftwareTarget,
        decision,
    ) -> SoftwareControlResponse:
        trace = SoftwareControlTrace(
            operation_type=request.operation_type.value,
            target_name=target.canonical_name,
            execution_status=SoftwareExecutionStatus.BLOCKED.value,
            failure_category="approval_denied",
            checkpoints=["blocked"],
        )
        result = SoftwareOperationResult(
            status=SoftwareExecutionStatus.BLOCKED,
            operation_type=request.operation_type,
            target_name=target.canonical_name,
            checkpoints=["blocked"],
            detail=decision.operator_message,
        )
        self._remember_trace(trace)
        return SoftwareControlResponse(
            assistant_response=decision.operator_message,
            response_contract={
                "bearing_title": "Software Approval Denied",
                "micro_response": decision.operator_message,
                "full_response": decision.operator_message,
            },
            trace=trace,
            result=result,
            active_request_state={},
            debug={
                "operation_type": request.operation_type.value,
                "target_name": target.canonical_name,
                "trace": trace.to_dict(),
                "result": result.to_dict(),
                "trust": decision.to_dict(),
            },
        )

    def _blocked_response(
        self,
        *,
        request: SoftwareOperationRequest,
        message: str,
        failure_category: str,
    ) -> SoftwareControlResponse:
        trace = SoftwareControlTrace(
            operation_type=request.operation_type.value,
            target_name=request.target_name,
            execution_status=SoftwareExecutionStatus.BLOCKED.value,
            failure_category=failure_category,
            checkpoints=["blocked"],
        )
        result = SoftwareOperationResult(
            status=SoftwareExecutionStatus.BLOCKED,
            operation_type=request.operation_type,
            target_name=request.target_name,
            checkpoints=["blocked"],
            detail=message,
        )
        self._remember_trace(trace)
        return SoftwareControlResponse(
            assistant_response=message,
            response_contract={
                "bearing_title": "Software Blocked",
                "micro_response": message,
                "full_response": message,
            },
            trace=trace,
            result=result,
            active_request_state={},
            debug={
                "operation_type": request.operation_type.value,
                "target_name": request.target_name,
                "result": result.to_dict(),
                "trace": trace.to_dict(),
            },
        )

    def _remember_trace(self, trace: SoftwareControlTrace) -> None:
        self._recent_traces.append(trace)

    def _completion_verb(self, operation_type: SoftwareOperationType) -> str:
        mapping = {
            SoftwareOperationType.INSTALL: "installed",
            SoftwareOperationType.UPDATE: "updated",
            SoftwareOperationType.UNINSTALL: "uninstalled",
            SoftwareOperationType.REPAIR: "repaired",
            SoftwareOperationType.LAUNCH: "launched",
            SoftwareOperationType.VERIFY: "verified",
        }
        return mapping.get(operation_type, "attempted")


def build_software_control_subsystem(
    config: SoftwareControlConfig,
    *,
    recovery: SoftwareRecoverySubsystem,
    safety: SafetyPolicy | None = None,
    system_probe: Any | None = None,
    trust_service: Any | None = None,
) -> SoftwareControlSubsystem:
    return SoftwareControlSubsystem(
        config=config,
        recovery=recovery,
        safety=safety or _NullSafetyPolicy(),
        system_probe=system_probe,
        trust_service=trust_service,
    )
