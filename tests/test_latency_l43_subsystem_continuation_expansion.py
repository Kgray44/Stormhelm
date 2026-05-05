from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from stormhelm.core.events import EventBuffer
from stormhelm.core.latency import attach_latency_metadata
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.subsystem_continuations import SubsystemContinuationRequest
from stormhelm.core.subsystem_continuations import SubsystemContinuationRunner
from stormhelm.core.subsystem_continuations import classify_subsystem_continuation
from stormhelm.core.subsystem_continuations import default_subsystem_continuation_registry
from stormhelm.core.tools.base import ToolContext


@dataclass(slots=True)
class _FakeSoftwareVerificationResponse:
    verified: bool
    evidence: list[str]
    detail: str = "Software verification completed."

    def to_dict(self) -> dict[str, Any]:
        status = "verified" if self.verified else "uncertain"
        return {
            "assistant_response": self.detail,
            "result": {
                "status": status,
                "operation_type": "verify",
                "target_name": "git",
                "verification_status": status,
                "evidence": list(self.evidence),
                "detail": self.detail,
            },
            "verification": {
                "status": status,
                "install_state": "installed" if self.verified else "unknown",
                "detail": self.detail,
                "evidence": list(self.evidence),
            },
            "debug": {"verification": {"evidence": list(self.evidence)}},
        }


class _FakeSoftwareControl:
    def __init__(self, response: _FakeSoftwareVerificationResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def execute_software_operation(self, **kwargs: Any) -> _FakeSoftwareVerificationResponse:
        self.calls.append(dict(kwargs))
        return self.response


class _FakeRecovery:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_recovery_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("run_recovery_plan")
        return {
            "status": "completed",
            "summary": "Recovery attempted a bounded route switch.",
            "retry_performed": False,
            "route_switched_to": "vendor_installer",
            "verification_status": "unverified",
            "evidence": ["local_recovery_plan"],
        }


class _FakeDiscordRelay:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def handle_request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        return {
            "assistant_response": "I attempted to send it through Discord, but I could not verify that it appeared.",
            "state": "sent_unverified",
            "attempt": {
                "state": "sent_unverified",
                "verification_strength": "weak",
                "verification_evidence": ["local_client_focus"],
                "send_summary": "Send attempt completed without verification.",
            },
            "debug": {"delivery_claimed": False},
        }


class _FakeSystemProbe:
    def network_diagnosis(self, *, focus: str = "overview", diagnostic_burst: bool = False) -> dict[str, Any]:
        return {
            "status": "completed",
            "focus": focus,
            "diagnostic_burst": diagnostic_burst,
            "evidence": ["adapter_status_checked", "dns_probe_completed"],
            "limitations": ["remote throughput not measured"],
        }


def _context(temp_config, **overrides: Any) -> ToolContext:
    return ToolContext(
        job_id="job-l43",
        config=temp_config,
        events=overrides.pop("events", EventBuffer(capacity=64)),
        notes=None,  # type: ignore[arg-type]
        preferences=None,  # type: ignore[arg-type]
        safety_policy=None,  # type: ignore[arg-type]
        **overrides,
    )


def test_l43_registry_reports_implemented_high_value_handlers() -> None:
    registry = default_subsystem_continuation_registry()

    descriptions = {item["operation_kind"]: item for item in registry.describe_all()}

    for operation_kind in {
        "software_control.verify_operation",
        "software_recovery.run_recovery_plan",
        "discord_relay.dispatch_approved_preview",
        "network.run_live_diagnosis",
        "workspace.restore_deep",
    }:
        assert registry.has_handler(operation_kind), operation_kind
        assert descriptions[operation_kind]["implemented"] is True
        assert descriptions[operation_kind]["supports_progress"] is True
        assert descriptions[operation_kind]["worker_lane"] in {"normal", "background"}
        assert "priority_level" in descriptions[operation_kind]


def test_l43_policy_preserves_inline_fast_paths_and_worker_back_halves() -> None:
    inline_cases = {
        ("calculations", "calculations.evaluate"),
        ("trust_approvals", "trust_approval.bind"),
        ("voice_control", "voice.stop_speaking"),
        ("browser_destination", "browser.open_url"),
        ("software_control", "software_control.plan_operation"),
        ("discord_relay", "discord_relay.preview"),
    }
    worker_cases = {
        ("software_control", "software_control.verify_operation"),
        ("software_recovery", "software_recovery.run_recovery_plan"),
        ("discord_relay", "discord_relay.dispatch_approved_preview"),
        ("network", "network.run_live_diagnosis"),
    }

    for route_family, operation_kind in inline_cases:
        policy = classify_subsystem_continuation(
            route_family=route_family,
            subsystem=route_family,
            operation_kind=operation_kind,
            approved=True,
        )
        assert policy.worker_continuation_expected is False
        assert policy.inline_required is True

    for route_family, operation_kind in worker_cases:
        policy = classify_subsystem_continuation(
            route_family=route_family,
            subsystem=route_family,
            operation_kind=operation_kind,
            approved=True,
        )
        assert policy.worker_continuation_expected is True
        assert policy.inline_required is False


def test_software_verification_handler_claims_verified_only_with_fresh_evidence(temp_config) -> None:
    runner = SubsystemContinuationRunner(events=EventBuffer(capacity=64))
    request = SubsystemContinuationRequest.create(
        route_family="software_control",
        subsystem="software_control",
        operation_kind="software_control.verify_operation",
        request_id="verify-git",
        payload_summary={"target_name": "git", "raw_input": "verify git"},
        verification_required=True,
    )
    context = _context(
        temp_config,
        software_control=_FakeSoftwareControl(
            _FakeSoftwareVerificationResponse(
                verified=True,
                evidence=["executable:git", "path:C:/Program Files/Git/bin/git.exe"],
            )
        ),
    )

    result = asyncio.run(runner.run(request, context)).to_dict()

    assert result["result_state"] == "verified"
    assert result["verification_state"] == "verified"
    assert result["verification_claimed"] is True
    assert result["debug"]["continuation_truth_clamps_applied"] == []
    assert result["debug"]["continuation_verification_evidence_count"] == 2


def test_stale_software_verification_cache_does_not_claim_verified(temp_config) -> None:
    runner = SubsystemContinuationRunner(events=EventBuffer(capacity=64))
    request = SubsystemContinuationRequest.create(
        route_family="software_control",
        subsystem="software_control",
        operation_kind="software_control.verify_operation",
        request_id="verify-git-cache",
        payload_summary={"target_name": "git", "raw_input": "verify git", "cache_only": True},
        freshness_warnings=["software_verification_cache_expired"],
        verification_required=True,
    )
    context = _context(
        temp_config,
        software_control=_FakeSoftwareControl(
            _FakeSoftwareVerificationResponse(verified=True, evidence=["cached_catalog_match"])
        ),
    )

    result = asyncio.run(runner.run(request, context)).to_dict()

    assert result["result_state"] == "completed_unverified"
    assert result["verification_state"] == "not_verified"
    assert result["verification_claimed"] is False
    assert "stale_or_cache_only_evidence" in result["debug"]["continuation_truth_clamps_applied"]


def test_software_recovery_handler_reports_attempted_not_fixed(temp_config) -> None:
    runner = SubsystemContinuationRunner(events=EventBuffer(capacity=64))
    request = SubsystemContinuationRequest.create(
        route_family="software_recovery",
        subsystem="software_recovery",
        operation_kind="software_recovery.run_recovery_plan",
        request_id="recover-git",
        payload_summary={
            "failure_event": {
                "failure_id": "failure-1",
                "operation_type": "install",
                "target_name": "git",
                "stage": "execution",
                "category": "adapter_mismatch",
                "message": "Package-manager executor unavailable.",
            }
        },
        verification_required=True,
    )
    context = _context(temp_config, software_recovery=_FakeRecovery())

    result = asyncio.run(runner.run(request, context)).to_dict()

    assert result["result_state"] == "completed_unverified"
    assert result["completion_claimed"] is True
    assert result["verification_claimed"] is False
    assert result["debug"]["continuation_progress_stages"] == [
        "classifying_failure",
        "running_recovery_step",
        "checking_recovery_result",
    ]
    assert result["debug"]["continuation_truth_clamps_applied"] == ["recovery_attempted_not_fixed"]


def test_discord_dispatch_handler_requires_approval_and_does_not_claim_delivery(temp_config) -> None:
    runner = SubsystemContinuationRunner(events=EventBuffer(capacity=64))
    pending_preview = {
        "destination": {"alias": "Baby", "label": "Baby"},
        "payload": {"kind": "selected_text", "summary": "message", "text": "hello"},
        "fingerprint": {"fingerprint_id": "fp-1"},
    }
    unapproved = SubsystemContinuationRequest.create(
        route_family="discord_relay",
        subsystem="discord_relay",
        operation_kind="discord_relay.dispatch_approved_preview",
        approval_state="not_approved",
        preview_fingerprint="fp-1",
        payload_summary={"pending_preview": pending_preview},
    )
    approved = SubsystemContinuationRequest.create(
        route_family="discord_relay",
        subsystem="discord_relay",
        operation_kind="discord_relay.dispatch_approved_preview",
        approval_state="approved",
        preview_fingerprint="fp-1",
        payload_summary={"pending_preview": pending_preview},
    )
    context = _context(temp_config, discord_relay=_FakeDiscordRelay())

    blocked = asyncio.run(runner.run(unapproved, context)).to_dict()
    result = asyncio.run(runner.run(approved, context)).to_dict()

    assert blocked["result_state"] == "blocked"
    assert blocked["error_code"] == "approval_required_before_dispatch"
    assert result["result_state"] == "sent_unverified"
    assert result["verification_state"] == "not_verified"
    assert result["completion_claimed"] is True
    assert result["verification_claimed"] is False
    assert "delivery_not_verified" in result["debug"]["continuation_truth_clamps_applied"]


def test_network_live_diagnosis_handler_reports_evidence_and_limitations(temp_config) -> None:
    runner = SubsystemContinuationRunner(events=EventBuffer(capacity=64))
    request = SubsystemContinuationRequest.create(
        route_family="network",
        subsystem="network",
        operation_kind="network.run_live_diagnosis",
        payload_summary={"focus": "latency", "diagnostic_burst": True},
        verification_required=True,
    )
    context = _context(temp_config, system_probe=_FakeSystemProbe())

    result = asyncio.run(runner.run(request, context)).to_dict()

    assert result["result_state"] == "completed_unverified"
    assert result["verification_state"] == "not_verified"
    assert result["debug"]["continuation_verification_evidence_count"] == 2
    assert result["debug"]["continuation_result_limitations"] == ["remote throughput not measured"]


def test_l43_latency_trace_and_kraken_rows_include_handler_fields() -> None:
    metadata = {
        "route_family": "software_control",
        "subsystem": "software_control",
        "subsystem_continuation": {
            "subsystem_continuation_created": True,
            "subsystem_continuation_id": "subcont-verify",
            "subsystem_continuation_kind": "software_control.verify_operation",
            "subsystem_continuation_stage": "verified",
            "subsystem_continuation_status": "completed",
            "subsystem_continuation_worker_lane": "normal",
            "subsystem_continuation_run_ms": 42.0,
            "subsystem_continuation_total_ms": 45.0,
            "subsystem_continuation_progress_event_count": 3,
            "subsystem_continuation_final_result_state": "verified",
            "subsystem_continuation_verification_state": "verified",
            "subsystem_continuation_handler": "software_control.verify_operation",
            "subsystem_continuation_handler_implemented": True,
            "continuation_progress_stages": ["resolving_target", "checking_install_state", "verification_complete"],
            "continuation_verification_required": True,
            "continuation_verification_attempted": True,
            "continuation_verification_evidence_count": 2,
            "continuation_truth_clamps_applied": [],
            "direct_subsystem_async_converted": True,
            "inline_front_half_ms": 9.0,
            "worker_back_half_ms": 42.0,
            "returned_before_subsystem_completion": True,
            "async_conversion_expected": True,
        },
    }
    attach_latency_metadata(
        metadata,
        stage_timings_ms={"total_latency_ms": 9.0, "inline_front_half_ms": 9.0},
        request_id="chat-test",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
    )
    case = CommandEvalCase(
        case_id="l43-row-1",
        message="verify Git",
        expected=ExpectedBehavior(route_family="software_control", subsystem="software_control"),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=9.0,
        ui_response="Verification queued.",
        actual_route_family="software_control",
        actual_subsystem="software_control",
        result_state="verification_pending",
        stage_timings_ms={"total_latency_ms": 9.0, "inline_front_half_ms": 9.0},
        latency_summary=dict(metadata["latency_summary"]),
        budget_result=dict(metadata["budget_result"]),
    )
    result = CommandEvalResult(case=case, observation=observation, assertions={})
    row = result.to_dict()
    aggregate = build_checkpoint_summary([result])["kraken_latency_report"]

    assert metadata["latency_summary"]["subsystem_continuation_handler"] == "software_control.verify_operation"
    assert row["subsystem_continuation_handler_implemented"] is True
    assert row["continuation_verification_evidence_count"] == 2
    assert aggregate["implemented_handler_count"] == 1
    assert aggregate["handler_count_by_route_family"] == {"software_control": 1}
    assert aggregate["p95_continuation_runtime_by_handler"]["software_control.verify_operation"] == 45.0
