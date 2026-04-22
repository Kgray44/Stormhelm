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


class CloudFallbackDisposition(StrEnum):
    DISABLED = "disabled"
    SKIPPED = "skipped"
    ADVISORY_USED = "advisory_used"


class RecoveryPlanStatus(StrEnum):
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass(slots=True)
class FailureEvent:
    failure_id: str
    operation_type: str
    target_name: str
    stage: str
    category: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "operation_type": self.operation_type,
            "target_name": self.target_name,
            "stage": self.stage,
            "category": self.category,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(slots=True)
class TroubleshootingContext:
    failure_event: FailureEvent
    operation_plan: dict[str, Any]
    verification: dict[str, Any] | None
    local_signals: dict[str, Any]
    redacted_context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_event": self.failure_event.to_dict(),
            "operation_plan": dict(self.operation_plan),
            "verification": dict(self.verification or {}) if self.verification is not None else None,
            "local_signals": dict(self.local_signals),
            "redacted_context": dict(self.redacted_context),
        }


@dataclass(slots=True)
class RecoveryHypothesis:
    summary: str
    confidence: float
    source: str = "local"
    recommended_route: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "confidence": self.confidence,
            "source": self.source,
            "recommended_route": self.recommended_route,
        }


@dataclass(slots=True)
class RecoveryPlan:
    status: RecoveryPlanStatus
    failure_category: str
    hypotheses: list[RecoveryHypothesis] = field(default_factory=list)
    selected_hypothesis: RecoveryHypothesis | None = None
    route_switch_candidate: str | None = None
    cloud_fallback_disposition: CloudFallbackDisposition = CloudFallbackDisposition.SKIPPED
    steps: list[str] = field(default_factory=list)
    assistant_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "failure_category": self.failure_category,
            "hypotheses": _serialize(self.hypotheses),
            "selected_hypothesis": _serialize(self.selected_hypothesis),
            "route_switch_candidate": self.route_switch_candidate,
            "cloud_fallback_disposition": self.cloud_fallback_disposition.value,
            "steps": list(self.steps),
            "assistant_summary": self.assistant_summary,
        }


@dataclass(slots=True)
class RecoveryResult:
    status: str
    summary: str
    retry_performed: bool = False
    route_switched_to: str | None = None
    verification_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "retry_performed": self.retry_performed,
            "route_switched_to": self.route_switched_to,
            "verification_status": self.verification_status,
        }


@dataclass(slots=True)
class RecoveryTrace:
    failure_category: str
    status: str
    cloud_fallback_disposition: str
    redaction_applied: bool
    selected_route: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_category": self.failure_category,
            "status": self.status,
            "cloud_fallback_disposition": self.cloud_fallback_disposition,
            "redaction_applied": self.redaction_applied,
            "selected_route": self.selected_route,
        }
