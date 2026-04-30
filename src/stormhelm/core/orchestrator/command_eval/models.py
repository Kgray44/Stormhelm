from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from pathlib import Path
from typing import Any

from stormhelm.core.latency import build_latency_trace


UI_PERCEIVED_LATENCY_NUMERIC_FIELDS = (
    "event_stream_delay_ms",
    "ui_bridge_apply_ms",
    "ui_render_visible_ms",
    "ghost_first_visible_state_ms",
    "approval_prompt_visible_ms",
    "voice_state_visible_ms",
    "route_state_visible_ms",
)

UI_PERCEIVED_LATENCY_FLAG_FIELDS = (
    "polling_fallback_used",
    "reconnect_gap_detected",
)


def json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return json_ready(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ExpectedBehavior:
    route_family: str
    subsystem: str
    tools: tuple[str, ...] = ()
    target_slots: dict[str, Any] = field(default_factory=dict)
    clarification: str = "none"
    approval: str = "not_expected"
    result_state: str = "dry_run_or_completed"
    verification: str = "bounded_or_not_applicable"
    response_terms: tuple[str, ...] = ()
    forbidden_overclaims: tuple[str, ...] = (
        "i verified",
        "verified that",
        "successfully installed",
        "sent it",
        "deleted it",
        "removed it",
    )
    latency_ms_max: int = 2500

    def to_dict(self) -> dict[str, Any]:
        return json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class CommandEvalCase:
    case_id: str
    message: str
    expected: ExpectedBehavior
    session_id: str = "default"
    surface_mode: str = "ghost"
    active_module: str = "chartroom"
    workspace_context: dict[str, Any] = field(default_factory=dict)
    input_context: dict[str, Any] = field(default_factory=dict)
    active_request_state: dict[str, Any] = field(default_factory=dict)
    sequence_id: str = ""
    turn_index: int = 0
    tags: tuple[str, ...] = ()
    notes: str = ""
    context_lane: str = "not_context_dependent"
    seeded_context_required: bool = False
    expected_context_source: str = "none"
    expected_prior_family: str = ""
    expected_prior_tool: str = ""
    expected_target_binding: str = ""
    expected_alternate_target: str = ""
    expected_confirmation_state: str = ""
    expected_behavior_without_context: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "session_id": self.session_id,
            "surface_mode": self.surface_mode,
            "active_module": self.active_module,
            "workspace_context": dict(self.workspace_context),
            "input_context": dict(self.input_context),
        }

    def to_dict(self) -> dict[str, Any]:
        return json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class CoreObservation:
    case_id: str
    input_boundary: str
    latency_ms: float
    ui_response: str
    session_id: str = "default"
    status: str = "completed"
    process_killed: bool = False
    timeout_seconds: float = 0.0
    elapsed_ms: float = 0.0
    child_pid: int = 0
    stdout_tail: str = ""
    stderr_tail: str = ""
    checkpoint_path: str = ""
    actual_route_family: str = ""
    actual_subsystem: str = ""
    tool_chain: tuple[str, ...] = ()
    tool_results: tuple[dict[str, Any], ...] = ()
    job_states: tuple[str, ...] = ()
    result_state: str = ""
    verification_state: str = ""
    clarification_observed: bool = False
    approval_observed: bool = False
    target_slots: dict[str, Any] = field(default_factory=dict)
    route_state: dict[str, Any] = field(default_factory=dict)
    planner_debug: dict[str, Any] = field(default_factory=dict)
    planner_obedience: dict[str, Any] = field(default_factory=dict)
    response_active_request_state: dict[str, Any] = field(default_factory=dict)
    snapshot_active_request_state: dict[str, Any] = field(default_factory=dict)
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    latency_trace: dict[str, Any] = field(default_factory=dict)
    latency_summary: dict[str, Any] = field(default_factory=dict)
    budget_result: dict[str, Any] = field(default_factory=dict)
    response_json_bytes: int = 0
    event_count: int = 0
    job_count: int = 0
    ui_event_count: int = 0
    workspace_item_count: int = 0
    active_context_bytes: int = 0
    active_context_item_count: int = 0
    truncated_workspace_items: bool = False
    largest_payload_fields: tuple[dict[str, Any], ...] = ()
    payload_guardrail_triggered: bool = False
    payload_guardrail_reason: str = ""
    route_handler_subspans: dict[str, float] = field(default_factory=dict)
    ai_provider_calls: tuple[dict[str, Any], ...] = ()
    actions: tuple[dict[str, Any], ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class AssertionOutcome:
    name: str
    passed: bool
    expected: Any
    actual: Any
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class CommandEvalResult:
    case: CommandEvalCase
    observation: CoreObservation
    assertions: dict[str, AssertionOutcome]
    run_id: str = ""
    case_index: int = 0
    history_strategy: str = "shared_session"
    failure_category: str = "passed"
    failure_reason: str = ""
    score_in_pass_fail: bool = True
    scoring_note: str = ""
    artifact_flush_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return all(outcome.passed for outcome in self.assertions.values())

    def to_dict(self) -> dict[str, Any]:
        route_candidates = _route_candidates(self.observation.route_state)
        route_scores = {
            str(candidate.get("route_family") or ""): candidate.get("score")
            for candidate in route_candidates
            if isinstance(candidate, dict)
        }
        fallback_reason = _fallback_reason(self.observation.route_state, self.observation.ui_response)
        ai_usage = _ai_usage_summary(
            case=self.case,
            observation=self.observation,
        )
        provider_called = bool(ai_usage["provider_called"]) or _provider_called(self.observation.events, self.observation.planner_debug)
        dry_run = any(
            isinstance(result.get("data"), dict) and bool(result.get("data", {}).get("dry_run"))
            for result in self.observation.tool_results
        )
        external_action_performed = any(
            not dry_run and _action_has_external_effect(action)
            for action in self.observation.actions
        )
        approval_state = _approval_state(self.observation.tool_results, self.observation.approval_observed)
        stage_timings = _stage_timings(self.observation, self.artifact_flush_ms)
        latency_trace = _latency_trace_for_observation(
            observation=self.observation,
            stage_timings=stage_timings,
            provider_called=provider_called,
            ai_usage=ai_usage,
        )
        latency_summary = (
            dict(self.observation.latency_summary)
            if self.observation.latency_summary
            else latency_trace.to_summary_dict()
        )
        budget_result = (
            dict(self.observation.budget_result)
            if self.observation.budget_result
            else latency_trace.budget_result().to_dict()
        )
        ui_perceived_latency = _ui_perceived_latency_fields(latency_summary)
        historical_blocker_labels = _historical_blocker_labels(
            case_id=self.case.case_id,
            actual_route_family=self.observation.actual_route_family,
            tool_chain=self.observation.tool_chain,
        )
        known_lane_labels = _known_lane_labels(
            case_id=self.case.case_id,
            expected_route_family=self.case.expected.route_family,
            actual_route_family=self.observation.actual_route_family,
            failure_category=self.failure_category,
            historical_blocker_labels=historical_blocker_labels,
        )
        generic_provider_selected_reason = fallback_reason if self.observation.actual_route_family == "generic_provider" else ""
        planner_v2_debug = self.observation.planner_debug.get("planner_v2")
        if not isinstance(planner_v2_debug, dict):
            planner_v2_debug = {}
        route_spine_debug = self.observation.planner_debug.get("route_spine")
        if not isinstance(route_spine_debug, dict):
            route_spine_debug = {}
        intent_frame = self.observation.planner_debug.get("intent_frame")
        if not isinstance(intent_frame, dict):
            intent_frame = planner_v2_debug.get("intent_frame") if isinstance(planner_v2_debug.get("intent_frame"), dict) else {}
        if not isinstance(intent_frame, dict):
            intent_frame = route_spine_debug.get("intent_frame") if isinstance(route_spine_debug.get("intent_frame"), dict) else {}
        native_decline_reasons = self.observation.planner_debug.get("native_decline_reasons")
        if not isinstance(native_decline_reasons, dict):
            route_decision = planner_v2_debug.get("route_decision") if isinstance(planner_v2_debug.get("route_decision"), dict) else {}
            native_decline_reasons = route_decision.get("native_decline_reasons") if isinstance(route_decision.get("native_decline_reasons"), dict) else {}
        if not isinstance(native_decline_reasons, dict):
            native_decline_reasons = route_spine_debug.get("native_decline_reasons") if isinstance(route_spine_debug.get("native_decline_reasons"), dict) else {}
        planner_v2_route_decision = (
            planner_v2_debug.get("route_decision")
            if isinstance(planner_v2_debug.get("route_decision"), dict)
            else {}
        )
        route_surface_type = _route_surface_type(
            route_state=self.observation.route_state,
            expected_family=self.case.expected.route_family,
            actual_family=self.observation.actual_route_family,
            tool_chain=self.observation.tool_chain,
            score_in_pass_fail=self.score_in_pass_fail,
        )
        routing_engine = _routing_engine_from_trace(
            planner_debug=self.observation.planner_debug,
            planner_v2_debug=planner_v2_debug,
            route_spine_debug=route_spine_debug,
            route_surface_type=route_surface_type,
            actual_family=self.observation.actual_route_family,
            status=self.observation.status,
            score_in_pass_fail=self.score_in_pass_fail,
        )
        payload = {
            "run_id": self.run_id,
            "test_id": self.case.case_id,
            "case_index": self.case_index,
            "session_id": self.observation.session_id,
            "history_strategy": self.history_strategy,
            "status": self.observation.status,
            "prompt": self.case.message,
            "input": self.case.message,
            "scenario_family": _scenario_family(self.case.case_id),
            "wording_style": _wording_style(self.case.case_id, self.case.tags),
            "expected_route_family": self.case.expected.route_family,
            "actual_route_family": self.observation.actual_route_family,
            "route_state": self.observation.route_state,
            "route_candidates": route_candidates,
            "route_scores": route_scores,
            "route_decline_reasons": _route_decline_reasons(route_candidates),
            "native_candidate_considered": any(
                str(candidate.get("route_family") or "") != "generic_provider" for candidate in route_candidates
            ),
            "native_candidate_blocked_by": _native_candidate_blocked_by(route_candidates),
            "generic_provider_eligible": any(
                str(candidate.get("route_family") or "") == "generic_provider" for candidate in route_candidates
            ),
            "generic_provider_selected_reason": generic_provider_selected_reason,
            "fallback_reason": fallback_reason,
            "provider_fallback_reason": fallback_reason if self.observation.actual_route_family == "generic_provider" else "",
            "routing_engine": routing_engine,
            "planner_v2_trace": planner_v2_debug,
            "intent_frame": intent_frame,
            "candidate_specs_considered": list(
                self.observation.planner_debug.get("candidate_specs_considered")
                or (planner_v2_debug.get("route_decision") or {}).get("candidate_specs_considered")
                or route_spine_debug.get("candidate_specs_considered")
                or []
            ),
            "selected_route_spec": str(
                self.observation.planner_debug.get("selected_route_spec")
                or (planner_v2_debug.get("route_decision") or {}).get("selected_route_spec")
                or route_spine_debug.get("selected_route_spec")
                or ""
            ),
            "native_decline_reasons": native_decline_reasons,
            "generic_provider_gate_reason": str(
                self.observation.planner_debug.get("generic_provider_gate_reason")
                or (planner_v2_debug.get("route_decision") or {}).get("generic_provider_gate_reason")
                or route_spine_debug.get("generic_provider_gate_reason")
                or ""
            ),
            "legacy_fallback_used": bool(
                self.observation.planner_debug.get("legacy_fallback_used")
                or planner_v2_debug.get("legacy_fallback_used")
                or route_spine_debug.get("legacy_fallback_used")
            ),
            "legacy_family": str(planner_v2_route_decision.get("legacy_family") or ""),
            "planner_v2_decline_reason": str(planner_v2_route_decision.get("planner_v2_decline_reason") or ""),
            "legacy_family_scheduled_for_migration": bool(
                planner_v2_route_decision.get("legacy_family_scheduled_for_migration")
            ),
            "migration_priority": str(planner_v2_route_decision.get("migration_priority") or ""),
            "provider_called": provider_called,
            "openai_called": ai_usage["openai_called"],
            "llm_called": ai_usage["llm_called"],
            "embedding_called": ai_usage["embedding_called"],
            "provider_call_count": ai_usage["provider_call_count"],
            "openai_call_count": ai_usage["openai_call_count"],
            "llm_call_count": ai_usage["llm_call_count"],
            "embedding_call_count": ai_usage["embedding_call_count"],
            "provider_names": ai_usage["provider_names"],
            "model_names": ai_usage["model_names"],
            "provider_call_purposes": ai_usage["provider_call_purposes"],
            "provider_call_sources": ai_usage["provider_call_sources"],
            "provider_call_allowed": ai_usage["provider_call_allowed"],
            "provider_call_violation": ai_usage["provider_call_violation"],
            "ai_usage_summary": ai_usage["ai_usage_summary"],
            "ai_provider_calls": ai_usage["ai_provider_calls"],
            "expected_subsystem": self.case.expected.subsystem,
            "actual_subsystem": self.observation.actual_subsystem,
            "expected_tool": list(self.case.expected.tools),
            "actual_tool": list(self.observation.tool_chain),
            "expected_result_state": self.case.expected.result_state,
            "actual_result_state": self.observation.result_state,
            "expected_approval_state": self.case.expected.approval,
            "actual_approval_state": approval_state,
            "expected_verification_state": self.case.expected.verification,
            "actual_verification_state": self.observation.verification_state,
            "planner_obedience": self.observation.planner_obedience,
            "response_active_request_state": self.observation.response_active_request_state,
            "snapshot_active_request_state": self.observation.snapshot_active_request_state,
            "result_state": self.observation.result_state,
            "verification_state": self.observation.verification_state,
            "approval_state": approval_state,
            "trust_state": _trust_state(self.observation.tool_results, self.observation.route_state),
            "target_extraction_summary": _target_extraction_summary(self.observation.route_state, self.observation.tool_results),
            "deictic_binding_summary": _deictic_binding_summary(self.observation.route_state),
            "missing_preconditions": _missing_preconditions(route_candidates, self.observation.tool_results),
            "route_surface_type": route_surface_type,
            "implemented_routeable_status": _implemented_routeable_status(self.case.expected.route_family),
            "dry_run": dry_run,
            "external_action_performed": external_action_performed,
            "latency_ms": self.observation.latency_ms,
            **stage_timings,
            "latency_trace": (
                dict(self.observation.latency_trace)
                if self.observation.latency_trace
                else latency_trace.to_dict()
            ),
            "latency_summary": latency_summary,
            "budget_result": budget_result,
            "longest_stage": str(latency_summary.get("longest_stage") or ""),
            "longest_stage_ms": float(latency_summary.get("longest_stage_ms") or 0.0),
            "budget_label": str(
                budget_result.get("budget_label")
                or latency_summary.get("budget_label")
                or ""
            ),
            "budget_target_ms": float(
                budget_result.get("target_ms")
                or latency_summary.get("budget_target_ms")
                or 0.0
            ),
            "budget_soft_ceiling_ms": float(
                budget_result.get("soft_ceiling_ms")
                or latency_summary.get("budget_soft_ceiling_ms")
                or 0.0
            ),
            "budget_hard_ceiling_ms": (
                float(
                    budget_result.get("hard_ceiling_ms")
                    or latency_summary.get("budget_hard_ceiling_ms")
                    or 0.0
                )
                if (
                    budget_result.get("hard_ceiling_ms")
                    or latency_summary.get("budget_hard_ceiling_ms")
                )
                else None
            ),
            "budget_exceeded": bool(
                budget_result.get("budget_exceeded")
                or latency_summary.get("budget_exceeded")
            ),
            "hard_ceiling_exceeded": bool(
                budget_result.get("hard_ceiling_exceeded")
                or latency_summary.get("hard_ceiling_exceeded")
            ),
            "execution_mode": str(latency_summary.get("execution_mode") or ""),
            "partial_response_returned": bool(latency_summary.get("partial_response_returned")),
            "async_expected": bool(
                latency_summary.get("async_expected")
                or budget_result.get("async_continuation_expected")
            ),
            "first_feedback_ms": (
                float(latency_summary.get("first_feedback_ms") or 0.0)
                if latency_summary.get("first_feedback_ms") is not None
                else None
            ),
            "l8_subsystem_id": str(latency_summary.get("subsystem_id") or ""),
            "l8_hot_path_name": str(latency_summary.get("hot_path_name") or ""),
            "l8_latency_mode": str(latency_summary.get("latency_mode") or ""),
            "l8_cache_hit": bool(latency_summary.get("cache_hit")),
            "l8_cache_age_ms": (
                float(latency_summary.get("cache_age_ms") or 0.0)
                if latency_summary.get("cache_age_ms") is not None
                else None
            ),
            "l8_cache_policy_id": str(latency_summary.get("cache_policy_id") or ""),
            "l8_live_probe_started": bool(latency_summary.get("live_probe_started")),
            "l8_provider_fallback_used": bool(latency_summary.get("provider_fallback_used")),
            "l8_heavy_context_used": bool(latency_summary.get("heavy_context_used")),
            "l8_planner_fast_path_used": bool(latency_summary.get("planner_fast_path_used")),
            "l8_route_handler_ms": (
                float(latency_summary.get("route_handler_ms") or 0.0)
                if latency_summary.get("route_handler_ms") is not None
                else None
            ),
            "provider_eligibility": dict(latency_summary.get("provider_eligibility") or {}),
            "provider_latency_summary": dict(latency_summary.get("provider_latency_summary") or {}),
            "provider_audit_timing": dict(latency_summary.get("provider_audit_timing") or {}),
            "provider_fallback_allowed": bool(latency_summary.get("provider_fallback_allowed")),
            "provider_fallback_blocked_reason": str(latency_summary.get("provider_fallback_blocked_reason") or ""),
            "provider_first_byte_ms": (
                float(latency_summary.get("provider_first_byte_ms") or 0.0)
                if latency_summary.get("provider_first_byte_ms") is not None
                else None
            ),
            "provider_first_token_ms": (
                float(latency_summary.get("provider_first_token_ms") or 0.0)
                if latency_summary.get("provider_first_token_ms") is not None
                else None
            ),
            "provider_first_output_ms": (
                float(latency_summary.get("provider_first_output_ms") or 0.0)
                if latency_summary.get("provider_first_output_ms") is not None
                else None
            ),
            "provider_total_ms": (
                float(latency_summary.get("provider_total_ms") or 0.0)
                if latency_summary.get("provider_total_ms") is not None
                else None
            ),
            "provider_timeout_hit": bool(latency_summary.get("provider_timeout_hit")),
            "provider_cancelled": bool(latency_summary.get("provider_cancelled")),
            "provider_failure_code": str(latency_summary.get("provider_failure_code") or ""),
            "provider_budget_label": str(latency_summary.get("provider_budget_label") or ""),
            "provider_budget_exceeded": bool(latency_summary.get("provider_budget_exceeded")),
            "provider_streaming_enabled": bool(latency_summary.get("provider_streaming_enabled")),
            "provider_streaming_used": bool(latency_summary.get("provider_streaming_used")),
            "provider_partial_result_count": int(latency_summary.get("provider_partial_result_count") or 0),
            "provider_name": str(latency_summary.get("provider_name") or next(iter(ai_usage["provider_names"]), "")),
            "provider_model_name": str(latency_summary.get("provider_model_name") or next(iter(ai_usage["model_names"]), "")),
            "native_route_blocked_by_provider": bool(latency_summary.get("native_route_blocked_by_provider")),
            "provider_payload_redacted": bool(latency_summary.get("provider_payload_redacted", True)),
            "provider_secrets_logged": bool(latency_summary.get("provider_secrets_logged")),
            "budget_exceeded_continuing": bool(latency_summary.get("budget_exceeded_continuing")),
            "fail_fast_reason": str(latency_summary.get("fail_fast_reason") or ""),
            "fast_path_used": bool(latency_summary.get("fast_path_used")),
            "route_triage_ms": float(latency_summary.get("route_triage_ms") or stage_timings.get("route_triage_ms") or 0.0),
            "triage_confidence": float(latency_summary.get("triage_confidence") or 0.0),
            "triage_reason_codes": list(latency_summary.get("triage_reason_codes") or []),
            "likely_route_families": list(latency_summary.get("likely_route_families") or []),
            "skipped_route_families": list(latency_summary.get("skipped_route_families") or []),
            "heavy_context_loaded": bool(latency_summary.get("heavy_context_loaded")),
            "heavy_context_reason": str(latency_summary.get("heavy_context_reason") or ""),
            "provider_fallback_suppressed_reason": str(latency_summary.get("provider_fallback_suppressed_reason") or ""),
            "planner_candidates_pruned_count": int(latency_summary.get("planner_candidates_pruned_count") or 0),
            "route_family_seams_evaluated": list(latency_summary.get("route_family_seams_evaluated") or []),
            "route_family_seams_skipped": list(latency_summary.get("route_family_seams_skipped") or []),
            "snapshots_checked": list(latency_summary.get("snapshots_checked") or []),
            "snapshots_used": list(latency_summary.get("snapshots_used") or []),
            "snapshots_refreshed": list(latency_summary.get("snapshots_refreshed") or []),
            "snapshots_invalidated": list(latency_summary.get("snapshots_invalidated") or []),
            "snapshot_hot_path_hit": bool(latency_summary.get("snapshot_hot_path_hit")),
            "snapshot_miss_reason": dict(latency_summary.get("snapshot_miss_reason") or {}),
            "snapshot_age_ms": dict(latency_summary.get("snapshot_age_ms") or {}),
            "snapshot_freshness": dict(latency_summary.get("snapshot_freshness") or {}),
            "stale_snapshot_used_cautiously": bool(latency_summary.get("stale_snapshot_used_cautiously")),
            "heavy_context_avoided_by_snapshot": bool(latency_summary.get("heavy_context_avoided_by_snapshot")),
            "invalidation_count": int(latency_summary.get("invalidation_count") or 0),
            "freshness_warnings": list(latency_summary.get("freshness_warnings") or []),
            "async_continuation": bool(latency_summary.get("async_continuation")),
            "async_strategy": str(latency_summary.get("async_strategy") or ""),
            "async_initial_response_returned": bool(
                latency_summary.get("async_initial_response_returned")
                or stage_timings.get("async_initial_response_returned")
            ),
            "route_continuation_id": str(latency_summary.get("route_continuation_id") or ""),
            "route_progress_stage": str(latency_summary.get("route_progress_stage") or ""),
            "route_progress_status": str(latency_summary.get("route_progress_status") or ""),
            "progress_event_count": int(
                latency_summary.get("progress_event_count")
                or stage_timings.get("progress_event_count")
                or 0
            ),
            "worker_lane": str(latency_summary.get("worker_lane") or ""),
            "worker_priority": str(latency_summary.get("worker_priority") or ""),
            "queue_depth_at_submit": int(latency_summary.get("queue_depth_at_submit") or 0),
            "queue_wait_ms": float(latency_summary.get("queue_wait_ms") or 0.0),
            "job_start_delay_ms": float(latency_summary.get("job_start_delay_ms") or 0.0),
            "job_run_ms": float(latency_summary.get("job_run_ms") or 0.0),
            "job_total_ms": float(latency_summary.get("job_total_ms") or 0.0),
            "worker_index": (
                int(latency_summary.get("worker_index") or 0)
                if latency_summary.get("worker_index") is not None
                else None
            ),
            "worker_capacity": int(latency_summary.get("worker_capacity") or 0),
            "workers_busy_at_submit": int(latency_summary.get("workers_busy_at_submit") or 0),
            "workers_idle_at_submit": int(latency_summary.get("workers_idle_at_submit") or 0),
            "worker_saturation_percent": float(latency_summary.get("worker_saturation_percent") or 0.0),
            "starvation_detected": bool(latency_summary.get("starvation_detected")),
            "interactive_jobs_waiting": int(latency_summary.get("interactive_jobs_waiting") or 0),
            "background_jobs_running": int(latency_summary.get("background_jobs_running") or 0),
            "background_job_count": int(latency_summary.get("background_job_count") or 0),
            "interactive_job_count": int(latency_summary.get("interactive_job_count") or 0),
            "scheduler_strategy": str(latency_summary.get("scheduler_strategy") or ""),
            "scheduler_pressure_state": str(latency_summary.get("scheduler_pressure_state") or ""),
            "scheduler_pressure_reasons": list(latency_summary.get("scheduler_pressure_reasons") or []),
            "protected_interactive_capacity": int(latency_summary.get("protected_interactive_capacity") or 0),
            "background_capacity_limit": int(latency_summary.get("background_capacity_limit") or 0),
            "protected_capacity_wait_reason": str(latency_summary.get("protected_capacity_wait_reason") or ""),
            "queue_wait_budget_ms": (
                float(latency_summary.get("queue_wait_budget_ms") or 0.0)
                if latency_summary.get("queue_wait_budget_ms") is not None
                else None
            ),
            "queue_wait_budget_exceeded": bool(latency_summary.get("queue_wait_budget_exceeded")),
            "subsystem_cap_key": str(latency_summary.get("subsystem_cap_key") or ""),
            "subsystem_cap_limit": (
                int(latency_summary.get("subsystem_cap_limit") or 0)
                if latency_summary.get("subsystem_cap_limit") is not None
                else None
            ),
            "subsystem_cap_wait_ms": float(latency_summary.get("subsystem_cap_wait_ms") or 0.0),
            "retry_policy": str(latency_summary.get("retry_policy") or ""),
            "retry_count": int(latency_summary.get("retry_count") or 0),
            "retry_max_attempts": int(latency_summary.get("retry_max_attempts") or 0),
            "retry_backoff_ms": float(latency_summary.get("retry_backoff_ms") or 0.0),
            "retry_last_error": str(latency_summary.get("retry_last_error") or ""),
            "attempt_count": int(latency_summary.get("attempt_count") or 0),
            "cancellation_state": str(latency_summary.get("cancellation_state") or ""),
            "yield_state": str(latency_summary.get("yield_state") or ""),
            "restart_recovery_state": str(latency_summary.get("restart_recovery_state") or ""),
            "job_required": bool(latency_summary.get("job_required") or stage_timings.get("job_required")),
            "task_required": bool(latency_summary.get("task_required") or stage_timings.get("task_required")),
            "event_progress_required": bool(
                latency_summary.get("event_progress_required")
                or stage_timings.get("event_progress_required")
            ),
            "subsystem_continuation_created": bool(
                latency_summary.get("subsystem_continuation_created")
                or stage_timings.get("subsystem_continuation_created")
            ),
            "subsystem_continuation_id": str(latency_summary.get("subsystem_continuation_id") or ""),
            "subsystem_continuation_kind": str(latency_summary.get("subsystem_continuation_kind") or ""),
            "subsystem_continuation_stage": str(latency_summary.get("subsystem_continuation_stage") or ""),
            "subsystem_continuation_status": str(latency_summary.get("subsystem_continuation_status") or ""),
            "subsystem_continuation_worker_lane": str(
                latency_summary.get("subsystem_continuation_worker_lane") or ""
            ),
            "returned_before_subsystem_completion": bool(
                latency_summary.get("returned_before_subsystem_completion")
                or stage_timings.get("returned_before_subsystem_completion")
            ),
            "inline_front_half_ms": float(
                latency_summary.get("inline_front_half_ms")
                or stage_timings.get("inline_front_half_ms")
                or 0.0
            ),
            "worker_back_half_ms": float(latency_summary.get("worker_back_half_ms") or 0.0),
            "continuation_queue_wait_ms": float(
                latency_summary.get("subsystem_continuation_queue_wait_ms")
                or latency_summary.get("continuation_queue_wait_ms")
                or 0.0
            ),
            "continuation_run_ms": float(
                latency_summary.get("subsystem_continuation_run_ms")
                or latency_summary.get("continuation_run_ms")
                or 0.0
            ),
            "continuation_total_ms": float(
                latency_summary.get("subsystem_continuation_total_ms")
                or latency_summary.get("continuation_total_ms")
                or 0.0
            ),
            "continuation_progress_event_count": int(
                latency_summary.get("subsystem_continuation_progress_event_count")
                or latency_summary.get("continuation_progress_event_count")
                or 0
            ),
            "continuation_final_result_state": str(
                latency_summary.get("subsystem_continuation_final_result_state")
                or latency_summary.get("continuation_final_result_state")
                or ""
            ),
            "continuation_verification_state": str(
                latency_summary.get("subsystem_continuation_verification_state")
                or latency_summary.get("continuation_verification_state")
                or ""
            ),
            "subsystem_continuation_handler": str(
                latency_summary.get("subsystem_continuation_handler") or ""
            ),
            "subsystem_continuation_handler_implemented": bool(
                latency_summary.get("subsystem_continuation_handler_implemented")
            ),
            "subsystem_continuation_handler_missing_reason": str(
                latency_summary.get("subsystem_continuation_handler_missing_reason") or ""
            ),
            "continuation_progress_stages": list(latency_summary.get("continuation_progress_stages") or []),
            "continuation_verification_required": bool(latency_summary.get("continuation_verification_required")),
            "continuation_verification_attempted": bool(latency_summary.get("continuation_verification_attempted")),
            "continuation_verification_evidence_count": int(
                latency_summary.get("continuation_verification_evidence_count") or 0
            ),
            "continuation_result_limitations": list(latency_summary.get("continuation_result_limitations") or []),
            "continuation_truth_clamps_applied": list(latency_summary.get("continuation_truth_clamps_applied") or []),
            "direct_subsystem_async_converted": bool(
                latency_summary.get("direct_subsystem_async_converted")
                or stage_timings.get("direct_subsystem_async_converted")
            ),
            "async_conversion_expected": bool(
                latency_summary.get("async_conversion_expected")
                or stage_timings.get("async_conversion_expected")
            ),
            "async_conversion_missing_reason": str(
                latency_summary.get("async_conversion_missing_reason") or ""
            ),
            "voice_streaming_tts_enabled": bool(
                latency_summary.get("voice_streaming_tts_enabled")
                or latency_summary.get("streaming_enabled")
            ),
            "voice_first_audio_ms": float(
                latency_summary.get("voice_first_audio_ms")
                or latency_summary.get("request_to_first_audio_ms")
                or 0.0
            ),
            "voice_core_to_first_audio_ms": float(
                latency_summary.get("voice_core_to_first_audio_ms")
                or latency_summary.get("core_result_to_first_audio_ms")
                or 0.0
            ),
            "voice_tts_first_chunk_ms": float(
                latency_summary.get("voice_tts_first_chunk_ms")
                or latency_summary.get("tts_start_to_first_chunk_ms")
                or 0.0
            ),
            "voice_playback_start_ms": float(
                latency_summary.get("voice_playback_start_ms")
                or latency_summary.get("first_chunk_to_playback_start_ms")
                or 0.0
            ),
            "voice_streaming_transport_kind": str(
                latency_summary.get("voice_streaming_transport_kind")
                or latency_summary.get("streaming_transport_kind")
                or ""
            ),
            "voice_first_chunk_before_complete": bool(
                latency_summary.get("voice_first_chunk_before_complete")
                or latency_summary.get("first_chunk_before_complete")
            ),
            "voice_stream_used_by_normal_path": bool(
                latency_summary.get("voice_stream_used_by_normal_path")
                or latency_summary.get("stream_used_by_normal_path")
            ),
            "voice_streaming_miss_reason": str(
                latency_summary.get("voice_streaming_miss_reason")
                or latency_summary.get("streaming_miss_reason")
                or ""
            ),
            "voice_live_format": str(
                latency_summary.get("voice_live_format")
                or latency_summary.get("live_format")
                or ""
            ),
            "voice_streaming_fallback_used": bool(
                latency_summary.get("voice_streaming_fallback_used")
                or latency_summary.get("fallback_used")
            ),
            "voice_prewarm_used": bool(
                latency_summary.get("voice_prewarm_used")
                or latency_summary.get("prewarm_used")
            ),
            "voice_partial_playback": bool(
                latency_summary.get("voice_partial_playback")
                or latency_summary.get("partial_playback")
            ),
            "voice_anchor_state": str(latency_summary.get("voice_anchor_state") or ""),
            "voice_speaking_visual_active": bool(
                latency_summary.get("voice_speaking_visual_active")
                or latency_summary.get("speaking_visual_active")
            ),
            "voice_audio_reactive_source": str(
                latency_summary.get("voice_audio_reactive_source")
                or latency_summary.get("audio_reactive_source")
                or ""
            ),
            "voice_audio_reactive_available": bool(
                latency_summary.get("voice_audio_reactive_available")
                or latency_summary.get("audio_reactive_available")
            ),
            "voice_anchor_motion_intensity": float(
                latency_summary.get("voice_anchor_motion_intensity")
                or latency_summary.get("motion_intensity")
                or 0.0
            ),
            "voice_anchor_audio_level": float(
                latency_summary.get("voice_anchor_audio_level")
                or latency_summary.get("smoothed_output_level")
                or latency_summary.get("output_level_rms")
                or 0.0
            ),
            "voice_visualizer_update_hz": int(
                latency_summary.get("voice_visualizer_update_hz")
                or latency_summary.get("visualizer_update_hz")
                or 0
            ),
            "voice_anchor_user_heard_claimed": bool(
                latency_summary.get("voice_anchor_user_heard_claimed")
                or latency_summary.get("user_heard_claimed")
            ),
            **ui_perceived_latency,
            "hard_timeout": bool(
                self.observation.process_killed
                or str(self.observation.status).strip().lower()
                in {"hard_timeout", "timeout", "process_killed"}
            ),
            "process_killed": self.observation.process_killed,
            "child_pid": self.observation.child_pid,
            "hard_timeout_seconds": self.observation.timeout_seconds,
            "timeout_seconds": self.observation.timeout_seconds,
            "elapsed_ms": self.observation.elapsed_ms or self.observation.latency_ms,
            "stdout_tail": self.observation.stdout_tail,
            "stderr_tail": self.observation.stderr_tail,
            "checkpoint_path": self.observation.checkpoint_path,
            "response_json_bytes": self.observation.response_json_bytes,
            "event_count": self.observation.event_count,
            "job_count": self.observation.job_count,
            "ui_event_count": self.observation.ui_event_count,
            "workspace_item_count": self.observation.workspace_item_count,
            "active_context_bytes": self.observation.active_context_bytes,
            "active_context_item_count": self.observation.active_context_item_count,
            "truncated_workspace_items": self.observation.truncated_workspace_items,
            "largest_payload_fields": list(self.observation.largest_payload_fields),
            "payload_guardrail_triggered": self.observation.payload_guardrail_triggered,
            "payload_guardrail_reason": self.observation.payload_guardrail_reason,
            "serialized_result_field_count": 0,
            "route_handler_subspans": self.observation.route_handler_subspans,
            "failure_category": self.failure_category,
            "failure_reason": self.failure_reason,
            "historical_blocker_labels": historical_blocker_labels,
            "known_lane_labels": known_lane_labels,
            "durable_row_written": True,
            "score_in_pass_fail": self.score_in_pass_fail,
            "scoring_note": self.scoring_note,
            "context_lane": self.case.context_lane,
            "seeded_context_required": self.case.seeded_context_required,
            "expected_context_source": self.case.expected_context_source,
            "expected_prior_family": self.case.expected_prior_family,
            "expected_prior_tool": self.case.expected_prior_tool,
            "expected_target_binding": self.case.expected_target_binding,
            "expected_alternate_target": self.case.expected_alternate_target,
            "expected_confirmation_state": self.case.expected_confirmation_state,
            "expected_behavior_without_context": self.case.expected_behavior_without_context,
            "case": self.case.to_dict(),
            "observation": self.observation.to_dict(),
            "assertions": {name: outcome.to_dict() for name, outcome in self.assertions.items()},
            "passed": self.passed,
        }
        payload["serialized_result_field_count"] = len(payload)
        return json_ready(payload)


def command_eval_result_from_dict(payload: dict[str, Any]) -> CommandEvalResult:
    case_payload = dict(payload.get("case") or {})
    expected_payload = dict(case_payload.get("expected") or {})
    expected = ExpectedBehavior(
        route_family=str(expected_payload.get("route_family") or ""),
        subsystem=str(expected_payload.get("subsystem") or ""),
        tools=tuple(str(item) for item in expected_payload.get("tools") or ()),
        target_slots=dict(expected_payload.get("target_slots") or {}),
        clarification=str(expected_payload.get("clarification") or "none"),
        approval=str(expected_payload.get("approval") or "not_expected"),
        result_state=str(expected_payload.get("result_state") or "dry_run_or_completed"),
        verification=str(expected_payload.get("verification") or "bounded_or_not_applicable"),
        response_terms=tuple(str(item) for item in expected_payload.get("response_terms") or ()),
        forbidden_overclaims=tuple(str(item) for item in expected_payload.get("forbidden_overclaims") or ()),
        latency_ms_max=int(expected_payload.get("latency_ms_max") or 2500),
    )
    case = CommandEvalCase(
        case_id=str(case_payload.get("case_id") or ""),
        message=str(case_payload.get("message") or ""),
        expected=expected,
        session_id=str(case_payload.get("session_id") or "default"),
        surface_mode=str(case_payload.get("surface_mode") or "ghost"),
        active_module=str(case_payload.get("active_module") or "chartroom"),
        workspace_context=dict(case_payload.get("workspace_context") or {}),
        input_context=dict(case_payload.get("input_context") or {}),
        active_request_state=dict(case_payload.get("active_request_state") or {}),
        sequence_id=str(case_payload.get("sequence_id") or ""),
        turn_index=int(case_payload.get("turn_index") or 0),
        tags=tuple(str(item) for item in case_payload.get("tags") or ()),
        notes=str(case_payload.get("notes") or ""),
        context_lane=str(case_payload.get("context_lane") or payload.get("context_lane") or "not_context_dependent"),
        seeded_context_required=bool(case_payload.get("seeded_context_required", payload.get("seeded_context_required", False))),
        expected_context_source=str(case_payload.get("expected_context_source") or payload.get("expected_context_source") or "none"),
        expected_prior_family=str(case_payload.get("expected_prior_family") or payload.get("expected_prior_family") or ""),
        expected_prior_tool=str(case_payload.get("expected_prior_tool") or payload.get("expected_prior_tool") or ""),
        expected_target_binding=str(case_payload.get("expected_target_binding") or payload.get("expected_target_binding") or ""),
        expected_alternate_target=str(case_payload.get("expected_alternate_target") or payload.get("expected_alternate_target") or ""),
        expected_confirmation_state=str(case_payload.get("expected_confirmation_state") or payload.get("expected_confirmation_state") or ""),
        expected_behavior_without_context=str(
            case_payload.get("expected_behavior_without_context")
            or payload.get("expected_behavior_without_context")
            or ""
        ),
    )
    observation_payload = dict(payload.get("observation") or {})
    latency_summary_payload = dict(
        observation_payload.get("latency_summary")
        or payload.get("latency_summary")
        or {}
    )
    latency_summary_payload = _merge_ui_perceived_latency_payload(
        latency_summary_payload,
        observation_payload,
        payload,
    )
    observation = CoreObservation(
        case_id=str(observation_payload.get("case_id") or case.case_id),
        input_boundary=str(observation_payload.get("input_boundary") or ""),
        latency_ms=float(observation_payload.get("latency_ms") or 0),
        ui_response=str(observation_payload.get("ui_response") or ""),
        session_id=str(observation_payload.get("session_id") or payload.get("session_id") or case.session_id),
        status=str(observation_payload.get("status") or payload.get("status") or "completed"),
        process_killed=bool(observation_payload.get("process_killed", payload.get("process_killed", False))),
        timeout_seconds=float(observation_payload.get("timeout_seconds") or payload.get("timeout_seconds") or 0.0),
        elapsed_ms=float(observation_payload.get("elapsed_ms") or payload.get("elapsed_ms") or observation_payload.get("latency_ms") or 0.0),
        child_pid=int(observation_payload.get("child_pid") or payload.get("child_pid") or 0),
        stdout_tail=str(observation_payload.get("stdout_tail") or payload.get("stdout_tail") or ""),
        stderr_tail=str(observation_payload.get("stderr_tail") or payload.get("stderr_tail") or ""),
        checkpoint_path=str(observation_payload.get("checkpoint_path") or payload.get("checkpoint_path") or ""),
        actual_route_family=str(observation_payload.get("actual_route_family") or ""),
        actual_subsystem=str(observation_payload.get("actual_subsystem") or ""),
        tool_chain=tuple(str(item) for item in observation_payload.get("tool_chain") or ()),
        tool_results=tuple(dict(item) for item in observation_payload.get("tool_results") or () if isinstance(item, dict)),
        job_states=tuple(str(item) for item in observation_payload.get("job_states") or ()),
        result_state=str(observation_payload.get("result_state") or ""),
        verification_state=str(observation_payload.get("verification_state") or ""),
        clarification_observed=bool(observation_payload.get("clarification_observed")),
        approval_observed=bool(observation_payload.get("approval_observed")),
        target_slots=dict(observation_payload.get("target_slots") or {}),
        route_state=dict(observation_payload.get("route_state") or {}),
        planner_debug=dict(observation_payload.get("planner_debug") or {}),
        planner_obedience=dict(observation_payload.get("planner_obedience") or {}),
        response_active_request_state=dict(
            observation_payload.get("response_active_request_state")
            or payload.get("response_active_request_state")
            or {}
        ),
        snapshot_active_request_state=dict(
            observation_payload.get("snapshot_active_request_state")
            or payload.get("snapshot_active_request_state")
            or {}
        ),
        stage_timings_ms=dict(observation_payload.get("stage_timings_ms") or _stage_timings_from_payload(payload)),
        latency_trace=dict(observation_payload.get("latency_trace") or payload.get("latency_trace") or {}),
        latency_summary=latency_summary_payload,
        budget_result=dict(observation_payload.get("budget_result") or payload.get("budget_result") or {}),
        response_json_bytes=int(observation_payload.get("response_json_bytes") or payload.get("response_json_bytes") or 0),
        event_count=int(observation_payload.get("event_count") or payload.get("event_count") or 0),
        job_count=int(observation_payload.get("job_count") or payload.get("job_count") or 0),
        ui_event_count=int(observation_payload.get("ui_event_count") or payload.get("ui_event_count") or 0),
        workspace_item_count=int(observation_payload.get("workspace_item_count") or payload.get("workspace_item_count") or 0),
        active_context_bytes=int(observation_payload.get("active_context_bytes") or payload.get("active_context_bytes") or 0),
        active_context_item_count=int(observation_payload.get("active_context_item_count") or payload.get("active_context_item_count") or 0),
        truncated_workspace_items=bool(observation_payload.get("truncated_workspace_items") or payload.get("truncated_workspace_items")),
        largest_payload_fields=tuple(
            dict(item)
            for item in (observation_payload.get("largest_payload_fields") or payload.get("largest_payload_fields") or ())
            if isinstance(item, dict)
        ),
        payload_guardrail_triggered=bool(observation_payload.get("payload_guardrail_triggered") or payload.get("payload_guardrail_triggered")),
        payload_guardrail_reason=str(observation_payload.get("payload_guardrail_reason") or payload.get("payload_guardrail_reason") or ""),
        route_handler_subspans=dict(observation_payload.get("route_handler_subspans") or payload.get("route_handler_subspans") or {}),
        ai_provider_calls=tuple(
            dict(item)
            for item in (observation_payload.get("ai_provider_calls") or payload.get("ai_provider_calls") or ())
            if isinstance(item, dict)
        ),
        actions=tuple(dict(item) for item in observation_payload.get("actions") or () if isinstance(item, dict)),
        events=tuple(dict(item) for item in observation_payload.get("events") or () if isinstance(item, dict)),
        errors=tuple(str(item) for item in observation_payload.get("errors") or ()),
    )
    assertions = {
        name: AssertionOutcome(
            name=str(item.get("name") or name),
            passed=bool(item.get("passed")),
            expected=item.get("expected"),
            actual=item.get("actual"),
            detail=str(item.get("detail") or ""),
        )
        for name, item in dict(payload.get("assertions") or {}).items()
        if isinstance(item, dict)
    }
    return CommandEvalResult(
        case=case,
        observation=observation,
        assertions=assertions,
        run_id=str(payload.get("run_id") or ""),
        case_index=int(payload.get("case_index") or 0),
        history_strategy=str(payload.get("history_strategy") or "shared_session"),
        failure_category=str(payload.get("failure_category") or "passed"),
        failure_reason=str(payload.get("failure_reason") or ""),
        score_in_pass_fail=bool(payload.get("score_in_pass_fail", True)),
        scoring_note=str(payload.get("scoring_note") or ""),
        artifact_flush_ms=float(payload.get("artifact_flush_ms") or 0.0),
    )


STAGE_LATENCY_FIELDS = (
    "http_boundary_ms",
    "session_create_or_load_ms",
    "history_context_ms",
    "memory_context_ms",
    "minimal_context_ms",
    "route_triage_ms",
    "snapshot_lookup_ms",
    "heavy_context_ms",
    "planner_route_ms",
    "route_handler_ms",
    "provider_call_ms",
    "provider_fallback_ms",
    "workspace_summary_ms",
    "workspace_detail_ms",
    "tool_planning_ms",
    "dry_run_plan_ms",
    "dry_run_executor_ms",
    "status_snapshot_ms",
    "active_request_state_ms",
    "event_collection_ms",
    "snapshot_ms",
    "job_collection_ms",
    "event_job_snapshot_ms",
    "db_write_ms",
    "response_compose_ms",
    "response_serialization_ms",
    "payload_compaction_ms",
    "memoized_summary_hits",
    "detail_load_deferred",
    "heavy_context_loaded",
    "fast_path_used",
    "planner_candidates_pruned_count",
    "snapshot_hot_path_hit",
    "heavy_context_avoided_by_snapshot",
    "invalidation_count",
    "inline_front_half_ms",
    "worker_back_half_ms",
    "subsystem_continuation_created",
    "direct_subsystem_async_converted",
    "returned_before_subsystem_completion",
    "async_conversion_expected",
    "asgi_request_receive_ms",
    "endpoint_dispatch_ms",
    "endpoint_return_to_asgi_ms",
    "http_client_wait_ms",
    "server_response_write_ms",
    "artifact_flush_ms",
    "total_latency_ms",
)


def _stage_timings(observation: CoreObservation, artifact_flush_ms: float = 0.0) -> dict[str, float]:
    raw = observation.stage_timings_ms if isinstance(observation.stage_timings_ms, dict) else {}
    timings = {field: round(float(raw.get(field) or 0.0), 3) for field in STAGE_LATENCY_FIELDS}
    if not timings["http_boundary_ms"]:
        timings["http_boundary_ms"] = round(float(observation.latency_ms or 0.0), 3)
    timings["artifact_flush_ms"] = round(float(artifact_flush_ms or raw.get("artifact_flush_ms") or 0.0), 3)
    if not timings["total_latency_ms"]:
        timings["total_latency_ms"] = round(float(observation.latency_ms or 0.0) + timings["artifact_flush_ms"], 3)
    attributed_fields = (
        "session_create_or_load_ms",
        "history_context_ms",
        "memory_context_ms",
        "minimal_context_ms",
        "route_triage_ms",
        "heavy_context_ms",
        "planner_route_ms",
        "route_handler_ms",
        "provider_call_ms",
        "provider_fallback_ms",
        "workspace_summary_ms",
        "workspace_detail_ms",
        "tool_planning_ms",
        "dry_run_plan_ms",
        "dry_run_executor_ms",
        "status_snapshot_ms",
        "active_request_state_ms",
        "event_collection_ms",
        "snapshot_ms",
        "job_collection_ms",
        "event_job_snapshot_ms",
        "db_write_ms",
        "response_compose_ms",
        "response_serialization_ms",
        "payload_compaction_ms",
        "artifact_flush_ms",
    )
    timings["unattributed_latency_ms"] = round(
        timings["total_latency_ms"] - sum(float(timings.get(field) or 0.0) for field in attributed_fields),
        3,
    )
    return timings


def _stage_timings_from_payload(payload: dict[str, Any]) -> dict[str, float]:
    return {
        field: float(payload.get(field) or 0.0)
        for field in STAGE_LATENCY_FIELDS
        if field in payload
    }


def _merge_ui_perceived_latency_payload(
    latency_summary: dict[str, Any],
    *payloads: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(latency_summary)
    fields = (
        *UI_PERCEIVED_LATENCY_NUMERIC_FIELDS,
        *UI_PERCEIVED_LATENCY_FLAG_FIELDS,
        "ui_render_visible_status",
    )
    for source in payloads:
        for field in fields:
            if field in source and field not in merged:
                merged[field] = source[field]
    return merged


def _ui_perceived_latency_fields(latency_summary: dict[str, Any]) -> dict[str, Any]:
    event_summary = _first_ui_event_render_summary(latency_summary)
    has_ui_latency_source = bool(event_summary) or any(
        _ui_latency_value(latency_summary, field) is not None
        for field in (
            *UI_PERCEIVED_LATENCY_NUMERIC_FIELDS,
            *UI_PERCEIVED_LATENCY_FLAG_FIELDS,
            "ui_render_visible_status",
        )
    )
    payload = {
        "event_stream_delay_ms": _optional_float(
            _ui_latency_value(latency_summary, "event_stream_delay_ms")
        ),
        "ui_bridge_apply_ms": _optional_float(
            _ui_latency_value(latency_summary, "ui_bridge_apply_ms")
            if _ui_latency_value(latency_summary, "ui_bridge_apply_ms") is not None
            else event_summary.get("received_to_bridge_update_ms")
        ),
        "ui_render_visible_ms": _optional_float(
            _ui_latency_value(latency_summary, "ui_render_visible_ms")
            if _ui_latency_value(latency_summary, "ui_render_visible_ms") is not None
            else event_summary.get("received_to_render_visible_ms")
        ),
        "ghost_first_visible_state_ms": _optional_float(
            _ui_latency_value(latency_summary, "ghost_first_visible_state_ms")
        ),
        "approval_prompt_visible_ms": _optional_float(
            _ui_latency_value(latency_summary, "approval_prompt_visible_ms")
        ),
        "voice_state_visible_ms": _optional_float(
            _ui_latency_value(latency_summary, "voice_state_visible_ms")
        ),
        "route_state_visible_ms": _optional_float(
            _ui_latency_value(latency_summary, "route_state_visible_ms")
        ),
        "polling_fallback_used": _truthy_latency_flag(
            _ui_latency_value(latency_summary, "polling_fallback_used")
            if _ui_latency_value(latency_summary, "polling_fallback_used") is not None
            else event_summary.get("used_polling_fallback")
        ),
        "reconnect_gap_detected": _truthy_latency_flag(
            _ui_latency_value(latency_summary, "reconnect_gap_detected")
            if _ui_latency_value(latency_summary, "reconnect_gap_detected") is not None
            else (
                event_summary.get("reconnect_gap_detected")
                if event_summary.get("reconnect_gap_detected") is not None
                else event_summary.get("reconnect_gap_recovered")
            )
        ),
    }
    render_status = str(
        _ui_latency_value(latency_summary, "ui_render_visible_status")
        or event_summary.get("render_confirmed")
        or ""
    ).strip().lower()
    if payload["ui_render_visible_ms"] is not None:
        payload["ui_render_visible_status"] = render_status or "measured"
    elif render_status in {"true", "measured", "confirmed"}:
        payload["ui_render_visible_status"] = "measured"
    else:
        payload["ui_render_visible_status"] = (
            (render_status or "not_measured")
            if has_ui_latency_source
            else None
        )
    return payload


def _ui_latency_value(latency_summary: dict[str, Any], field: str) -> Any:
    if field in latency_summary:
        return latency_summary.get(field)
    for nested_key in (
        "ui_perceived_latency",
        "ui_latency",
        "ui_bridge_latency",
        "ui_render_latency",
    ):
        nested = latency_summary.get(nested_key)
        if isinstance(nested, dict) and field in nested:
            return nested.get(field)
    return None


def _first_ui_event_render_summary(latency_summary: dict[str, Any]) -> dict[str, Any]:
    summaries = latency_summary.get("ui_event_render_latency_summaries")
    if isinstance(summaries, list):
        for item in summaries:
            if isinstance(item, dict):
                return dict(item)
    summary = latency_summary.get("ui_event_render_latency_summary")
    if isinstance(summary, dict):
        return dict(summary)
    nested = latency_summary.get("ui_perceived_latency")
    if isinstance(nested, dict):
        nested_summary = nested.get("ui_event_render_latency_summary")
        if isinstance(nested_summary, dict):
            return dict(nested_summary)
    return {}


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _truthy_latency_flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {
            "1",
            "true",
            "yes",
            "used",
            "detected",
            "recovered",
        }
    return bool(value)


def _latency_trace_for_observation(
    *,
    observation: CoreObservation,
    stage_timings: dict[str, float],
    provider_called: bool,
    ai_usage: dict[str, Any],
):
    if observation.latency_trace:
        existing = dict(observation.latency_trace)
        return build_latency_trace(
            metadata={
                "latency_trace": existing,
                "latency_summary": observation.latency_summary,
                "budget_result": observation.budget_result,
                "route_state": observation.route_state,
                "planner_debug": observation.planner_debug,
                "planner_obedience": observation.planner_obedience,
            },
            stage_timings_ms=stage_timings,
            trace_id=str(existing.get("trace_id") or ""),
            request_id=str(existing.get("request_id") or ""),
            session_id=observation.session_id,
            route_family=observation.actual_route_family or None,
            subsystem=observation.actual_subsystem or None,
            provider_called=provider_called,
            openai_called=bool(ai_usage.get("openai_called")),
            llm_called=bool(ai_usage.get("llm_called")),
            embedding_called=bool(ai_usage.get("embedding_called")),
            job_count=observation.job_count,
            event_count=observation.event_count,
            async_continuation=_observation_async_continuation(observation),
        )
    return build_latency_trace(
        metadata={
            "route_state": observation.route_state,
            "planner_debug": observation.planner_debug,
            "planner_obedience": observation.planner_obedience,
        },
        stage_timings_ms=stage_timings,
        request_id=observation.case_id,
        session_id=observation.session_id,
        surface_mode="ghost",
        route_family=observation.actual_route_family or None,
        subsystem=observation.actual_subsystem or None,
        total_ms=observation.latency_ms,
        provider_called=provider_called,
        openai_called=bool(ai_usage.get("openai_called")),
        llm_called=bool(ai_usage.get("llm_called")),
        embedding_called=bool(ai_usage.get("embedding_called")),
        job_count=observation.job_count,
        event_count=observation.event_count,
        async_continuation=_observation_async_continuation(observation),
    )


def _observation_async_continuation(observation: CoreObservation) -> bool:
    return any(
        str(state or "").strip().lower()
        not in {"", "completed", "failed", "cancelled", "canceled"}
        for state in observation.job_states
    )


def _route_candidates(route_state: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = route_state.get("candidates") if isinstance(route_state, dict) else []
    if not isinstance(candidates, list):
        return []
    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]


def _route_decline_reasons(route_candidates: list[dict[str, Any]]) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    for candidate in route_candidates:
        family = str(candidate.get("route_family") or "")
        decline = [
            *[str(item) for item in candidate.get("disqualifiers") or []],
            *[f"missing:{item}" for item in candidate.get("missing_evidence") or []],
        ]
        provider_reason = str(candidate.get("provider_fallback_reason") or "").strip()
        if provider_reason:
            decline.append(provider_reason)
        if family and decline:
            reasons[family] = decline
    return reasons


def _native_candidate_blocked_by(route_candidates: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for candidate in route_candidates:
        if str(candidate.get("route_family") or "") == "generic_provider":
            continue
        blockers.extend(str(item) for item in candidate.get("disqualifiers") or [])
        blockers.extend(f"missing:{item}" for item in candidate.get("missing_evidence") or [])
    return list(dict.fromkeys(blockers))


def _target_extraction_summary(route_state: dict[str, Any], tool_results: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    for result in tool_results:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        summary = data.get("target_extraction_summary")
        if isinstance(summary, dict):
            return dict(summary)
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    candidates = route_state.get("candidates") if isinstance(route_state.get("candidates"), list) else []
    selected_targets: list[dict[str, Any]] = []
    for candidate in candidates:
        for target in candidate.get("target_candidates") or []:
            if isinstance(target, dict) and target.get("selected"):
                selected_targets.append(dict(target))
    return {
        "winner_family": winner.get("route_family"),
        "selected_targets": selected_targets,
    }


def _deictic_binding_summary(route_state: dict[str, Any]) -> dict[str, Any]:
    deictic = route_state.get("deictic_binding") if isinstance(route_state.get("deictic_binding"), dict) else {}
    return dict(deictic)


def _missing_preconditions(route_candidates: list[dict[str, Any]], tool_results: tuple[dict[str, Any], ...]) -> list[str]:
    missing: list[str] = []
    for candidate in route_candidates:
        missing.extend(str(item) for item in candidate.get("missing_evidence") or [])
    for result in tool_results:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        preconditions = data.get("missing_preconditions")
        if isinstance(preconditions, list):
            missing.extend(str(item) for item in preconditions)
    return list(dict.fromkeys(missing))


def _route_surface_type(
    *,
    route_state: dict[str, Any],
    expected_family: str,
    actual_family: str,
    tool_chain: tuple[str, ...],
    score_in_pass_fail: bool,
) -> str:
    if not score_in_pass_fail:
        return "excluded"
    if route_state:
        return "planner"
    family = (expected_family or actual_family or "").strip().lower()
    if family in {"time", "notes", "terminal"}:
        return "direct"
    if tool_chain:
        return "legacy"
    return "legacy"


def _routing_engine_from_trace(
    *,
    planner_debug: dict[str, Any],
    planner_v2_debug: dict[str, Any],
    route_spine_debug: dict[str, Any],
    route_surface_type: str,
    actual_family: str,
    status: str,
    score_in_pass_fail: bool,
) -> str:
    explicit = (
        planner_debug.get("routing_engine")
        or planner_v2_debug.get("routing_engine")
        or route_spine_debug.get("routing_engine")
    )
    if explicit:
        return str(explicit)
    family = str(actual_family or "").strip()
    if family == "generic_provider":
        return "generic_provider"
    if not score_in_pass_fail or route_surface_type == "excluded":
        return "excluded"
    if str(status or "").strip().lower() in {"error", "hard_timeout", "timeout"}:
        return "error"
    if route_surface_type == "direct":
        return "direct_handler"
    if route_surface_type == "legacy":
        return "legacy_planner"
    if route_surface_type == "planner":
        return "legacy_planner"
    return "error"


def _implemented_routeable_status(expected_family: str) -> str:
    family = (expected_family or "").strip().lower()
    direct_only = {"time", "notes", "terminal"}
    scaffold_or_docs = {"trusted_hook_register"}
    if family in direct_only:
        return "implemented_direct_only"
    if family in scaffold_or_docs:
        return "scaffold_only"
    if family:
        return "implemented_routeable"
    return ""


def _fallback_reason(route_state: dict[str, Any], ui_response: str) -> str:
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    reason = str(winner.get("provider_fallback_reason") or "").strip()
    if reason:
        return reason
    if "OpenAI integration is not configured" in ui_response:
        return "provider_not_configured"
    if str(winner.get("route_family") or "") == "generic_provider":
        return "generic_provider_fallback"
    return ""


def _provider_called(events: tuple[dict[str, Any], ...], planner_debug: dict[str, Any]) -> bool:
    if planner_debug.get("provider_called"):
        return True
    for event in events:
        subsystem = str(event.get("subsystem") or event.get("source") or "").lower()
        event_type = str(event.get("event_type") or "").lower()
        if "provider" in subsystem or "openai" in subsystem or "provider" in event_type:
            return True
    return False


def _ai_usage_summary(*, case: CommandEvalCase, observation: CoreObservation) -> dict[str, Any]:
    calls = [dict(item) for item in observation.ai_provider_calls if isinstance(item, dict)]
    allowed = _provider_call_allowed(case)
    provider_call_count = len(calls)
    openai_call_count = sum(1 for item in calls if bool(item.get("openai_called")))
    llm_call_count = sum(1 for item in calls if bool(item.get("llm_called")))
    embedding_call_count = sum(1 for item in calls if bool(item.get("embedding_called")))
    provider_names = _unique_sorted(str(item.get("provider_name") or "") for item in calls)
    model_names = _unique_sorted(str(item.get("model_name") or "") for item in calls)
    purposes = _unique_sorted(str(item.get("purpose") or "") for item in calls)
    sources = _unique_sorted(str(item.get("source") or "") for item in calls)
    blocked_count = sum(1 for item in calls if bool(item.get("blocked")))
    violation = bool(provider_call_count and not allowed)
    if any(bool(item.get("provider_call_violation")) for item in calls) and not allowed:
        violation = True
    if not provider_call_count:
        summary = "no provider/model calls observed"
    else:
        suffix = "blocked" if blocked_count else "allowed" if allowed else "violation"
        summary = (
            f"{provider_call_count} provider/model call attempt(s); "
            f"openai={openai_call_count}, llm={llm_call_count}, embeddings={embedding_call_count}; {suffix}"
        )
    return {
        "provider_called": bool(provider_call_count),
        "openai_called": bool(openai_call_count),
        "llm_called": bool(llm_call_count),
        "embedding_called": bool(embedding_call_count),
        "provider_call_count": provider_call_count,
        "openai_call_count": openai_call_count,
        "llm_call_count": llm_call_count,
        "embedding_call_count": embedding_call_count,
        "provider_names": provider_names,
        "model_names": model_names,
        "provider_call_purposes": purposes,
        "provider_call_sources": sources,
        "provider_call_allowed": allowed,
        "provider_call_violation": violation,
        "ai_usage_summary": summary,
        "ai_provider_calls": calls,
    }


def _provider_call_allowed(case: CommandEvalCase) -> bool:
    tags = {str(tag).strip().lower() for tag in case.tags}
    return bool(tags & {"provider_fallback_diagnostic", "provider_allowed", "ai_allowed", "model_allowed"})


def _unique_sorted(values: Any) -> list[str]:
    return sorted({value for value in values if value})


def _action_has_external_effect(action: dict[str, Any]) -> bool:
    action_type = str(action.get("type") or "").strip().lower()
    return action_type in {"open_external", "send_external", "external_dispatch"}


def _approval_state(tool_results: tuple[dict[str, Any], ...], approval_observed: bool) -> str:
    for result in tool_results:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if data.get("approval_required"):
            return "approval_required"
        decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
        if decision.get("approval_state"):
            return str(decision.get("approval_state"))
    return "observed" if approval_observed else "not_required"


def _trust_state(tool_results: tuple[dict[str, Any], ...], route_state: dict[str, Any]) -> str:
    for result in tool_results:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        trust_state = data.get("trust_state") or data.get("trust_level")
        if trust_state:
            return str(trust_state)
        decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
        trust_state = decision.get("trust_state") or decision.get("trust_level")
        if trust_state:
            return str(trust_state)
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    trust_state = winner.get("trust_state") or winner.get("trust_level")
    return str(trust_state or "not_applicable")


def _historical_blocker_labels(*, case_id: str, actual_route_family: str, tool_chain: tuple[str, ...]) -> list[str]:
    if "routine_save" in case_id or actual_route_family == "routine" and "routine_save" in tool_chain:
        return ["known_unreproduced_product_latency_blocker"]
    return []


def _known_lane_labels(
    *,
    case_id: str,
    expected_route_family: str,
    actual_route_family: str,
    failure_category: str,
    historical_blocker_labels: list[str],
) -> list[str]:
    labels = list(historical_blocker_labels)
    if (
        failure_category == "latency_issue"
        and (expected_route_family in {"workspace_operations", "task_continuity"} or actual_route_family in {"workspace_operations", "task_continuity"})
    ):
        labels.append("known_workspace_latency_lane")
    if case_id.startswith("trusted_hook_register") and failure_category == "feature_map_overexpectation":
        labels.append("trusted_hook_register_feature_map_overexpectation")
    return list(dict.fromkeys(labels))


def _scenario_family(case_id: str) -> str:
    for marker in (
        "_unsupported_probe_",
        "_command_mode_",
        "_cross_family_",
        "_follow_up_",
        "_near_miss_",
        "_ambiguous_",
        "_canonical_",
        "_correction_",
        "_shorthand_",
        "_indirect_",
        "_question_",
        "_polite_",
        "_casual_",
        "_slang_",
        "_terse_",
        "_typo_",
        "_noisy_",
        "_deictic_",
        "_confirm_",
        "_negative_",
    ):
        if marker in case_id:
            return case_id.split(marker, 1)[0]
    parts = case_id.rsplit("_", 2)
    return parts[0] if parts else case_id


def _wording_style(case_id: str, tags: tuple[str, ...]) -> str:
    known_styles = (
        "canonical",
        "command_mode",
        "casual",
        "polite",
        "shorthand",
        "typo",
        "slang",
        "indirect",
        "question",
        "terse",
        "deictic",
        "follow_up",
        "ambiguous",
        "near_miss",
        "cross_family",
        "negative",
        "noisy",
        "confirm",
        "correction",
        "unsupported_probe",
    )
    for style in known_styles:
        if f"_{style}_" in case_id:
            return style
    for style in known_styles:
        if style in tags:
            return style
    return ""
