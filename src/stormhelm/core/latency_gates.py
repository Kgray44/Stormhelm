from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from enum import Enum
from pathlib import Path
from statistics import mean
from typing import Any

from stormhelm.shared.time import utc_now_iso


NATIVE_HOT_PATH_FAMILIES = {
    "browser_destination",
    "calculations",
    "discord_relay",
    "network",
    "screen_awareness",
    "software_control",
    "task_continuity",
    "workspace_operations",
}

PROTECTED_NATIVE_PROVIDER_FAMILIES = {
    "app_control",
    "browser_destination",
    "calculations",
    "camera_awareness",
    "discord_relay",
    "file_operation",
    "network",
    "screen_awareness",
    "software_control",
    "software_recovery",
    "system_control",
    "task_continuity",
    "trust_approvals",
    "voice_control",
    "web_retrieval",
    "workspace_operations",
}

PRIVATE_REPORT_KEYS = {
    "api_key",
    "audio",
    "authorization",
    "content",
    "discord_payload",
    "input",
    "message",
    "password",
    "payload",
    "prompt",
    "raw_audio",
    "raw_payload",
    "raw_prompt",
    "raw_screenshot",
    "screenshot",
    "secret",
    "token",
}


class LatencyGateStatistic(str, Enum):
    P50 = "p50"
    P90 = "p90"
    P95 = "p95"
    P99 = "p99"
    MAX = "max"
    COUNT = "count"
    RATIO = "ratio"


class LatencyGateSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    FAIL = "fail"
    RELEASE_BLOCKING = "release_blocking"


class LatencyReleasePosture(str, Enum):
    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    BLOCKED_LATENCY_REGRESSION = "blocked_latency_regression"
    BLOCKED_CORRECTNESS_REGRESSION = "blocked_correctness_regression"
    BLOCKED_TIMEOUT = "blocked_timeout"
    BLOCKED_UNKNOWN_OUTLIER = "blocked_unknown_outlier"
    BLOCKED_EXPIRED_SLOW_LANE = "blocked_expired_slow_lane"
    BLOCKED_PROVIDER_NATIVE_HIJACK = "blocked_provider_native_hijack"
    BLOCKED_MISSING_REQUIRED_METRICS = "blocked_missing_required_metrics"
    NOT_ENOUGH_SAMPLES = "not_enough_samples"
    INVALID_RUN = "invalid_run"


@dataclass(frozen=True, slots=True)
class LatencyGateResult:
    gate_id: str
    lane_id: str
    passed: bool
    severity: str
    observed_value: float | int | None
    threshold_value: float | int | None
    sample_count: int
    failing_rows: tuple[str, ...] = ()
    known_slow_lane_matches: tuple[str, ...] = ()
    unclassified_outliers: tuple[str, ...] = ()
    message: str = ""
    blocking_release: bool = False
    delta_from_baseline: float | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class LatencyGate:
    gate_id: str
    lane_id: str
    metric_name: str
    statistic: LatencyGateStatistic | str
    threshold_ms: float | None = None
    threshold_count: int | None = None
    threshold_ratio: float | None = None
    severity: LatencyGateSeverity | str = LatencyGateSeverity.WARNING
    applies_to: str = "focused_suite"
    route_family: str = ""
    subsystem: str = ""
    surface: str = ""
    allowed_known_slow_lane_ids: tuple[str, ...] = ()
    expiration_policy: str = "known_slow_lanes_must_be_unexpired"
    enabled: bool = True
    config_source: str = "stormhelm_default_l10"
    notes: str = ""
    min_sample_count: int = 1

    def evaluate(
        self,
        *,
        values: list[float],
        sample_rows: list[dict[str, Any]],
        known_slow_lane_matches: list[str] | None = None,
        unclassified_outliers: list[str] | None = None,
    ) -> LatencyGateResult:
        severity = _enum_value(self.severity)
        statistic = _enum_value(self.statistic)
        if not self.enabled:
            return LatencyGateResult(
                gate_id=self.gate_id,
                lane_id=self.lane_id,
                passed=True,
                severity=LatencyGateSeverity.INFO.value,
                observed_value=None,
                threshold_value=None,
                sample_count=0,
                message="Gate disabled.",
            )
        if len(values) < self.min_sample_count:
            return LatencyGateResult(
                gate_id=self.gate_id,
                lane_id=self.lane_id,
                passed=False,
                severity=LatencyGateSeverity.WARNING.value,
                observed_value=len(values),
                threshold_value=self.min_sample_count,
                sample_count=len(values),
                message=f"Not enough samples for {self.gate_id}: {len(values)} < {self.min_sample_count}.",
            )

        observed = _observed_stat(values, statistic)
        threshold = self.threshold_ms
        if statistic == LatencyGateStatistic.COUNT.value:
            observed = len(values)
            threshold = float(self.threshold_count if self.threshold_count is not None else 0)
        elif statistic == LatencyGateStatistic.RATIO.value:
            threshold = self.threshold_ratio
        if threshold is None:
            passed = True
        else:
            passed = float(observed or 0.0) <= float(threshold)
        message = (
            f"{self.gate_id} passed."
            if passed
            else f"{self.gate_id} observed {observed} above threshold {threshold}."
        )
        failing_rows = tuple(_row_id(row) for row in sample_rows if _numeric(row.get(self.metric_name)) is not None)
        return LatencyGateResult(
            gate_id=self.gate_id,
            lane_id=self.lane_id,
            passed=passed,
            severity=severity,
            observed_value=observed,
            threshold_value=threshold,
            sample_count=len(values),
            failing_rows=() if passed else failing_rows[:20],
            known_slow_lane_matches=tuple(known_slow_lane_matches or ()),
            unclassified_outliers=tuple(unclassified_outliers or ()),
            message=message,
            blocking_release=(not passed and severity == LatencyGateSeverity.RELEASE_BLOCKING.value),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["statistic"] = _enum_value(self.statistic)
        payload["severity"] = _enum_value(self.severity)
        return _json_ready(payload)


@dataclass(frozen=True, slots=True)
class LatencyLaneProfile:
    lane_id: str
    name: str
    description: str
    included_route_families: tuple[str, ...] = ()
    excluded_route_families: tuple[str, ...] = ()
    required_tags: tuple[str, ...] = ()
    excluded_tags: tuple[str, ...] = ()
    includes_provider_calls: bool = False
    includes_async_continuations: bool = False
    includes_voice: bool = False
    includes_ui: bool = False
    includes_render_visible: bool = False
    expected_sample_count_min: int = 1
    gate_ids: tuple[str, ...] = ()
    known_slow_lane_policy: str = "explicit_scoped_unexpired_only"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class KnownSlowLane:
    slow_lane_id: str
    route_family: str
    lane_id: str
    reason: str
    expected_latency_ms: float
    max_accepted_latency_ms: float
    mitigation_plan: str
    created_at: str
    expires_at: str
    subsystem: str = ""
    owner: str = ""
    regression_test_reference: str = ""
    issue_reference: str = ""
    allowed_count: int | None = None
    applies_to_tags: tuple[str, ...] = ()
    blocking_after_expiration: bool = True
    status: str = "active"

    def __post_init__(self) -> None:
        if not str(self.expires_at or "").strip():
            raise ValueError("KnownSlowLane.expires_at is required.")
        if not str(self.mitigation_plan or "").strip():
            raise ValueError("KnownSlowLane.mitigation_plan is required.")

    def is_expired(self, now: str | datetime | None = None) -> bool:
        return _parse_time(self.expires_at) <= _parse_time(now or utc_now_iso())

    def matches(self, row: dict[str, Any], *, lane_id: str, now: str | datetime | None = None) -> bool:
        return (
            self.status == "active"
            and self.lane_id == lane_id
            and self.route_family == _route_family(row)
            and _numeric(row.get("total_latency_ms")) is not None
            and float(row.get("total_latency_ms") or 0.0) <= self.max_accepted_latency_ms
        )

    def to_dict(self, *, now: str | datetime | None = None) -> dict[str, Any]:
        payload = asdict(self)
        payload["expired"] = self.is_expired(now)
        return _json_ready(payload)


def default_latency_lane_profiles() -> dict[str, LatencyLaneProfile]:
    return {
        "native_local_overall": LatencyLaneProfile(
            lane_id="native_local_overall",
            name="Native Local Overall",
            description="Local/native rows excluding provider fallback latency.",
            excluded_route_families=("generic_provider",),
            includes_provider_calls=False,
            gate_ids=("native.local.p95", "native.max.warning"),
        ),
        "native_hot_path": LatencyLaneProfile(
            lane_id="native_hot_path",
            name="Native Hot Path",
            description="L8 native hot paths without provider calls.",
            included_route_families=tuple(sorted(NATIVE_HOT_PATH_FAMILIES)),
            includes_provider_calls=False,
            gate_ids=("native.hot_path.p95",),
        ),
        "calculations_hot_path": _route_lane("calculations_hot_path", "calculations", "Calculations Hot Path"),
        "browser_destination_hot_path": _route_lane("browser_destination_hot_path", "browser_destination", "Browser Destination Hot Path"),
        "software_plan_hot_path": _route_lane("software_plan_hot_path", "software_control", "Software Plan Hot Path"),
        "discord_preview_hot_path": _route_lane("discord_preview_hot_path", "discord_relay", "Discord Preview Hot Path"),
        "screen_simple_context_hot_path": _route_lane("screen_simple_context_hot_path", "screen_awareness", "Screen Simple Context Hot Path"),
        "workspace_task_memory_hot_path": _route_lane("workspace_task_memory_hot_path", "task_continuity", "Workspace/Task/Memory Hot Path"),
        "network_cached_status_hot_path": _route_lane("network_cached_status_hot_path", "network", "Network Cached Status Hot Path"),
        "async_long_task_ack": LatencyLaneProfile(
            lane_id="async_long_task_ack",
            name="Async Long Task Acknowledgement",
            description="Rows that should be judged by first feedback/ack, not full completion.",
            includes_async_continuations=True,
            gate_ids=("async.ack.p95",),
        ),
        "provider_fallback": LatencyLaneProfile(
            lane_id="provider_fallback",
            name="Provider Fallback",
            description="Provider fallback rows and provider timing only.",
            included_route_families=("generic_provider",),
            includes_provider_calls=True,
            gate_ids=("provider.first_output.p95",),
        ),
        "provider_enabled_native_protection": LatencyLaneProfile(
            lane_id="provider_enabled_native_protection",
            name="Provider Native Protection",
            description="Native rows where provider calls must remain zero unless explicitly expected.",
            includes_provider_calls=False,
            gate_ids=("provider.native_hijack.count",),
        ),
        "voice_mock_first_audio": LatencyLaneProfile(
            lane_id="voice_mock_first_audio",
            name="Voice Mock First Audio",
            description="Mock/local first-audio timing without user-heard claims.",
            includes_voice=True,
            gate_ids=("voice.first_audio_mock.p95",),
        ),
        "voice_realtime_bounded": LatencyLaneProfile(
            lane_id="voice_realtime_bounded",
            name="Voice Realtime Bounded",
            description="Realtime-visible bounded voice rows.",
            includes_voice=True,
        ),
        "ui_bridge_event_apply": LatencyLaneProfile(
            lane_id="ui_bridge_event_apply",
            name="UI Bridge Event Apply",
            description="Event frame to bridge/model timing.",
            includes_ui=True,
            gate_ids=("ui.bridge_apply.p95",),
        ),
        "ui_render_visible": LatencyLaneProfile(
            lane_id="ui_render_visible",
            name="UI Render Visible",
            description="True render-visible timing where confirmed; unknown remains unknown.",
            includes_ui=True,
            includes_render_visible=True,
        ),
        "command_eval_correctness_latency": LatencyLaneProfile(
            lane_id="command_eval_correctness_latency",
            name="Command Eval Correctness + Latency",
            description="Combined correctness and latency accounting without collapsing categories.",
        ),
        "full_kraken_suite": LatencyLaneProfile(
            lane_id="full_kraken_suite",
            name="Full Kraken Suite",
            description="Full command-eval profile including classified long-running lanes.",
            includes_provider_calls=True,
            includes_async_continuations=True,
            includes_voice=True,
            includes_ui=True,
        ),
    }


def default_latency_gates() -> tuple[LatencyGate, ...]:
    return (
        LatencyGate("native.local.p95", "native_local_overall", "total_latency_ms", "p95", threshold_ms=2000, severity="release_blocking", applies_to="focused_suite"),
        LatencyGate("ghost.first_feedback.p95", "native_local_overall", "first_feedback_ms", "p95", threshold_ms=500, severity="warning", applies_to="focused_suite", min_sample_count=1),
        LatencyGate("planner.route.p95", "native_local_overall", "planner_route_ms", "p95", threshold_ms=500, severity="release_blocking", applies_to="focused_suite", min_sample_count=1),
        LatencyGate("route.handler.p95", "native_local_overall", "route_handler_ms", "p95", threshold_ms=2000, severity="release_blocking", applies_to="focused_suite", min_sample_count=1),
        LatencyGate("voice.first_audio_mock.p95", "voice_mock_first_audio", "voice_first_audio_ms", "p95", threshold_ms=3000, severity="release_blocking", applies_to="voice_lane", min_sample_count=1),
        LatencyGate("provider.first_output.p95", "provider_fallback", "provider_first_output_ms", "p95", threshold_ms=3000, severity="warning", applies_to="provider_lane", min_sample_count=1),
    )


def rows_for_lane(rows: list[dict[str, Any]], lane: LatencyLaneProfile) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        if not _row_matches_lane(row, lane):
            continue
        selected.append(row)
    return selected


def build_latency_gate_report(
    rows: list[dict[str, Any]],
    *,
    profile: str = "focused_hot_path_profile",
    gates: list[LatencyGate] | tuple[LatencyGate, ...] | None = None,
    known_slow_lanes: list[KnownSlowLane] | tuple[KnownSlowLane, ...] | None = None,
    live_provider_run: bool = False,
    run_mode: str = "headless",
    now: str | datetime | None = None,
) -> dict[str, Any]:
    safe_rows = [_sanitize_row(row) for row in rows if isinstance(row, dict)]
    now_text = _format_time(now or utc_now_iso())
    lanes = default_latency_lane_profiles()
    known_lanes = list(known_slow_lanes or ())
    lane_rows = {lane_id: rows_for_lane(safe_rows, lane) for lane_id, lane in lanes.items()}
    lane_summary = {
        lane_id: {
            **_value_summary([_latency_value_for_lane(row, lane_id) for row in selected]),
            "expected_sample_count_min": lanes[lane_id].expected_sample_count_min,
        }
        for lane_id, selected in lane_rows.items()
    }
    provider_metrics = _provider_fallback_metrics(safe_rows, live_provider_run=live_provider_run)
    ui_metrics = _ui_perceived_latency_metrics(safe_rows)
    voice_metrics = _voice_first_audio_metrics(safe_rows)
    hard_timeout_count = sum(1 for row in safe_rows if _is_hard_timeout(row))
    correctness_failure_count = sum(1 for row in safe_rows if _is_correctness_failure(row))
    outliers = classify_latency_outliers(
        safe_rows,
        lane_id="full_kraken_suite" if profile == "full_kraken_profile" else "native_local_overall",
        threshold_ms=40000 if profile in {"full_kraken_profile", "command_eval_profile"} else 5000,
        p95_ms=_value_summary([_numeric(row.get("total_latency_ms")) for row in safe_rows])["p95"] or 0,
        known_slow_lanes=known_lanes,
        now=now_text,
    )
    expired_slow_lane_matches = [item for item in outliers if item.get("classification") == "known_slow_lane_expired"]
    unclassified_severe = [
        item for item in outliers if item.get("classification") == "unclassified" and float(item.get("total_ms") or 0.0) >= 40000
    ]

    gate_results: list[LatencyGateResult] = []
    selected_gates = tuple(gates or default_latency_gates())
    for gate in selected_gates:
        if gate.lane_id not in lane_rows:
            continue
        values = [
            _metric_value(row, gate.metric_name, lane_id=gate.lane_id)
            for row in lane_rows[gate.lane_id]
        ]
        values = [float(value) for value in values if value is not None]
        if not values:
            continue
        gate_results.append(gate.evaluate(values=values, sample_rows=lane_rows[gate.lane_id]))
    if provider_metrics["unexpected_provider_native_call_count"]:
        gate_results.append(
            LatencyGateResult(
                gate_id="provider.native_hijack.count",
                lane_id="provider_enabled_native_protection",
                passed=False,
                severity=LatencyGateSeverity.RELEASE_BLOCKING.value,
                observed_value=provider_metrics["unexpected_provider_native_call_count"],
                threshold_value=0,
                sample_count=len(safe_rows),
                message="Unexpected provider call appeared in protected native route lane.",
                blocking_release=True,
            )
        )
    if ui_metrics["fake_render_confirmed_count"]:
        gate_results.append(
            LatencyGateResult(
                gate_id="ui.render_confirmed.source_required",
                lane_id="ui_render_visible",
                passed=False,
                severity=LatencyGateSeverity.RELEASE_BLOCKING.value,
                observed_value=ui_metrics["fake_render_confirmed_count"],
                threshold_value=0,
                sample_count=len(safe_rows),
                message="Render-visible timing was marked confirmed without confirmation evidence.",
                blocking_release=True,
            )
        )
    if unclassified_severe:
        gate_results.append(
            LatencyGateResult(
                gate_id="outlier.unclassified_severe.count",
                lane_id="full_kraken_suite",
                passed=False,
                severity=LatencyGateSeverity.RELEASE_BLOCKING.value,
                observed_value=len(unclassified_severe),
                threshold_value=0,
                sample_count=len(safe_rows),
                unclassified_outliers=tuple(str(item.get("row_id") or "") for item in unclassified_severe),
                message="Unclassified severe max latency outlier above hard ceiling.",
                blocking_release=True,
            )
        )
    if expired_slow_lane_matches:
        gate_results.append(
            LatencyGateResult(
                gate_id="known_slow_lane.expired.count",
                lane_id="full_kraken_suite",
                passed=False,
                severity=LatencyGateSeverity.RELEASE_BLOCKING.value,
                observed_value=len(expired_slow_lane_matches),
                threshold_value=0,
                sample_count=len(safe_rows),
                message="Expired known slow lane matched an outlier.",
                blocking_release=True,
            )
        )
    release_posture = determine_release_posture(
        gate_results,
        hard_timeout_count=hard_timeout_count,
        unexpected_provider_native_call_count=provider_metrics["unexpected_provider_native_call_count"],
        unclassified_outlier_count=len(unclassified_severe),
        expired_slow_lane_count=len(expired_slow_lane_matches),
        correctness_failure_count=correctness_failure_count,
        fake_render_confirmed_count=ui_metrics["fake_render_confirmed_count"],
        sample_count=len(safe_rows),
    )
    return _json_ready(
        {
            "phase": "L10",
            "run_metadata": {
                "profile": profile,
                "run_mode": run_mode,
                "generated_at": now_text,
                "sample_count": len(safe_rows),
                "provider_fallback_default_enabled": False,
            },
            "profiles": _profile_summary(profile),
            "lane_profiles": {lane_id: lane.to_dict() for lane_id, lane in lanes.items()},
            "lane_summary": lane_summary,
            "gates": [gate.to_dict() for gate in selected_gates],
            "gate_results": [result.to_dict() for result in gate_results],
            "gate_summary": _gate_summary(gate_results),
            "release_posture": release_posture,
            "known_baseline_gaps": default_known_baseline_gaps(),
            "known_slow_lanes": [lane.to_dict(now=now_text) for lane in known_lanes],
            "expired_slow_lanes": [lane.to_dict(now=now_text) for lane in known_lanes if lane.is_expired(now_text)],
            "outlier_investigation": outliers,
            "route_family_histograms": build_route_family_histograms(safe_rows, group_by=("route_family", "lane_id")),
            "provider_fallback_metrics": provider_metrics,
            "voice_first_audio_metrics": voice_metrics,
            "ui_perceived_latency_metrics": ui_metrics,
            "correctness_latency_summary": {
                "correctness_failure_count": correctness_failure_count,
                "latency_failure_count": sum(1 for result in gate_results if not result.passed and "latency" in result.message.lower()),
                "hard_timeout_count": hard_timeout_count,
            },
            "recommended_next_actions": _recommended_next_actions(release_posture, outliers),
        }
    )


def determine_release_posture(
    gate_results: list[LatencyGateResult],
    *,
    hard_timeout_count: int,
    unexpected_provider_native_call_count: int = 0,
    unclassified_outlier_count: int = 0,
    expired_slow_lane_count: int = 0,
    correctness_failure_count: int = 0,
    fake_render_confirmed_count: int = 0,
    sample_count: int | None = None,
) -> dict[str, Any]:
    failed = [result for result in gate_results if not result.passed and result.severity in {LatencyGateSeverity.FAIL.value, LatencyGateSeverity.RELEASE_BLOCKING.value}]
    warned = [result for result in gate_results if not result.passed and result.severity == LatencyGateSeverity.WARNING.value]
    blocking_reasons = [f"{result.gate_id}: {result.message}" for result in failed if result.blocking_release or result.severity == LatencyGateSeverity.RELEASE_BLOCKING.value]
    if sample_count == 0:
        posture = LatencyReleasePosture.NOT_ENOUGH_SAMPLES.value
    elif fake_render_confirmed_count:
        posture = LatencyReleasePosture.BLOCKED_MISSING_REQUIRED_METRICS.value
    elif hard_timeout_count:
        posture = LatencyReleasePosture.BLOCKED_TIMEOUT.value
    elif unexpected_provider_native_call_count:
        posture = LatencyReleasePosture.BLOCKED_PROVIDER_NATIVE_HIJACK.value
    elif expired_slow_lane_count:
        posture = LatencyReleasePosture.BLOCKED_EXPIRED_SLOW_LANE.value
    elif unclassified_outlier_count:
        posture = LatencyReleasePosture.BLOCKED_UNKNOWN_OUTLIER.value
    elif blocking_reasons:
        posture = LatencyReleasePosture.BLOCKED_LATENCY_REGRESSION.value
    elif warned:
        posture = LatencyReleasePosture.PASS_WITH_WARNINGS.value
    else:
        posture = LatencyReleasePosture.PASS.value
    return {
        "posture": posture,
        "blocking_reasons": blocking_reasons,
        "warning_reasons": [f"{result.gate_id}: {result.message}" for result in warned],
        "gates_passed": sum(1 for result in gate_results if result.passed),
        "gates_failed": len(failed),
        "gates_warned": len(warned),
        "known_slow_lanes_active": 0,
        "known_slow_lanes_expired": expired_slow_lane_count,
        "unclassified_outliers": unclassified_outlier_count,
        "hard_timeout_count": hard_timeout_count,
        "unexpected_provider_native_call_count": unexpected_provider_native_call_count,
        "correctness_failure_count": correctness_failure_count,
        "generated_at": utc_now_iso(),
    }


def classify_latency_outliers(
    rows: list[dict[str, Any]],
    *,
    lane_id: str,
    threshold_ms: float,
    p95_ms: float,
    known_slow_lanes: list[KnownSlowLane] | tuple[KnownSlowLane, ...] | None = None,
    now: str | datetime | None = None,
) -> list[dict[str, Any]]:
    outliers: list[dict[str, Any]] = []
    for row in rows:
        total = _numeric(row.get("total_latency_ms") or row.get("latency_ms"))
        if total is None or total <= threshold_ms:
            continue
        classification = _classify_outlier(row, lane_id=lane_id)
        known_match = ""
        for slow_lane in known_slow_lanes or ():
            if slow_lane.matches(row, lane_id=lane_id, now=now):
                known_match = slow_lane.slow_lane_id
                classification = "known_slow_lane_expired" if slow_lane.is_expired(now) else "known_slow_lane_active"
                break
        outliers.append(
            {
                "row_id": _row_id(row),
                "request_id": str(row.get("request_id") or ""),
                "lane_id": lane_id,
                "route_family": _route_family(row),
                "subsystem": str(row.get("subsystem") or row.get("actual_subsystem") or ""),
                "total_ms": total,
                "p95_delta_ms": round(total - float(p95_ms or 0.0), 3),
                "longest_stage": str(row.get("longest_stage") or ""),
                "longest_stage_ms": _numeric(row.get("longest_stage_ms")),
                "budget_label": str(row.get("budget_label") or ""),
                "budget_exceeded": bool(row.get("budget_exceeded")),
                "async_continuation": bool(row.get("async_continuation") or row.get("async_initial_response_returned")),
                "provider_fallback_used": _provider_called(row),
                "provider_timing_summary": _provider_timing_summary(row),
                "cache_hit": row.get("cache_hit") if row.get("cache_hit") is not None else row.get("l8_cache_hit"),
                "heavy_context_used": bool(row.get("heavy_context_used") or row.get("heavy_context_loaded") or row.get("l8_heavy_context_used")),
                "ui_event_delay": row.get("event_stream_delay_ms") or row.get("ui_bridge_apply_ms"),
                "voice_first_audio_ms": row.get("voice_first_audio_ms"),
                "known_slow_lane_match": known_match,
                "classification": classification,
                "recommended_action": _recommended_action_for_classification(classification),
            }
        )
    return outliers


def build_route_family_histograms(
    rows: list[dict[str, Any]],
    *,
    group_by: tuple[str, ...] = ("route_family",),
    low_sample_threshold: int = 5,
) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _histogram_key(row, group_by)
        buckets.setdefault(key, []).append(row)
    histograms: dict[str, dict[str, Any]] = {}
    for key, bucket in sorted(buckets.items()):
        values = [_numeric(row.get("total_latency_ms") or row.get("latency_ms")) for row in bucket]
        stats = _value_summary(values)
        stats.update(
            {
                "hard_timeout_count": sum(1 for row in bucket if _is_hard_timeout(row)),
                "budget_exceeded_count": sum(1 for row in bucket if row.get("budget_exceeded")),
                "provider_call_count": sum(_provider_call_count(row) for row in bucket),
                "async_continuation_count": sum(1 for row in bucket if row.get("async_continuation") or row.get("async_initial_response_returned")),
                "correctness_failure_count": sum(1 for row in bucket if _is_correctness_failure(row)),
                "unknown_classification_count": sum(1 for row in bucket if row.get("classification") in {"unclassified", ""}),
                "low_confidence": stats["count"] < low_sample_threshold,
            }
        )
        histograms[key] = stats
    return histograms


def format_latency_gate_report_markdown(report: dict[str, Any]) -> str:
    posture = report.get("release_posture") if isinstance(report.get("release_posture"), dict) else {}
    lines = [
        "# Stormhelm L10 Latency Gate Report",
        "",
        "## Release Posture",
        f"- posture: {posture.get('posture', 'invalid_run')}",
        f"- blocking_reasons: {posture.get('blocking_reasons', [])}",
        f"- warning_reasons: {posture.get('warning_reasons', [])}",
        "",
        "## Gate Summary",
        f"- {report.get('gate_summary', {})}",
        "",
        "## Lane Summary",
        f"- native_local_overall: {(report.get('lane_summary') or {}).get('native_local_overall', {})}",
        f"- provider_fallback: {(report.get('lane_summary') or {}).get('provider_fallback', {})}",
        "",
        "## Provider Fallback Metrics",
        f"- {report.get('provider_fallback_metrics', {})}",
        "",
        "## Voice First-Audio Metrics",
        f"- {report.get('voice_first_audio_metrics', {})}",
        "",
        "## UI Perceived-Latency Metrics",
        f"- {report.get('ui_perceived_latency_metrics', {})}",
        "",
        "## Known Baseline / Non-Blocking Gaps",
    ]
    for note in report.get("known_baseline_gaps", []):
        if not isinstance(note, dict):
            continue
        lines.append(
            f"- {note.get('gap_id')}: {note.get('current_status')} | blocking={note.get('blocking')} | affects_gates={note.get('affects_latency_gates')}"
        )
    lines.extend(["", "## Outlier Investigation"])
    outliers = report.get("outlier_investigation") or []
    if not outliers:
        lines.append("- None.")
    for item in outliers[:20]:
        if isinstance(item, dict):
            lines.append(
                f"- {item.get('row_id')}: {item.get('total_ms')} ms | {item.get('classification')} | longest={item.get('longest_stage')}"
            )
    lines.extend(["", "## Recommended Next Actions"])
    for action in report.get("recommended_next_actions", []):
        lines.append(f"- {action}")
    return "\n".join(lines).strip() + "\n"


def write_latency_gate_report(output_dir: Path, report: dict[str, Any]) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latency_profile_report.json"
    md_path = output_dir / "latency_profile_report.md"
    json_path.write_text(json.dumps(_json_ready(report), indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(format_latency_gate_report_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def default_known_baseline_gaps() -> list[dict[str, Any]]:
    return [
        {
            "gap_id": "l7_1_render_visible_unknown",
            "source_phase": "L7.1",
            "current_status": "True QML render-visible timing may be unknown/not_measured unless a live QML hook confirms it.",
            "affects_latency_gates": "ui_render_visible only when live_ui profile requires it",
            "blocking": False,
            "recommended_follow_up": "Keep bridge/model timing; require live UI mode before gating render-visible p95.",
        },
        {
            "gap_id": "l9_live_provider_streaming_not_run",
            "source_phase": "L9",
            "current_status": "Mock provider streaming metrics are available; live provider token streaming is not required for local L10 gates.",
            "affects_latency_gates": "provider live lane only",
            "blocking": False,
            "recommended_follow_up": "Add a live-provider smoke lane only when provider streaming contract is available.",
        },
        {
            "gap_id": "command_usability_web_retrieval_fetch_coverage",
            "source_phase": "pre-L10 baseline",
            "current_status": "tests/test_command_usability_evaluation.py may still fail registry/corpus coverage for web_retrieval_fetch.",
            "affects_latency_gates": "no",
            "blocking": False,
            "recommended_follow_up": "Classify separately from latency and routing regressions.",
        },
        {
            "gap_id": "windows_pytest_temp_cleanup_winerror5",
            "source_phase": "environment",
            "current_status": "Windows pytest temp cleanup may emit WinError 5 after otherwise passing tests.",
            "affects_latency_gates": "no unless report generation/test execution fails",
            "blocking": False,
            "recommended_follow_up": "Treat as environment noise when it appears after successful test execution.",
        },
    ]


def mock_provider_rows(samples: int) -> list[dict[str, Any]]:
    return [
        {
            "test_id": f"provider-mock-{index}",
            "actual_route_family": "generic_provider",
            "provider_called": True,
            "provider_call_count": 1,
            "provider_first_output_ms": 1.0,
            "provider_total_ms": 4.0,
            "provider_streaming_used": True,
            "provider_partial_result_count": 1,
            "provider_timing_mode": "mock",
            "total_latency_ms": 4.0,
        }
        for index in range(max(0, int(samples)))
    ]


def mock_voice_rows(samples: int) -> list[dict[str, Any]]:
    return [
        {
            "test_id": f"voice-mock-{index}",
            "actual_route_family": "voice_control",
            "voice_first_audio_ms": 900.0,
            "voice_tts_first_chunk_ms": 250.0,
            "voice_playback_start_ms": 450.0,
            "voice_user_heard_claimed": False,
            "total_latency_ms": 900.0,
        }
        for index in range(max(0, int(samples)))
    ]


def load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _route_lane(lane_id: str, route_family: str, name: str) -> LatencyLaneProfile:
    return LatencyLaneProfile(
        lane_id=lane_id,
        name=name,
        description=f"{name} rows excluding provider fallback.",
        included_route_families=(route_family,),
        includes_provider_calls=False,
    )


def _row_matches_lane(row: dict[str, Any], lane: LatencyLaneProfile) -> bool:
    route = _route_family(row)
    lane_id = lane.lane_id
    if lane_id == "provider_fallback":
        return _provider_called(row) or route == "generic_provider" or row.get("provider_first_output_ms") is not None
    if lane_id == "native_local_overall":
        return route not in {"generic_provider", ""} and not _provider_called(row)
    if lane_id == "native_hot_path":
        return not _provider_called(row) and (
            bool(str(row.get("l8_hot_path_name") or row.get("hot_path_name") or "").strip())
            or route in NATIVE_HOT_PATH_FAMILIES
        )
    if lane_id == "async_long_task_ack":
        return bool(row.get("async_continuation") or row.get("async_initial_response_returned") or row.get("first_feedback_ms") is not None)
    if lane_id == "ui_render_visible":
        return row.get("ui_render_visible_ms") is not None or bool(row.get("ui_render_visible_status"))
    if lane_id == "ui_bridge_event_apply":
        return row.get("ui_bridge_apply_ms") is not None or row.get("event_stream_delay_ms") is not None
    if lane_id in {"voice_mock_first_audio", "voice_realtime_bounded"}:
        return row.get("voice_first_audio_ms") is not None or route == "voice_control"
    if lane.included_route_families and route not in set(lane.included_route_families):
        return False
    if lane.excluded_route_families and route in set(lane.excluded_route_families):
        return False
    if not lane.includes_provider_calls and _provider_called(row):
        return False
    return True


def _latency_value_for_lane(row: dict[str, Any], lane_id: str) -> float | None:
    if lane_id == "async_long_task_ack":
        return _numeric(row.get("first_feedback_ms"))
    if lane_id == "provider_fallback":
        return _numeric(row.get("provider_total_ms")) or _numeric(row.get("total_latency_ms"))
    if lane_id == "voice_mock_first_audio":
        return _numeric(row.get("voice_first_audio_ms"))
    if lane_id == "ui_bridge_event_apply":
        return _numeric(row.get("ui_bridge_apply_ms"))
    if lane_id == "ui_render_visible":
        return _numeric(row.get("ui_render_visible_ms"))
    return _numeric(row.get("total_latency_ms") or row.get("latency_ms"))


def _metric_value(row: dict[str, Any], metric_name: str, *, lane_id: str) -> float | None:
    if metric_name == "total_latency_ms":
        return _latency_value_for_lane(row, lane_id)
    return _numeric(row.get(metric_name))


def _provider_fallback_metrics(rows: list[dict[str, Any]], *, live_provider_run: bool) -> dict[str, Any]:
    provider_rows = [row for row in rows if _provider_called(row) or _route_family(row) == "generic_provider" or row.get("provider_first_output_ms") is not None]
    unexpected = [
        row for row in rows
        if _provider_called(row) and _route_family(row) in PROTECTED_NATIVE_PROVIDER_FAMILIES
    ]
    timing_modes = {str(row.get("provider_timing_mode") or "").strip() for row in provider_rows if str(row.get("provider_timing_mode") or "").strip()}
    return {
        "provider_calls_total": sum(_provider_call_count(row) for row in provider_rows),
        "provider_calls_by_route_family": _count_by(provider_rows, _route_family),
        "provider_fallback_allowed_count": sum(1 for row in provider_rows if row.get("provider_fallback_allowed")),
        "provider_fallback_denied_count": sum(1 for row in provider_rows if row.get("provider_fallback_blocked_reason")),
        "provider_blocked_by_native_route_count": sum(1 for row in provider_rows if row.get("provider_fallback_blocked_reason") == "provider_blocked_by_native_route"),
        "unexpected_provider_native_call_count": len(unexpected),
        "unexpected_provider_calls_on_native_routes": [_row_id(row) for row in unexpected],
        "provider_first_output_ms": _value_summary([_numeric(row.get("provider_first_output_ms")) for row in provider_rows]),
        "provider_total_ms": _value_summary([_numeric(row.get("provider_total_ms")) for row in provider_rows]),
        "provider_timeout_count": sum(1 for row in provider_rows if row.get("provider_timeout_hit") or str(row.get("provider_failure_code") or "").startswith("provider_timeout")),
        "provider_cancelled_count": sum(1 for row in provider_rows if row.get("provider_cancelled") or row.get("provider_failure_code") == "provider_cancelled"),
        "provider_failed_count": sum(1 for row in provider_rows if row.get("provider_failure_code") and not str(row.get("provider_failure_code")).startswith("provider_timeout")),
        "provider_streaming_used_count": sum(1 for row in provider_rows if row.get("provider_streaming_used")),
        "provider_partial_result_count": sum(int(row.get("provider_partial_result_count") or 0) for row in provider_rows),
        "provider_timing_mode": "live" if live_provider_run else "mock" if timing_modes == {"mock"} else "mixed" if len(timing_modes) > 1 else next(iter(timing_modes), "not_run"),
        "live_provider_timing_status": "run" if live_provider_run else "not_run",
    }


def _ui_perceived_latency_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fake_confirmed = [
        row for row in rows
        if str(row.get("ui_render_visible_status") or "").lower() == "confirmed"
        and not str(row.get("render_confirmation_source") or row.get("ui_render_confirmation_source") or "").strip()
    ]
    statuses = {str(row.get("ui_render_visible_status") or "").strip().lower() for row in rows if str(row.get("ui_render_visible_status") or "").strip()}
    return {
        "event_stream_delay_ms": _value_summary([_numeric(row.get("event_stream_delay_ms")) for row in rows]),
        "ui_bridge_apply_ms": _value_summary([_numeric(row.get("ui_bridge_apply_ms")) for row in rows]),
        "ui_model_notify_ms": _value_summary([_numeric(row.get("ui_model_notify_ms") or row.get("bridge_update_to_model_notify_ms")) for row in rows]),
        "ui_render_visible_ms": _value_summary([_numeric(row.get("ui_render_visible_ms")) for row in rows]),
        "ui_render_visible_status": "unknown" if "unknown" in statuses or not statuses else ",".join(sorted(statuses)),
        "unknown_or_not_measured_count": sum(1 for row in rows if str(row.get("ui_render_visible_status") or "").lower() in {"unknown", "not_measured", "not_visible", "hidden"}),
        "fake_render_confirmed_count": len(fake_confirmed),
    }


def _voice_first_audio_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    voice_rows = [row for row in rows if row.get("voice_first_audio_ms") is not None or _route_family(row) == "voice_control"]
    return {
        "voice_first_audio_ms": _value_summary([_numeric(row.get("voice_first_audio_ms")) for row in voice_rows]),
        "core_result_to_first_audio_ms": _value_summary([_numeric(row.get("voice_core_to_first_audio_ms") or row.get("core_result_to_first_audio_ms")) for row in voice_rows]),
        "tts_first_chunk_ms": _value_summary([_numeric(row.get("voice_tts_first_chunk_ms") or row.get("tts_start_to_first_chunk_ms")) for row in voice_rows]),
        "playback_start_ms": _value_summary([_numeric(row.get("voice_playback_start_ms") or row.get("first_chunk_to_playback_start_ms")) for row in voice_rows]),
        "voice_user_heard_claimed_count": sum(1 for row in voice_rows if row.get("voice_user_heard_claimed")),
        "tts_started_as_playback_started_count": sum(
            1 for row in voice_rows
            if row.get("voice_tts_first_chunk_ms") is not None
            and row.get("voice_playback_start_ms") is not None
            and _numeric(row.get("voice_tts_first_chunk_ms")) == _numeric(row.get("voice_playback_start_ms"))
        ),
    }


def _classify_outlier(row: dict[str, Any], *, lane_id: str) -> str:
    if _is_hard_timeout(row):
        return "hard_timeout"
    if _is_correctness_failure(row):
        return "correctness_failure"
    if _provider_called(row) or lane_id == "provider_fallback":
        return "provider_latency"
    if lane_id == "async_long_task_ack" or row.get("async_initial_response_returned"):
        return "async_ack_latency"
    longest = str(row.get("longest_stage") or "").lower()
    if "planner" in longest:
        return "planner_slow"
    if "context" in longest:
        return "context_assembly_slow"
    if "db_write" in longest:
        return "db_write_slow"
    if "serialization" in longest:
        return "serialization_slow"
    if "route_handler" in longest:
        return "route_handler_slow"
    if row.get("ui_bridge_apply_ms") is not None:
        return "ui_bridge_delay"
    if row.get("voice_first_audio_ms") is not None:
        return "voice_first_audio_slow"
    return "unclassified"


def _recommended_action_for_classification(classification: str) -> str:
    return {
        "provider_latency": "Inspect provider fallback budget, streaming, timeout, and availability metadata.",
        "hard_timeout": "Treat as release-blocking timeout and inspect child-process checkpoint.",
        "correctness_failure": "Fix route/result correctness separately from latency gates.",
        "route_handler_slow": "Inspect route handler subspans and hot-path cache/defer behavior.",
        "planner_slow": "Inspect planner route timing and route-triage pruning.",
        "known_slow_lane_active": "Confirm mitigation remains active before renewal.",
        "known_slow_lane_expired": "Renew or remove the slow-lane allowance before release.",
        "ui_bridge_delay": "Inspect L7 event-to-bridge/model timing.",
        "voice_first_audio_slow": "Inspect STT/Core/TTS/playback stage timing without user-heard claims.",
        "unclassified": "Investigate and classify before release.",
    }.get(classification, "Inspect the classified latency lane.")


def _recommended_next_actions(release_posture: dict[str, Any], outliers: list[dict[str, Any]]) -> list[str]:
    posture = str(release_posture.get("posture") or "")
    if posture == LatencyReleasePosture.PASS.value:
        return ["No release-blocking latency gate failures were found."]
    actions = []
    for reason in release_posture.get("blocking_reasons") or []:
        actions.append(str(reason))
    for outlier in outliers[:5]:
        actions.append(f"{outlier.get('row_id')}: {outlier.get('recommended_action')}")
    return actions or ["Review warnings before release."]


def _profile_summary(profile: str) -> dict[str, Any]:
    return {
        "selected_profile": profile,
        "available_profiles": [
            "focused_hot_path_profile",
            "full_kraken_profile",
            "native_only_profile",
            "provider_profile",
            "provider_mock",
            "voice_profile",
            "voice_mock",
            "ui_profile",
            "async_long_task_profile",
            "command_eval_profile",
        ],
    }


def _gate_summary(results: list[LatencyGateResult]) -> dict[str, Any]:
    return {
        "passed": sum(1 for result in results if result.passed),
        "failed": sum(1 for result in results if not result.passed and result.severity in {LatencyGateSeverity.FAIL.value, LatencyGateSeverity.RELEASE_BLOCKING.value}),
        "warned": sum(1 for result in results if not result.passed and result.severity == LatencyGateSeverity.WARNING.value),
        "release_blocking": sum(1 for result in results if result.blocking_release),
    }


def _histogram_key(row: dict[str, Any], group_by: tuple[str, ...]) -> str:
    parts = []
    for field in group_by:
        if field == "route_family":
            value = _route_family(row)
        else:
            value = str(row.get(field) or "")
        parts.append(f"{field}={value or 'unknown'}")
    return "|".join(parts)


def _provider_timing_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "first_output_ms": row.get("provider_first_output_ms"),
        "total_provider_ms": row.get("provider_total_ms"),
        "failure_code": row.get("provider_failure_code"),
    }


def _sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in row.items():
        lowered = str(key or "").lower()
        if _is_private_report_key(lowered):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, dict):
            safe[key] = {
                str(child_key): child_value
                for child_key, child_value in value.items()
                if not _is_private_report_key(str(child_key).lower())
                and isinstance(child_value, (str, int, float, bool, type(None)))
            }
        elif isinstance(value, list):
            safe[key] = [item for item in value if isinstance(item, (str, int, float, bool))]
    return safe


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("test_id") or row.get("case_id") or row.get("request_id") or row.get("row_id") or "unknown")


def _route_family(row: dict[str, Any]) -> str:
    return str(row.get("actual_route_family") or row.get("route_family") or row.get("expected_route_family") or "").strip()


def _provider_called(row: dict[str, Any]) -> bool:
    return bool(row.get("provider_called") or _provider_call_count(row) > 0 or row.get("provider_fallback_used"))


def _provider_call_count(row: dict[str, Any]) -> int:
    try:
        explicit = int(row.get("provider_call_count") or 0)
    except (TypeError, ValueError):
        explicit = 0
    return explicit or (1 if row.get("provider_called") else 0)


def _is_hard_timeout(row: dict[str, Any]) -> bool:
    return bool(row.get("hard_timeout") or row.get("process_killed") or str(row.get("status") or "").lower() == "hard_timeout" or str(row.get("result_state") or "").lower() == "hard_timeout")


def _is_correctness_failure(row: dict[str, Any]) -> bool:
    failure = str(row.get("failure_category") or "").lower()
    if failure and "latency" not in failure and "timeout" not in failure:
        return True
    return str(row.get("status") or "").lower() in {"failed", "fail"} and not _is_hard_timeout(row)


def _numeric(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_private_report_key(lowered_key: str) -> bool:
    key = str(lowered_key or "").strip().lower()
    if key in PRIVATE_REPORT_KEYS:
        return True
    return key.startswith(("raw_", "private_", "secret_", "token_", "password_")) or key.endswith(("_api_key", "_token", "_secret"))


def _observed_stat(values: list[float], statistic: str) -> float:
    if statistic == LatencyGateStatistic.P50.value:
        return _percentile(values, 0.5) or 0.0
    if statistic == LatencyGateStatistic.P90.value:
        return _percentile(values, 0.9) or 0.0
    if statistic == LatencyGateStatistic.P95.value:
        return _percentile(values, 0.95) or 0.0
    if statistic == LatencyGateStatistic.P99.value:
        return _percentile(values, 0.99) or 0.0
    if statistic == LatencyGateStatistic.MAX.value:
        return max(values) if values else 0.0
    if statistic == LatencyGateStatistic.RATIO.value:
        return values[0] if values else 0.0
    return float(len(values))


def _value_summary(values: list[float | None]) -> dict[str, Any]:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return {"count": 0, "min": None, "p50": None, "median": None, "p90": None, "p95": None, "p99": None, "max": None}
    return {
        "count": len(clean),
        "min": _percentile(clean, 0.0),
        "p50": _percentile(clean, 0.5),
        "median": _percentile(clean, 0.5),
        "p90": _percentile(clean, 0.9),
        "p95": _percentile(clean, 0.95),
        "p99": _percentile(clean, 0.99),
        "max": _percentile(clean, 1.0),
        "mean": round(mean(clean), 3),
    }


def _percentile(values: list[float], p: float) -> float | None:
    clean = sorted(values)
    if not clean:
        return None
    if len(clean) == 1:
        return round(clean[0], 3)
    index = (len(clean) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(clean) - 1)
    fraction = index - lower
    return round(clean[lower] * (1 - fraction) + clean[upper] * fraction, 3)


def _count_by(rows: list[dict[str, Any]], key_fn: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(key_fn(row) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _enum_value(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def _format_time(value: str | datetime) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
