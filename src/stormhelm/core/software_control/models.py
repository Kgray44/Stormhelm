from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {str(key): _serialize(item) for key, item in asdict(value).items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class SoftwareOperationType(StrEnum):
    INSTALL = "install"
    UPDATE = "update"
    UNINSTALL = "uninstall"
    REPAIR = "repair"
    LAUNCH = "launch"
    VERIFY = "verify"


class SoftwareSourceKind(StrEnum):
    PACKAGE_MANAGER = "package_manager"
    VENDOR_INSTALLER = "vendor_installer"
    BROWSER_GUIDED = "browser_guided"


class SoftwareTrustLevel(StrEnum):
    TRUSTED = "trusted"
    KNOWN = "known"
    UNVERIFIED = "unverified"


class SoftwareCheckpointStatus(StrEnum):
    FOUND = "found"
    LIKELY_FOUND = "likely_found"
    PREPARED = "prepared"
    WAITING_CONFIRMATION = "waiting_confirmation"
    DOWNLOADED = "downloaded"
    LAUNCHED = "launched"
    ATTEMPTED = "attempted"
    COMPLETED = "completed"
    VERIFIED = "verified"
    BLOCKED = "blocked"
    FAILED = "failed"
    PARTIALLY_COMPLETE = "partially_complete"
    UNCERTAIN = "uncertain"


class SoftwareExecutionStatus(StrEnum):
    PREPARED = "prepared"
    WAITING_CONFIRMATION = "waiting_confirmation"
    ATTEMPTED = "attempted"
    COMPLETED = "completed"
    VERIFIED = "verified"
    BLOCKED = "blocked"
    FAILED = "failed"
    PARTIALLY_COMPLETE = "partially_complete"
    RECOVERY_IN_PROGRESS = "recovery_in_progress"
    UNCERTAIN = "uncertain"


class SoftwareVerificationStatus(StrEnum):
    VERIFIED = "verified"
    ABSENT = "absent"
    MISMATCH = "mismatch"
    UNVERIFIED = "unverified"
    UNCERTAIN = "uncertain"


class SoftwareInstallState(StrEnum):
    INSTALLED = "installed"
    ABSENT = "absent"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class SoftwareRouteDisposition(StrEnum):
    NOT_REQUESTED = "not_requested"
    FEATURE_DISABLED = "feature_disabled"
    ROUTING_DISABLED = "routing_disabled"
    DIRECT_REQUEST = "direct_request"
    FOLLOW_UP_CONFIRMATION = "follow_up_confirmation"


@dataclass(slots=True)
class SoftwareTarget:
    canonical_name: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    package_ids: dict[str, str] = field(default_factory=dict)
    vendor_url: str | None = None
    browser_query: str | None = None
    launch_names: list[str] = field(default_factory=list)
    install_state: SoftwareInstallState = SoftwareInstallState.UNKNOWN
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "display_name": self.display_name,
            "aliases": list(self.aliases),
            "package_ids": dict(self.package_ids),
            "vendor_url": self.vendor_url,
            "browser_query": self.browser_query,
            "launch_names": list(self.launch_names),
            "install_state": self.install_state.value,
            "description": self.description,
        }


@dataclass(slots=True)
class SoftwareSource:
    kind: SoftwareSourceKind
    route: str
    label: str
    locator: str
    trust_level: SoftwareTrustLevel = SoftwareTrustLevel.TRUSTED
    requires_browser: bool = False
    requires_elevation: bool = False
    policy_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "route": self.route,
            "label": self.label,
            "locator": self.locator,
            "trust_level": self.trust_level.value,
            "requires_browser": self.requires_browser,
            "requires_elevation": self.requires_elevation,
            "policy_notes": list(self.policy_notes),
        }


@dataclass(slots=True)
class SoftwarePlanStep:
    title: str
    status: SoftwareCheckpointStatus
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass(slots=True)
class SoftwareOperationPlan:
    operation_type: SoftwareOperationType
    target: SoftwareTarget
    sources: list[SoftwareSource] = field(default_factory=list)
    selected_source: SoftwareSource | None = None
    presentation_depth: str = "ghost"
    requires_command_deck: bool = False
    steps: list[SoftwarePlanStep] = field(default_factory=list)
    response_contract: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_type": self.operation_type.value,
            "target": self.target.to_dict(),
            "sources": _serialize(self.sources),
            "selected_source": _serialize(self.selected_source),
            "presentation_depth": self.presentation_depth,
            "requires_command_deck": self.requires_command_deck,
            "steps": _serialize(self.steps),
            "response_contract": dict(self.response_contract),
        }


@dataclass(slots=True)
class SoftwareOperationRequest:
    request_id: str
    source_surface: str
    raw_input: str
    user_visible_text: str
    operation_type: SoftwareOperationType
    target_name: str
    request_stage: str = "prepare_plan"
    follow_up_reuse: bool = False
    selected_source_route: str | None = None
    task_id: str | None = None
    trust_request_id: str | None = None
    approval_scope: str | None = None
    approval_outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "source_surface": self.source_surface,
            "raw_input": self.raw_input,
            "user_visible_text": self.user_visible_text,
            "operation_type": self.operation_type.value,
            "target_name": self.target_name,
            "request_stage": self.request_stage,
            "follow_up_reuse": self.follow_up_reuse,
            "selected_source_route": self.selected_source_route,
            "task_id": self.task_id,
            "trust_request_id": self.trust_request_id,
            "approval_scope": self.approval_scope,
            "approval_outcome": self.approval_outcome,
        }


@dataclass(slots=True)
class SoftwareOperationResult:
    status: SoftwareExecutionStatus
    operation_type: SoftwareOperationType
    target_name: str
    selected_source: SoftwareSource | None = None
    install_state: SoftwareInstallState = SoftwareInstallState.UNKNOWN
    verification_status: SoftwareVerificationStatus = SoftwareVerificationStatus.UNVERIFIED
    checkpoints: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "operation_type": self.operation_type.value,
            "target_name": self.target_name,
            "selected_source": _serialize(self.selected_source),
            "install_state": self.install_state.value,
            "verification_status": self.verification_status.value,
            "checkpoints": list(self.checkpoints),
            "evidence": list(self.evidence),
            "detail": self.detail,
        }


@dataclass(slots=True)
class SoftwareVerificationResult:
    status: SoftwareVerificationStatus
    install_state: SoftwareInstallState
    detail: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "install_state": self.install_state.value,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass(slots=True)
class SoftwareControlTrace:
    operation_type: str
    target_name: str
    route_selected: str | None = None
    execution_status: str = SoftwareExecutionStatus.UNCERTAIN.value
    verification_status: str | None = None
    recovery_invoked: bool = False
    presentation_depth: str = "ghost"
    follow_up_reuse: bool = False
    source_candidates: list[dict[str, Any]] = field(default_factory=list)
    policy_decisions: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)
    uncertain_points: list[str] = field(default_factory=list)
    failure_category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_type": self.operation_type,
            "target_name": self.target_name,
            "route_selected": self.route_selected,
            "execution_status": self.execution_status,
            "verification_status": self.verification_status,
            "recovery_invoked": self.recovery_invoked,
            "presentation_depth": self.presentation_depth,
            "follow_up_reuse": self.follow_up_reuse,
            "source_candidates": _serialize(self.source_candidates),
            "policy_decisions": _serialize(self.policy_decisions),
            "checkpoints": list(self.checkpoints),
            "uncertain_points": list(self.uncertain_points),
            "failure_category": self.failure_category,
        }


@dataclass(slots=True)
class SoftwarePlannerEvaluation:
    candidate: bool
    disposition: SoftwareRouteDisposition
    operation_type: str | None = None
    target_name: str | None = None
    request_stage: str = "prepare_plan"
    feature_enabled: bool = False
    planner_routing_enabled: bool = False
    follow_up_reuse: bool = False
    approval_scope: str | None = None
    approval_outcome: str | None = None
    trust_request_id: str | None = None
    route_confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "disposition": self.disposition.value,
            "operation_type": self.operation_type,
            "target_name": self.target_name,
            "request_stage": self.request_stage,
            "feature_enabled": self.feature_enabled,
            "planner_routing_enabled": self.planner_routing_enabled,
            "follow_up_reuse": self.follow_up_reuse,
            "approval_scope": self.approval_scope,
            "approval_outcome": self.approval_outcome,
            "trust_request_id": self.trust_request_id,
            "route_confidence": self.route_confidence,
            "reasons": list(self.reasons),
        }


@dataclass(slots=True)
class SoftwareControlResponse:
    assistant_response: str
    response_contract: dict[str, str]
    trace: SoftwareControlTrace
    result: SoftwareOperationResult | None = None
    verification: SoftwareVerificationResult | None = None
    recovery_plan: Any | None = None
    recovery_result: Any | None = None
    active_request_state: dict[str, object] | None = None
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assistant_response": self.assistant_response,
            "response_contract": dict(self.response_contract),
            "trace": self.trace.to_dict(),
            "result": _serialize(self.result),
            "verification": _serialize(self.verification),
            "recovery_plan": _serialize(self.recovery_plan),
            "recovery_result": _serialize(self.recovery_result),
            "active_request_state": dict(self.active_request_state or {}),
            "debug": dict(self.debug),
        }
