from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import stormhelm.core.discord_relay.service as relay_service_module
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
    clock=None,
    trust_service=None,
):
    session_state = ConversationStateStore(FakePreferencesRepository())
    return (
        build_discord_relay_subsystem(
            temp_config.discord_relay,
            session_state=session_state,
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

    assert response.state == DiscordDispatchState.READY
    assert response.preview is not None
    assert response.preview.destination.alias == "Baby"
    assert response.preview.route_mode == DiscordRouteMode.LOCAL_CLIENT_AUTOMATION
    assert response.preview.payload.kind == DiscordPayloadKind.PAGE_LINK
    assert response.active_request_state is not None
    assert response.active_request_state["parameters"]["pending_preview"]["payload"]["kind"] == "page_link"
    assert "haven't sent anything yet" in response.assistant_response


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

    assert attempt.state == DiscordDispatchState.FAILED
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

    assert response.state == DiscordDispatchState.READY
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

    assert response.state == DiscordDispatchState.FAILED
    assert response.preview is not None
    assert response.preview.policy.blocks
    assert "credentials or secrets" in response.assistant_response


@pytest.mark.parametrize("dispatch_state", [DiscordDispatchState.STARTED, DiscordDispatchState.VERIFIED])
def test_discord_relay_dispatch_propagates_honest_send_state(temp_config, dispatch_state: DiscordDispatchState) -> None:
    adapter = FakeDispatchAdapter(state=dispatch_state)
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

    assert response.state == dispatch_state
    assert response.attempt is not None
    assert response.attempt.route_mode == DiscordRouteMode.LOCAL_CLIENT_AUTOMATION
    assert adapter.calls


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

    assert response.state == DiscordDispatchState.FAILED
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

    assert response.state == DiscordDispatchState.FAILED
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

    assert response.state == DiscordDispatchState.FAILED
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

    assert response.state == DiscordDispatchState.FAILED
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

    assert response.state == DiscordDispatchState.FAILED
    assert "changed after preview" in response.assistant_response.lower()
    assert response.debug["invalidation_reason"] == "note_changed_after_preview"
    assert not adapter.calls


def test_discord_relay_invalidates_preview_after_timeout(temp_config) -> None:
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

    assert response.state == DiscordDispatchState.FAILED
    assert "stale" in response.assistant_response.lower()
    assert response.debug["invalidation_reason"] == "preview_expired"
    assert not adapter.calls


def test_discord_relay_blocks_duplicate_confirm_attempts_in_short_window(temp_config) -> None:
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

    assert first.state == DiscordDispatchState.STARTED
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

    assert second.state == DiscordDispatchState.FAILED
    assert "duplicate send attempt" in second.assistant_response.lower()
    assert second.debug["duplicate_suppressed"] is True
    assert len(adapter.calls) == 1


def test_discord_relay_uses_likely_completed_wording_when_verification_is_weak(temp_config) -> None:
    adapter = FakeDispatchAdapter(
        state=DiscordDispatchState.UNCERTAIN,
        verification_strength="moderate",
        verification_evidence=["Discord stayed focused on Baby after the send key."],
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

    assert response.state == DiscordDispatchState.UNCERTAIN
    assert "appears to have completed" in response.assistant_response.lower()
    assert "cannot verify delivery" in response.assistant_response.lower()


def test_discord_relay_records_contract_backed_claim_ceiling_for_uncertain_send(temp_config) -> None:
    adapter = FakeDispatchAdapter(
        state=DiscordDispatchState.UNCERTAIN,
        verification_strength="moderate",
        verification_evidence=["Discord stayed focused on Baby after the send key."],
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
    assert response.debug["adapter_execution"]["claim_ceiling"] == "observed"
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

    assert response.state == DiscordDispatchState.FAILED
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

    assert attempt.state == DiscordDispatchState.FAILED
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

    assert attempt.state == DiscordDispatchState.FAILED
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

    assert attempt.state == DiscordDispatchState.VERIFIED
    assert attempt.verification_strength == "strong"
    assert any("Verified message bubble" in item for item in attempt.verification_evidence)
    assert ("submit_send", None) in driver.actions


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

    assert attempt.state == DiscordDispatchState.FAILED
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

    assert response.state == DiscordDispatchState.READY
    assert response.active_request_state is not None
    assert response.active_request_state["trust"]["decision"] == "downgraded"
    assert response.active_request_state["trust"]["request_id"] != ""
    assert "approval is required" in response.assistant_response.lower()


def test_discord_relay_session_grant_reuses_without_second_prompt(temp_config, trust_harness) -> None:
    adapter = FakeDispatchAdapter(state=DiscordDispatchState.STARTED)
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

    assert dispatched.state == DiscordDispatchState.STARTED
    assert adapter.calls
    assert second_preview.active_request_state is not None
    assert second_preview.active_request_state["trust"]["decision"] == "allowed"
    assert "existing this session grant" in second_preview.assistant_response.lower()
