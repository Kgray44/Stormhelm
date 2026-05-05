from __future__ import annotations

from dataclasses import dataclass, field
import os

import pytest

import stormhelm.core.discord_relay.service as relay_service_module
from stormhelm.config.models import DiscordTrustedAliasConfig
from stormhelm.core.adapters import AdapterContract
from stormhelm.core.adapters import AdapterContractRegistry
from stormhelm.core.adapters import ApprovalDescriptor
from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import RollbackDescriptor
from stormhelm.core.adapters import TrustTier
from stormhelm.core.adapters import VerificationDescriptor
from stormhelm.core.discord_relay import DiscordDestination
from stormhelm.core.discord_relay import DiscordDestinationKind
from stormhelm.core.discord_relay import DiscordDispatchAttempt
from stormhelm.core.discord_relay import DiscordDispatchPreview
from stormhelm.core.discord_relay import DiscordDispatchState
from stormhelm.core.discord_relay import DiscordLocalDispatchResult
from stormhelm.core.discord_relay import DiscordLocalDispatchStep
from stormhelm.core.discord_relay import DiscordLocalDispatchStepName
from stormhelm.core.discord_relay import DiscordLocalDispatchStepStatus
from stormhelm.core.discord_relay import DiscordPayloadCandidate
from stormhelm.core.discord_relay import DiscordPayloadKind
from stormhelm.core.discord_relay import DiscordPolicyDecision
from stormhelm.core.discord_relay import DiscordPolicyOutcome
from stormhelm.core.discord_relay import DiscordRouteMode
from stormhelm.core.discord_relay import LocalDiscordClientAdapter
from stormhelm.core.discord_relay import OfficialDiscordScaffoldAdapter
from stormhelm.core.discord_relay import build_discord_relay_subsystem
from stormhelm.core.orchestrator.session_state import ConversationStateStore


def _future_contract(adapter_id: str) -> AdapterContract:
    return AdapterContract(
        adapter_id=adapter_id,
        display_name=adapter_id.replace(".", " ").title(),
        family="future",
        description="Scaffold contract for relay hardening tests.",
        observation_modes=["semantic_context"],
        action_modes=["send_via_local_client"],
        artifact_modes=["dispatch_trace"],
        preview_modes=["mandatory_preview"],
        safety_posture=["backend_owned"],
        failure_posture=["explicit_limits"],
        trust_tier=TrustTier.EXTERNAL_DISPATCH,
        approval=ApprovalDescriptor(required=True, preview_allowed=True, preview_required=True, available_scopes=["once"]),
        verification=VerificationDescriptor(
            posture="bounded",
            max_claimable_outcome=ClaimOutcome.INITIATED,
            evidence=["synthetic relay test evidence"],
        ),
        rollback=RollbackDescriptor(supported=False, posture="none"),
        planner_tags=["future"],
        local_first=False,
        external_side_effects=True,
        offline_behavior="partial",
    )


class FakePreferencesRepository:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def set_preference(self, key: str, value: object) -> None:
        self.values[key] = value

    def get_all(self) -> dict[str, object]:
        return dict(self.values)


@dataclass(slots=True)
class FakeObservationResult:
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


@dataclass(slots=True)
class FakeObservationSource:
    payload: dict[str, object]

    def observe(self, **_: object) -> FakeObservationResult:
        return FakeObservationResult(payload=self.payload)


@dataclass(slots=True)
class FakeDispatchAdapter:
    state: DiscordDispatchState
    verification_strength: str = "moderate"
    verification_evidence: list[str] = field(default_factory=lambda: ["Fake adapter executed the relay path."])
    send_summary: str | None = None
    debug: dict[str, object] = field(default_factory=dict)
    calls: list[dict[str, object]] = field(default_factory=list, init=False)

    def send(self, *, destination, preview) -> DiscordDispatchAttempt:
        self.calls.append({"destination": destination.to_dict(), "preview": preview.to_dict()})
        summary = "Verified in fake adapter." if self.state == DiscordDispatchState.VERIFIED else "Started in fake adapter."
        return DiscordDispatchAttempt(
            state=self.state,
            route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
            route_basis="fake_adapter",
            verification_evidence=list(self.verification_evidence),
            verification_strength=self.verification_strength,
            send_summary=self.send_summary or summary,
            debug=dict(self.debug),
        )


@dataclass(slots=True)
class StubDispatchAdapter(FakeDispatchAdapter):
    adapter_kind: str = "stub"

    def capability(self) -> dict[str, object]:
        return {
            "route_mode": DiscordRouteMode.LOCAL_CLIENT_AUTOMATION.value,
            "preview_supported": True,
            "dispatch_supported": True,
            "verification_supported": True,
            "requires_trust_approval": True,
            "uses_discord_api_user_token": False,
            "uses_self_bot": False,
            "uses_local_client": False,
            "adapter_kind": self.adapter_kind,
            "unavailable_reason": "test stub must not be treated as real dispatch",
        }


@dataclass(slots=True)
class UnavailableDispatchAdapter(FakeDispatchAdapter):
    def capability(self) -> dict[str, object]:
        return {
            "route_mode": DiscordRouteMode.LOCAL_CLIENT_AUTOMATION.value,
            "preview_supported": True,
            "dispatch_supported": False,
            "verification_supported": False,
            "requires_trust_approval": True,
            "uses_discord_api_user_token": False,
            "uses_self_bot": False,
            "uses_local_client": False,
            "adapter_kind": "unavailable",
            "unavailable_reason": "test local automation unavailable",
        }


@dataclass(slots=True)
class FakeRealDispatchAdapter(FakeDispatchAdapter):
    verification_supported: bool = False

    def capability(self) -> dict[str, object]:
        return {
            "route_mode": DiscordRouteMode.LOCAL_CLIENT_AUTOMATION.value,
            "preview_supported": True,
            "dispatch_supported": True,
            "verification_supported": self.verification_supported,
            "requires_trust_approval": True,
            "uses_discord_api_user_token": False,
            "uses_self_bot": False,
            "uses_local_client": True,
            "adapter_kind": "real",
            "route_constraint": "can_navigate_to_alias_dm",
            "can_focus_client": True,
            "can_launch_client": True,
            "can_identify_discord_surface": True,
            "can_navigate_dm": True,
            "can_locate_message_input": True,
            "can_insert_text": True,
            "can_press_send": True,
            "can_verify_send": self.verification_supported,
            "can_verify_sent_message": self.verification_supported,
            "can_report_failure": True,
        }


@dataclass(slots=True)
class StepResultDispatchAdapter(FakeRealDispatchAdapter):
    local_result: dict[str, object] = field(default_factory=dict)
    capability_overrides: dict[str, object] = field(default_factory=dict)

    def capability(self) -> dict[str, object]:
        capability = FakeRealDispatchAdapter.capability(self)
        capability.update(dict(self.capability_overrides))
        return capability

    def send(self, *, destination, preview) -> DiscordDispatchAttempt:
        self.calls.append({"destination": destination.to_dict(), "preview": preview.to_dict()})
        debug = dict(self.debug)
        if self.local_result:
            debug["local_dispatch_result"] = dict(self.local_result)
        return DiscordDispatchAttempt(
            state=self.state,
            route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
            route_basis="step_result_adapter",
            verification_evidence=list(self.verification_evidence),
            verification_strength=self.verification_strength,
            send_summary=self.send_summary or "Step-result adapter attempted the relay path.",
            debug=debug,
        )


@dataclass(slots=True)
class FakeClock:
    now: float = 1_000.0

    def __call__(self) -> float:
        return self.now


@dataclass(slots=True)
class FakeClipboardBridge:
    text_values: list[str] = field(default_factory=list)
    file_path_values: list[list[str]] = field(default_factory=list)

    def set_text(self, value: str) -> None:
        self.text_values.append(value)

    def set_file_paths(self, paths: list[str]) -> None:
        self.file_path_values.append(list(paths))


@dataclass(slots=True)
class FailingClipboardBridge:
    failure_reason: str = "clipboard_lock_failed"
    attempts: list[tuple[str, object]] = field(default_factory=list)

    def set_text(self, value: str) -> None:
        self.attempts.append(("text", value))
        raise RuntimeError(self.failure_reason)

    def set_file_paths(self, paths: list[str]) -> None:
        self.attempts.append(("files", list(paths)))
        raise RuntimeError(self.failure_reason)


@dataclass(slots=True)
class FakeDriver:
    actions: list[tuple[str, object]] = field(default_factory=list)

    def hotkey(self, sequence: list[str]) -> None:
        self.actions.append(("hotkey", tuple(sequence)))

    def key(self, key_name: str) -> None:
        self.actions.append(("key", key_name))

    def sleep(self, seconds: float) -> None:
        self.actions.append(("sleep", seconds))

    def submit_navigation(self) -> None:
        self.actions.append(("submit_navigation", None))

    def submit_send(self) -> None:
        self.actions.append(("submit_send", None))


class FailingPasteDriver(FakeDriver):
    def hotkey(self, sequence: list[str]) -> None:
        if tuple(sequence) == ("ctrl", "v"):
            raise RuntimeError("paste_failed")
        super().hotkey(sequence)


class FailingSendDriver(FakeDriver):
    def submit_send(self) -> None:
        self.actions.append(("submit_send", None))
        raise RuntimeError("send_gesture_failed")


@dataclass(slots=True)
class FakeSystemProbe:
    focused_window: dict[str, object]
    verification_result: dict[str, object] | None = None
    app_control_calls: list[dict[str, object]] = field(default_factory=list)

    def app_control(self, **kwargs: object) -> None:
        self.app_control_calls.append(dict(kwargs))

    def window_status(self) -> dict[str, object]:
        return {"focused_window": dict(self.focused_window)}

    def discord_relay_verification(self, **_: object) -> dict[str, object]:
        return dict(self.verification_result or {})


def _build_service(
    temp_config,
    *,
    observation_payload: dict[str, object] | None = None,
    local_adapter=None,
    system_probe=None,
    clock=None,
    trust_service=None,
):
    session_state = ConversationStateStore(FakePreferencesRepository())
    return (
        build_discord_relay_subsystem(
            temp_config.discord_relay,
            session_state=session_state,
            system_probe=system_probe,
            observation_source=FakeObservationSource(observation_payload or {}),
            local_adapter=local_adapter,
            clock=clock,
            trust_service=trust_service,
        ),
        session_state,
    )


def _adapter_preview(
    *,
    payload_kind: DiscordPayloadKind = DiscordPayloadKind.PAGE_LINK,
    text: str | None = None,
    url: str | None = "https://example.com/relay",
    title: str | None = "Relay Page",
) -> DiscordDispatchPreview:
    return DiscordDispatchPreview(
        destination=DiscordDestination(
            alias="Baby",
            label="Baby",
            destination_kind=DiscordDestinationKind.PERSONAL_DM,
            route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
            search_query="Baby",
        ),
        payload=DiscordPayloadCandidate(
            kind=payload_kind,
            summary="Relay preview",
            provenance="workspace_active_item",
            confidence=0.95,
            title=title,
            url=url,
            text=text,
            preview_text=text or url,
        ),
        route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
        note_text=None,
        policy=DiscordPolicyDecision(outcome=DiscordPolicyOutcome.ALLOWED),
    )


def _local_result(
    *,
    result_state: DiscordDispatchState,
    final_send_gesture_performed: bool,
    message_inserted: bool = True,
    verification_attempted: bool = False,
    verification_evidence_present: bool = False,
    failure_step: str | None = None,
    failure_reason: str | None = None,
    route_constraint: str = "can_navigate_to_alias_dm",
) -> dict[str, object]:
    steps = [
        DiscordLocalDispatchStep(
            step_id="test-capability-check",
            relay_request_id="test-relay",
            step_name=DiscordLocalDispatchStepName.CAPABILITY_CHECK,
            status=DiscordLocalDispatchStepStatus.SUCCEEDED,
            adapter_kind="real",
            capability_required="can_dispatch",
            capability_declared=True,
            evidence_summary="Test adapter declared dispatch support.",
            safe_to_continue=True,
        ),
        DiscordLocalDispatchStep(
            step_id="test-perform-send",
            relay_request_id="test-relay",
            step_name=DiscordLocalDispatchStepName.PERFORM_SEND_GESTURE,
            status=DiscordLocalDispatchStepStatus.SUCCEEDED
            if final_send_gesture_performed
            else DiscordLocalDispatchStepStatus.SKIPPED,
            adapter_kind="real",
            capability_required="can_press_send",
            capability_declared=True,
            evidence_summary="Test adapter send gesture result.",
            safe_to_continue=final_send_gesture_performed,
        ),
    ]
    return DiscordLocalDispatchResult(
        relay_request_id="test-relay",
        recipient_alias="Baby",
        adapter_kind="real",
        route_constraint=route_constraint,
        dispatch_supported=True,
        verification_supported=verification_attempted,
        steps=steps,
        final_send_gesture_performed=final_send_gesture_performed,
        message_inserted=message_inserted,
        verification_attempted=verification_attempted,
        verification_evidence_present=verification_evidence_present,
        result_state=result_state,
        sent_claimed=result_state in {DiscordDispatchState.SENT_UNVERIFIED, DiscordDispatchState.SENT_VERIFIED},
        verified_claimed=result_state == DiscordDispatchState.SENT_VERIFIED,
        user_message="test local dispatch result",
        failure_step=failure_step,
        failure_reason=failure_reason,
    ).to_dict()


def test_discord_relay_preview_resolves_current_page_to_baby(temp_config) -> None:
    service, _ = _build_service(temp_config)

    response = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "module": "browser",
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert response.state == DiscordDispatchState.PREVIEW_READY
    assert response.preview is not None
    assert response.preview.destination.alias == "Baby"
    assert response.preview.route_mode == DiscordRouteMode.LOCAL_CLIENT_AUTOMATION
    assert response.preview.payload.kind == DiscordPayloadKind.PAGE_LINK
    assert response.active_request_state is not None
    assert response.active_request_state["parameters"]["pending_preview"]["payload"]["kind"] == "page_link"
    assert "haven't sent anything yet" in response.assistant_response


def test_discord_relay_preview_active_state_preserves_dispatchable_pending_preview(temp_config) -> None:
    service, session_state = _build_service(temp_config)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {"kind": "text", "value": "clipboard relay body"}},
        workspace_context={"active_item": {}},
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert preview.active_request_state is not None
    session_state.set_active_request_state("default", preview.active_request_state)
    cached = session_state.get_active_request_state("default")

    pending_preview = cached["parameters"]["pending_preview"]  # type: ignore[index]
    assert pending_preview["destination"]["alias"] == "Baby"
    assert pending_preview["payload"]["kind"] == "clipboard_text"
    assert pending_preview["payload"]["text"] == "clipboard relay body"
    assert pending_preview["fingerprint"]["payload_source"] == "clipboard"


def test_discord_relay_clipboard_source_is_labeled_as_clipboard_not_selected_text(temp_config) -> None:
    service, _ = _build_service(temp_config)

    response = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {"kind": "text", "value": "clipboard relay body"}},
        workspace_context={"active_item": {}},
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert response.state == DiscordDispatchState.PREVIEW_READY
    assert response.preview is not None
    assert response.preview.payload.kind == DiscordPayloadKind.CLIPBOARD_TEXT
    assert response.debug["payload_source"]["label"] == "clipboard"
    response_text = response.assistant_response.lower()
    assert "clipboard text" in response_text
    assert "selected text" not in response_text


def test_build_discord_relay_subsystem_accepts_clock_injection(temp_config) -> None:
    clock = FakeClock(now=4321.5)
    service, _ = _build_service(temp_config, clock=clock)

    response = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert response.preview is not None
    assert response.preview.created_at == pytest.approx(4321.5)
    assert response.preview.expires_at == pytest.approx(4441.5)


def test_official_discord_route_remains_explicit_and_scaffolded(temp_config) -> None:
    adapter = OfficialDiscordScaffoldAdapter(config=temp_config.discord_relay)
    destination = DiscordDestination(
        alias="Debug",
        label="Debug Channel",
        destination_kind=DiscordDestinationKind.CHANNEL,
        route_mode=DiscordRouteMode.OFFICIAL_BOT_WEBHOOK,
        search_query="debug",
    )
    preview = DiscordDispatchPreview(
        destination=destination,
        payload=DiscordPayloadCandidate(
            kind=DiscordPayloadKind.SELECTED_TEXT,
            summary="Relay preview",
            provenance="active_selection",
            confidence=0.95,
            text="log excerpt",
            preview_text="log excerpt",
        ),
        route_mode=DiscordRouteMode.OFFICIAL_BOT_WEBHOOK,
        note_text=None,
        policy=DiscordPolicyDecision(outcome=DiscordPolicyOutcome.ALLOWED),
    )

    attempt = adapter.send(destination=destination, preview=preview)

    assert attempt.state == DiscordDispatchState.DISPATCH_NOT_IMPLEMENTED
    assert attempt.route_mode == DiscordRouteMode.OFFICIAL_BOT_WEBHOOK
    assert "scaffolded only" in (attempt.send_summary or "").lower()


def test_discord_relay_uses_screen_disambiguation_only_to_break_payload_tie(temp_config) -> None:
    service, _ = _build_service(
        temp_config,
        observation_payload={
            "focus_metadata": {"process_name": "chrome"},
            "workspace_snapshot": {"module": "browser"},
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "module": "browser",
            "active_item": {
                "title": "Relay Notes",
                "url": "https://example.com/page",
                "path": "C:/Stormhelm/docs/relay-notes.md",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert response.state == DiscordDispatchState.PREVIEW_READY
    assert response.preview is not None
    assert response.preview.payload.kind == DiscordPayloadKind.PAGE_LINK
    assert response.preview.screen_awareness_used is True


def test_discord_relay_rejects_stale_recent_entity_for_generic_this_request(temp_config) -> None:
    service, _ = _build_service(temp_config)

    response = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_entities": [
                {
                    "title": "Yesterday page",
                    "url": "https://example.com/yesterday",
                }
            ],
        },
        workspace_context={"active_item": {}},
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert response.state == DiscordDispatchState.UNRESOLVED
    assert response.preview is None
    assert "current" in response.assistant_response.lower()
    assert "stale" in response.assistant_response.lower()


def test_discord_relay_preview_exposes_payload_source_in_preview_and_debug_state(temp_config) -> None:
    service, _ = _build_service(temp_config)

    response = service.handle_request(
        session_id="default",
        operator_text="send this page to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "module": "browser",
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "page_link",
            "request_stage": "preview",
        },
    )

    assert response.preview is not None
    assert "source:" in response.assistant_response.lower()
    assert "current page" in response.assistant_response.lower()
    assert response.debug["payload_source"]["label"] == "current page"
    assert response.debug["payload_source"]["strength"] == "strong_current"


def test_discord_relay_blocks_secret_text_payload(temp_config) -> None:
    service, _ = _build_service(temp_config)

    response = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={
            "selection": {"kind": "text", "value": "API key: sk-test-secret", "preview": "API key: sk-test-secret"},
            "clipboard": {},
        },
        workspace_context={"active_item": {}},
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_BLOCKED
    assert response.preview is not None
    assert response.preview.policy.blocks
    assert "credentials or secrets" in response.assistant_response


@pytest.mark.parametrize(
    ("dispatch_state", "verification_strength", "verification_supported", "debug", "expected_state"),
    [
        (
            DiscordDispatchState.STARTED,
            "moderate",
            False,
            {"dispatch_attempted": True, "final_send_gesture_performed": True, "verification_attempted": False},
            DiscordDispatchState.SENT_UNVERIFIED,
        ),
        (
            DiscordDispatchState.VERIFIED,
            "strong",
            True,
            {"dispatch_attempted": True, "final_send_gesture_performed": True, "verification_attempted": True},
            DiscordDispatchState.SENT_VERIFIED,
        ),
    ],
)
def test_discord_relay_dispatch_propagates_honest_send_state(
    temp_config,
    dispatch_state: DiscordDispatchState,
    verification_strength: str,
    verification_supported: bool,
    debug: dict[str, object],
    expected_state: DiscordDispatchState,
) -> None:
    adapter = FakeRealDispatchAdapter(
        state=dispatch_state,
        verification_strength=verification_strength,
        verification_supported=verification_supported,
        debug=debug,
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == expected_state
    assert response.attempt is not None
    assert response.attempt.route_mode == DiscordRouteMode.LOCAL_CLIENT_AUTOMATION
    assert adapter.calls


def test_discord_relay_stub_adapter_cannot_report_sent_or_verified(temp_config) -> None:
    adapter = StubDispatchAdapter(state=DiscordDispatchState.VERIFIED)
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state.value in {"dispatch_not_implemented", "dispatch_unavailable"}
    assert response.attempt is None
    assert not adapter.calls
    response_text = response.assistant_response.lower()
    assert "not wired" in response_text or "not available" in response_text or "not implemented" in response_text
    assert "verified" not in response_text
    assert "sent to baby" not in response_text


def test_discord_relay_dispatch_unsupported_is_truthful_and_keeps_native_continuation(temp_config) -> None:
    adapter = UnavailableDispatchAdapter(state=DiscordDispatchState.VERIFIED)
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_UNAVAILABLE
    assert response.response_contract["sent"] is False
    assert response.response_contract["verified"] is False
    assert response.debug["route_family"] == "discord_relay"
    assert response.debug["provider_fallback_attempted"] is False
    assert response.debug["openai_required"] is False
    assert response.active_request_state is not None
    assert response.active_request_state["parameters"]["pending_preview"]["destination"]["alias"] == "Baby"  # type: ignore[index]
    assert "cannot reach discord/local automation" in response.assistant_response.lower()
    assert not adapter.calls


def test_discord_relay_real_adapter_attempt_without_verification_is_not_verified(temp_config) -> None:
    adapter = FakeRealDispatchAdapter(
        state=DiscordDispatchState.UNCERTAIN,
        verification_strength="none",
        verification_evidence=["Issued the Discord send key."],
        debug={"final_send_gesture_performed": True, "dispatch_attempted": True, "verification_attempted": False},
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state.value == "sent_unverified"
    assert "could not verify" in response.assistant_response.lower()
    assert response.response_contract["verified"] is False


def test_discord_relay_verified_send_requires_supported_strong_evidence(temp_config) -> None:
    adapter = FakeRealDispatchAdapter(
        state=DiscordDispatchState.VERIFIED,
        verification_strength="moderate",
        verification_supported=True,
        verification_evidence=["Adapter reported weak post-send evidence."],
        debug={"dispatch_attempted": True, "final_send_gesture_performed": True, "verification_attempted": True},
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.SENT_UNVERIFIED
    assert response.response_contract["sent"] is True
    assert response.response_contract["verified"] is False
    assert "sent to baby" not in response.assistant_response.lower()


def test_discord_local_automation_diagnostic_reports_step_capabilities(temp_config) -> None:
    adapter = LocalDiscordClientAdapter(
        config=temp_config.discord_relay,
        system_probe=FakeSystemProbe(focused_window={"process_name": "discord", "window_title": "Baby | Discord"}),
        clipboard=FakeClipboardBridge(),
        driver=FakeDriver(),
        open_target=lambda target: None,
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    diagnostic = service.local_automation_diagnostic()

    assert diagnostic["adapter_kind"] == "real"
    assert diagnostic["route_constraint"] == "can_navigate_to_alias_dm"
    assert diagnostic["focus_client"] == "supported"
    assert diagnostic["identify_surface"] == "supported"
    assert diagnostic["navigate_dm"] == "supported"
    assert diagnostic["locate_message_input"] == "supported"
    assert diagnostic["insert_text"] == "supported"
    assert diagnostic["press_send"] == "supported"
    assert diagnostic["verify_message"] in {"supported", "unsupported"}
    assert diagnostic["live_dispatch_ready"] is True
    assert {step["step_name"] for step in diagnostic["steps"]} >= {
        "capability_check",
        "focus_client",
        "identify_discord_surface",
        "navigate_recipient_dm",
        "locate_message_input",
        "insert_payload",
        "perform_send_gesture",
        "verify_message_visible",
    }


def test_discord_relay_cannot_send_when_send_gesture_capability_missing(temp_config) -> None:
    adapter = StepResultDispatchAdapter(
        state=DiscordDispatchState.SENT_UNVERIFIED,
        debug={"dispatch_attempted": True, "final_send_gesture_performed": True},
        local_result=_local_result(
            result_state=DiscordDispatchState.SENT_UNVERIFIED,
            final_send_gesture_performed=True,
        ),
        capability_overrides={"can_press_send": False},
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )
    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state in {DiscordDispatchState.DISPATCH_UNAVAILABLE, DiscordDispatchState.DISPATCH_BLOCKED}
    assert response.response_contract["sent"] is False
    assert response.debug["final_send_gesture_performed"] is False
    assert "sent to baby" not in response.assistant_response.lower()


def test_discord_relay_step_result_requires_send_gesture_for_sent_unverified(temp_config) -> None:
    adapter = StepResultDispatchAdapter(
        state=DiscordDispatchState.SENT_UNVERIFIED,
        debug={"dispatch_attempted": True, "final_send_gesture_performed": False},
        local_result=_local_result(
            result_state=DiscordDispatchState.SENT_UNVERIFIED,
            final_send_gesture_performed=False,
            failure_step="perform_send_gesture",
            failure_reason="send_gesture_not_performed",
        ),
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )
    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED
    assert response.response_contract["sent"] is False
    assert response.debug["final_send_gesture_performed"] is False
    assert response.debug["failure_step"] == "perform_send_gesture"


def test_discord_relay_step_result_requires_verification_evidence_for_sent_verified(temp_config) -> None:
    adapter = StepResultDispatchAdapter(
        state=DiscordDispatchState.SENT_VERIFIED,
        verification_strength="strong",
        verification_supported=True,
        debug={"dispatch_attempted": True, "final_send_gesture_performed": True, "verification_attempted": True},
        local_result=_local_result(
            result_state=DiscordDispatchState.SENT_VERIFIED,
            final_send_gesture_performed=True,
            verification_attempted=True,
            verification_evidence_present=False,
        ),
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )
    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.SENT_UNVERIFIED
    assert response.response_contract["sent"] is True
    assert response.response_contract["verified"] is False
    assert response.debug["verification_evidence_present"] is False
    assert "sent to baby" not in response.assistant_response.lower()


def test_discord_relay_success_wording_only_appears_for_verified_send(temp_config) -> None:
    service, _ = _build_service(temp_config)
    preview = _adapter_preview()
    states = [
        DiscordDispatchState.DISPATCH_NOT_IMPLEMENTED,
        DiscordDispatchState.DISPATCH_UNAVAILABLE,
        DiscordDispatchState.DISPATCH_BLOCKED,
        DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED,
        DiscordDispatchState.DISPATCH_FAILED,
        DiscordDispatchState.SENT_UNVERIFIED,
        DiscordDispatchState.SENT_VERIFIED,
    ]

    for state in states:
        attempt = DiscordDispatchAttempt(
            state=state,
            route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
            route_basis="unit_test",
            verification_strength="strong" if state == DiscordDispatchState.SENT_VERIFIED else "none",
            verification_evidence=["Observed message evidence."]
            if state == DiscordDispatchState.SENT_VERIFIED
            else ["Attempt evidence only."],
            send_summary="Fake adapter says message sent and delivered.",
            debug={"dispatch_attempted": state != DiscordDispatchState.DISPATCH_NOT_IMPLEMENTED},
        )
        assistant_response, contract = service._dispatch_contract(preview=preview, attempt=attempt)
        text = assistant_response.lower()
        if state == DiscordDispatchState.SENT_VERIFIED:
            assert "sent to baby" in text
            assert contract["verified"] is True
        else:
            assert "sent to baby" not in text
            assert "delivered" not in text
            assert "message sent" not in text
            assert contract["verified"] is False


def test_discord_relay_scaffolds_screenshot_payloads_in_this_pass(temp_config) -> None:
    service, _ = _build_service(temp_config)

    response = service.handle_request(
        session_id="default",
        operator_text="send this screenshot to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={"active_item": {}},
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "screenshot_candidate",
            "request_stage": "preview",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_BLOCKED
    assert response.preview is not None
    assert response.preview.payload.kind == DiscordPayloadKind.SCREENSHOT_CANDIDATE
    assert "scaffolded only" in response.assistant_response.lower()


def test_discord_relay_invalidates_preview_when_active_page_changes_before_confirm(temp_config) -> None:
    clock = FakeClock()
    adapter = FakeDispatchAdapter(state=DiscordDispatchState.STARTED)
    service, _ = _build_service(temp_config, local_adapter=adapter, clock=clock)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "module": "browser",
            "active_item": {
                "title": "Original Page",
                "url": "https://example.com/original",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "module": "browser",
            "active_item": {
                "title": "Different Page",
                "url": "https://example.com/different",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_FAILED
    assert "stale" in response.assistant_response.lower()
    assert response.debug["invalidation_reason"] == "page_changed_after_preview"
    assert not adapter.calls


def test_discord_relay_invalidates_preview_when_clipboard_changes_before_confirm(temp_config) -> None:
    clock = FakeClock()
    adapter = FakeDispatchAdapter(state=DiscordDispatchState.STARTED)
    service, _ = _build_service(temp_config, local_adapter=adapter, clock=clock)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {"kind": "text", "value": "first clipboard body"}},
        workspace_context={"active_item": {}},
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {"kind": "text", "value": "second clipboard body"}},
        workspace_context={"active_item": {}},
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_FAILED
    assert "clipboard" in response.assistant_response.lower()
    assert response.debug["invalidation_reason"] == "clipboard_changed_after_preview"
    assert not adapter.calls


def test_discord_relay_invalidates_preview_when_file_disappears_before_confirm(temp_config, tmp_path) -> None:
    clock = FakeClock()
    adapter = FakeDispatchAdapter(state=DiscordDispatchState.STARTED)
    service, _ = _build_service(temp_config, local_adapter=adapter, clock=clock)
    target = tmp_path / "dispatch.txt"
    target.write_text("stormhelm relay", encoding="utf-8")

    preview = service.handle_request(
        session_id="default",
        operator_text="send this file to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "dispatch.txt",
                "path": str(target),
                "kind": "text-file",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "file",
            "request_stage": "preview",
        },
    )

    target.unlink()

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "dispatch.txt",
                "path": str(target),
                "kind": "text-file",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_FAILED
    assert "file" in response.assistant_response.lower()
    assert response.debug["invalidation_reason"] == "file_missing_after_preview"
    assert not adapter.calls


def test_discord_relay_invalidates_note_preview_when_note_changes_before_confirm(temp_config) -> None:
    clock = FakeClock()
    adapter = FakeDispatchAdapter(state=DiscordDispatchState.STARTED)
    service, _ = _build_service(temp_config, local_adapter=adapter, clock=clock)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "module": "notes",
            "active_item": {
                "title": "Bridge Note",
                "path": "C:/Stormhelm/notes/bridge.md",
                "kind": "note",
                "text": "original note body",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "note_artifact",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "module": "notes",
            "active_item": {
                "title": "Bridge Note",
                "path": "C:/Stormhelm/notes/bridge.md",
                "kind": "note",
                "text": "edited note body",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_FAILED
    assert "changed after preview" in response.assistant_response.lower()
    assert response.debug["invalidation_reason"] == "note_changed_after_preview"
    assert not adapter.calls


def test_discord_relay_preserves_preview_after_confirmation_timeout(temp_config) -> None:
    clock = FakeClock()
    adapter = FakeDispatchAdapter(state=DiscordDispatchState.STARTED)
    service, _ = _build_service(temp_config, local_adapter=adapter, clock=clock)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert preview.preview is not None
    clock.now = float(preview.preview.expires_at or 0.0) + 1.0

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.APPROVAL_EXPIRED
    assert "confirmation expired" in response.assistant_response.lower()
    assert "send it now" in response.assistant_response.lower()
    assert response.debug["invalidation_reason"] == "preview_expired"
    assert response.active_request_state is not None
    assert response.active_request_state["parameters"]["pending_preview"]["destination"]["alias"] == "Baby"  # type: ignore[index]
    assert not adapter.calls


def test_discord_relay_expired_approval_preserves_preview_and_asks_only_for_confirmation(temp_config) -> None:
    clock = FakeClock()
    adapter = FakeRealDispatchAdapter(state=DiscordDispatchState.SENT_UNVERIFIED)
    service, _ = _build_service(temp_config, local_adapter=adapter, clock=clock)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {"kind": "text", "value": "clipboard body"}},
        workspace_context={"active_item": {}},
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )
    assert preview.preview is not None
    clock.now = float(preview.preview.expires_at or 0.0) + 1.0

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {"kind": "text", "value": "clipboard body"}},
        workspace_context={"active_item": {}},
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state.value == "approval_expired"
    assert response.preview is not None
    assert response.preview.destination.alias == "Baby"
    assert response.preview.payload.text == "clipboard body"
    assert "baby" in response.assistant_response.lower()
    assert "clipboard" in response.assistant_response.lower()
    assert "who" not in response.assistant_response.lower()
    assert "what should i send" not in response.assistant_response.lower()
    assert not adapter.calls


def test_discord_relay_blocks_duplicate_confirm_attempts_in_short_window(temp_config) -> None:
    clock = FakeClock()
    adapter = FakeRealDispatchAdapter(
        state=DiscordDispatchState.SENT_UNVERIFIED,
        debug={"dispatch_attempted": True, "final_send_gesture_performed": True, "verification_attempted": False},
    )
    service, _ = _build_service(temp_config, local_adapter=adapter, clock=clock)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    first = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert first.state == DiscordDispatchState.SENT_UNVERIFIED
    clock.now += 5.0

    second = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert second.state == DiscordDispatchState.DISPATCH_BLOCKED
    assert "duplicate send attempt" in second.assistant_response.lower()
    assert second.debug["duplicate_suppressed"] is True
    assert len(adapter.calls) == 1


def test_discord_relay_uses_unverified_wording_when_verification_is_weak(temp_config) -> None:
    adapter = FakeRealDispatchAdapter(
        state=DiscordDispatchState.UNCERTAIN,
        verification_strength="moderate",
        verification_evidence=["Discord stayed focused on Baby after the send key."],
        debug={"dispatch_attempted": True, "final_send_gesture_performed": True, "verification_attempted": False},
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.SENT_UNVERIFIED
    assert "could not verify" in response.assistant_response.lower()
    assert "appears to have completed" not in response.assistant_response.lower()
    assert response.response_contract["sent"] is True
    assert response.response_contract["verified"] is False


def test_discord_relay_records_contract_backed_claim_ceiling_for_uncertain_send(temp_config) -> None:
    adapter = FakeRealDispatchAdapter(
        state=DiscordDispatchState.UNCERTAIN,
        verification_strength="moderate",
        verification_evidence=["Discord stayed focused on Baby after the send key."],
        debug={"dispatch_attempted": True, "final_send_gesture_performed": True, "verification_attempted": False},
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.debug["adapter_contract"]["adapter_id"] == "relay.discord_local_client"
    assert response.debug["adapter_execution"]["claim_ceiling"] == "initiated"
    assert "verified that the message appears" not in response.assistant_response.lower()


def test_discord_relay_fails_closed_when_route_is_not_contract_backed(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _build_service(temp_config)
    broken_contracts = AdapterContractRegistry()
    broken_contracts.register_contract(_future_contract("future.other_route"))
    monkeypatch.setattr(relay_service_module, "default_adapter_contract_registry", lambda: broken_contracts)

    response = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={
            "active_page": {
                "url": "https://example.com/article",
                "title": "Relay page",
            }
        },
        workspace_context={"active_item": {}},
        request_slots={
            "destination_alias": "Baby",
            "request_stage": "preview",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_BLOCKED
    assert response.preview is None
    assert "contract-backed" in response.assistant_response.lower()
    assert response.debug["adapter_contract_status"]["contract_required"] is True
    assert response.debug["adapter_contract_status"]["healthy"] is False


def test_local_discord_adapter_refuses_when_wrong_thread_is_focused(temp_config) -> None:
    clipboard = FakeClipboardBridge()
    driver = FakeDriver()
    probe = FakeSystemProbe(
        focused_window={"process_name": "discord", "window_title": "General | Discord"},
    )
    opens: list[str] = []
    adapter = LocalDiscordClientAdapter(
        config=temp_config.discord_relay,
        system_probe=probe,
        clipboard=clipboard,
        driver=driver,
        open_target=opens.append,
    )

    attempt = adapter.send(destination=_adapter_preview().destination, preview=_adapter_preview())

    assert attempt.state == DiscordDispatchState.DISPATCH_BLOCKED
    assert attempt.failure_reason == "discord_destination_unverified"
    assert attempt.debug["wrong_thread_refusal"] is True
    assert attempt.debug["dispatch_side_effects_emitted"] is False
    assert attempt.debug["send_key_issued"] is False
    assert ("submit_send", None) not in driver.actions
    assert driver.actions.count(("submit_navigation", None)) == 1


def test_local_discord_adapter_refuses_when_destination_cannot_be_confidently_verified(temp_config) -> None:
    clipboard = FakeClipboardBridge()
    driver = FakeDriver()
    probe = FakeSystemProbe(
        focused_window={"process_name": "discord", "window_title": ""},
    )
    opens: list[str] = []
    adapter = LocalDiscordClientAdapter(
        config=temp_config.discord_relay,
        system_probe=probe,
        clipboard=clipboard,
        driver=driver,
        open_target=opens.append,
    )

    attempt = adapter.send(destination=_adapter_preview().destination, preview=_adapter_preview())

    assert attempt.state == DiscordDispatchState.DISPATCH_BLOCKED
    assert attempt.failure_reason == "discord_destination_unverified"
    assert attempt.debug["wrong_thread_refusal"] is True
    assert attempt.debug["dispatch_side_effects_emitted"] is False
    assert attempt.debug["send_key_issued"] is False
    assert ("submit_send", None) not in driver.actions
    assert driver.actions.count(("submit_navigation", None)) == 1


def test_local_discord_adapter_returns_verified_when_strong_evidence_probe_confirms_delivery(temp_config) -> None:
    clipboard = FakeClipboardBridge()
    driver = FakeDriver()
    probe = FakeSystemProbe(
        focused_window={"process_name": "discord", "window_title": "Baby | Discord"},
        verification_result={
            "verified": True,
            "strength": "strong",
            "evidence": ["Verified message bubble in Baby's thread."],
        },
    )
    opens: list[str] = []
    adapter = LocalDiscordClientAdapter(
        config=temp_config.discord_relay,
        system_probe=probe,
        clipboard=clipboard,
        driver=driver,
        open_target=opens.append,
    )

    attempt = adapter.send(destination=_adapter_preview().destination, preview=_adapter_preview())

    assert attempt.state == DiscordDispatchState.SENT_VERIFIED
    assert attempt.verification_strength == "strong"
    assert any("Verified message bubble" in item for item in attempt.verification_evidence)
    assert ("submit_send", None) in driver.actions


def test_local_discord_adapter_clipboard_copy_is_not_insertion_when_paste_fails(temp_config) -> None:
    clipboard = FakeClipboardBridge()
    driver = FailingPasteDriver()
    probe = FakeSystemProbe(
        focused_window={"process_name": "discord", "window_title": "Baby | Discord"},
    )
    adapter = LocalDiscordClientAdapter(
        config=temp_config.discord_relay,
        system_probe=probe,
        clipboard=clipboard,
        driver=driver,
        open_target=lambda target: None,
    )
    preview = _adapter_preview(payload_kind=DiscordPayloadKind.SELECTED_TEXT, text="hello from Stormhelm")

    attempt = adapter.send(destination=preview.destination, preview=preview)

    assert clipboard.text_values == ["hello from Stormhelm"]
    assert attempt.state == DiscordDispatchState.DISPATCH_FAILED
    assert attempt.debug["message_inserted"] is False
    assert attempt.debug["payload_copied_to_clipboard"] is True
    assert attempt.debug["final_send_gesture_performed"] is False
    assert attempt.debug["failure_step"] == "insert_payload"
    assert attempt.debug["local_dispatch_result"]["message_inserted"] is False
    assert ("submit_send", None) not in driver.actions


def test_local_discord_adapter_insert_success_without_send_is_not_sent(temp_config) -> None:
    clipboard = FakeClipboardBridge()
    driver = FailingSendDriver()
    probe = FakeSystemProbe(
        focused_window={"process_name": "discord", "window_title": "Baby | Discord"},
    )
    adapter = LocalDiscordClientAdapter(
        config=temp_config.discord_relay,
        system_probe=probe,
        clipboard=clipboard,
        driver=driver,
        open_target=lambda target: None,
    )
    preview = _adapter_preview(payload_kind=DiscordPayloadKind.SELECTED_TEXT, text="hello from Stormhelm")

    attempt = adapter.send(destination=preview.destination, preview=preview)

    assert attempt.state == DiscordDispatchState.DISPATCH_FAILED
    assert attempt.debug["message_inserted"] is True
    assert attempt.debug["final_send_gesture_performed"] is False
    assert attempt.debug["failure_step"] == "perform_send_gesture"
    assert attempt.debug["local_dispatch_result"]["result_state"] == "dispatch_failed"
    assert ("submit_send", None) in driver.actions


def test_discord_relay_current_dm_only_constraint_blocks_without_target_identity(temp_config) -> None:
    adapter = StepResultDispatchAdapter(
        state=DiscordDispatchState.SENT_UNVERIFIED,
        debug={"dispatch_attempted": True, "final_send_gesture_performed": True},
        local_result=_local_result(
            result_state=DiscordDispatchState.SENT_UNVERIFIED,
            final_send_gesture_performed=True,
            route_constraint="current_dm_only",
        ),
        capability_overrides={
            "route_constraint": "current_dm_only",
            "can_navigate_dm": False,
            "can_identify_discord_surface": False,
        },
    )
    service, _ = _build_service(temp_config, local_adapter=adapter)

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )
    response = service.handle_request(
        session_id="default",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    assert response.state == DiscordDispatchState.DISPATCH_BLOCKED
    assert response.debug["route_constraint"] == "current_dm_only"
    assert response.debug["failure_step"] == "navigate_recipient_dm"
    assert response.response_contract["sent"] is False
    assert not adapter.calls


def test_local_discord_adapter_classifies_clipboard_lock_as_transport_failure(temp_config) -> None:
    clipboard = FailingClipboardBridge()
    driver = FakeDriver()
    probe = FakeSystemProbe(
        focused_window={"process_name": "discord", "window_title": "Baby | Discord"},
    )
    adapter = LocalDiscordClientAdapter(
        config=temp_config.discord_relay,
        system_probe=probe,
        clipboard=clipboard,
        driver=driver,
        open_target=lambda target: None,
    )

    attempt = adapter.send(destination=_adapter_preview().destination, preview=_adapter_preview())

    assert attempt.state == DiscordDispatchState.DISPATCH_FAILED
    assert attempt.failure_reason == "clipboard_transport_failed"
    assert attempt.send_summary is not None
    assert "clipboard access failed" in attempt.send_summary.lower()
    assert attempt.debug["failure_stage"] == "payload_insertion"
    assert attempt.debug["transport_failure_kind"] == "clipboard_lock_failed"


def test_discord_relay_preview_attaches_trust_state_when_enabled(temp_config, trust_harness) -> None:
    service, _ = _build_service(temp_config, trust_service=trust_harness["trust_service"])

    response = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert response.state == DiscordDispatchState.APPROVAL_REQUIRED
    assert response.active_request_state is not None
    assert response.active_request_state["trust"]["decision"] == "downgraded"
    assert response.active_request_state["trust"]["request_id"] != ""
    assert "approval is required" in response.assistant_response.lower()


def test_discord_relay_session_grant_reuses_without_second_prompt(temp_config, trust_harness) -> None:
    adapter = FakeRealDispatchAdapter(
        state=DiscordDispatchState.SENT_UNVERIFIED,
        debug={"dispatch_attempted": True, "final_send_gesture_performed": True, "verification_attempted": False},
    )
    service, _ = _build_service(
        temp_config,
        local_adapter=adapter,
        trust_service=trust_harness["trust_service"],
    )

    preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    request_id = str(preview.active_request_state["trust"]["request_id"])  # type: ignore[index]
    dispatched = service.handle_request(
        session_id="default",
        operator_text="send it for this session",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
            "trust_request_id": request_id,
            "approval_scope": "session",
            "approval_outcome": "approve",
        },
    )
    second_preview = service.handle_request(
        session_id="default",
        operator_text="send this to Baby",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {}, "clipboard": {}},
        workspace_context={
            "active_item": {
                "title": "Stormhelm Relay Prompt",
                "url": "https://example.com/relay",
                "kind": "browser-tab",
            }
        },
        request_slots={
            "destination_alias": "Baby",
            "payload_hint": "contextual",
            "request_stage": "preview",
        },
    )

    assert dispatched.state == DiscordDispatchState.SENT_UNVERIFIED
    assert adapter.calls
    assert second_preview.active_request_state is not None
    assert second_preview.active_request_state["trust"]["decision"] == "allowed"
    assert "existing this session grant" in second_preview.assistant_response.lower()


def _live_discord_test_settings() -> dict[str, object]:
    enabled = os.getenv("STORMHELM_DISCORD_LIVE_TEST", "").strip() == "1"
    recipient = os.getenv("STORMHELM_DISCORD_LIVE_TEST_RECIPIENT", "").strip()
    message = os.getenv("STORMHELM_DISCORD_LIVE_TEST_MESSAGE", "").strip()
    confirmation = os.getenv("STORMHELM_DISCORD_LIVE_TEST_CONFIRM", "").strip()
    ready = (
        enabled
        and bool(recipient)
        and bool(message)
        and confirmation == "I_UNDERSTAND_THIS_SENDS_A_REAL_MESSAGE"
    )
    missing = [
        name
        for name, value in (
            ("STORMHELM_DISCORD_LIVE_TEST", "1" if enabled else ""),
            ("STORMHELM_DISCORD_LIVE_TEST_RECIPIENT", recipient),
            ("STORMHELM_DISCORD_LIVE_TEST_MESSAGE", message),
            ("STORMHELM_DISCORD_LIVE_TEST_CONFIRM", confirmation),
        )
        if not value
    ]
    if enabled and confirmation != "I_UNDERSTAND_THIS_SENDS_A_REAL_MESSAGE":
        missing.append("STORMHELM_DISCORD_LIVE_TEST_CONFIRM")
    return {
        "ready": ready,
        "recipient": recipient,
        "message": message,
        "confirmation": confirmation,
        "missing": sorted(set(missing)),
    }


def test_discord_relay_live_test_safety_gate_skipped_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "STORMHELM_DISCORD_LIVE_TEST",
        "STORMHELM_DISCORD_LIVE_TEST_RECIPIENT",
        "STORMHELM_DISCORD_LIVE_TEST_MESSAGE",
        "STORMHELM_DISCORD_LIVE_TEST_CONFIRM",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = _live_discord_test_settings()

    assert settings["ready"] is False
    assert "STORMHELM_DISCORD_LIVE_TEST" in settings["missing"]


def test_discord_relay_live_test_requires_recipient_message_and_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STORMHELM_DISCORD_LIVE_TEST", "1")
    monkeypatch.setenv("STORMHELM_DISCORD_LIVE_TEST_RECIPIENT", "Baby")
    monkeypatch.delenv("STORMHELM_DISCORD_LIVE_TEST_MESSAGE", raising=False)
    monkeypatch.setenv("STORMHELM_DISCORD_LIVE_TEST_CONFIRM", "wrong")

    settings = _live_discord_test_settings()

    assert settings["ready"] is False
    assert "STORMHELM_DISCORD_LIVE_TEST_MESSAGE" in settings["missing"]
    assert "STORMHELM_DISCORD_LIVE_TEST_CONFIRM" in settings["missing"]


@pytest.mark.skipif(
    not _live_discord_test_settings()["ready"],
    reason="live Discord local-client dispatch is opt-in only",
)
def test_discord_relay_live_local_client_dispatch_gate(temp_config) -> None:
    settings = _live_discord_test_settings()
    alias = str(settings["recipient"])
    search_query = alias
    harmless_message = str(settings["message"])
    print("WARNING: running live Discord local-client send test. This sends the configured message.")

    temp_config.discord_relay.trusted_aliases[alias.lower()] = DiscordTrustedAliasConfig(
        alias=alias,
        label=alias,
        search_query=search_query,
        trusted=True,
    )
    from stormhelm.core.system.probe import SystemProbe

    service, _ = _build_service(temp_config, system_probe=SystemProbe(temp_config))

    preview = service.handle_request(
        session_id="live-discord-test",
        operator_text=f"send this to {alias}",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {"kind": "text", "value": harmless_message, "preview": harmless_message}},
        workspace_context={"active_item": {}},
        request_slots={
            "destination_alias": alias,
            "payload_hint": "selected_text",
            "request_stage": "preview",
        },
    )
    assert preview.preview is not None

    response = service.handle_request(
        session_id="live-discord-test",
        operator_text="send it",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={"selection": {"kind": "text", "value": harmless_message, "preview": harmless_message}},
        workspace_context={"active_item": {}},
        request_slots={
            **dict(preview.active_request_state["parameters"]),  # type: ignore[index]
            "request_stage": "dispatch",
        },
    )

    print(
        {
            "state": response.state.value,
            "dispatch_attempted": response.debug.get("dispatch_attempted"),
            "final_send_gesture_performed": response.debug.get("final_send_gesture_performed"),
            "verification_attempted": response.debug.get("verification_attempted"),
            "steps": response.debug.get("steps"),
            "adapter_kind": response.debug.get("adapter_kind"),
            "failure_reason": response.debug.get("failure_reason"),
        }
    )
    assert response.debug["adapter_kind"] in {"real", "unavailable"}
    assert response.response_contract["sent"] is (response.state in {DiscordDispatchState.SENT_UNVERIFIED, DiscordDispatchState.SENT_VERIFIED})
    assert response.response_contract["verified"] is (response.state == DiscordDispatchState.SENT_VERIFIED)
