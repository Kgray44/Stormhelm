from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from PySide6 import QtCore

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceConfirmationConfig
from stormhelm.core.api.app import create_app
from stormhelm.core.events import EventBuffer
from stormhelm.core.trust import ApprovalState
from stormhelm.core.trust import PermissionScope
from stormhelm.core.trust import TrustActionKind
from stormhelm.core.trust import TrustActionRequest
from stormhelm.core.tasks.models import TaskState
from stormhelm.core.voice import VoiceConfirmationStrength
from stormhelm.core.voice import VoiceSpokenConfirmationIntentKind
from stormhelm.core.voice import VoiceSpokenConfirmationRequest
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.shared.time import utc_now_iso
from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.controllers.main_controller import MainController
from stormhelm.ui.voice_surface import build_voice_ui_state
from tests.test_voice_manual_turn import RecordingCoreBridge
from tests.test_voice_manual_turn import _openai_config
from tests.test_trust_service import _save_task


class _VoiceConfirmationClient(QtCore.QObject):
    error_occurred = QtCore.Signal(str, str)
    snapshot_received = QtCore.Signal(dict)
    health_received = QtCore.Signal(dict)
    chat_received = QtCore.Signal(dict)
    note_saved = QtCore.Signal(dict)
    voice_action_received = QtCore.Signal(dict)
    stream_event_received = QtCore.Signal(dict)
    stream_state_received = QtCore.Signal(dict)
    stream_gap_received = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.confirmation_calls: list[dict[str, object]] = []
        self.snapshot_calls = 0

    def fetch_snapshot(self) -> None:
        self.snapshot_calls += 1

    def submit_spoken_confirmation(
        self, payload: dict[str, object] | None = None
    ) -> None:
        self.confirmation_calls.append(dict(payload or {}))


def _voice_config(**overrides: Any) -> VoiceConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "mode": "manual",
        "manual_input_enabled": True,
        "spoken_responses_enabled": True,
        "debug_mock_provider": True,
        "confirmation": VoiceConfirmationConfig(
            enabled=True,
            max_confirmation_age_ms=30_000,
            allow_soft_yes_for_low_risk=True,
            require_strong_phrase_for_destructive=True,
            consume_once=True,
        ),
    }
    values.update(overrides)
    return VoiceConfig(**values)


def _service(
    *,
    events: EventBuffer | None = None,
    voice_config: VoiceConfig | None = None,
    openai_config: OpenAIConfig | None = None,
):
    service = build_voice_subsystem(
        voice_config or _voice_config(),
        openai_config or _openai_config(),
        events=events,
    )
    service.attach_core_bridge(RecordingCoreBridge())
    return service


def _pending_request(
    *,
    request_id: str,
    task_id: str = "task-alpha",
    subject: str = "firefox",
    route_family: str = "software_control",
    subsystem: str = "software_control",
    payload_hash: str = "payload-alpha",
    risk_level: str = "medium",
    required_strength: str = "explicit_confirm",
    action_key: str = "software_control.install",
    suggested_scope: PermissionScope = PermissionScope.ONCE,
) -> TrustActionRequest:
    return TrustActionRequest(
        request_id=request_id,
        family=route_family,
        action_key=action_key,
        subject=subject,
        session_id="default",
        task_id=task_id,
        action_kind=TrustActionKind.SOFTWARE_CONTROL,
        approval_required=True,
        preview_allowed=True,
        suggested_scope=suggested_scope,
        available_scopes=[PermissionScope.ONCE, PermissionScope.TASK],
        operator_justification=f"{subject.title()} may change local state.",
        operator_message=(
            f"Approval is required before Stormhelm can install {subject.title()}."
        ),
        details={
            "route_family": route_family,
            "subsystem": subsystem,
            "payload_hash": payload_hash,
            "target_summary": f"Install {subject.title()}",
            "risk_level": risk_level,
            "required_confirmation_strength": required_strength,
        },
    )


def _create_pending(
    trust_harness,
    *,
    request_id: str = "voice-confirm-1",
    **kwargs: Any,
):
    task_id = str(kwargs.get("task_id", "task-alpha") or "").strip()
    if task_id:
        _save_task(trust_harness, task_id=task_id, state=TaskState.IN_PROGRESS)
    trust = trust_harness["trust_service"]
    decision = trust.evaluate_action(_pending_request(request_id=request_id, **kwargs))
    assert decision.approval_request is not None
    return decision.approval_request


def _expire_pending(trust_harness, approval_request_id: str) -> None:
    repository = trust_harness["trust_service"].repository
    pending = repository.get_approval_request(approval_request_id)
    assert pending is not None
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    pending.expires_at = past
    pending.updated_at = utc_now_iso()
    repository.save_approval_request(pending)


def test_spoken_confirmation_classifier_is_conservative() -> None:
    service = _service()

    assert (
        service.classify_spoken_confirmation("yeah").intent
        == VoiceSpokenConfirmationIntentKind.CONFIRM
    )
    assert (
        service.classify_spoken_confirmation("confirm").provided_strength
        == VoiceConfirmationStrength.EXPLICIT_CONFIRM
    )
    assert (
        service.classify_spoken_confirmation("no").intent
        == VoiceSpokenConfirmationIntentKind.REJECT
    )
    assert (
        service.classify_spoken_confirmation("show me the plan").intent
        == VoiceSpokenConfirmationIntentKind.SHOW_PLAN
    )
    ambiguous = service.classify_spoken_confirmation("sure maybe")
    assert ambiguous.intent == VoiceSpokenConfirmationIntentKind.AMBIGUOUS
    assert ambiguous.requires_pending_confirmation is True


def test_yes_without_pending_confirmation_does_not_execute_or_route(
    trust_harness,
) -> None:
    service = _service(events=trust_harness["events"])
    service.attach_trust_service(trust_harness["trust_service"])

    result = asyncio.run(
        service.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript="yes",
                session_id="default",
                task_id="task-alpha",
                source="manual_voice",
            )
        )
    )

    assert result.status == "no_pending_confirmation"
    assert result.consumed_confirmation is False
    assert result.action_executed is False
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False
    assert trust_harness["trust_service"].repository.list_grants(session_id="default") == []


def test_fresh_matching_spoken_confirm_consumes_pending_once(trust_harness) -> None:
    events = trust_harness["events"]
    service = _service(events=events)
    service.attach_trust_service(trust_harness["trust_service"])
    pending = _create_pending(
        trust_harness,
        task_id="task-alpha",
        payload_hash="payload-alpha",
        required_strength="explicit_confirm",
    )

    result = asyncio.run(
        service.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript="confirm",
                session_id="default",
                task_id="task-alpha",
                route_family="software_control",
                pending_confirmation_id=pending.approval_request_id,
                metadata={"payload_hash": "payload-alpha"},
            )
        )
    )

    stored = trust_harness["trust_service"].repository.get_approval_request(
        pending.approval_request_id
    )
    assert result.status == "confirmed"
    assert result.consumed_confirmation is True
    assert result.action_executed is False
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False
    assert stored is not None
    assert stored.state == ApprovalState.APPROVED_ONCE
    assert service.status_snapshot()["spoken_confirmation"]["last_result"][
        "status"
    ] == "confirmed"

    again = asyncio.run(
        service.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript="confirm",
                session_id="default",
                task_id="task-alpha",
                route_family="software_control",
                pending_confirmation_id=pending.approval_request_id,
                metadata={"payload_hash": "payload-alpha"},
            )
        )
    )
    assert again.status in {"stale", "no_pending_confirmation", "binding_failed"}
    assert again.consumed_confirmation is False

    voice_events = [event["event_type"] for event in events.recent(limit=64)]
    assert "voice.spoken_confirmation_received" in voice_events
    assert "voice.spoken_confirmation_accepted" in voice_events
    assert "voice.spoken_confirmation_consumed" in voice_events


def test_spoken_confirmation_rejects_stale_and_payload_mismatch(
    trust_harness,
) -> None:
    service = _service(events=trust_harness["events"])
    service.attach_trust_service(trust_harness["trust_service"])
    stale = _create_pending(
        trust_harness,
        request_id="voice-confirm-stale",
        task_id="task-alpha",
        payload_hash="payload-alpha",
    )
    _expire_pending(trust_harness, stale.approval_request_id)

    stale_result = asyncio.run(
        service.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript="confirm",
                session_id="default",
                task_id="task-alpha",
                pending_confirmation_id=stale.approval_request_id,
                metadata={"payload_hash": "payload-alpha"},
            )
        )
    )
    assert stale_result.status == "expired"
    assert stale_result.consumed_confirmation is False

    mismatch = _create_pending(
        trust_harness,
        request_id="voice-confirm-mismatch",
        task_id="task-alpha",
        payload_hash="payload-alpha",
    )
    mismatch_result = asyncio.run(
        service.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript="confirm",
                session_id="default",
                task_id="task-alpha",
                pending_confirmation_id=mismatch.approval_request_id,
                metadata={"payload_hash": "payload-beta"},
            )
        )
    )
    assert mismatch_result.status == "binding_failed"
    assert mismatch_result.binding is not None
    assert mismatch_result.binding.invalid_reason == "payload_mismatch"


def test_risk_strength_blocks_weak_confirmation_for_high_risk(
    trust_harness,
) -> None:
    service = _service(events=trust_harness["events"])
    service.attach_trust_service(trust_harness["trust_service"])
    high_risk = _create_pending(
        trust_harness,
        request_id="voice-confirm-high-risk",
        risk_level="high",
        required_strength="explicit_confirm",
    )

    weak = asyncio.run(
        service.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript="yeah",
                session_id="default",
                task_id="task-alpha",
                pending_confirmation_id=high_risk.approval_request_id,
                metadata={"payload_hash": "payload-alpha"},
            )
        )
    )
    assert weak.status == "binding_failed"
    assert weak.binding is not None
    assert weak.binding.invalid_reason == "confirmation_strength_insufficient"
    assert weak.consumed_confirmation is False

    explicit = asyncio.run(
        service.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript="confirm",
                session_id="default",
                task_id="task-alpha",
                pending_confirmation_id=high_risk.approval_request_id,
                metadata={"payload_hash": "payload-alpha"},
            )
        )
    )
    assert explicit.status == "confirmed"
    assert explicit.consumed_confirmation is True


def test_reject_and_show_plan_do_not_execute_action(trust_harness) -> None:
    service = _service(events=trust_harness["events"])
    service.attach_trust_service(trust_harness["trust_service"])
    pending = _create_pending(trust_harness, request_id="voice-confirm-reject")

    show_plan = asyncio.run(
        service.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript="show me the plan",
                session_id="default",
                task_id="task-alpha",
                pending_confirmation_id=pending.approval_request_id,
            )
        )
    )
    assert show_plan.status == "shown"
    assert show_plan.consumed_confirmation is False
    assert "Approval is required" in show_plan.user_message
    assert show_plan.action_executed is False

    rejected = asyncio.run(
        service.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript="no",
                session_id="default",
                task_id="task-alpha",
                pending_confirmation_id=pending.approval_request_id,
                metadata={"payload_hash": "payload-alpha"},
            )
        )
    )
    stored = trust_harness["trust_service"].repository.get_approval_request(
        pending.approval_request_id
    )
    assert rejected.status == "rejected"
    assert rejected.consumed_confirmation is True
    assert rejected.action_executed is False
    assert stored is not None
    assert stored.state == ApprovalState.DENIED


def test_manual_voice_short_confirmation_is_intercepted_before_core(
    trust_harness,
) -> None:
    service = _service(events=trust_harness["events"])
    bridge = RecordingCoreBridge()
    service.attach_core_bridge(bridge)
    service.attach_trust_service(trust_harness["trust_service"])
    pending = _create_pending(
        trust_harness,
        request_id="voice-confirm-manual",
        task_id="task-alpha",
        payload_hash="payload-alpha",
    )

    result = asyncio.run(
        service.submit_manual_voice_turn(
            "confirm",
            session_id="default",
            metadata={
                "task_id": "task-alpha",
                "pending_confirmation_id": pending.approval_request_id,
                "payload_hash": "payload-alpha",
            },
        )
    )

    assert result.ok is True
    assert result.core_result is not None
    assert result.core_result.result_state == "confirmation_accepted"
    assert result.core_result.provenance["voice_confirmation"]["status"] == "confirmed"
    assert result.core_result.provenance["voice_confirmation"][
        "action_executed"
    ] is False
    assert bridge.calls == []


def test_voice16_api_routes_are_backend_owned(temp_config) -> None:
    route_paths = {
        route.path
        for route in create_app(temp_config).routes
        if isinstance(route, APIRoute)
    }

    assert "/voice/confirmation/status" in route_paths
    assert "/voice/confirmation/submit" in route_paths


def test_voice16_api_yes_without_pending_confirmation_is_noop(temp_config) -> None:
    temp_config.voice.enabled = True
    temp_config.voice.mode = "manual"
    temp_config.voice.manual_input_enabled = True

    with TestClient(create_app(temp_config)) as client:
        response = client.post(
            "/voice/confirmation/submit",
            json={"transcript": "yes", "session_id": "default"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["action"] == "voice.handleSpokenConfirmation"
    assert payload["result"]["status"] == "no_pending_confirmation"
    assert payload["result"]["action_executed"] is False
    assert payload["result"]["core_task_cancelled"] is False
    assert payload["voice"]["spoken_confirmation"]["last_status"] == (
        "no_pending_confirmation"
    )


def test_bridge_and_controller_route_spoken_confirmation_to_client(
    temp_config,
) -> None:
    bridge = UiBridge(temp_config)
    client = _VoiceConfirmationClient()
    MainController(config=temp_config, bridge=bridge, client=client)

    bridge.submitSpokenConfirmation("confirm", "approval-1", "task-1")

    assert client.confirmation_calls == [
        {
            "transcript": "confirm",
            "session_id": "default",
            "source": "deck",
            "pending_confirmation_id": "approval-1",
            "task_id": "task-1",
        }
    ]


def test_voice16_ui_payload_surfaces_confirmation_truth_without_done_language() -> None:
    payload = build_voice_ui_state(
        {
            "voice": {
                "availability": {"available": True, "provider_name": "openai"},
                "state": {"state": "idle"},
                "capture": {"enabled": True, "available": True},
                "manual_turns": {"last_core_result_state": "requires_confirmation"},
                "spoken_confirmation": {
                    "enabled": True,
                    "pending_confirmation_count": 1,
                    "last_status": "binding_failed",
                    "last_pending_confirmation_id": "approval-1",
                    "last_intent": {
                        "intent": "confirm",
                        "matched_phrase_family": "confirm_normal",
                    },
                    "last_binding": {
                        "valid": False,
                        "invalid_reason": "payload_mismatch",
                        "required_confirmation_strength": "explicit_confirm",
                        "provided_confirmation_strength": "normal_confirm",
                    },
                    "last_result": {
                        "status": "binding_failed",
                        "reason": "payload_mismatch",
                        "user_message": (
                            "That confirmation no longer matches the current action."
                        ),
                        "action_executed": False,
                        "core_task_cancelled": False,
                        "core_result_mutated": False,
                    },
                    "confirmation_requires_pending_binding": True,
                    "confirmation_accepted_does_not_execute_action": True,
                },
                "runtime_truth": {
                    "spoken_yes_is_not_global_permission": True,
                    "spoken_confirmation_is_not_command_authority": True,
                    "confirmation_accepted_does_not_mean_action_completed": True,
                },
            }
        }
    )

    assert payload["spoken_confirmation_enabled"] is True
    assert payload["pending_confirmation_count"] == 1
    assert payload["last_spoken_confirmation_status"] == "binding_failed"
    assert payload["last_spoken_confirmation_intent"] == "confirm"
    assert payload["ghost"]["primary_label"] == (
        "That confirmation no longer matches the current action."
    )
    assert payload["truth_flags"]["spoken_yes_is_not_global_permission"] is True
    assert (
        payload["truth_flags"]["confirmation_accepted_does_not_mean_action_completed"]
        is True
    )
    assert any(
        section["title"] == "Confirmation"
        for section in payload["deck"]["sections"]
    )
    rendered = str(payload).lower()
    for forbidden in ["done", "all set", "verified", "sent", "installed"]:
        assert forbidden not in rendered
