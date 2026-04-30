from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from time import monotonic
from typing import Any
from uuid import uuid4

from stormhelm.shared.time import utc_now_iso


PROTECTED_NATIVE_ROUTE_FAMILIES = {
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

NATIVE_TRUTH_STATES = {
    "answer",
    "answered",
    "clarify",
    "clarification",
    "needs_clarification",
    "refuse",
    "refused",
    "plan",
    "planned",
    "planning",
    "preview",
    "preview_ready",
    "queued",
    "ready_after_approval",
    "route_selected",
    "routed",
    "running",
    "unsupported_native",
}

SENSITIVE_PROVIDER_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "discord_payload",
    "message",
    "password",
    "payload",
    "private",
    "prompt",
    "raw_audio",
    "raw_image",
    "raw_prompt",
    "raw_screenshot",
    "secret",
    "token",
)


class ProviderFallbackState(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    DISABLED = "disabled"
    NOT_ALLOWED = "not_allowed"
    ELIGIBLE = "eligible"
    SELECTED = "selected"
    PREPARING = "preparing"
    RUNNING = "running"
    STREAMING = "streaming"
    PARTIAL_RESULT = "partial_result"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class ProviderFailureCode(str, Enum):
    TIMEOUT_FIRST_OUTPUT = "provider_timeout_first_output"
    TIMEOUT_TOTAL = "provider_timeout_total"
    UNAVAILABLE = "provider_unavailable"
    DISABLED = "provider_disabled"
    NOT_ALLOWED = "provider_not_allowed"
    PAYLOAD_NOT_SAFE = "provider_payload_not_safe"
    RATE_LIMITED = "provider_rate_limited"
    AUTH_MISSING = "provider_auth_missing"
    AUTH_FAILED = "provider_auth_failed"
    NETWORK_ERROR = "provider_network_error"
    STREAM_FAILED = "provider_stream_failed"
    CANCELLED = "provider_cancelled"
    BLOCKED_BY_NATIVE_ROUTE = "provider_blocked_by_native_route"
    REFUSED = "provider_refused"
    RESULT_INVALID = "provider_result_invalid"
    UNKNOWN_FAILURE = "provider_unknown_failure"


@dataclass(frozen=True, slots=True)
class ProviderFallbackEligibility:
    request_id: str
    route_family: str
    native_route_candidates: tuple[str, ...] = ()
    native_route_winner: str = ""
    native_route_state: str = ""
    native_can_answer: bool = False
    native_can_clarify: bool = False
    native_can_refuse: bool = False
    provider_fallback_enabled: bool = False
    provider_fallback_allowed: bool = False
    provider_fallback_reason: str = ""
    provider_fallback_blocked_reason: str = ""
    user_requested_open_ended_reasoning: bool = False
    native_decline_code: str = ""
    config_allows_provider: bool = False
    trust_allows_provider: bool = True
    privacy_allows_provider: bool = True
    payload_safe_for_provider: bool = True
    provider_available: bool | None = None
    provider_unavailable_reason: str = ""
    expected_provider_budget_class: str = "provider_fallback"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class ProviderLatencyBudget:
    budget_id: str = "provider_fallback.default"
    label: str = "provider_fallback"
    target_first_output_ms: float = 1500.0
    soft_first_output_ms: float = 3000.0
    hard_first_output_ms: float = 6000.0
    target_total_ms: float = 4000.0
    soft_total_ms: float = 8000.0
    hard_total_ms: float = 12000.0
    stream_required_when_available: bool = True
    partial_progress_required: bool = True
    cancellation_supported: bool = True
    timeout_state: str = ProviderFallbackState.TIMED_OUT.value
    fallback_state: str = ProviderFallbackState.FAILED.value
    surface_mode: str = "ghost"
    route_family: str = "generic_provider"
    provider_name: str = ""
    model_name: str = ""
    enabled_by_config: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class ProviderLatencySummary:
    request_id: str
    provider_call_id: str
    provider_name: str
    route_family: str
    model_name: str = ""
    fallback_allowed: bool = False
    fallback_reason: str = ""
    provider_enabled: bool = False
    streaming_enabled: bool = False
    streaming_used: bool = False
    cancellation_supported: bool = False
    first_byte_ms: float | None = None
    first_token_ms: float | None = None
    first_output_ms: float | None = None
    total_provider_ms: float | None = None
    total_user_visible_ms: float | None = None
    timeout_ms: float | None = None
    timeout_hit: bool = False
    cancelled: bool = False
    failure_code: str = ""
    provider_budget_label: str = "provider_fallback"
    provider_budget_exceeded: bool = False
    native_route_blocked_by_provider: bool = False
    payload_redacted: bool = True
    secrets_logged: bool = False
    fallback_state: str = ProviderFallbackState.NOT_APPLICABLE.value
    partial_result_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class ProviderAuditTiming:
    provider_call_id: str
    request_id: str
    provider_name: str
    model_name: str = ""
    allowed: bool = False
    denied: bool = False
    denial_reason: str = ""
    started_at: str = field(default_factory=utc_now_iso)
    first_output_at: str | None = None
    completed_at: str | None = None
    cancelled_at: str | None = None
    failed_at: str | None = None
    timeout_at: str | None = None
    total_ms: float | None = None
    budget_label: str = "provider_fallback"
    budget_exceeded: bool = False
    streaming_used: bool = False
    fallback_reason: str = ""
    payload_classification: str = "unknown"
    payload_redacted: bool = True
    secrets_logged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class ProviderCancellationResult:
    provider_call_id: str
    request_id: str
    cancel_requested_at: str
    cancel_completed_at: str | None = None
    cancellation_supported: bool = False
    cancellation_attempted: bool = False
    cancellation_succeeded: bool = False
    cancellation_reason: str = ""
    final_provider_state: str = ""
    partial_output_available: bool = False
    user_visible_message: str = ""
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class ProviderCallHandle:
    provider_call_id: str
    request_id: str
    cancellation_supported: bool
    state: str = ProviderFallbackState.RUNNING.value
    partial_output_available: bool = False
    trace_id: str = ""
    started_monotonic: float = field(default_factory=monotonic)


@dataclass(frozen=True, slots=True)
class MockProviderStreamResult:
    events: tuple[dict[str, Any], ...]
    summary: ProviderLatencySummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [dict(event) for event in self.events],
            "summary": self.summary.to_dict(),
        }


class ProviderCallRegistry:
    def __init__(self) -> None:
        self._calls: dict[str, ProviderCallHandle] = {}

    def start_call(
        self,
        *,
        request_id: str,
        provider_call_id: str = "",
        cancellation_supported: bool,
        trace_id: str = "",
    ) -> ProviderCallHandle:
        call_id = provider_call_id or f"provider-{uuid4().hex}"
        handle = ProviderCallHandle(
            provider_call_id=call_id,
            request_id=str(request_id or "").strip(),
            cancellation_supported=bool(cancellation_supported),
            trace_id=trace_id or f"provider-trace-{uuid4().hex}",
        )
        self._calls[call_id] = handle
        return handle

    def complete_call(self, provider_call_id: str) -> None:
        handle = self._calls.get(provider_call_id)
        if handle is None:
            return
        self._calls[provider_call_id] = ProviderCallHandle(
            provider_call_id=handle.provider_call_id,
            request_id=handle.request_id,
            cancellation_supported=handle.cancellation_supported,
            state=ProviderFallbackState.COMPLETED.value,
            partial_output_available=handle.partial_output_available,
            trace_id=handle.trace_id,
            started_monotonic=handle.started_monotonic,
        )

    def call_state(self, provider_call_id: str) -> str:
        handle = self._calls.get(provider_call_id)
        return handle.state if handle is not None else "unknown"

    def cancel_call(
        self,
        provider_call_id: str,
        *,
        reason: str,
    ) -> ProviderCancellationResult:
        requested_at = utc_now_iso()
        handle = self._calls.get(provider_call_id)
        if handle is None:
            return ProviderCancellationResult(
                provider_call_id=str(provider_call_id or "").strip(),
                request_id="",
                cancel_requested_at=requested_at,
                cancellation_reason=str(reason or "").strip(),
                final_provider_state="unknown_call",
                user_visible_message="No matching provider call was active.",
            )
        if handle.state == ProviderFallbackState.COMPLETED.value:
            return ProviderCancellationResult(
                provider_call_id=handle.provider_call_id,
                request_id=handle.request_id,
                cancel_requested_at=requested_at,
                cancellation_supported=handle.cancellation_supported,
                cancellation_attempted=False,
                cancellation_succeeded=False,
                cancellation_reason=str(reason or "").strip(),
                final_provider_state="completed_before_cancel",
                partial_output_available=handle.partial_output_available,
                user_visible_message="Provider call completed before cancellation.",
                trace_id=handle.trace_id,
            )
        if not handle.cancellation_supported:
            return ProviderCancellationResult(
                provider_call_id=handle.provider_call_id,
                request_id=handle.request_id,
                cancel_requested_at=requested_at,
                cancellation_supported=False,
                cancellation_attempted=False,
                cancellation_succeeded=False,
                cancellation_reason=str(reason or "").strip(),
                final_provider_state=handle.state,
                partial_output_available=handle.partial_output_available,
                user_visible_message="Provider cancellation is not supported.",
                trace_id=handle.trace_id,
            )
        completed_at = utc_now_iso()
        self._calls[provider_call_id] = ProviderCallHandle(
            provider_call_id=handle.provider_call_id,
            request_id=handle.request_id,
            cancellation_supported=handle.cancellation_supported,
            state=ProviderFallbackState.CANCELLED.value,
            partial_output_available=handle.partial_output_available,
            trace_id=handle.trace_id,
            started_monotonic=handle.started_monotonic,
        )
        return ProviderCancellationResult(
            provider_call_id=handle.provider_call_id,
            request_id=handle.request_id,
            cancel_requested_at=requested_at,
            cancel_completed_at=completed_at,
            cancellation_supported=True,
            cancellation_attempted=True,
            cancellation_succeeded=True,
            cancellation_reason=str(reason or "").strip(),
            final_provider_state=ProviderFallbackState.CANCELLED.value,
            partial_output_available=handle.partial_output_available,
            user_visible_message="Provider fallback cancelled.",
            trace_id=handle.trace_id,
        )


def evaluate_provider_fallback_eligibility(
    *,
    request_id: str,
    route_family: str,
    native_route_candidates: tuple[str, ...] | list[str] = (),
    native_route_winner: str = "",
    native_route_state: str = "",
    native_can_answer: bool = False,
    native_can_clarify: bool = False,
    native_can_refuse: bool = False,
    provider_fallback_enabled: bool = False,
    config_allows_provider: bool = False,
    trust_allows_provider: bool = True,
    privacy_allows_provider: bool = True,
    payload_safe_for_provider: bool = True,
    user_requested_open_ended_reasoning: bool = False,
    native_decline_code: str = "",
    provider_available: bool | None = None,
    provider_unavailable_reason: str = "",
    provider_availability_probe: Any | None = None,
) -> ProviderFallbackEligibility:
    family = _normalized(route_family)
    winner = _normalized(native_route_winner)
    state = _normalized(native_route_state)
    candidates = tuple(_normalized(item) for item in native_route_candidates if _normalized(item))

    base = {
        "request_id": str(request_id or "").strip(),
        "route_family": family,
        "native_route_candidates": candidates,
        "native_route_winner": winner,
        "native_route_state": state,
        "native_can_answer": bool(native_can_answer),
        "native_can_clarify": bool(native_can_clarify),
        "native_can_refuse": bool(native_can_refuse),
        "provider_fallback_enabled": bool(provider_fallback_enabled),
        "config_allows_provider": bool(config_allows_provider),
        "trust_allows_provider": bool(trust_allows_provider),
        "privacy_allows_provider": bool(privacy_allows_provider),
        "payload_safe_for_provider": bool(payload_safe_for_provider),
        "user_requested_open_ended_reasoning": bool(user_requested_open_ended_reasoning),
        "native_decline_code": _normalized(native_decline_code),
        "provider_available": provider_available,
        "provider_unavailable_reason": "",
    }

    def blocked(reason: str) -> ProviderFallbackEligibility:
        return ProviderFallbackEligibility(
            **base,
            provider_fallback_allowed=False,
            provider_fallback_blocked_reason=reason,
        )

    if not provider_fallback_enabled or not config_allows_provider:
        return blocked(ProviderFailureCode.DISABLED.value)
    if not trust_allows_provider:
        return blocked(ProviderFailureCode.NOT_ALLOWED.value)
    if not privacy_allows_provider:
        return blocked("provider_privacy_blocked")
    if not payload_safe_for_provider:
        return blocked(ProviderFailureCode.PAYLOAD_NOT_SAFE.value)
    if _native_route_blocks_provider(
        route_family=family,
        native_route_winner=winner,
        native_route_state=state,
        native_can_answer=native_can_answer,
        native_can_clarify=native_can_clarify,
        native_can_refuse=native_can_refuse,
        native_decline_code=_normalized(native_decline_code),
    ):
        return blocked(ProviderFailureCode.BLOCKED_BY_NATIVE_ROUTE.value)

    if provider_available is None and callable(provider_availability_probe):
        provider_available = bool(provider_availability_probe())
        base["provider_available"] = provider_available

    if provider_available is False:
        reason = _normalized(provider_unavailable_reason) or ProviderFailureCode.UNAVAILABLE.value
        return ProviderFallbackEligibility(
            **{**base, "provider_available": False, "provider_unavailable_reason": reason},
            provider_fallback_allowed=False,
            provider_fallback_blocked_reason=reason,
        )

    if user_requested_open_ended_reasoning:
        return ProviderFallbackEligibility(
            **base,
            provider_fallback_allowed=True,
            provider_fallback_reason="open_ended_reasoning_allowed",
        )
    if _normalized(native_decline_code) or state in {"declined", "unsupported"}:
        return ProviderFallbackEligibility(
            **base,
            provider_fallback_allowed=True,
            provider_fallback_reason="native_decline_allowed",
        )
    if family == "generic_provider" and not winner and not candidates:
        return ProviderFallbackEligibility(
            **base,
            provider_fallback_allowed=True,
            provider_fallback_reason="no_native_route_available",
        )
    return blocked(ProviderFailureCode.NOT_ALLOWED.value)


def default_provider_latency_budget(
    config: Any | None = None,
    *,
    route_family: str = "generic_provider",
    provider_name: str = "",
    model_name: str = "",
    surface_mode: str = "ghost",
) -> ProviderLatencyBudget:
    source = getattr(config, "provider_fallback", config) if config is not None else None

    def value(name: str, default: Any) -> Any:
        return getattr(source, name, default) if source is not None else default

    return ProviderLatencyBudget(
        target_first_output_ms=float(value("target_first_output_ms", 1500)),
        soft_first_output_ms=float(value("soft_first_output_ms", 3000)),
        hard_first_output_ms=float(value("hard_first_output_ms", 6000)),
        target_total_ms=float(value("target_total_ms", 4000)),
        soft_total_ms=float(value("soft_total_ms", 8000)),
        hard_total_ms=float(value("hard_total_ms", 12000)),
        stream_required_when_available=bool(value("allow_streaming", True)),
        partial_progress_required=bool(value("allow_partial_progress", True)),
        cancellation_supported=bool(value("allow_cancellation", True)),
        enabled_by_config=bool(value("enabled", False)),
        route_family=str(route_family or "generic_provider").strip(),
        provider_name=str(provider_name or "").strip(),
        model_name=str(model_name or "").strip(),
        surface_mode=str(surface_mode or "ghost").strip() or "ghost",
    )


def build_provider_latency_summary(
    *,
    request_id: str,
    provider_call_id: str,
    provider_name: str,
    route_family: str,
    fallback_allowed: bool,
    provider_enabled: bool,
    fallback_reason: str = "",
    model_name: str = "",
    streaming_enabled: bool = False,
    streaming_used: bool = False,
    cancellation_supported: bool = False,
    first_byte_ms: float | None = None,
    first_token_ms: float | None = None,
    first_output_ms: float | None = None,
    total_provider_ms: float | None = None,
    total_user_visible_ms: float | None = None,
    timeout_ms: float | None = None,
    cancelled: bool = False,
    failure_code: str = "",
    partial_result_count: int = 0,
    budget: ProviderLatencyBudget | None = None,
    native_route_blocked_by_provider: bool = False,
) -> ProviderLatencySummary:
    budget = budget or default_provider_latency_budget(
        route_family=route_family,
        provider_name=provider_name,
        model_name=model_name,
    )
    first_output = _float_or_none(first_output_ms)
    total = _float_or_none(total_provider_ms)
    failure = _normalized(failure_code)
    timeout_hit = False
    budget_exceeded = False
    state = ProviderFallbackState.NOT_APPLICABLE.value
    if not provider_enabled:
        state = ProviderFallbackState.DISABLED.value
        failure = failure or ProviderFailureCode.DISABLED.value
    elif not fallback_allowed:
        state = ProviderFallbackState.BLOCKED.value
        failure = failure or ProviderFailureCode.NOT_ALLOWED.value
    elif cancelled:
        state = ProviderFallbackState.CANCELLED.value
        failure = failure or ProviderFailureCode.CANCELLED.value
    elif failure in {
        ProviderFailureCode.TIMEOUT_FIRST_OUTPUT.value,
        ProviderFailureCode.TIMEOUT_TOTAL.value,
    }:
        state = ProviderFallbackState.TIMED_OUT.value
        timeout_hit = True
        budget_exceeded = True
        timeout_ms = timeout_ms or (
            budget.hard_first_output_ms
            if failure == ProviderFailureCode.TIMEOUT_FIRST_OUTPUT.value
            else budget.hard_total_ms
        )
    elif failure:
        state = ProviderFallbackState.FAILED.value
    elif first_output is not None and first_output > budget.hard_first_output_ms:
        state = ProviderFallbackState.TIMED_OUT.value
        failure = ProviderFailureCode.TIMEOUT_FIRST_OUTPUT.value
        timeout_hit = True
        budget_exceeded = True
        timeout_ms = budget.hard_first_output_ms
    elif total is not None and total > budget.hard_total_ms:
        state = ProviderFallbackState.TIMED_OUT.value
        failure = ProviderFailureCode.TIMEOUT_TOTAL.value
        timeout_hit = True
        budget_exceeded = True
        timeout_ms = budget.hard_total_ms
    elif first_output is not None or total is not None:
        if first_output is not None and first_output > budget.soft_first_output_ms:
            budget_exceeded = True
        if total is not None and total > budget.soft_total_ms:
            budget_exceeded = True
        if partial_result_count > 0 and (total is None or streaming_used):
            state = ProviderFallbackState.PARTIAL_RESULT.value
        else:
            state = ProviderFallbackState.COMPLETED.value
    elif fallback_allowed:
        state = ProviderFallbackState.RUNNING.value

    return ProviderLatencySummary(
        request_id=str(request_id or "").strip(),
        provider_call_id=str(provider_call_id or "").strip(),
        provider_name=str(provider_name or "").strip(),
        model_name=str(model_name or "").strip(),
        route_family=str(route_family or "").strip(),
        fallback_allowed=bool(fallback_allowed),
        fallback_reason=str(fallback_reason or "").strip(),
        provider_enabled=bool(provider_enabled),
        streaming_enabled=bool(streaming_enabled),
        streaming_used=bool(streaming_used),
        cancellation_supported=bool(cancellation_supported),
        first_byte_ms=_float_or_none(first_byte_ms),
        first_token_ms=_float_or_none(first_token_ms),
        first_output_ms=first_output,
        total_provider_ms=total,
        total_user_visible_ms=_float_or_none(total_user_visible_ms),
        timeout_ms=_float_or_none(timeout_ms),
        timeout_hit=bool(timeout_hit),
        cancelled=bool(cancelled),
        failure_code=failure,
        provider_budget_label=budget.label,
        provider_budget_exceeded=bool(budget_exceeded),
        native_route_blocked_by_provider=bool(native_route_blocked_by_provider),
        fallback_state=state,
        partial_result_count=max(0, int(partial_result_count or 0)),
    )


def run_mock_provider_stream(
    *,
    request_id: str,
    provider_call_id: str,
    chunks: tuple[str, ...] | list[str],
    provider_name: str = "mock",
    model_name: str = "mock-model",
    route_family: str = "generic_provider",
    complete: bool = True,
    fail_at_chunk: int | None = None,
) -> MockProviderStreamResult:
    call_id = str(provider_call_id or f"provider-{uuid4().hex}")
    request = str(request_id or "").strip()
    events: list[dict[str, Any]] = [
        _provider_event(
            "provider_request_started",
            request_id=request,
            provider_call_id=call_id,
            route_family=route_family,
            provider_name=provider_name,
            model_name=model_name,
            provider_fallback_state=ProviderFallbackState.RUNNING.value,
        )
    ]
    safe_chunks = [str(chunk or "").strip() for chunk in chunks if str(chunk or "").strip()]
    first_output_ms: float | None = None
    partial_count = 0
    failure = ""
    state = ProviderFallbackState.PARTIAL_RESULT.value
    for index, chunk in enumerate(safe_chunks, start=1):
        if fail_at_chunk is not None and index >= fail_at_chunk:
            failure = ProviderFailureCode.STREAM_FAILED.value
            events.append(
                _provider_event(
                    "provider_failed",
                    request_id=request,
                    provider_call_id=call_id,
                    route_family=route_family,
                    provider_name=provider_name,
                    model_name=model_name,
                    provider_fallback_state=ProviderFallbackState.FAILED.value,
                    failure_code=failure,
                )
            )
            state = ProviderFallbackState.FAILED.value
            break
        event_type = "provider_first_output" if index == 1 else "provider_partial_output"
        if first_output_ms is None:
            first_output_ms = float(index)
        partial_count += 1
        events.append(
            _provider_event(
                event_type,
                request_id=request,
                provider_call_id=call_id,
                route_family=route_family,
                provider_name=provider_name,
                model_name=model_name,
                provider_fallback_state=ProviderFallbackState.PARTIAL_RESULT.value,
                output_summary=sanitize_provider_output_summary(chunk),
                is_final=False,
                verification_claimed=False,
                tool_execution_allowed=False,
            )
        )
    if complete and not failure:
        state = ProviderFallbackState.COMPLETED.value
        events.append(
            _provider_event(
                "provider_stream_completed",
                request_id=request,
                provider_call_id=call_id,
                route_family=route_family,
                provider_name=provider_name,
                model_name=model_name,
                provider_fallback_state=ProviderFallbackState.COMPLETED.value,
                is_final=True,
                verification_claimed=False,
                tool_execution_allowed=False,
            )
        )
    summary = build_provider_latency_summary(
        request_id=request,
        provider_call_id=call_id,
        provider_name=provider_name,
        model_name=model_name,
        route_family=route_family,
        fallback_allowed=True,
        provider_enabled=True,
        streaming_enabled=True,
        streaming_used=True,
        cancellation_supported=True,
        first_output_ms=first_output_ms,
        total_provider_ms=float(max(1, len(events))),
        failure_code=failure,
        partial_result_count=partial_count,
    )
    if state in {
        ProviderFallbackState.PARTIAL_RESULT.value,
        ProviderFallbackState.COMPLETED.value,
    }:
        summary = ProviderLatencySummary(
            **{
                **summary.to_dict(),
                "fallback_state": state,
            }
        )
    return MockProviderStreamResult(events=tuple(events), summary=summary)


def sanitize_provider_output_summary(text: str, *, limit: int = 120) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if _looks_secret(cleaned):
        return "[redacted]"
    if len(cleaned) > limit:
        return f"{cleaned[:limit].rstrip()}..."
    return cleaned


def sanitize_provider_payload_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    payload_keys: list[str] = []
    redacted_fields: list[str] = []
    safe_fields: dict[str, Any] = {}
    for key, value in source.items():
        key_text = str(key or "").strip()
        if not key_text:
            continue
        lowered = key_text.lower()
        if _sensitive_provider_key(lowered):
            redacted_fields.append(key_text)
            continue
        payload_keys.append(key_text)
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value) if value is not None else ""
            safe_fields[key_text] = "[redacted]" if _looks_secret(text) else value
        elif isinstance(value, (list, tuple)):
            safe_fields[key_text] = f"{len(value)} item(s)"
        elif isinstance(value, dict):
            safe_fields[key_text] = f"{len(value)} field(s)"
        else:
            safe_fields[key_text] = type(value).__name__
    return {
        "payload_keys": sorted(payload_keys),
        "redacted_fields": sorted(redacted_fields),
        "safe_fields": safe_fields,
        "payload_redacted": bool(redacted_fields),
        "payload_classification": "redacted" if redacted_fields else "metadata_only",
    }


def _provider_event(event_type: str, **payload: Any) -> dict[str, Any]:
    return {
        "event_family": "provider",
        "event_type": event_type,
        "severity": "info" if not str(event_type).endswith("failed") else "error",
        "subsystem": "provider_fallback",
        "visibility_scope": "deck_context",
        "message": _provider_event_message(event_type),
        "payload": {key: _json_ready(value) for key, value in payload.items()},
    }


def _provider_event_message(event_type: str) -> str:
    return {
        "provider_request_started": "Provider fallback running.",
        "provider_first_output": "Provider fallback produced first output.",
        "provider_partial_output": "Provider fallback produced partial output.",
        "provider_stream_completed": "Provider fallback completed.",
        "provider_failed": "Provider fallback failed.",
    }.get(event_type, "Provider fallback updated.")


def _native_route_blocks_provider(
    *,
    route_family: str,
    native_route_winner: str,
    native_route_state: str,
    native_can_answer: bool,
    native_can_clarify: bool,
    native_can_refuse: bool,
    native_decline_code: str,
) -> bool:
    if native_decline_code:
        return False
    if native_can_answer or native_can_clarify or native_can_refuse:
        return True
    winner = native_route_winner or route_family
    if winner in PROTECTED_NATIVE_ROUTE_FAMILIES and winner not in {"unsupported", "generic_provider"}:
        return True
    if route_family in PROTECTED_NATIVE_ROUTE_FAMILIES and native_route_state in NATIVE_TRUTH_STATES:
        return True
    return False


def _sensitive_provider_key(key: str) -> bool:
    return any(part in key for part in SENSITIVE_PROVIDER_KEY_PARTS)


def _looks_secret(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return lowered.startswith(("sk-", "pk-")) or "bearer " in lowered or "api_key" in lowered


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return value
