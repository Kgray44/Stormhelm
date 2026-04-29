from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any

from stormhelm.core.context_snapshots import SNAPSHOT_POLICIES
from stormhelm.core.latency import safe_latency_value
from stormhelm.core.subsystem_continuations import default_subsystem_continuation_registry


class AuditStatus(str, Enum):
    LIVE_USED = "live_used"
    PARTIAL_USED = "partial_used"
    SCAFFOLD_ONLY = "scaffold_only"
    POLICY_ONLY = "policy_only"
    TEST_ONLY = "test_only"
    FUTURE_DEFERRED = "future_deferred"
    DEAD_UNUSED = "dead_unused"
    UNKNOWN = "unknown"


class AuditRecommendation(str, Enum):
    KEEP = "keep"
    WIRE_NOW = "wire_now"
    LABEL_FUTURE = "label_future"
    DEFER_TO_PHASE = "defer_to_phase"
    REMOVE_OR_SIMPLIFY = "remove_or_simplify"
    INVESTIGATE = "investigate"


@dataclass(frozen=True, slots=True)
class LatencyIntegrationInventoryItem:
    feature_id: str
    phase_introduced: str
    feature_name: str
    category: str
    source_files: tuple[str, ...] = ()
    models_or_functions: tuple[str, ...] = ()
    config_flags: tuple[str, ...] = ()
    runtime_entrypoints: tuple[str, ...] = ()
    normal_path_usage: str = ""
    test_coverage: tuple[str, ...] = ()
    status_surface: tuple[str, ...] = ()
    trace_fields: tuple[str, ...] = ()
    kraken_fields: tuple[str, ...] = ()
    current_status: AuditStatus = AuditStatus.UNKNOWN
    evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    risk_if_left_as_is: str = ""
    recommended_action: AuditRecommendation = AuditRecommendation.INVESTIGATE
    recommended_phase: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["current_status"] = self.current_status.value
        payload["recommended_action"] = self.recommended_action.value
        return safe_latency_value(payload)


@dataclass(frozen=True, slots=True)
class LatencyIntegrationAudit:
    audit_id: str = "latency_integration_audit_l5a"
    scope: str = "Stormhelm latency/async/worker/voice stack L0-L5"
    generated_by: str = "stormhelm.core.latency_integration_audit.build_latency_integration_audit"
    items: tuple[LatencyIntegrationInventoryItem, ...] = ()
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "scope": self.scope,
            "generated_by": self.generated_by,
            "summary": safe_latency_value(dict(self.summary)),
            "items": [item.to_dict() for item in self.items],
        }


def build_latency_integration_audit() -> LatencyIntegrationAudit:
    registry = default_subsystem_continuation_registry()
    registered = {item["operation_kind"]: item for item in registry.describe_all()}
    snapshot_families = tuple(sorted(SNAPSHOT_POLICIES))
    items: list[LatencyIntegrationInventoryItem] = [
        _item(
            "l0.latency_trace_contract",
            "L0",
            "Unified latency trace contract",
            "L0 tracing",
            source_files=("src/stormhelm/core/latency.py",),
            models_or_functions=("LatencyTrace", "LatencyStage", "LatencyBudget", "LatencyBudgetResult"),
            runtime_entrypoints=("attach_latency_metadata",),
            normal_path_usage="Normal responses normalize stage timings into latency_trace and latency_summary.",
            test_coverage=("tests/test_latency_l0_tracing.py",),
            status_surface=("assistant_message.metadata.latency_trace", "assistant_message.metadata.latency_summary"),
            trace_fields=("latency_trace", "latency_summary", "stage_timings_ms", "budget_result"),
            kraken_fields=("total_latency_ms", "longest_stage", "budget_label"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("LatencyTrace.to_dict is used by attach_latency_metadata.", "L0 tests exercise serialization, budgets, redaction, and longest stage."),
            risk="Low; keep as the common contract.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l0.chat_send_metadata",
            "L0",
            "/chat/send timing metadata",
            "L0 tracing",
            source_files=("src/stormhelm/core/api/app.py", "src/stormhelm/core/orchestrator/assistant.py"),
            models_or_functions=("attach_latency_metadata", "AssistantOrchestrator.handle_message"),
            runtime_entrypoints=("/chat/send",),
            normal_path_usage="/chat/send preserves stage_timings_ms and attaches latency_trace, latency_summary, and budget_result.",
            test_coverage=("tests/test_latency_l0_tracing.py", "tests/test_assistant_orchestrator.py"),
            status_surface=("assistant_message.metadata.stage_timings_ms", "assistant_message.metadata.latency_summary"),
            trace_fields=("endpoint_dispatch_ms", "endpoint_return_to_asgi_ms", "response_serialization_ms"),
            kraken_fields=("stage_timings_ms", "latency_trace"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("FastAPI endpoint adds endpoint return timings before serialization.", "Assistant tests assert latency metadata remains present."),
            risk="Low; payload size remains bounded by trace serializers.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l0.command_eval_latency_projection",
            "L0",
            "Command eval and Kraken latency rows",
            "L0 tracing",
            source_files=("src/stormhelm/core/orchestrator/command_eval/models.py", "src/stormhelm/core/orchestrator/command_eval/report.py"),
            models_or_functions=("CommandEvalResult.to_row", "build_latency_report"),
            runtime_entrypoints=("command evaluation runner",),
            normal_path_usage="Command evaluation rows project latency_summary into row fields and aggregate p95/max metrics.",
            test_coverage=("tests/test_command_usability_evaluation.py", "tests/test_latency_l0_tracing.py"),
            status_surface=("command eval JSON/Markdown reports",),
            trace_fields=("longest_stage", "longest_stage_ms"),
            kraken_fields=("p50", "p90", "p95", "p99", "max"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("CommandEvalResult.to_row copies latency trace and summary fields.", "Report aggregation includes route/stage latency summaries."),
            risk="Low; scoring calibration remains separate from correctness.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l0.voice_latency_projection",
            "L0",
            "Voice latency summary compatibility",
            "L0 tracing",
            source_files=("src/stormhelm/core/voice/evaluation.py", "src/stormhelm/core/latency.py"),
            models_or_functions=("VoiceLatencyBreakdown", "VoiceLatencyBreakdown.to_latency_summary"),
            runtime_entrypoints=("voice evaluation",),
            normal_path_usage="Voice evaluation projects voice marks into the unified latency summary shape.",
            test_coverage=("tests/test_voice_latency_instrumentation.py", "tests/test_latency_l5_voice_streaming_first_audio.py"),
            status_surface=("voice latency summary",),
            trace_fields=("voice_involved", "voice_first_audio_ms"),
            kraken_fields=("voice_first_audio_ms", "voice_core_to_first_audio_ms"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("VoiceLatencyBreakdown emits L0-compatible fields.", "L5 tests assert first-audio projection remains serializable."),
            risk="Low; real device benchmarks are still a separate L5.1 proof need.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l1.route_latency_policy",
            "L1",
            "Route latency policy and execution modes",
            "L1 budgets and partial response",
            source_files=("src/stormhelm/core/latency.py", "src/stormhelm/core/orchestrator/route_triage.py", "src/stormhelm/core/api/app.py"),
            models_or_functions=("RouteLatencyPolicy", "RouteExecutionMode", "classify_route_latency_policy"),
            runtime_entrypoints=("AssistantOrchestrator.handle_message", "voice action endpoints",),
            normal_path_usage="Route family, request kind, and fail-fast state select budget labels and execution mode for response metadata.",
            test_coverage=("tests/test_latency_l1_budget_partial_response.py",),
            status_surface=("assistant_message.metadata.latency_policy", "assistant_message.metadata.execution_mode"),
            trace_fields=("budget_label", "execution_mode", "first_feedback_ms", "fail_fast_reason"),
            kraken_fields=("execution_mode", "budget_exceeded_by_execution_mode", "fail_fast_reasons"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("classify_route_latency_policy is called from latency metadata attachment and voice action responses.", "L1 tests cover budget labels, execution modes, and fail-fast fields."),
            risk="Low; budgets are diagnostic and posture-oriented, not success criteria.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l1.partial_response_posture",
            "L1",
            "Partial response posture",
            "L1 budgets and partial response",
            source_files=("src/stormhelm/core/latency.py", "src/stormhelm/core/orchestrator/assistant.py"),
            models_or_functions=("build_partial_response_posture",),
            runtime_entrypoints=("attach_latency_metadata", "AssistantOrchestrator._emit_first_feedback_event"),
            normal_path_usage="Metadata and first-feedback events expose plan-first, async-first, blocked, or unsupported posture without claiming completion.",
            test_coverage=("tests/test_latency_l1_budget_partial_response.py", "tests/test_latency_l4_async_progress.py"),
            status_surface=("assistant_message.metadata.partial_response", "latency.first_feedback_ready"),
            trace_fields=("partial_response_returned", "async_continuation", "budget_exceeded_continuing"),
            kraken_fields=("partial_response_returned", "async_expected", "budget_exceeded_continuing"),
            current_status=AuditStatus.PARTIAL_USED,
            evidence=("Partial posture is attached to normal metadata.", "Actual non-blocking return depends on route/tool async seams."),
            missing=("Not every plan-first or async-expected subsystem has a real continuation front half."),
            risk="Medium; route-dependent coverage can be mistaken for universal async behavior.",
            action=AuditRecommendation.DEFER_TO_PHASE,
            phase_next="L5.1/L6",
        ),
        _item(
            "l1.fail_fast_posture",
            "L1",
            "Fail-fast unavailable or blocked posture",
            "L1 budgets and partial response",
            source_files=("src/stormhelm/core/orchestrator/assistant.py", "src/stormhelm/core/api/app.py", "src/stormhelm/core/latency.py"),
            models_or_functions=("_fail_fast_reason_from_debug", "_voice_fail_fast_reason"),
            runtime_entrypoints=("/chat/send", "voice control endpoints"),
            normal_path_usage="Provider disabled, voice unavailable, playback disabled, and unsupported route states surface fail_fast_reason.",
            test_coverage=("tests/test_latency_l1_budget_partial_response.py",),
            status_surface=("assistant_message.metadata.fail_fast_reason", "voice action response metadata"),
            trace_fields=("fail_fast_reason", "execution_mode"),
            kraken_fields=("fail_fast_reason", "fail_fast_count"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("Provider-disabled and voice/playback-disabled cases are tested.", "Fail-fast reason flows into trace and Kraken rows."),
            risk="Low; remains a truth/reporting field, not a route bypass.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l2.fast_route_classifier",
            "L2",
            "Fast route triage classifier",
            "L2 route triage",
            source_files=("src/stormhelm/core/orchestrator/route_triage.py", "src/stormhelm/core/orchestrator/assistant.py", "src/stormhelm/core/orchestrator/planner.py"),
            models_or_functions=("FastRouteClassifier", "RouteTriageResult", "route_triage_from_dict"),
            runtime_entrypoints=("AssistantOrchestrator.handle_message", "DeterministicPlanner.plan"),
            normal_path_usage="/chat/send runs triage before planner and passes advisory route hints into deterministic planning.",
            test_coverage=("tests/test_latency_l2_fast_route_triage.py",),
            status_surface=("assistant_message.metadata.route_triage_result", "planner_debug.route_triage"),
            trace_fields=("route_triage_ms", "likely_route_families", "skipped_route_families"),
            kraken_fields=("route_triage_ms", "fast_path_used", "provider_fallback_suppressed_reason"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("AssistantOrchestrator constructs FastRouteClassifier and records route_triage_ms every request.", "Planner uses triage to skip unrelated seams when confidence is high."),
            risk="Low; triage remains advisory and does not execute actions.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l2.provider_fallback_suppression",
            "L2",
            "Native route provider fallback suppression",
            "L2 route triage",
            source_files=("src/stormhelm/core/orchestrator/planner.py", "src/stormhelm/core/latency.py"),
            models_or_functions=("DeterministicPlanner._plan_with_route_triage",),
            runtime_entrypoints=("DeterministicPlanner.plan",),
            normal_path_usage="Confident native triage marks provider fallback as ineligible and records suppression reason.",
            test_coverage=("tests/test_latency_l2_fast_route_triage.py",),
            status_surface=("planner_debug.provider_fallback_suppressed_reason",),
            trace_fields=("provider_fallback_eligible", "provider_fallback_suppressed_reason"),
            kraken_fields=("provider_fallback_suppressed_count", "native_route_protection_count"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("Calculation and browser tests assert native_route_triage suppression.",),
            risk="Low; open-ended requests can still use provider fallback when eligible.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l3.context_snapshot_store",
            "L3",
            "Context snapshot store and hot-path lookups",
            "L3 context snapshots",
            source_files=("src/stormhelm/core/context_snapshots.py", "src/stormhelm/core/orchestrator/assistant.py"),
            models_or_functions=("ContextSnapshot", "ContextSnapshotStore", "_prepare_context_snapshots"),
            runtime_entrypoints=("AssistantOrchestrator.handle_message", "AssistantOrchestrator._workspace_summary_for_request"),
            normal_path_usage="/chat/send uses provider, active request, workspace, software, Discord, screen, task, and voice snapshots depending on route triage.",
            test_coverage=("tests/test_latency_l3_context_snapshots.py",),
            status_surface=("planner_debug.context_snapshots",),
            trace_fields=("snapshots_checked", "snapshots_used", "snapshot_hot_path_hit", "snapshot_miss_reason"),
            kraken_fields=("snapshot_hot_path_hit", "snapshot_miss_reason", "heavy_context_avoided_by_snapshot"),
            current_status=AuditStatus.LIVE_USED,
            evidence=(f"Snapshot policy registry has {len(snapshot_families)} families.", "Assistant records snapshot activity into planner debug and trace metadata."),
            risk="Low for populated families; policy-only families are itemized separately.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l3.snapshot_family_policy_matrix",
            "L3",
            "Snapshot family policy matrix",
            "L3 context snapshots",
            source_files=("src/stormhelm/core/context_snapshots.py",),
            models_or_functions=("SNAPSHOT_POLICIES", "ContextSnapshotPolicy"),
            runtime_entrypoints=("ContextSnapshotPolicy.for_family",),
            normal_path_usage="Policies bound TTL, stale-use, deictic, routing, and verification posture for each declared family.",
            test_coverage=("tests/test_latency_l3_context_snapshots.py",),
            status_surface=("planner_debug.context_snapshots", "ContextSnapshotStore.safe_debug_payload"),
            trace_fields=("snapshot_freshness", "snapshot_age_ms", "freshness_warnings"),
            kraken_fields=("snapshot_age_ms", "freshness_warnings"),
            current_status=AuditStatus.PARTIAL_USED,
            evidence=("All declared policies serialize and enforce freshness behavior.", "Only a subset of families are refreshed by current request paths."),
            missing=("Several families rely on TTL and future invalidation rather than live event hooks.",),
            risk="Medium; policy breadth can read like full runtime coverage unless docs distinguish it.",
            action=AuditRecommendation.LABEL_FUTURE,
            phase_next="L5.1/L6",
            notes=f"Policy families: {', '.join(snapshot_families)}",
        ),
        _item(
            "l3.snapshot_invalidation_hooks",
            "L3",
            "Snapshot invalidation hooks",
            "L3 context snapshots",
            source_files=("src/stormhelm/core/orchestrator/assistant.py", "src/stormhelm/core/context_snapshots.py"),
            models_or_functions=("ContextSnapshotStore.invalidate", "ContextSnapshotStore.prune_expired"),
            runtime_entrypoints=("workspace mutation direct tools",),
            normal_path_usage="Workspace mutation tools invalidate active workspace snapshots; other families primarily age out by TTL.",
            test_coverage=("tests/test_latency_l3_context_snapshots.py",),
            status_surface=("planner_debug.context_snapshots.snapshots_invalidated",),
            trace_fields=("snapshots_invalidated", "invalidation_count"),
            kraken_fields=("invalidation_count",),
            current_status=AuditStatus.PARTIAL_USED,
            evidence=("Workspace save/restore/clear/archive/rename/tag invalidates active workspace cache.",),
            missing=("Trust, Discord, screen, clipboard, provider, network, and voice invalidation are not broadly event-driven yet.",),
            risk="Medium; stale-vs-current truth relies on TTL for many families.",
            action=AuditRecommendation.DEFER_TO_PHASE,
            phase_next="L5.1/L6",
        ),
        _item(
            "l4.async_route_progress_contract",
            "L4",
            "Async route progress contract",
            "L4 async progress",
            source_files=("src/stormhelm/core/async_routes.py", "src/stormhelm/core/orchestrator/assistant.py"),
            models_or_functions=("AsyncRouteDecision", "RouteProgressState", "AsyncRouteHandle", "AsyncRouteContinuation"),
            runtime_entrypoints=("AssistantOrchestrator._handle_job_backed_tool",),
            normal_path_usage="Registered async tools can return an initial response and job/progress handle while work continues.",
            test_coverage=("tests/test_latency_l4_async_progress.py",),
            status_surface=("assistant_message.metadata.async_route_handle", "job.progress events"),
            trace_fields=("async_strategy", "async_initial_response_returned", "route_continuation_id"),
            kraken_fields=("async_initial_response_returned", "event_progress_required_count"),
            current_status=AuditStatus.PARTIAL_USED,
            evidence=("Async route metadata and events are live for job-backed async tools.", "Broad direct subsystem routes still need explicit continuation front halves."),
            missing=("Most production direct subsystem handlers remain sync unless routed through a registered async tool/continuation."),
            risk="Medium; async contract exists but is not universal route behavior.",
            action=AuditRecommendation.DEFER_TO_PHASE,
            phase_next="L5.1/L6",
        ),
        _item(
            "l41.job_manager_lane_timing",
            "L4.1",
            "Worker lane metadata and queue/run timing",
            "L4.1 worker scheduler",
            source_files=("src/stormhelm/core/jobs/manager.py", "src/stormhelm/core/jobs/models.py", "src/stormhelm/core/worker_utilization.py"),
            models_or_functions=("WorkerLane", "WorkerPriorityLevel", "JobManager.submit", "JobRecord.timing_summary"),
            runtime_entrypoints=("JobManager.submit", "ToolExecutor.execute"),
            normal_path_usage="Every queued job records lane, priority, queue wait, run time, total time, worker index, and submit-time worker pressure.",
            test_coverage=("tests/test_latency_l41_worker_utilization.py", "tests/test_job_manager.py"),
            status_surface=("/status.worker_state", "job lifecycle events"),
            trace_fields=("worker_lane", "queue_wait_ms", "job_run_ms", "job_total_ms"),
            kraken_fields=("worker_lane", "queue_wait_ms", "job_run_ms", "job_total_ms"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("JobManager.submit stamps lane and pressure metadata.", "Progress and lifecycle event payloads include safe worker timing."),
            risk="Low; queue timing is observed separately from run timing.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l41.background_refresh_hook",
            "L4.1",
            "Safe background refresh hook",
            "L4.1 worker scheduler",
            source_files=("src/stormhelm/core/jobs/manager.py",),
            models_or_functions=("JobManager.submit_background_refresh",),
            runtime_entrypoints=("manual/internal callers",),
            normal_path_usage="Helper submits background-lane maintenance jobs, but broad snapshot refresh coverage is not wired into normal request paths.",
            test_coverage=("tests/test_latency_l41_worker_utilization.py",),
            status_surface=("job lifecycle events",),
            trace_fields=("worker_lane", "background_job_count"),
            kraken_fields=("background_job_count",),
            current_status=AuditStatus.SCAFFOLD_ONLY,
            evidence=("submit_background_refresh uses background lane and maintenance priority.",),
            missing=("No broad runtime policy currently schedules provider, voice, network, telemetry, or snapshot-prune refresh jobs automatically.",),
            risk="Medium; hook can be mistaken for refresh coverage.",
            action=AuditRecommendation.LABEL_FUTURE,
            phase_next="L5.1/L6",
        ),
        _item(
            "l41.inline_fast_path_protection",
            "L4.1",
            "Inline fast-path protection",
            "L4.1 worker scheduler",
            source_files=("src/stormhelm/core/worker_utilization.py", "src/stormhelm/core/orchestrator/assistant.py"),
            models_or_functions=("classify_worker_route_policy", "INLINE_FAST_ROUTE_FAMILIES"),
            runtime_entrypoints=("worker route policy", "/chat/send direct paths"),
            normal_path_usage="Calculations, trust approvals, voice stop-speaking, browser destinations, and simple clarification remain inline unless a route explicitly requires work.",
            test_coverage=("tests/test_latency_l41_worker_utilization.py", "tests/test_latency_l2_fast_route_triage.py"),
            status_surface=("latency_summary.worker_lane",),
            trace_fields=("worker_lane", "worker_priority"),
            kraken_fields=("worker_lane", "worker_priority"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("Policy returns use_worker=false for cheap deterministic route families.", "Tests assert calculations/trust/voice/direct URL are not queued."),
            risk="Low; protects Ghost hot path.",
            action=AuditRecommendation.KEEP,
        ),
        _item(
            "l42.workspace_assemble_deep_continuation",
            "L4.2",
            "Workspace assemble deep subsystem continuation",
            "L4.2/L4.3 subsystem continuations",
            source_files=("src/stormhelm/core/orchestrator/assistant.py", "src/stormhelm/core/subsystem_continuations.py"),
            models_or_functions=("AssistantOrchestrator._queue_workspace_assembly_continuation", "_run_workspace_assemble"),
            runtime_entrypoints=("AssistantOrchestrator._queue_workspace_assembly_continuation", "subsystem_continuation tool"),
            normal_path_usage="/chat/send workspace_assemble direct tool path queues a subsystem_continuation job and returns before worker completion.",
            test_coverage=("tests/test_latency_l42_subsystem_continuations.py",),
            status_surface=("subsystem.continuation.created events", "assistant_message.metadata.subsystem_continuation"),
            trace_fields=("subsystem_continuation_created", "returned_before_subsystem_completion", "inline_front_half_ms"),
            kraken_fields=("subsystem_continuation_kind", "direct_subsystem_async_converted"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("Workspace assemble front half creates a JobManager job in AssistantOrchestrator.", "Registry handler is implemented and tested."),
            risk="Low; completion and verification claims are clamped.",
            action=AuditRecommendation.KEEP,
        ),
        _continuation_item(
            feature_id="l43.workspace_restore_deep_continuation",
            phase="L4.3",
            operation_kind="workspace.restore_deep",
            registry_status=registered.get("workspace.restore_deep", {}),
            status=AuditStatus.PARTIAL_USED,
            missing=("handler registered but not automatically created by /chat/send front half",),
            phase_next="L5.1",
        ),
        _continuation_item(
            feature_id="l43.software_verify_operation_continuation",
            phase="L4.3",
            operation_kind="software_control.verify_operation",
            registry_status=registered.get("software_control.verify_operation", {}),
            status=AuditStatus.PARTIAL_USED,
            missing=("handler registered and tested through runner, but broad software routes do not automatically offload verification yet",),
            phase_next="L5.1",
        ),
        _continuation_item(
            feature_id="l43.software_recovery_plan_continuation",
            phase="L4.3",
            operation_kind="software_recovery.run_recovery_plan",
            registry_status=registered.get("software_recovery.run_recovery_plan", {}),
            status=AuditStatus.PARTIAL_USED,
            missing=("handler registered and tested through runner, but direct recovery routes are not broadly converted to continuation front halves",),
            phase_next="L5.1",
        ),
        _continuation_item(
            feature_id="l43.discord_dispatch_approved_preview_continuation",
            phase="L4.3",
            operation_kind="discord_relay.dispatch_approved_preview",
            registry_status=registered.get("discord_relay.dispatch_approved_preview", {}),
            status=AuditStatus.PARTIAL_USED,
            missing=("handler registered and freshness-gated, but dispatch front-half conversion remains narrow/manual",),
            phase_next="L5.1",
        ),
        _continuation_item(
            feature_id="l43.network_live_diagnosis_continuation",
            phase="L4.3",
            operation_kind="network.run_live_diagnosis",
            registry_status=registered.get("network.run_live_diagnosis", {}),
            status=AuditStatus.PARTIAL_USED,
            missing=("handler registered and tested through runner, but normal network route conversion is not broad",),
            phase_next="L5.1",
        ),
        _item(
            "l43.screen_awareness_verify_change_continuation",
            "L4.3",
            "Screen awareness verify-change continuation",
            "L4.2/L4.3 subsystem continuations",
            source_files=("src/stormhelm/core/subsystem_continuations.py", "src/stormhelm/core/orchestrator/command_eval/report.py"),
            models_or_functions=("classify_subsystem_continuation", "SubsystemContinuationRegistry.describe"),
            runtime_entrypoints=("policy classification only",),
            normal_path_usage="Policy knows screen_awareness.verify_change, but no default handler is registered.",
            test_coverage=("tests/test_latency_l42_subsystem_continuations.py", "tests/test_latency_l44_async_validation.py"),
            status_surface=("async coverage audit",),
            trace_fields=("subsystem_continuation_handler_missing_reason",),
            kraken_fields=("async_coverage_audit.status_by_handler.screen_awareness.verify_change",),
            current_status=AuditStatus.POLICY_ONLY,
            evidence=("Policy classifies verify_change as continuation-expected.", "L4.4 coverage audit expects continuation_handler_missing."),
            missing=("No registered handler and no normal /chat/send front-half creation.",),
            risk="Medium; this is the clearest decorative-pipe risk if not labeled.",
            action=AuditRecommendation.DEFER_TO_PHASE,
            phase_next="L5.1/L6",
        ),
        _item(
            "l42.software_execute_approved_operation_continuation",
            "L4.2",
            "Software execute-approved-operation continuation",
            "L4.2/L4.3 subsystem continuations",
            source_files=("src/stormhelm/core/subsystem_continuations.py", "src/stormhelm/core/worker_utilization.py"),
            models_or_functions=("CONTINUATION_OPERATION_KINDS", "DEFAULT_SUBSYSTEM_CONCURRENCY_CAPS"),
            runtime_entrypoints=("policy classification only",),
            normal_path_usage="Policy and cap keys know the operation, but authority/trust front-half conversion is intentionally deferred.",
            test_coverage=("tests/test_latency_l44_async_validation.py",),
            status_surface=("async coverage audit",),
            trace_fields=("async_conversion_missing_reason",),
            kraken_fields=("async_coverage_audit",),
            current_status=AuditStatus.POLICY_ONLY,
            evidence=("L4.4 report marks execute-approved-operation as later/needs trust seam first.",),
            missing=("No default handler and no automatic conversion from approved software execution route.",),
            risk="High if mislabeled because side-effect execution must not move into workers without trust-proofed front half.",
            action=AuditRecommendation.DEFER_TO_PHASE,
            phase_next="L6",
        ),
        _item(
            "l44.validation_and_kraken_reporting",
            "L4.4",
            "Async validation, coverage audit, and tail classification",
            "L4.4 validation and Kraken",
            source_files=("src/stormhelm/core/orchestrator/command_eval/report.py",),
            models_or_functions=("augment_l44_async_validation", "validate_l44_truth_clamps", "assess_l44_scheduler_pressure"),
            runtime_entrypoints=("command evaluation report builder",),
            normal_path_usage="Kraken/command evaluation aggregates include async coverage, truth clamps, scheduler pressure, and tail categories from rows.",
            test_coverage=("tests/test_latency_l44_async_validation.py",),
            status_surface=("command eval report JSON/Markdown",),
            trace_fields=("continuation_truth_clamps_applied", "scheduler_pressure_state"),
            kraken_fields=("l44_async_validation", "tail_latency_classification"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("Report builder derives coverage and truth clamp findings from rows.", "Tests cover implemented, missing, and unsafe-claim cases."),
            risk="Medium; Kraken scoring still needs calibration after partial-response behavior changes.",
            action=AuditRecommendation.KEEP,
            phase_next="L5.1",
        ),
        _item(
            "l45.priority_scheduler_and_caps",
            "L4.5",
            "Priority scheduler, protected capacity, and subsystem caps",
            "L4.5 scheduler hardening",
            source_files=("src/stormhelm/core/jobs/manager.py", "src/stormhelm/core/worker_utilization.py"),
            models_or_functions=("JobManager._select_eligible_pending_index", "SchedulerPolicy", "DEFAULT_SUBSYSTEM_CONCURRENCY_CAPS"),
            runtime_entrypoints=("JobManager worker loop",),
            normal_path_usage="Queued jobs are selected by priority/lane order and blocked by background protected capacity or subsystem caps when needed.",
            test_coverage=("tests/test_latency_l45_scheduler_hardening.py",),
            status_surface=("/status.worker_state", "job lifecycle events"),
            trace_fields=("scheduler_strategy", "scheduler_pressure_state", "subsystem_cap_key", "protected_capacity_wait_reason"),
            kraken_fields=("scheduler_pressure_state", "subsystem_cap_key", "queue_wait_budget_exceeded"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("Scheduler uses priority sort keys and eligibility checks.", "Tests prove interactive priority, protected capacity, and subsystem cap waits."),
            risk="Medium; pressure tuning needs real Kraken load, but mechanics are live.",
            action=AuditRecommendation.KEEP,
            phase_next="L5.1",
        ),
        _item(
            "l45.retry_yield_cancellation_cooperation",
            "L4.5",
            "Retry, yield, cancellation, and restart state",
            "L4.5 scheduler hardening",
            source_files=("src/stormhelm/core/jobs/manager.py", "src/stormhelm/core/jobs/models.py", "src/stormhelm/core/worker_utilization.py"),
            models_or_functions=("RetryPolicy", "CancellationState", "YieldState", "RestartRecoveryState"),
            runtime_entrypoints=("JobManager.cancel", "JobManager._execute_job", "JobManager.stop"),
            normal_path_usage="JobManager records cancel/retry/restart states; actual cooperation depends on tool handlers and explicit safe retry policy.",
            test_coverage=("tests/test_latency_l45_scheduler_hardening.py", "tests/test_job_manager.py"),
            status_surface=("/status.worker_state", "job lifecycle events"),
            trace_fields=("retry_policy", "retry_count", "cancellation_state", "yield_state", "restart_recovery_state"),
            kraken_fields=("retry_policy", "cancellation_state", "restart_recovery_state"),
            current_status=AuditStatus.PARTIAL_USED,
            evidence=("Cancel-before-start and safe-read retry framework are implemented in JobManager.",),
            missing=("Most real tools do not cooperatively poll yield/cancellation, and side-effect jobs default to no automatic retry.",),
            risk="Medium; framework can be overclaimed as full cooperative cancellation.",
            action=AuditRecommendation.DEFER_TO_PHASE,
            phase_next="L5.1/L6",
        ),
        _item(
            "l5.streaming_tts_contracts",
            "L5",
            "Streaming TTS contracts and fake provider path",
            "L5 voice streaming",
            source_files=("src/stormhelm/core/voice/models.py", "src/stormhelm/core/voice/providers.py", "src/stormhelm/core/voice/service.py"),
            models_or_functions=("VoiceStreamingTTSRequest", "VoiceStreamingTTSChunk", "VoiceStreamingTTSResult", "MockVoiceProvider.stream_speech"),
            config_flags=("voice.openai.stream_tts_outputs", "voice.openai.tts_live_format"),
            runtime_entrypoints=("VoiceService.stream_core_approved_spoken_text",),
            normal_path_usage="Core-approved normal voice output can use the streaming service path when streaming TTS and streaming playback are enabled.",
            test_coverage=("tests/test_latency_l5_voice_streaming_first_audio.py", "tests/test_latency_l51_voice_streaming_reality.py"),
            status_surface=("voice.status_snapshot.speech_synthesis",),
            trace_fields=("voice_streaming_tts_enabled", "voice_tts_first_chunk_ms", "voice_streaming_transport_kind"),
            kraken_fields=("voice_streaming_enabled_count", "voice_streaming_transport_kind_counts"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("Streaming contract, redaction, fallback, fake chunk flow, and normal path selection are tested.",),
            missing=("Live device/provider smoke remains opt-in and environment-gated.",),
            risk="Low; transport/device proof is tracked by separate OpenAI and playback inventory items.",
            action=AuditRecommendation.KEEP,
            phase_next="L6",
        ),
        _item(
            "l5.true_openai_http_streaming",
            "L5",
            "True OpenAI HTTP streaming transport",
            "L5 voice streaming",
            source_files=("src/stormhelm/core/voice/providers.py",),
            models_or_functions=("OpenAIVoiceProvider.stream_speech",),
            config_flags=("voice.openai.stream_tts_outputs",),
            runtime_entrypoints=("VoiceService.stream_core_approved_spoken_text",),
            normal_path_usage="OpenAI provider uses an HTTP streaming path when the normal provider path is selected; injected transport tests prove true-stream labeling, while legacy buffered helpers are labeled buffered_chunk_projection.",
            test_coverage=("tests/test_latency_l5_voice_streaming_first_audio.py", "tests/test_latency_l51_voice_streaming_reality.py"),
            status_surface=("voice.status_snapshot.speech_synthesis",),
            trace_fields=("voice_streaming_tts_enabled", "voice_streaming_transport_kind", "voice_streaming_fallback_used"),
            kraken_fields=("voice_streaming_transport_kind_counts", "voice_streaming_fallback_count", "voice_buffered_projection_count"),
            current_status=AuditStatus.PARTIAL_USED,
            evidence=("OpenAI streaming code path and buffered-projection labels are unit-tested with injected transports.",),
            missing=("No live OpenAI network smoke benchmark has been run in this repo state.",),
            risk="Medium; live provider first-audio improvement is plausible but not proven without opt-in network smoke.",
            action=AuditRecommendation.DEFER_TO_PHASE,
            phase_next="L6",
        ),
        _item(
            "l5.local_live_playback_backend_streaming",
            "L5",
            "Local live playback backend streaming",
            "L5 voice streaming",
            source_files=("src/stormhelm/core/voice/providers.py", "src/stormhelm/core/voice/service.py"),
            models_or_functions=("VoiceLivePlaybackRequest", "VoiceLivePlaybackSession", "LocalPlaybackProvider.start_stream"),
            config_flags=("voice.playback.streaming_enabled", "voice.playback.streaming_fallback_to_file"),
            runtime_entrypoints=("VoiceService.stream_core_approved_spoken_text", "MockPlaybackProvider.start_stream"),
            normal_path_usage="Playback contracts and mock live stream path are implemented; local provider reports unsupported unless its backend exposes stream methods.",
            test_coverage=("tests/test_latency_l5_voice_streaming_first_audio.py", "tests/test_voice_playback_provider.py"),
            status_surface=("voice.status_snapshot.playback",),
            trace_fields=("voice_playback_start_ms", "voice_partial_playback"),
            kraken_fields=("voice_partial_playback_count",),
            current_status=AuditStatus.PARTIAL_USED,
            evidence=("Mock live playback and local backend hook paths exist.",),
            missing=("No replacement live PCM/WAV backend is proven on a real device.",),
            risk="Medium; real playback first-audio gain is unproven without a live backend.",
            action=AuditRecommendation.DEFER_TO_PHASE,
            phase_next="L6",
        ),
        _item(
            "l5.normal_assistant_voice_output_streaming",
            "L5",
            "Normal assistant voice output uses streaming when enabled",
            "L5 voice streaming",
            source_files=("src/stormhelm/core/api/app.py", "src/stormhelm/core/voice/service.py"),
            models_or_functions=("_schedule_assistant_voice_output", "VoiceService.stream_core_approved_spoken_text"),
            config_flags=("voice.openai.stream_tts_outputs", "voice.playback.streaming_enabled"),
            runtime_entrypoints=("/chat/send assistant voice output scheduler",),
            normal_path_usage="/chat/send assistant voice output and capture play-response select the streaming service path when streaming TTS and streaming playback are enabled.",
            test_coverage=("tests/test_latency_l5_voice_streaming_first_audio.py", "tests/test_latency_l51_voice_streaming_reality.py"),
            status_surface=("voice.status_snapshot.speech_synthesis", "voice.status_snapshot.playback"),
            trace_fields=("voice_streaming_tts_enabled", "voice_first_audio_ms", "voice_stream_used_by_normal_path"),
            kraken_fields=("voice_first_audio_ms", "voice_streaming_path_used_count", "normal_path_streaming_miss_count"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("Normal /chat/send assistant voice output and capture play-response streaming are covered by L5.1 tests.",),
            missing=("Wake-loop playback still uses the older buffered path where its seam is broader.",),
            risk="Medium; normal manual/chat paths are live, but wake-loop streaming needs a later bounded pass.",
            action=AuditRecommendation.KEEP,
            phase_next="L6",
        ),
        _item(
            "l5.voice_first_audio_metrics",
            "L5",
            "Voice prewarm and first-audio metrics",
            "L5 voice streaming",
            source_files=("src/stormhelm/core/voice/service.py", "src/stormhelm/core/voice/evaluation.py", "src/stormhelm/core/latency.py"),
            models_or_functions=("VoicePlaybackPrewarmResult", "VoiceProviderPrewarmResult", "VoiceFirstAudioLatency"),
            config_flags=("voice.playback.prewarm_enabled",),
            runtime_entrypoints=("VoiceService.prewarm_voice_output", "manual/audio Core-routing setup"),
            normal_path_usage="Manual and audio paths prewarm provider/playback shells; status and latency summaries expose first-audio fields.",
            test_coverage=("tests/test_latency_l5_voice_streaming_first_audio.py", "tests/test_voice_latency_instrumentation.py"),
            status_surface=("voice.status_snapshot.speech_synthesis.first_audio_latency", "voice.status_snapshot.playback"),
            trace_fields=("voice_prewarm_used", "voice_first_audio_ms", "voice_core_to_first_audio_ms"),
            kraken_fields=("voice_prewarm_used_count", "voice_first_audio_ms"),
            current_status=AuditStatus.LIVE_USED,
            evidence=("Prewarm is called during manual/audio Core-routing setup when enabled.", "Metrics serialize into voice summary and unified latency trace."),
            missing=("Wake and Realtime prewarm coverage is limited.",),
            risk="Medium; first-audio measurements are test/synthetic until live smoke benchmarks run.",
            action=AuditRecommendation.KEEP,
            phase_next="L6",
        ),
        _item(
            "ui.status_and_deck_surfaces",
            "L0-L5",
            "Status, command surface, and Deck/Ghost payload exposure",
            "UI/status/reporting surfaces",
            source_files=("src/stormhelm/core/container.py", "src/stormhelm/core/api/app.py", "src/stormhelm/ui/voice_surface.py"),
            models_or_functions=("CoreContainer.status_snapshot", "voice status payloads"),
            runtime_entrypoints=("/status", "/voice/readiness", "/chat/send metadata"),
            normal_path_usage="Backend status exposes worker_state and voice streaming/prewarm status; chat metadata exposes latency and continuation summaries.",
            test_coverage=("tests/test_ui_bridge.py", "tests/test_command_surface.py", "tests/test_voice_ui_state_payload.py"),
            status_surface=("/status.worker_state", "/status.voice", "assistant_message.metadata"),
            trace_fields=("latency_summary", "worker_state", "voice_first_audio_ms"),
            kraken_fields=("latency row fields",),
            current_status=AuditStatus.PARTIAL_USED,
            evidence=("Core /status includes worker_state and voice status.", "Command surface tests cover existing metadata consumers."),
            missing=("No broad QML pass proves every new L0-L5 field is rendered in Deck; Ghost intentionally stays compact."),
            risk="Medium; backend fields may be richer than UI display until a later Deck pass.",
            action=AuditRecommendation.DEFER_TO_PHASE,
            phase_next="L6",
        ),
    ]
    return LatencyIntegrationAudit(items=tuple(items), summary=_summary(items))


def render_latency_integration_audit_markdown(audit: LatencyIntegrationAudit | None = None) -> str:
    audit = audit or build_latency_integration_audit()
    items = list(audit.items)
    live = [item for item in items if item.current_status == AuditStatus.LIVE_USED]
    partial = [item for item in items if item.current_status == AuditStatus.PARTIAL_USED]
    scaffold = [
        item
        for item in items
        if item.current_status in {AuditStatus.SCAFFOLD_ONLY, AuditStatus.POLICY_ONLY, AuditStatus.FUTURE_DEFERRED}
    ]
    dead = [item for item in items if item.current_status in {AuditStatus.TEST_ONLY, AuditStatus.DEAD_UNUSED, AuditStatus.UNKNOWN}]
    lines = [
        "# Stormhelm Latency Integration Audit",
        "",
        "Phase L5A is an evidence ledger for the L0-L5 latency, async, worker, continuation, and voice stack. It does not add new runtime behavior. A feature is labeled live only when a normal path uses it and tests plus trace/status/Kraken surfaces expose it.",
        "",
        "## Executive Summary",
        "",
        f"- Inventory items: {len(items)}",
        f"- Live used: {len(live)}",
        f"- Partial used: {len(partial)}",
        f"- Scaffold/policy/future: {len(scaffold)}",
        f"- Test-only/dead/unknown: {len(dead)}",
        "",
        "## Fully Live And Used",
        "",
        _feature_list(live),
        "",
        "## Partially Wired",
        "",
        _feature_list(partial),
        "",
        "## Scaffold Or Policy Only",
        "",
        _feature_list(scaffold),
        "",
        "## Test-only, Dead, Or Unknown",
        "",
        _feature_list(dead) if dead else "None identified in the L5A inventory.",
        "",
        "## Risk Ranking",
        "",
        "- High: software execute continuations must not be claimed as worker-backed route behavior until the trust/side-effect front half is proofed.",
        "- Medium: true OpenAI provider streaming, real-device live playback, wake-loop streaming, snapshot invalidation breadth, background refresh coverage, retry/yield/cancel cooperation, and UI rendering depth need later burn-down.",
        "- Low: L0 trace contracts, command-eval projection, route triage, inline hot-path protection, core worker timing, streaming TTS contracts, and normal assistant voice-output streaming are wired and tested.",
        "",
        "## Recommended L5.1 Scope",
        "",
        "- Keep normal assistant voice output on the Core-approved streaming path and preserve buffered fallback labels.",
        "- Run opt-in live OpenAI and local playback smoke checks when device/network credentials are available.",
        "- Keep mock first-audio smoke as deterministic regression coverage and compare it against live smoke later.",
        "- Do not relabel true provider/device behavior as fully live until a live smoke artifact proves it.",
        "",
        "## Recommended Later Phases",
        "",
        "- L5.1/L6: broaden event-driven snapshot invalidation and safe background refresh coverage.",
        "- L6: convert additional subsystem front halves only after trust, freshness, and verification seams are explicit.",
        "- L6: add Deck rendering for the most useful worker/scheduler/continuation fields while keeping Ghost compact.",
        "",
        "## Evidence Table",
        "",
        "| Feature | Phase | Status | Runtime usage | Test coverage | Trace/Kraken visibility | Risk | Recommendation | Future phase |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(
            "| {feature} | {phase} | {status} | {runtime} | {tests} | {visibility} | {risk} | {action} | {future} |".format(
                feature=_cell(item.feature_id),
                phase=_cell(item.phase_introduced),
                status=_cell(item.current_status.value),
                runtime=_cell(item.normal_path_usage or "None"),
                tests=_cell(", ".join(item.test_coverage) or "None"),
                visibility=_cell(", ".join(item.trace_fields + item.kraken_fields + item.status_surface) or "None"),
                risk=_cell(item.risk_if_left_as_is or "Not assessed"),
                action=_cell(item.recommended_action.value),
                future=_cell(item.recommended_phase or ""),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _item(
    feature_id: str,
    phase_introduced: str,
    name: str,
    category: str,
    *,
    source_files: tuple[str, ...] = (),
    models_or_functions: tuple[str, ...] = (),
    config_flags: tuple[str, ...] = (),
    runtime_entrypoints: tuple[str, ...] = (),
    normal_path_usage: str = "",
    test_coverage: tuple[str, ...] = (),
    status_surface: tuple[str, ...] = (),
    trace_fields: tuple[str, ...] = (),
    kraken_fields: tuple[str, ...] = (),
    current_status: AuditStatus,
    evidence: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
    risk: str = "",
    action: AuditRecommendation,
    phase_next: str = "",
    notes: str = "",
) -> LatencyIntegrationInventoryItem:
    return LatencyIntegrationInventoryItem(
        feature_id=feature_id,
        phase_introduced=phase_introduced,
        feature_name=name,
        category=category,
        source_files=tuple(source_files),
        models_or_functions=tuple(models_or_functions),
        config_flags=tuple(config_flags),
        runtime_entrypoints=tuple(runtime_entrypoints),
        normal_path_usage=normal_path_usage,
        test_coverage=tuple(test_coverage),
        status_surface=tuple(status_surface),
        trace_fields=tuple(trace_fields),
        kraken_fields=tuple(kraken_fields),
        current_status=current_status,
        evidence=tuple(evidence),
        missing_evidence=tuple(missing),
        risk_if_left_as_is=risk,
        recommended_action=action,
        recommended_phase=phase_next,
        notes=notes,
    )


def _continuation_item(
    *,
    feature_id: str,
    phase: str,
    operation_kind: str,
    registry_status: dict[str, Any],
    status: AuditStatus,
    missing: tuple[str, ...],
    phase_next: str,
) -> LatencyIntegrationInventoryItem:
    implemented = bool(registry_status.get("implemented"))
    evidence = (
        "handler registered" if implemented else "handler missing",
        f"registry handler status: {registry_status.get('handler_name') or operation_kind}",
    )
    return _item(
        feature_id,
        phase,
        f"{operation_kind} continuation",
        "L4.2/L4.3 subsystem continuations",
        source_files=("src/stormhelm/core/subsystem_continuations.py", "src/stormhelm/core/orchestrator/command_eval/report.py"),
        models_or_functions=("SubsystemContinuationRegistry", "SubsystemContinuationRunner", operation_kind),
        runtime_entrypoints=("subsystem_continuation tool",),
        normal_path_usage=f"{operation_kind} has a registry handler path, but automatic /chat/send front-half use is limited unless noted elsewhere.",
        test_coverage=("tests/test_latency_l43_subsystem_continuation_expansion.py", "tests/test_latency_l44_async_validation.py"),
        status_surface=("subsystem continuation events", "async coverage audit"),
        trace_fields=("subsystem_continuation_handler", "continuation_truth_clamps_applied"),
        kraken_fields=("p95_continuation_runtime_by_handler", "async_coverage_audit"),
        current_status=status,
        evidence=evidence,
        missing=missing,
        risk="Medium; handler existence is not the same as automatic normal-route conversion.",
        action=AuditRecommendation.DEFER_TO_PHASE,
        phase_next=phase_next,
    )


def _summary(items: list[LatencyIntegrationInventoryItem]) -> dict[str, Any]:
    by_status = Counter(item.current_status.value for item in items)
    by_category = Counter(item.category for item in items)
    return {
        "item_count": len(items),
        "by_status": dict(sorted(by_status.items())),
        "by_category": dict(sorted(by_category.items())),
        "unknown_count": by_status.get(AuditStatus.UNKNOWN.value, 0),
        "high_risk_items": [
            item.feature_id
            for item in items
            if str(item.risk_if_left_as_is).lower().startswith("high")
        ],
    }


def _feature_list(items: list[LatencyIntegrationInventoryItem]) -> str:
    if not items:
        return "None."
    return "\n".join(
        f"- `{item.feature_id}`: {item.feature_name} ({item.current_status.value})"
        for item in items
    )


def _cell(value: object) -> str:
    text = str(value or "").replace("\n", " ").replace("|", "\\|")
    return text[:900]
