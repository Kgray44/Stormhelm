from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from stormhelm.config.models import SoftwareRecoveryConfig
from stormhelm.core.software_recovery.cloud import redact_diagnostic_value
from stormhelm.core.software_recovery.models import CloudFallbackDisposition
from stormhelm.core.software_recovery.models import FailureEvent
from stormhelm.core.software_recovery.models import RecoveryHypothesis
from stormhelm.core.software_recovery.models import RecoveryPlan
from stormhelm.core.software_recovery.models import RecoveryPlanStatus
from stormhelm.core.software_recovery.models import RecoveryResult
from stormhelm.core.software_recovery.models import RecoveryTrace
from stormhelm.core.software_recovery.models import TroubleshootingContext


@dataclass(slots=True)
class SoftwareRecoverySubsystem:
    config: SoftwareRecoveryConfig
    openai_enabled: bool = False
    cloud_troubleshooter: Any | None = None
    _recent_traces: deque[RecoveryTrace] = field(default_factory=lambda: deque(maxlen=24), init=False)

    def status_snapshot(self) -> dict[str, object]:
        last_trace = self._recent_traces[-1].to_dict() if self._recent_traces else None
        return {
            "phase": "recovery1",
            "enabled": self.config.enabled,
            "cloud_fallback_enabled": self.config.cloud_fallback_enabled and self.openai_enabled,
            "capabilities": {
                "local_troubleshooting": self.config.local_troubleshooting_enabled,
                "structured_retry_planning": True,
                "safe_route_switching": True,
                "cloud_advisory_fallback": self.config.cloud_fallback_enabled,
            },
            "runtime_hooks": {
                "redaction_enabled": self.config.redaction_enabled,
                "cloud_model": self.config.cloud_fallback_model,
                "cloud_adapter_ready": self.cloud_troubleshooter is not None,
            },
            "last_trace": last_trace,
        }

    def classify_failure(self, failure_event: FailureEvent) -> str:
        category = str(failure_event.category or "").strip().lower()
        return category or "unknown_failure"

    def build_troubleshooting_context(
        self,
        *,
        failure_event: FailureEvent,
        operation_plan: dict[str, Any],
        verification: dict[str, Any] | None,
        local_signals: dict[str, Any],
    ) -> TroubleshootingContext:
        raw_context = {
            "failure_event": failure_event.to_dict(),
            "operation_plan": dict(operation_plan),
            "verification": dict(verification or {}) if verification is not None else None,
            "local_signals": dict(local_signals),
        }
        redacted = redact_diagnostic_value(raw_context) if self.config.redaction_enabled else raw_context
        return TroubleshootingContext(
            failure_event=failure_event,
            operation_plan=dict(operation_plan),
            verification=dict(verification or {}) if verification is not None else None,
            local_signals=dict(local_signals),
            redacted_context=redacted if isinstance(redacted, dict) else {},
        )

    def diagnose_failure(self, context: TroubleshootingContext) -> RecoveryPlan:
        local_hypotheses = self._local_hypotheses(context)
        selected = max(local_hypotheses, key=lambda hypothesis: hypothesis.confidence) if local_hypotheses else None
        cloud_disposition = CloudFallbackDisposition.SKIPPED
        cloud_hypotheses: list[RecoveryHypothesis] = []

        if not self.config.cloud_fallback_enabled or not self.openai_enabled:
            cloud_disposition = CloudFallbackDisposition.DISABLED
        elif self.cloud_troubleshooter is not None and self._should_use_cloud(context, selected):
            payload = self._cloud_payload(context)
            cloud_results = self.cloud_troubleshooter.diagnose(payload)
            if isinstance(cloud_results, list):
                for item in cloud_results:
                    if not isinstance(item, dict):
                        continue
                    cloud_hypotheses.append(
                        RecoveryHypothesis(
                            summary=str(item.get("summary") or "Cloud advisory proposed a bounded recovery step.").strip(),
                            confidence=float(item.get("confidence") or 0.0),
                            source="cloud",
                            recommended_route=str(item.get("recommended_route") or "").strip() or None,
                        )
                    )
            if cloud_hypotheses:
                cloud_disposition = CloudFallbackDisposition.ADVISORY_USED

        all_hypotheses = list(local_hypotheses) + list(cloud_hypotheses)
        if all_hypotheses:
            selected = max(all_hypotheses, key=lambda hypothesis: hypothesis.confidence)
        route_switch_candidate = selected.recommended_route if selected is not None else None
        plan = RecoveryPlan(
            status=RecoveryPlanStatus.READY,
            failure_category=context.failure_event.category,
            hypotheses=all_hypotheses,
            selected_hypothesis=selected,
            route_switch_candidate=route_switch_candidate,
            cloud_fallback_disposition=cloud_disposition,
            steps=self._plan_steps(context, route_switch_candidate),
            assistant_summary=selected.summary if selected is not None else "Stormhelm prepared the next bounded troubleshooting step.",
        )
        self._remember_trace(
            RecoveryTrace(
                failure_category=context.failure_event.category,
                status=plan.status.value,
                cloud_fallback_disposition=plan.cloud_fallback_disposition.value,
                redaction_applied=self.config.redaction_enabled,
                selected_route=route_switch_candidate,
            )
        )
        return plan

    def build_recovery_plan(self, context: TroubleshootingContext) -> RecoveryPlan:
        return self.diagnose_failure(context)

    def execute_recovery_plan(self, plan: RecoveryPlan) -> RecoveryResult:
        if plan.route_switch_candidate:
            return RecoveryResult(
                status="completed",
                summary=f"Recovery prepared a safe route switch to {plan.route_switch_candidate.replace('_', ' ')}.",
                retry_performed=False,
                route_switched_to=plan.route_switch_candidate,
                verification_status="unverified",
            )
        return RecoveryResult(
            status="completed",
            summary="Recovery prepared the next bounded troubleshooting step.",
            retry_performed=False,
            route_switched_to=None,
            verification_status="unverified",
        )

    def verify_recovery_result(self, result: RecoveryResult) -> dict[str, Any]:
        return {
            "status": result.verification_status or "unverified",
            "route_switched_to": result.route_switched_to,
            "retry_performed": result.retry_performed,
        }

    def _local_hypotheses(self, context: TroubleshootingContext) -> list[RecoveryHypothesis]:
        category = self.classify_failure(context.failure_event)
        if category in {"unresolved_target", "source_resolution_failed"}:
            return [
                RecoveryHypothesis(
                    summary="Try the trusted vendor route instead of the unresolved package-manager route.",
                    confidence=0.63,
                    source="local",
                    recommended_route="vendor_installer",
                )
            ]
        if category == "adapter_mismatch":
            return [
                RecoveryHypothesis(
                    summary="Route the operation through the trusted vendor installer while the package-manager executor is unavailable.",
                    confidence=0.82,
                    source="local",
                    recommended_route="vendor_installer",
                )
            ]
        if category == "verification_mismatch":
            return [
                RecoveryHypothesis(
                    summary="Re-run verification locally and compare the detected version against the expected target before claiming success.",
                    confidence=0.88,
                    source="local",
                    recommended_route=None,
                )
            ]
        return [
            RecoveryHypothesis(
                summary="Collect one more local checkpoint before changing routes or retrying.",
                confidence=0.44,
                source="local",
                recommended_route=None,
            )
        ]

    def _should_use_cloud(
        self,
        context: TroubleshootingContext,
        selected: RecoveryHypothesis | None,
    ) -> bool:
        category = self.classify_failure(context.failure_event)
        if category not in {"unresolved_target", "unknown_dialog", "unfamiliar_installer"}:
            return False
        if selected is None:
            return True
        return selected.confidence < 0.7

    def _cloud_payload(self, context: TroubleshootingContext) -> dict[str, Any]:
        payload = dict(context.redacted_context)
        payload["cloud_model"] = self.config.cloud_fallback_model
        return payload

    def _plan_steps(self, context: TroubleshootingContext, route_switch_candidate: str | None) -> list[str]:
        steps = [
            f"Classified failure category as {context.failure_event.category}.",
            "Built a bounded troubleshooting context from local signals.",
        ]
        if route_switch_candidate:
            steps.append(f"Prepared a route switch to {route_switch_candidate.replace('_', ' ')}.")
        else:
            steps.append("Prepared the next local verification step.")
        return steps[: self.config.max_recovery_steps]

    def _remember_trace(self, trace: RecoveryTrace) -> None:
        self._recent_traces.append(trace)


def build_software_recovery_subsystem(
    config: SoftwareRecoveryConfig,
    *,
    openai_enabled: bool,
    cloud_troubleshooter: Any | None = None,
) -> SoftwareRecoverySubsystem:
    return SoftwareRecoverySubsystem(
        config=config,
        openai_enabled=openai_enabled,
        cloud_troubleshooter=cloud_troubleshooter,
    )
