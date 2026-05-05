from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.parse import urlparse

from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import attach_contract_metadata
from stormhelm.core.adapters import build_execution_report
from stormhelm.core.adapters import claim_outcome_from_verification_strength
from stormhelm.core.adapters import default_adapter_contract_registry
from stormhelm.config.models import DiscordRelayConfig
from stormhelm.core.discord_relay.adapters import LocalDiscordClientAdapter
from stormhelm.core.discord_relay.adapters import OfficialDiscordScaffoldAdapter
from stormhelm.core.discord_relay.models import DiscordDestination
from stormhelm.core.discord_relay.models import DiscordDestinationKind
from stormhelm.core.discord_relay.models import DiscordDispatchAttempt
from stormhelm.core.discord_relay.models import DiscordDispatchPreview
from stormhelm.core.discord_relay.models import DiscordDispatchState
from stormhelm.core.discord_relay.models import DiscordPayloadCandidate
from stormhelm.core.discord_relay.models import DiscordPayloadKind
from stormhelm.core.discord_relay.models import DiscordPolicyDecision
from stormhelm.core.discord_relay.models import DiscordPolicyOutcome
from stormhelm.core.discord_relay.models import DiscordRelayCapability
from stormhelm.core.discord_relay.models import DiscordRelayResponse
from stormhelm.core.discord_relay.models import DiscordRelayTrace
from stormhelm.core.discord_relay.models import DiscordRouteMode
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.screen_awareness.observation import NativeContextObservationSource
from stormhelm.core.trust import PermissionScope
from stormhelm.core.trust import TrustActionKind
from stormhelm.core.trust import TrustActionRequest

_BROWSER_PROCESSES = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "arc", "safari"}
_FILE_PROCESSES = {"explorer", "code", "notepad", "notepad++", "devenv", "acrord32", "sumatrapdf"}
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", flags=re.IGNORECASE),
    re.compile(r"\bapi[_ -]?key\b", flags=re.IGNORECASE),
    re.compile(r"\btoken\b", flags=re.IGNORECASE),
    re.compile(r"\bpassword\b", flags=re.IGNORECASE),
    re.compile(r"\bsecret\b", flags=re.IGNORECASE),
]
_PRIOR_CONTEXT_PATTERN = re.compile(r"\b(previous|prior|last|recent|earlier|yesterday|before)\b", flags=re.IGNORECASE)
_DEFAULT_PREVIEW_TTL_SECONDS = 120.0
_DEFAULT_DUPLICATE_WINDOW_SECONDS = 15.0


def _clean_text(value: object) -> str | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    return text or None


def _preview_text(value: object, *, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _looks_like_url(value: object) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _coerce_payload_kind(value: object, *, fallback: DiscordPayloadKind = DiscordPayloadKind.SELECTED_TEXT) -> DiscordPayloadKind:
    try:
        return DiscordPayloadKind(str(value or "").strip())
    except ValueError:
        return fallback


def _coerce_route_mode(value: object, *, fallback: DiscordRouteMode = DiscordRouteMode.LOCAL_CLIENT_AUTOMATION) -> DiscordRouteMode:
    try:
        return DiscordRouteMode(str(value or "").strip())
    except ValueError:
        return fallback


def _coerce_destination_kind(
    value: object,
    *,
    fallback: DiscordDestinationKind = DiscordDestinationKind.PERSONAL_DM,
) -> DiscordDestinationKind:
    try:
        return DiscordDestinationKind(str(value or "").strip())
    except ValueError:
        return fallback


def _coerce_relay_capability(value: object, *, route_mode: DiscordRouteMode) -> DiscordRelayCapability:
    if isinstance(value, DiscordRelayCapability):
        return value
    if isinstance(value, dict):
        return DiscordRelayCapability(
            route_mode=_coerce_route_mode(value.get("route_mode"), fallback=route_mode),
            preview_supported=bool(value.get("preview_supported", value.get("can_preview", True))),
            dispatch_supported=bool(value.get("dispatch_supported", value.get("can_dispatch", False))),
            verification_supported=bool(
                value.get("verification_supported", value.get("can_verify_sent_message", value.get("can_verify_send", False)))
            ),
            requires_trust_approval=bool(value.get("requires_trust_approval", True)),
            uses_discord_api_user_token=bool(
                value.get("uses_discord_api_user_token", value.get("uses_discord_user_token", False))
            ),
            uses_discord_user_token=bool(
                value.get("uses_discord_user_token", value.get("uses_discord_api_user_token", False))
            ),
            uses_self_bot=bool(value.get("uses_self_bot", False)),
            uses_local_client=bool(value.get("uses_local_client", False)),
            adapter_kind=str(value.get("adapter_kind") or "unavailable").strip().lower() or "unavailable",
            unavailable_reason=_clean_text(value.get("unavailable_reason")),
            route_constraint=str(value.get("route_constraint") or "unsupported").strip() or "unsupported",
            can_preview=bool(value.get("can_preview", value.get("preview_supported", True))),
            can_dispatch=bool(value.get("can_dispatch", value.get("dispatch_supported", False))),
            can_verify_send=bool(
                value.get("can_verify_send", value.get("can_verify_sent_message", value.get("verification_supported", False)))
            ),
            can_focus_client=bool(value.get("can_focus_client", False)),
            can_launch_client=bool(value.get("can_launch_client", False)),
            can_identify_discord_surface=bool(value.get("can_identify_discord_surface", False)),
            can_navigate_dm=bool(value.get("can_navigate_dm", False)),
            can_locate_message_input=bool(value.get("can_locate_message_input", False)),
            can_insert_text=bool(value.get("can_insert_text", False)),
            can_press_send=bool(value.get("can_press_send", False)),
            can_verify_sent_message=bool(
                value.get("can_verify_sent_message", value.get("can_verify_send", value.get("verification_supported", False)))
            ),
            can_report_failure=bool(value.get("can_report_failure", True)),
            rollback_posture=str(value.get("rollback_posture") or "none").strip() or "none",
            trust_requirements=[
                str(item)
                for item in value.get("trust_requirements", ["explicit_approval"])
                if str(item).strip()
            ],
        )
    return DiscordRelayCapability(
        route_mode=route_mode,
        preview_supported=True,
        dispatch_supported=False,
        verification_supported=False,
        requires_trust_approval=True,
        uses_discord_api_user_token=False,
        uses_self_bot=False,
        uses_local_client=False,
        adapter_kind="stub",
        unavailable_reason="adapter_does_not_declare_dispatch_capability",
    )


def _payload_source_details(payload: DiscordPayloadCandidate) -> dict[str, str]:
    if payload.provenance == "active_selection":
        if payload.kind == DiscordPayloadKind.PAGE_LINK:
            return {"label": "selected page", "strength": "strong_current"}
        if payload.kind == DiscordPayloadKind.FILE:
            return {"label": "selected file", "strength": "strong_current"}
        return {"label": "current selection", "strength": "strong_current"}
    if payload.provenance == "workspace_active_item":
        if payload.kind == DiscordPayloadKind.PAGE_LINK:
            return {"label": "current page", "strength": "strong_current"}
        if payload.kind == DiscordPayloadKind.FILE:
            return {"label": "current file", "strength": "strong_current"}
        if payload.kind == DiscordPayloadKind.NOTE_ARTIFACT:
            return {"label": "current note", "strength": "strong_current"}
        return {"label": "current active item", "strength": "strong_current"}
    if payload.provenance == "clipboard":
        return {"label": "clipboard", "strength": "supporting_hint"}
    if payload.provenance == "recent_entity":
        return {"label": "recent session artifact", "strength": "stale_artifact"}
    if payload.provenance == "operator_request":
        return {"label": "operator request", "strength": "explicit_request"}
    return {"label": "unknown source", "strength": "unknown"}


@dataclass(slots=True)
class DiscordRelaySubsystem:
    config: DiscordRelayConfig
    session_state: ConversationStateStore
    system_probe: Any | None = None
    observation_source: Any | None = None
    local_adapter: Any | None = None
    official_adapter: Any | None = None
    trust_service: Any | None = None
    clock: Callable[[], float] = time.time
    preview_ttl_seconds: float = _DEFAULT_PREVIEW_TTL_SECONDS
    duplicate_window_seconds: float = _DEFAULT_DUPLICATE_WINDOW_SECONDS
    _recent_traces: deque[DiscordRelayTrace] = field(default_factory=lambda: deque(maxlen=24), init=False)
    _recent_dispatches: dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.observation_source is None:
            self.observation_source = NativeContextObservationSource(system_probe=self.system_probe)
        if self.local_adapter is None:
            self.local_adapter = LocalDiscordClientAdapter(config=self.config, system_probe=self.system_probe)
        if self.official_adapter is None:
            self.official_adapter = OfficialDiscordScaffoldAdapter(config=self.config)

    def status_snapshot(self) -> dict[str, Any]:
        last_trace = self._recent_traces[-1].to_dict() if self._recent_traces else None
        local_capability = self._capability_for_route(DiscordRouteMode.LOCAL_CLIENT_AUTOMATION)
        official_capability = self._capability_for_route(DiscordRouteMode.OFFICIAL_BOT_WEBHOOK)
        local_diagnostic = self.local_automation_diagnostic()
        return {
            "phase": "discord1",
            "enabled": self.config.enabled,
            "planner_routing_enabled": self.config.planner_routing_enabled,
            "debug_events_enabled": self.config.debug_events_enabled,
            "screen_disambiguation_enabled": self.config.screen_disambiguation_enabled,
            "preview_before_send": self.config.preview_before_send,
            "verification_enabled": self.config.verification_enabled,
            "preview_ttl_seconds": self.preview_ttl_seconds,
            "duplicate_window_seconds": self.duplicate_window_seconds,
            "capabilities": {
                "trusted_alias_resolution": True,
                "page_link": True,
                "file_payload": True,
                "selected_text": True,
                "note_artifact_payload": True,
                "local_dm_route": self.config.local_dm_route_enabled,
                "official_bot_webhook_route": self.config.bot_webhook_routes_enabled,
                "screenshot_payload_scaffold": True,
            },
            "truthfulness_contract": {
                "preview_required": True,
                "route_mode_explicit": True,
                "no_false_delivery_claims": True,
                "screen_awareness_secondary_only": True,
                "personal_dm_uses_local_client_session": True,
                "preview_fingerprint_binding": True,
                "duplicate_send_suppression": True,
                "payload_mutation_checks": True,
            },
            "runtime_hooks": {
                "observation_source_ready": self.observation_source is not None,
                "local_adapter_ready": self.local_adapter is not None,
                "official_adapter_ready": self.official_adapter is not None,
                "system_probe_available": self.system_probe is not None,
            },
            "relay_capabilities": {
                "local_client_automation": local_capability.to_dict(),
                "official_bot_webhook": official_capability.to_dict(),
            },
            "local_automation_diagnostic": local_diagnostic,
            "recent_trace_count": len(self._recent_traces),
            "last_trace": last_trace,
        }

    def local_automation_diagnostic(self) -> dict[str, Any]:
        capability = self._capability_for_route(DiscordRouteMode.LOCAL_CLIENT_AUTOMATION)
        diagnostic_reader = getattr(self.local_adapter, "diagnostic", None)
        result: dict[str, Any] = {}
        if callable(diagnostic_reader):
            try:
                raw_result = diagnostic_reader(relay_request_id="diagnostic", recipient_alias="")
                result = raw_result.to_dict() if hasattr(raw_result, "to_dict") else dict(raw_result)
            except Exception as error:
                result = {
                    "adapter_kind": "unavailable",
                    "route_constraint": "unsupported",
                    "dispatch_supported": False,
                    "verification_supported": False,
                    "steps": [],
                    "failure_reason": str(error).strip() or "diagnostic_failed",
                }
        if not result:
            result = {
                "adapter_kind": capability.adapter_kind,
                "route_constraint": capability.route_constraint,
                "dispatch_supported": capability.dispatch_supported,
                "verification_supported": capability.verification_supported,
                "steps": [],
                "failure_reason": capability.unavailable_reason,
            }

        def support(flag: bool) -> str:
            return "supported" if flag else "unsupported"

        reason = (
            result.get("failure_reason")
            or capability.unavailable_reason
            or self._first_local_diagnostic_gap(capability)
        )
        live_dispatch_ready = bool(
            capability.adapter_kind == "real"
            and capability.dispatch_supported
            and capability.can_focus_client
            and capability.can_identify_discord_surface
            and capability.can_locate_message_input
            and capability.can_insert_text
            and capability.can_press_send
            and capability.route_constraint in {"can_navigate_to_alias_dm", "current_dm_only"}
        )
        return {
            "adapter_kind": capability.adapter_kind,
            "route_mode": DiscordRouteMode.LOCAL_CLIENT_AUTOMATION.value,
            "route_constraint": capability.route_constraint,
            "discord_surface_found": bool(result.get("target_identity_verified", False)),
            "focus_client": support(capability.can_focus_client),
            "launch_client": support(capability.can_launch_client),
            "identify_surface": support(capability.can_identify_discord_surface),
            "navigate_dm": support(capability.can_navigate_dm),
            "locate_message_input": support(capability.can_locate_message_input),
            "insert_text": support(capability.can_insert_text),
            "press_send": support(capability.can_press_send),
            "verify_message": support(capability.can_verify_sent_message),
            "dispatch_supported": capability.dispatch_supported,
            "verification_supported": capability.verification_supported,
            "live_dispatch_ready": live_dispatch_ready,
            "reason": None if live_dispatch_ready else reason,
            "steps": list(result.get("steps") or []),
        }

    def _first_local_diagnostic_gap(self, capability: DiscordRelayCapability) -> str | None:
        for name, supported in (
            ("focus_client unsupported", capability.can_focus_client),
            ("identify_surface unsupported", capability.can_identify_discord_surface),
            ("navigate_dm unsupported", capability.can_navigate_dm or capability.route_constraint == "current_dm_only"),
            ("locate_message_input unsupported", capability.can_locate_message_input),
            ("insert_text unsupported", capability.can_insert_text),
            ("press_send unsupported", capability.can_press_send),
        ):
            if not supported:
                return name
        if not capability.can_verify_sent_message:
            return "verify_message unsupported"
        return None

    def _capability_for_route(self, route_mode: DiscordRouteMode) -> DiscordRelayCapability:
        adapter = self.local_adapter if route_mode == DiscordRouteMode.LOCAL_CLIENT_AUTOMATION else self.official_adapter
        capability_reader = getattr(adapter, "capability", None)
        if callable(capability_reader):
            try:
                return _coerce_relay_capability(capability_reader(), route_mode=route_mode)
            except Exception:
                return DiscordRelayCapability(
                    route_mode=route_mode,
                    preview_supported=True,
                    dispatch_supported=False,
                    verification_supported=False,
                    requires_trust_approval=True,
                    adapter_kind="unavailable",
                    unavailable_reason="capability_probe_failed",
                )
        return _coerce_relay_capability(None, route_mode=route_mode)

    def _dispatch_capability_block(
        self,
        *,
        preview: DiscordDispatchPreview,
        capability: DiscordRelayCapability,
    ) -> dict[str, Any] | None:
        if capability.uses_discord_api_user_token or capability.uses_discord_user_token or capability.uses_self_bot:
            return {
                "state": DiscordDispatchState.DISPATCH_BLOCKED,
                "assistant_response": (
                    "Discord dispatch is blocked because that route would use an unsupported Discord API/user-token path."
                ),
                "bearing_title": "Discord Blocked",
                "micro_response": "Discord dispatch is blocked by policy.",
                "failure_reason": "discord_policy_blocked",
                "failure_step": "capability_check",
            }
        adapter_kind = str(capability.adapter_kind or "").strip().lower()
        if adapter_kind in {"mock", "stub"}:
            return {
                "state": DiscordDispatchState.DISPATCH_NOT_IMPLEMENTED,
                "assistant_response": (
                    "Discord local-client dispatch is not wired yet. I can only prepare the message right now."
                ),
                "bearing_title": "Discord Dispatch Unavailable",
                "micro_response": "Discord dispatch is not wired yet.",
                "failure_reason": capability.unavailable_reason or f"{adapter_kind}_adapter",
                "failure_step": "capability_check",
            }
        if not capability.dispatch_supported:
            return {
                "state": DiscordDispatchState.DISPATCH_UNAVAILABLE,
                "assistant_response": (
                    f"I have the message ready for {preview.destination.label}, but I cannot reach Discord/local automation."
                ),
                "bearing_title": "Discord Dispatch Unavailable",
                "micro_response": "Discord local automation is unavailable.",
                "failure_reason": capability.unavailable_reason or "dispatch_not_supported",
                "failure_step": "capability_check",
            }
        if preview.route_mode == DiscordRouteMode.LOCAL_CLIENT_AUTOMATION:
            if capability.route_constraint == "current_dm_only" and not capability.can_identify_discord_surface:
                return {
                    "state": DiscordDispatchState.DISPATCH_BLOCKED,
                    "assistant_response": (
                        f"I held the message for {preview.destination.label} because this adapter can only use the current DM "
                        "and cannot verify the active Discord recipient."
                    ),
                    "bearing_title": "Discord Blocked",
                    "micro_response": "Discord recipient verification is missing.",
                    "failure_reason": "current_dm_identity_verification_unsupported",
                    "failure_step": "navigate_recipient_dm",
                }
            required_step_capabilities = (
                ("focus_client", capability.can_focus_client),
                ("identify_discord_surface", capability.can_identify_discord_surface),
                ("locate_message_input", capability.can_locate_message_input),
                ("insert_payload", capability.can_insert_text),
                ("perform_send_gesture", capability.can_press_send),
            )
            for failure_step, declared in required_step_capabilities:
                if declared:
                    continue
                return {
                    "state": DiscordDispatchState.DISPATCH_UNAVAILABLE,
                    "assistant_response": (
                        f"I have the message ready for {preview.destination.label}, but local Discord automation "
                        f"cannot perform the {failure_step.replace('_', ' ')} step."
                    ),
                    "bearing_title": "Discord Dispatch Unavailable",
                    "micro_response": "Discord local automation is incomplete.",
                    "failure_reason": f"{failure_step}_unsupported",
                    "failure_step": failure_step,
                }
            if capability.route_constraint == "unsupported":
                return {
                    "state": DiscordDispatchState.DISPATCH_UNAVAILABLE,
                    "assistant_response": (
                        f"I have the message ready for {preview.destination.label}, but local Discord routing is unsupported."
                    ),
                    "bearing_title": "Discord Dispatch Unavailable",
                    "micro_response": "Discord local routing is unsupported.",
                    "failure_reason": "route_constraint_unsupported",
                    "failure_step": "navigate_recipient_dm",
                }
        if preview.route_mode == DiscordRouteMode.LOCAL_CLIENT_AUTOMATION and not capability.uses_local_client:
            return {
                "state": DiscordDispatchState.DISPATCH_UNAVAILABLE,
                "assistant_response": (
                    f"I have the message ready for {preview.destination.label}, but Discord local-client dispatch is not available."
                ),
                "bearing_title": "Discord Dispatch Unavailable",
                "micro_response": "Discord local-client dispatch is unavailable.",
                "failure_reason": capability.unavailable_reason or "local_client_capability_missing",
                "failure_step": "capability_check",
            }
        return None

    def handle_request(
        self,
        *,
        session_id: str,
        operator_text: str,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, Any] | None,
        workspace_context: dict[str, Any] | None = None,
        request_slots: dict[str, Any] | None = None,
    ) -> DiscordRelayResponse:
        active_context = active_context or {}
        workspace_context = workspace_context or {}
        slots = dict(request_slots or {})
        stage = str(slots.get("request_stage") or "preview").strip().lower() or "preview"
        destination_alias = _clean_text(slots.get("destination_alias"))
        note_text = _clean_text(slots.get("note_text"))
        approval_scope = str(slots.get("approval_scope") or "").strip().lower() or None
        approval_outcome = str(slots.get("approval_outcome") or "approve").strip().lower() or "approve"
        trust_request_id = str(slots.get("trust_request_id") or "").strip() or None

        if not self.config.enabled:
            return self._terminal_response(
                utterance=operator_text,
                stage=stage,
                destination_alias=destination_alias,
                state=DiscordDispatchState.FAILED,
                assistant_response="Discord relay isn't enabled in this environment.",
                bearing_title="Discord Relay Disabled",
                micro_response="Discord relay is disabled.",
            )

        if stage == "dispatch":
            pending_preview = slots.get("pending_preview") if isinstance(slots.get("pending_preview"), dict) else {}
            preview = self._preview_from_dict(pending_preview)
            if preview is None:
                return self._terminal_response(
                    utterance=operator_text,
                    stage=stage,
                    destination_alias=destination_alias,
                    state=DiscordDispatchState.DISPATCH_FAILED,
                    assistant_response="I don't have a confirmed Discord preview to send yet.",
                    bearing_title="Discord Relay Issue",
                    micro_response="No pending Discord preview is available.",
                )
            validation = self._validate_preview_for_dispatch(
                preview=preview,
                active_context=active_context,
                workspace_context=workspace_context,
            )
            if not validation["valid"]:
                if validation["reason"] == "preview_expired":
                    renewed_preview = self._renew_preview(preview)
                    payload_source = _payload_source_details(renewed_preview.payload)
                    return self._terminal_response(
                        utterance=operator_text,
                        stage=stage,
                        destination_alias=renewed_preview.destination.alias,
                        state=DiscordDispatchState.APPROVAL_EXPIRED,
                        assistant_response=(
                            f"Confirmation expired. I still have the preview for {renewed_preview.destination.label} "
                            f"using {payload_source['label']}. Send it now?"
                        ),
                        bearing_title="Discord Confirmation Expired",
                        micro_response="Confirmation expired; preview is still ready.",
                        active_request_state=self._pending_preview_request_state(renewed_preview),
                        debug={
                            **self._relay_debug_fields(
                                preview=renewed_preview,
                                capability=self._capability_for_route(renewed_preview.route_mode),
                                result_state=DiscordDispatchState.APPROVAL_EXPIRED,
                                pending_preview_found=True,
                                continuation_detected=True,
                                approval_expired=True,
                            ),
                            "request_stage": stage,
                            "invalidation_reason": validation["reason"],
                        },
                        preview=renewed_preview,
                        preview_fingerprint=str(renewed_preview.fingerprint.get("fingerprint_id") or ""),
                        invalidation_reason=str(validation["reason"]),
                    )
                return self._terminal_response(
                    utterance=operator_text,
                    stage=stage,
                    destination_alias=preview.destination.alias,
                    state=DiscordDispatchState.DISPATCH_FAILED,
                    assistant_response=self._invalidation_message(preview, str(validation["reason"])),
                    bearing_title="Discord Preview Stale",
                    micro_response="The preview must be refreshed before sending.",
                    active_request_state={},
                    debug={
                        **self._relay_debug_fields(
                            preview=preview,
                            capability=self._capability_for_route(preview.route_mode),
                            result_state=DiscordDispatchState.DISPATCH_FAILED,
                            pending_preview_found=True,
                            continuation_detected=True,
                        ),
                        "request_stage": stage,
                        "invalidation_reason": validation["reason"],
                        "preview_fingerprint": dict(preview.fingerprint),
                    },
                    preview=preview,
                    preview_fingerprint=str(preview.fingerprint.get("fingerprint_id") or ""),
                    invalidation_reason=str(validation["reason"]),
                )
            duplicate = self._check_duplicate_send(preview)
            if duplicate["blocked"]:
                return self._terminal_response(
                    utterance=operator_text,
                    stage=stage,
                    destination_alias=preview.destination.alias,
                    state=DiscordDispatchState.DISPATCH_BLOCKED,
                    assistant_response="I blocked a duplicate send attempt. Refresh the preview if you want to send it again.",
                    bearing_title="Discord Duplicate Blocked",
                    micro_response="I blocked a duplicate send attempt.",
                    active_request_state={},
                    debug={
                        "request_stage": stage,
                        "destination": preview.destination.to_dict(),
                        "preview": preview.to_dict(),
                        "duplicate_suppressed": True,
                        "duplicate_within_seconds": duplicate["within_seconds"],
                        "preview_fingerprint": dict(preview.fingerprint),
                    },
                    preview=preview,
                    preview_fingerprint=str(preview.fingerprint.get("fingerprint_id") or ""),
                    duplicate_suppressed=True,
                )
            route_contract_status = self._relay_route_contract_assessment(preview.route_mode)
            if not route_contract_status["healthy"]:
                return self._terminal_response(
                    utterance=operator_text,
                    stage=stage,
                    destination_alias=preview.destination.alias,
                    state=DiscordDispatchState.DISPATCH_BLOCKED,
                    assistant_response=(
                        "I can't continue that Discord route because it isn't valid contract-backed adapter work yet."
                    ),
                    bearing_title="Discord Route Unavailable",
                    micro_response="That Discord route isn't contract-backed right now.",
                    active_request_state={},
                    debug={
                        "request_stage": stage,
                        "destination": preview.destination.to_dict(),
                        "preview": preview.to_dict(),
                        "adapter_contract_status": route_contract_status,
                    },
                    preview=preview,
                )
            capability = self._capability_for_route(preview.route_mode)
            capability_block = self._dispatch_capability_block(preview=preview, capability=capability)
            if capability_block is not None:
                return self._terminal_response(
                    utterance=operator_text,
                    stage=stage,
                    destination_alias=preview.destination.alias,
                    state=capability_block["state"],
                    assistant_response=capability_block["assistant_response"],
                    bearing_title=capability_block["bearing_title"],
                    micro_response=capability_block["micro_response"],
                    active_request_state=self._pending_preview_request_state(preview),
                    debug={
                        **self._relay_debug_fields(
                            preview=preview,
                            capability=capability,
                            result_state=capability_block["state"],
                            pending_preview_found=True,
                            continuation_detected=True,
                            failure_reason=capability_block["failure_reason"],
                            failure_step=capability_block.get("failure_step"),
                        ),
                        "request_stage": stage,
                        "failure_reason": capability_block["failure_reason"],
                        "failure_step": capability_block.get("failure_step"),
                        "adapter_contract_status": route_contract_status,
                    },
                    preview=preview,
                )
            trust_decision = None
            if self.trust_service is not None:
                trust_request = self._trust_request(session_id=session_id, preview=preview)
                if trust_request_id:
                    trust_decision = self.trust_service.respond_to_request(
                        approval_request_id=trust_request_id,
                        decision=approval_outcome,
                        session_id=session_id,
                        scope=self._trust_scope(approval_scope),
                        task_id="",
                    )
                else:
                    trust_decision = self.trust_service.evaluate_action(trust_request)
                if trust_decision.outcome == "blocked":
                    denied = approval_outcome in {"deny", "denied", "cancel", "cancelled", "stop"}
                    return self._terminal_response(
                        utterance=operator_text,
                        stage=stage,
                        destination_alias=preview.destination.alias,
                        state=DiscordDispatchState.CANCELLED if denied else DiscordDispatchState.DISPATCH_BLOCKED,
                        assistant_response=trust_decision.operator_message,
                        bearing_title="Discord Approval Denied",
                        micro_response=trust_decision.operator_message,
                        active_request_state={},
                        debug={
                            **self._relay_debug_fields(
                                preview=preview,
                                capability=capability,
                                result_state=DiscordDispatchState.CANCELLED
                                if denied
                                else DiscordDispatchState.DISPATCH_BLOCKED,
                                pending_preview_found=True,
                                continuation_detected=True,
                                failure_reason="approval_denied" if denied else "approval_blocked",
                            ),
                            "request_stage": stage,
                            "trust": trust_decision.to_dict(),
                        },
                        preview=preview,
                    )
                if not trust_decision.allowed:
                    return self._terminal_response(
                        utterance=operator_text,
                        stage=stage,
                        destination_alias=preview.destination.alias,
                        state=DiscordDispatchState.APPROVAL_REQUIRED,
                        assistant_response=trust_decision.operator_message,
                        bearing_title="Discord Approval Needed",
                        micro_response=trust_decision.operator_message,
                        active_request_state=self.trust_service.attach_request_state(
                            self._pending_preview_request_state(preview),
                            decision=trust_decision,
                        ),
                        debug={
                            **self._relay_debug_fields(
                                preview=preview,
                                capability=capability,
                                result_state=DiscordDispatchState.APPROVAL_REQUIRED,
                                pending_preview_found=True,
                                continuation_detected=True,
                            ),
                            "request_stage": stage,
                            "trust": trust_decision.to_dict(),
                        },
                        preview=preview,
                    )
            attempt = self._normalize_attempt_for_capability(
                preview=preview,
                attempt=self._dispatch_preview(preview),
                capability=capability,
            )
            if self._attempt_performed_final_send(attempt):
                self._remember_dispatch(preview)
                if self.trust_service is not None and trust_decision is not None:
                    self.trust_service.mark_action_executed(
                        action_request=self._trust_request(session_id=session_id, preview=preview),
                        grant=trust_decision.grant,
                        summary=f"Attempted Discord relay to {preview.destination.alias}.",
                        details={"verification_strength": attempt.verification_strength},
                    )
            self.session_state.remember_alias(
                "discord_destination",
                preview.destination.alias,
                target=preview.destination.to_alias_target(),
            )
            trace = DiscordRelayTrace(
                utterance=operator_text,
                stage=stage,
                destination_alias=preview.destination.alias,
                route_mode=preview.route_mode.value,
                payload_kind=preview.payload.kind.value,
                state=attempt.state,
                policy_outcome=preview.policy.outcome,
                screen_awareness_used=preview.screen_awareness_used,
                preview_fingerprint=str(preview.fingerprint.get("fingerprint_id") or ""),
                wrong_thread_refusal=bool(attempt.debug.get("wrong_thread_refusal")),
                verification_strength=attempt.verification_strength,
            )
            self._remember_trace(trace)
            assistant_response, contract = self._dispatch_contract(preview=preview, attempt=attempt)
            return DiscordRelayResponse(
                assistant_response=assistant_response,
                response_contract=contract,
                state=attempt.state,
                preview=preview,
                attempt=attempt,
                trace=trace,
                debug={
                    **self._relay_debug_fields(
                        preview=preview,
                        capability=capability,
                        result_state=attempt.state,
                        pending_preview_found=True,
                        continuation_detected=True,
                        attempt=attempt,
                    ),
                    "request_stage": stage,
                    "attempt": attempt.to_dict(),
                    "payload_source": _payload_source_details(preview.payload),
                    "adapter_contract": dict(contract.get("adapter_contract") or {}) if isinstance(contract, dict) else {},
                    "adapter_execution": dict(contract.get("adapter_execution") or {}) if isinstance(contract, dict) else {},
                    "trust": trust_decision.to_dict() if trust_decision is not None else {},
                },
                active_request_state=self._pending_preview_request_state(preview)
                if bool(attempt.debug.get("wrong_thread_refusal"))
                else {},
            )

        destination = self._resolve_destination(destination_alias)
        if destination is None:
            unresolved_alias = destination_alias or "that destination"
            return self._terminal_response(
                utterance=operator_text,
                stage=stage,
                destination_alias=destination_alias,
                state=DiscordDispatchState.UNRESOLVED,
                assistant_response=f'I could not resolve "{unresolved_alias}" as a trusted Discord destination yet.',
                bearing_title="Discord Relay",
                micro_response="I need a trusted Discord destination alias.",
                active_request_state={},
            )
        route_contract_status = self._relay_route_contract_assessment(destination.route_mode)
        if not route_contract_status["healthy"]:
            return self._terminal_response(
                utterance=operator_text,
                stage=stage,
                destination_alias=destination.alias,
                state=DiscordDispatchState.DISPATCH_BLOCKED,
                assistant_response=(
                    f"I can't use {destination.label}'s Discord route because it isn't valid contract-backed adapter work yet."
                ),
                bearing_title="Discord Route Unavailable",
                micro_response="That Discord route isn't contract-backed right now.",
                active_request_state={},
                debug={
                    "request_stage": stage,
                    "destination": destination.to_dict(),
                    "adapter_contract_status": route_contract_status,
                },
            )

        payload_hint = str(slots.get("payload_hint") or "contextual").strip().lower() or "contextual"
        resolution = self._resolve_payload(
            operator_text=operator_text,
            session_id=session_id,
            surface_mode=surface_mode,
            active_module=active_module,
            active_context=active_context,
            workspace_context=workspace_context,
            payload_hint=payload_hint,
        )
        payload = resolution.get("payload") if isinstance(resolution.get("payload"), DiscordPayloadCandidate) else None
        if payload is None:
            candidate_summaries = list(resolution.get("candidate_summaries") or [])
            ambiguity_reason = _clean_text(resolution.get("ambiguity_reason")) or "I couldn't truthfully resolve what “this” refers to yet."
            choices = list(resolution.get("ambiguity_choices") or [])
            assistant_response = f"What should I send to {destination.label}? {ambiguity_reason}"
            if choices:
                quoted = ", ".join(f'"{item}"' for item in choices)
                assistant_response = f"{ambiguity_reason} Reply with {quoted}."
            trace = self._trace_for_resolution(
                utterance=operator_text,
                stage=stage,
                destination=destination,
                payload=None,
                state=DiscordDispatchState.UNRESOLVED,
                screen_awareness_used=bool(resolution.get("screen_awareness_used", False)),
            )
            self._remember_trace(trace)
            return DiscordRelayResponse(
                assistant_response=assistant_response,
                response_contract={
                    "bearing_title": "Discord Relay",
                    "micro_response": "I need a clearer relay target.",
                    "full_response": assistant_response,
                },
                state=DiscordDispatchState.UNRESOLVED,
                trace=trace,
                debug={
                    "request_stage": stage,
                    "destination": destination.to_dict(),
                    "payload_candidates": list(candidate_summaries),
                    "screen_awareness_used": bool(resolution.get("screen_awareness_used", False)),
                    "ambiguity_reason": ambiguity_reason,
                    "ambiguity_choices": choices,
                    "stale_candidates_suppressed": bool(resolution.get("stale_candidates_suppressed", False)),
                },
                active_request_state=self._clarification_request_state(
                    destination=destination,
                    note_text=note_text,
                    choices=choices,
                ),
            )

        policy = self._policy_for_payload(payload)
        preview = self._build_preview(
            destination=destination,
            payload=payload,
            note_text=note_text,
            policy=policy,
            active_context=active_context,
            workspace_context=workspace_context,
            candidate_summaries=list(resolution.get("candidate_summaries") or []),
        )
        trace_state = preview.state
        trace = self._trace_for_resolution(
            utterance=operator_text,
            stage=stage,
            destination=destination,
            payload=payload,
            state=trace_state,
            policy=policy,
            screen_awareness_used=preview.screen_awareness_used,
            preview_fingerprint=str(preview.fingerprint.get("fingerprint_id") or ""),
        )
        self._remember_trace(trace)
        if policy.outcome == DiscordPolicyOutcome.BLOCKED:
            assistant_response = self._policy_block_message(preview)
            return DiscordRelayResponse(
                assistant_response=assistant_response,
                response_contract={
                    "bearing_title": "Discord Relay Blocked",
                    "micro_response": "I won't send that payload.",
                    "full_response": assistant_response,
                },
                state=DiscordDispatchState.DISPATCH_BLOCKED,
                preview=preview,
                trace=trace,
                debug={
                    "request_stage": stage,
                    "destination": destination.to_dict(),
                    "preview": preview.to_dict(),
                    "payload_source": _payload_source_details(preview.payload),
                },
                active_request_state={},
            )

        self.session_state.remember_alias(
            "discord_destination",
            destination.alias,
            target=destination.to_alias_target(),
        )
        capability = self._capability_for_route(preview.route_mode)
        assistant_response, contract = self._preview_contract(preview, capability=capability)
        active_request_state = self._pending_preview_request_state(preview)
        trust_decision = None
        response_state = DiscordDispatchState.PREVIEW_READY
        if self.trust_service is not None:
            trust_decision = self.trust_service.evaluate_action(self._trust_request(session_id=session_id, preview=preview))
            active_request_state = self.trust_service.attach_request_state(active_request_state, decision=trust_decision)
            if not trust_decision.allowed:
                response_state = DiscordDispatchState.APPROVAL_REQUIRED
        return DiscordRelayResponse(
            assistant_response=self._merge_trust_prompt(
                assistant_response,
                trust_decision.operator_message if trust_decision is not None else "",
            ),
            response_contract=contract,
            state=response_state,
            preview=preview,
            trace=trace,
            debug={
                **self._relay_debug_fields(
                    preview=preview,
                    capability=capability,
                    result_state=response_state,
                    pending_preview_found=True,
                    continuation_detected=False,
                ),
                "request_stage": stage,
                "screen_awareness_used": preview.screen_awareness_used,
                "payload_candidates": list(resolution.get("candidate_summaries") or []),
                "payload_source": _payload_source_details(preview.payload),
                "adapter_contract": dict(contract.get("adapter_contract") or {}) if isinstance(contract, dict) else {},
                "adapter_execution": dict(contract.get("adapter_execution") or {}) if isinstance(contract, dict) else {},
                "trust": trust_decision.to_dict() if trust_decision is not None else {},
            },
            active_request_state=active_request_state,
        )

    def _terminal_response(
        self,
        *,
        utterance: str,
        stage: str,
        destination_alias: str | None,
        state: DiscordDispatchState,
        assistant_response: str,
        bearing_title: str,
        micro_response: str,
        active_request_state: dict[str, object] | None = None,
        debug: dict[str, Any] | None = None,
        preview: DiscordDispatchPreview | None = None,
        attempt: DiscordDispatchAttempt | None = None,
        preview_fingerprint: str | None = None,
        invalidation_reason: str | None = None,
        duplicate_suppressed: bool = False,
        wrong_thread_refusal: bool = False,
        verification_strength: str | None = None,
    ) -> DiscordRelayResponse:
        trace = DiscordRelayTrace(
            utterance=utterance,
            stage=stage,
            destination_alias=destination_alias,
            route_mode=None,
            payload_kind=None,
            state=state,
            preview_fingerprint=preview_fingerprint,
            invalidation_reason=invalidation_reason,
            duplicate_suppressed=duplicate_suppressed,
            wrong_thread_refusal=wrong_thread_refusal,
            verification_strength=verification_strength,
        )
        self._remember_trace(trace)
        return DiscordRelayResponse(
            assistant_response=assistant_response,
            response_contract={
                "bearing_title": bearing_title,
                "micro_response": micro_response,
                "full_response": assistant_response,
                "result_state": state.value,
                "sent": state in {DiscordDispatchState.SENT_UNVERIFIED, DiscordDispatchState.SENT_VERIFIED},
                "verified": state == DiscordDispatchState.SENT_VERIFIED,
            },
            state=state,
            preview=preview,
            attempt=attempt,
            trace=trace,
            debug=dict(debug or {}),
            active_request_state=active_request_state,
        )

    def _resolve_destination(self, alias: str | None) -> DiscordDestination | None:
        lookup = _clean_text(alias)
        if not lookup:
            return None
        config_match = self.config.trusted_aliases.get(lookup.lower())
        if config_match is not None:
            return DiscordDestination(
                alias=config_match.alias,
                label=config_match.label,
                destination_kind=_coerce_destination_kind(config_match.destination_kind),
                route_mode=_coerce_route_mode(config_match.route_mode),
                navigation_mode=config_match.navigation_mode,
                search_query=config_match.search_query or config_match.label,
                thread_uri=config_match.thread_uri,
                trusted=config_match.trusted,
                matched_alias=lookup.lower(),
                confidence=1.0,
            )
        session_match = self.session_state.resolve_alias("discord_destination", lookup)
        if not isinstance(session_match, dict):
            return None
        return DiscordDestination(
            alias=str(session_match.get("alias") or lookup),
            label=str(session_match.get("label") or session_match.get("alias") or lookup),
            destination_kind=_coerce_destination_kind(session_match.get("destination_kind")),
            route_mode=_coerce_route_mode(session_match.get("route_mode")),
            navigation_mode=str(session_match.get("navigation_mode") or "quick_switch"),
            search_query=_clean_text(session_match.get("search_query")) or str(session_match.get("label") or lookup),
            thread_uri=_clean_text(session_match.get("thread_uri")),
            trusted=bool(session_match.get("trusted", True)),
            matched_alias=_clean_text(session_match.get("matched_alias")) or lookup.lower(),
            confidence=float(session_match.get("confidence") or 1.0),
        )

    def _resolve_payload(
        self,
        *,
        operator_text: str,
        session_id: str,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, Any],
        workspace_context: dict[str, Any],
        payload_hint: str,
    ) -> dict[str, Any]:
        candidates = self._payload_candidates(active_context=active_context, workspace_context=workspace_context)
        filtered = self._filter_candidates(candidates, payload_hint=payload_hint, operator_text=operator_text)
        stale_candidates_suppressed = False
        if self._prefers_current_context(operator_text=operator_text, payload_hint=payload_hint):
            filtered, stale_candidates_suppressed = self._suppress_stale_recent_candidates(filtered)
        if not filtered:
            return {
                "payload": None,
                "candidate_summaries": [candidate.summary for candidate in candidates],
                "ambiguity_reason": (
                    "I only found stale session artifacts for “this,” not a current visible, active, or selected payload I can trust yet."
                    if stale_candidates_suppressed
                    else "I couldn't find a supported current page, file, selected text, or note payload to preview."
                ),
                "ambiguity_choices": [],
                "screen_awareness_used": False,
                "stale_candidates_suppressed": stale_candidates_suppressed,
            }

        chosen, ambiguous = self._choose_candidate(filtered)
        if chosen is None and self.config.screen_disambiguation_enabled and self.observation_source is not None:
            observation = self._observe_native_context(
                session_id=session_id,
                surface_mode=surface_mode,
                active_module=active_module,
                active_context=active_context,
                workspace_context=workspace_context,
            )
            if observation:
                self._apply_screen_disambiguation(filtered, observation)
                chosen, ambiguous = self._choose_candidate(filtered)
                if chosen is not None:
                    chosen.screen_awareness_used = True
        if chosen is None:
            return {
                "payload": None,
                "candidate_summaries": [candidate.summary for candidate in filtered],
                "ambiguity_reason": "I found more than one plausible payload for “this,” and I can't truthfully choose yet.",
                "ambiguity_choices": self._ambiguity_choices(filtered) if ambiguous else [],
                "screen_awareness_used": any(candidate.screen_awareness_used for candidate in filtered),
                "stale_candidates_suppressed": stale_candidates_suppressed,
            }
        return {
            "payload": chosen,
            "candidate_summaries": [candidate.summary for candidate in filtered],
            "ambiguity_reason": None,
            "ambiguity_choices": [],
            "screen_awareness_used": chosen.screen_awareness_used,
            "stale_candidates_suppressed": stale_candidates_suppressed,
        }

    def _payload_candidates(
        self,
        *,
        active_context: dict[str, Any],
        workspace_context: dict[str, Any],
    ) -> list[DiscordPayloadCandidate]:
        candidates: list[DiscordPayloadCandidate] = []
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        clipboard = active_context.get("clipboard") if isinstance(active_context.get("clipboard"), dict) else {}
        recent_entities = active_context.get("recent_entities") if isinstance(active_context.get("recent_entities"), list) else []
        active_item = workspace_context.get("active_item") if isinstance(workspace_context.get("active_item"), dict) else {}

        selection_kind = str(selection.get("kind") or "").strip().lower()
        selection_value = selection.get("value")
        if selection_kind == "url" or _looks_like_url(selection_value):
            url = str(selection_value)
            candidates.append(
                DiscordPayloadCandidate(
                    kind=DiscordPayloadKind.PAGE_LINK,
                    summary=f"Selected page link: {_preview_text(url)}",
                    provenance="active_selection",
                    confidence=0.97,
                    title=str(active_item.get("title") or "").strip() or None,
                    url=url,
                    preview_text=url,
                )
            )
        elif selection_kind in {"file_path", "paths"}:
            path_value = selection_value[0] if isinstance(selection_value, list) and selection_value else selection_value
            path_text = _clean_text(path_value)
            if path_text:
                candidates.append(
                    DiscordPayloadCandidate(
                        kind=DiscordPayloadKind.FILE,
                        summary=f"Selected file: {path_text}",
                        provenance="active_selection",
                        confidence=0.96,
                        path=path_text,
                        preview_text=path_text,
                    )
                )
        elif selection_kind in {"text", "code"}:
            selected_text = _clean_text(selection_value)
            if selected_text:
                candidates.append(
                    DiscordPayloadCandidate(
                        kind=DiscordPayloadKind.SELECTED_TEXT,
                        summary=f"Selected text: {_preview_text(selected_text)}",
                        provenance="active_selection",
                        confidence=0.95,
                        text=selected_text,
                        preview_text=_preview_text(selected_text),
                    )
                )

        note_text = self._active_note_text(active_item)
        if note_text:
            note_title = _clean_text(active_item.get("title") or active_item.get("name")) or "Current note"
            candidates.append(
                DiscordPayloadCandidate(
                    kind=DiscordPayloadKind.NOTE_ARTIFACT,
                    summary=f"Current note/artifact: {note_title}",
                    provenance="workspace_active_item",
                    confidence=0.93,
                    title=note_title,
                    text=note_text,
                    preview_text=_preview_text(note_text),
                    metadata={"kind": active_item.get("kind"), "path": active_item.get("path")},
                )
            )

        active_url = _clean_text(active_item.get("url"))
        if active_url:
            active_title = _clean_text(active_item.get("title") or active_item.get("name"))
            candidates.append(
                DiscordPayloadCandidate(
                    kind=DiscordPayloadKind.PAGE_LINK,
                    summary=f"Current page: {active_title or active_url}",
                    provenance="workspace_active_item",
                    confidence=0.9,
                    title=active_title,
                    url=active_url,
                    preview_text=_preview_text(active_url),
                )
            )

        active_path = _clean_text(active_item.get("path"))
        if active_path:
            candidates.append(
                DiscordPayloadCandidate(
                    kind=DiscordPayloadKind.FILE,
                    summary=f"Current file: {active_path}",
                    provenance="workspace_active_item",
                    confidence=0.88,
                    path=active_path,
                    preview_text=active_path,
                    metadata={"title": active_item.get("title"), "kind": active_item.get("kind")},
                )
            )

        for entity in recent_entities:
            if not isinstance(entity, dict):
                continue
            entity_url = _clean_text(entity.get("url"))
            entity_path = _clean_text(entity.get("path"))
            entity_title = _clean_text(entity.get("title") or entity.get("name"))
            if entity_url and not any(candidate.url == entity_url for candidate in candidates):
                candidates.append(
                    DiscordPayloadCandidate(
                        kind=DiscordPayloadKind.PAGE_LINK,
                        summary=f"Recent page: {entity_title or entity_url}",
                        provenance="recent_entity",
                        confidence=0.42,
                        title=entity_title,
                        url=entity_url,
                        preview_text=_preview_text(entity_url),
                    )
                )
            if entity_path and not any(candidate.path == entity_path for candidate in candidates):
                candidates.append(
                    DiscordPayloadCandidate(
                        kind=DiscordPayloadKind.FILE,
                        summary=f"Recent file: {entity_path}",
                        provenance="recent_entity",
                        confidence=0.4,
                        path=entity_path,
                        preview_text=entity_path,
                    )
                )

        clipboard_value = clipboard.get("value")
        clipboard_kind = str(clipboard.get("kind") or "").strip().lower()
        if clipboard_kind == "url" or _looks_like_url(clipboard_value):
            url = str(clipboard_value)
            if not any(candidate.url == url for candidate in candidates):
                candidates.append(
                    DiscordPayloadCandidate(
                        kind=DiscordPayloadKind.PAGE_LINK,
                        summary=f"Clipboard page link: {_preview_text(url)}",
                        provenance="clipboard",
                        confidence=0.7,
                        url=url,
                        preview_text=url,
                    )
                )
        else:
            clipboard_text = _clean_text(clipboard_value)
            if clipboard_text and not any(candidate.text == clipboard_text for candidate in candidates):
                candidates.append(
                    DiscordPayloadCandidate(
                        kind=DiscordPayloadKind.CLIPBOARD_TEXT,
                        summary=f"Clipboard text: {_preview_text(clipboard_text)}",
                        provenance="clipboard",
                        confidence=0.66,
                        text=clipboard_text,
                        preview_text=_preview_text(clipboard_text),
                    )
                )
        return candidates

    def _filter_candidates(
        self,
        candidates: list[DiscordPayloadCandidate],
        *,
        payload_hint: str,
        operator_text: str,
    ) -> list[DiscordPayloadCandidate]:
        if payload_hint == "contextual":
            if "screenshot" in operator_text.lower():
                return [
                    DiscordPayloadCandidate(
                        kind=DiscordPayloadKind.SCREENSHOT_CANDIDATE,
                        summary="Screenshot relay placeholder",
                        provenance="operator_request",
                        confidence=0.4,
                        preview_text="Screenshot capture relay is scaffolded only in this pass.",
                    ),
                    *candidates,
                ]
            return list(candidates)
        expected_kind = {
            "page_link": DiscordPayloadKind.PAGE_LINK,
            "file": DiscordPayloadKind.FILE,
            "selected_text": DiscordPayloadKind.SELECTED_TEXT,
            "note_artifact": DiscordPayloadKind.NOTE_ARTIFACT,
            "screenshot_candidate": DiscordPayloadKind.SCREENSHOT_CANDIDATE,
        }.get(payload_hint)
        filtered = [candidate for candidate in candidates if expected_kind is None or candidate.kind == expected_kind]
        if expected_kind == DiscordPayloadKind.SCREENSHOT_CANDIDATE:
            filtered.insert(
                0,
                DiscordPayloadCandidate(
                    kind=DiscordPayloadKind.SCREENSHOT_CANDIDATE,
                    summary="Screenshot relay placeholder",
                    provenance="operator_request",
                    confidence=0.9,
                    preview_text="Screenshot capture relay is scaffolded only in this pass.",
                ),
            )
        return filtered

    def _prefers_current_context(self, *, operator_text: str, payload_hint: str) -> bool:
        if payload_hint not in {"contextual", "page_link", "file", "selected_text", "note_artifact"}:
            return False
        return _PRIOR_CONTEXT_PATTERN.search(operator_text or "") is None

    def _suppress_stale_recent_candidates(
        self,
        candidates: list[DiscordPayloadCandidate],
    ) -> tuple[list[DiscordPayloadCandidate], bool]:
        filtered = [candidate for candidate in candidates if candidate.provenance != "recent_entity"]
        return filtered, len(filtered) != len(candidates)

    def _choose_candidate(
        self,
        candidates: list[DiscordPayloadCandidate],
    ) -> tuple[DiscordPayloadCandidate | None, bool]:
        ranked = sorted(candidates, key=lambda item: item.confidence, reverse=True)
        if not ranked:
            return None, False
        if len(ranked) == 1:
            return ranked[0], False
        top = ranked[0]
        runner_up = ranked[1]
        if top.kind == runner_up.kind:
            return top, False
        if (top.confidence - runner_up.confidence) >= 0.15:
            return top, False
        return None, True

    def _observe_native_context(
        self,
        *,
        session_id: str,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, Any],
        workspace_context: dict[str, Any],
    ) -> dict[str, Any]:
        observe = getattr(self.observation_source, "observe", None)
        if not callable(observe):
            return {}
        try:
            observation = observe(
                session_id=session_id,
                surface_mode=surface_mode,
                active_module=active_module,
                active_context=active_context,
                workspace_context=workspace_context,
            )
        except Exception:
            return {}
        return observation.to_dict() if hasattr(observation, "to_dict") else {}

    def _apply_screen_disambiguation(
        self,
        candidates: list[DiscordPayloadCandidate],
        observation: dict[str, Any],
    ) -> None:
        focus_metadata = observation.get("focus_metadata") if isinstance(observation.get("focus_metadata"), dict) else {}
        process_name = str(focus_metadata.get("process_name") or "").strip().lower()
        workspace_snapshot = observation.get("workspace_snapshot") if isinstance(observation.get("workspace_snapshot"), dict) else {}
        module_name = str(workspace_snapshot.get("module") or "").strip().lower()
        if process_name in _BROWSER_PROCESSES or module_name == "browser":
            for candidate in candidates:
                if candidate.kind == DiscordPayloadKind.PAGE_LINK:
                    candidate.confidence += 0.2
        if process_name in _FILE_PROCESSES or module_name in {"files", "notes", "artifacts"}:
            for candidate in candidates:
                if candidate.kind == DiscordPayloadKind.FILE:
                    candidate.confidence += 0.2
                if candidate.kind == DiscordPayloadKind.NOTE_ARTIFACT:
                    candidate.confidence += 0.16

    def _policy_for_payload(self, payload: DiscordPayloadCandidate) -> DiscordPolicyDecision:
        warnings = list(payload.warnings)
        blocks: list[str] = []
        if payload.kind == DiscordPayloadKind.SCREENSHOT_CANDIDATE:
            blocks.append("Screenshot relay is scaffolded only in this pass.")
        text_body = _clean_text(payload.text) or ""
        for pattern in _SECRET_PATTERNS:
            if text_body and pattern.search(text_body):
                blocks.append("The selected payload looks like it may contain credentials or secrets.")
                break
        if payload.kind == DiscordPayloadKind.FILE:
            if not payload.path:
                blocks.append("The selected file path is missing.")
            else:
                path = Path(payload.path)
                if not path.exists():
                    blocks.append("The selected file no longer exists on disk.")
                elif path.is_dir():
                    blocks.append("Folder relay is outside the first-pass payload contract.")
                else:
                    warnings.append("File delivery uses the local Discord client attachment path and may remain uncertain until Discord finishes processing it.")
        if payload.kind == DiscordPayloadKind.CLIPBOARD_TEXT:
            warnings.append("Clipboard text was used because a stronger native payload was not available.")
        outcome = DiscordPolicyOutcome.ALLOWED if not blocks else DiscordPolicyOutcome.BLOCKED
        return DiscordPolicyDecision(
            outcome=outcome,
            warnings=warnings,
            blocks=blocks,
            requires_confirmation=True,
        )

    def _policy_block_message(self, preview: DiscordDispatchPreview) -> str:
        reason = preview.policy.blocks[0] if preview.policy.blocks else "The payload is blocked by relay policy."
        return (
            f'I won\'t send that to {preview.destination.label} yet. {reason} '
            f"Route: {preview.route_mode.value}."
        )

    def _build_preview(
        self,
        *,
        destination: DiscordDestination,
        payload: DiscordPayloadCandidate,
        note_text: str | None,
        policy: DiscordPolicyDecision,
        active_context: dict[str, Any],
        workspace_context: dict[str, Any],
        candidate_summaries: list[str],
    ) -> DiscordDispatchPreview:
        created_at = float(self.clock())
        preview = DiscordDispatchPreview(
            destination=destination,
            payload=payload,
            route_mode=destination.route_mode,
            note_text=note_text,
            policy=policy,
            state=DiscordDispatchState.PREVIEW_READY
            if policy.outcome == DiscordPolicyOutcome.ALLOWED
            else DiscordDispatchState.DISPATCH_BLOCKED,
            screen_awareness_used=payload.screen_awareness_used,
            candidate_summaries=list(candidate_summaries),
            created_at=created_at,
            expires_at=created_at + self.preview_ttl_seconds,
        )
        preview.fingerprint = self._build_preview_fingerprint(
            preview=preview,
            active_context=active_context,
            workspace_context=workspace_context,
        )
        return preview

    def _renew_preview(self, preview: DiscordDispatchPreview) -> DiscordDispatchPreview:
        now = float(self.clock())
        preview.created_at = now
        preview.expires_at = now + self.preview_ttl_seconds
        preview.state = DiscordDispatchState.PREVIEW_READY
        return preview

    def _relay_debug_fields(
        self,
        *,
        preview: DiscordDispatchPreview,
        capability: DiscordRelayCapability,
        result_state: DiscordDispatchState,
        pending_preview_found: bool,
        continuation_detected: bool,
        attempt: DiscordDispatchAttempt | None = None,
        approval_expired: bool = False,
        failure_reason: str | None = None,
        failure_step: str | None = None,
    ) -> dict[str, Any]:
        payload_hash = str(preview.fingerprint.get("payload_hash") or "") if isinstance(preview.fingerprint, dict) else ""
        local_result = self._attempt_local_dispatch_result(attempt) if attempt is not None else {}
        dispatch_attempted = bool(attempt and self._attempt_attempted_dispatch(attempt))
        final_send_gesture = bool(attempt and self._attempt_performed_final_send(attempt))
        verification_attempted = bool(attempt and attempt.debug.get("verification_attempted"))
        message_inserted = bool(local_result.get("message_inserted") or (attempt and attempt.debug.get("message_inserted")))
        target_identity_verified = bool(
            local_result.get("target_identity_verified") or (attempt and attempt.debug.get("target_identity_verified"))
        )
        verification_evidence_present = bool(
            local_result.get("verification_evidence_present")
            or (attempt and attempt.debug.get("verification_evidence_present"))
        )
        sent_claimed = result_state in {DiscordDispatchState.SENT_UNVERIFIED, DiscordDispatchState.SENT_VERIFIED}
        verified_claimed = result_state == DiscordDispatchState.SENT_VERIFIED
        return {
            "route_family": "discord_relay",
            "route_mode": preview.route_mode.value,
            "route_constraint": local_result.get("route_constraint") or capability.route_constraint,
            "pending_relay_request_id": str(preview.fingerprint.get("fingerprint_id") or ""),
            "pending_preview_found": pending_preview_found,
            "continuation_detected": continuation_detected,
            "recipient_known": bool(preview.destination.alias),
            "recipient_alias": preview.destination.alias,
            "recipient_resolved": bool(preview.destination.trusted),
            "target_identity_verified": target_identity_verified,
            "payload_known": bool(preview.payload.preview_text or preview.payload.text or preview.payload.url or preview.payload.path),
            "payload_source": preview.payload.provenance,
            "payload_source_details": _payload_source_details(preview.payload),
            "payload_hash_present": bool(payload_hash),
            "approval_state": "expired" if approval_expired else "required" if capability.requires_trust_approval else "not_required",
            "approval_expired": approval_expired,
            "adapter_kind": capability.adapter_kind,
            "dispatch_supported": capability.dispatch_supported,
            "verification_supported": capability.verification_supported,
            "dispatch_attempted": dispatch_attempted,
            "message_inserted": message_inserted,
            "final_send_gesture_performed": final_send_gesture,
            "verification_attempted": verification_attempted,
            "verification_evidence_present": verification_evidence_present,
            "result_state": result_state.value,
            "sent_claimed": sent_claimed,
            "verified_claimed": verified_claimed,
            "openai_required": False,
            "provider_fallback_attempted": False,
            "steps": list(local_result.get("steps") or []),
            "failure_step": failure_step or local_result.get("failure_step") or (attempt.debug.get("failure_step") if attempt is not None else None),
            "failure_reason": failure_reason
            or (attempt.failure_reason if attempt is not None else None)
            or local_result.get("failure_reason"),
            "discord_relay_capability": capability.to_dict(),
            "destination": preview.destination.to_dict(),
            "preview": preview.to_dict(),
        }

    def _attempt_local_dispatch_result(self, attempt: DiscordDispatchAttempt | None) -> dict[str, Any]:
        if attempt is None:
            return {}
        value = attempt.debug.get("local_dispatch_result") if isinstance(attempt.debug, dict) else None
        return dict(value) if isinstance(value, dict) else {}

    def _attempt_attempted_dispatch(self, attempt: DiscordDispatchAttempt) -> bool:
        local_result = self._attempt_local_dispatch_result(attempt)
        if local_result:
            if bool(attempt.debug.get("dispatch_attempted")):
                return True
            if str(local_result.get("result_state") or "") == DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED.value:
                return True
            if bool(local_result.get("final_send_gesture_performed") or local_result.get("message_inserted")):
                return True
            return any(
                str(step.get("status") or "") in {"succeeded", "failed", "blocked"}
                and str(step.get("step_name") or "")
                not in {"capability_check", "focus_client", "identify_discord_surface", "navigate_recipient_dm"}
                for step in local_result.get("steps") or []
                if isinstance(step, dict)
            )
        return bool(
            attempt.debug.get("dispatch_attempted")
            or attempt.debug.get("dispatch_side_effects_emitted")
            or attempt.debug.get("send_key_issued")
            or attempt.debug.get("final_send_gesture_performed")
            or attempt.state
            in {
                DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED,
                DiscordDispatchState.SENT_UNVERIFIED,
                DiscordDispatchState.SENT_VERIFIED,
            }
        )

    def _attempt_performed_final_send(self, attempt: DiscordDispatchAttempt) -> bool:
        local_result = self._attempt_local_dispatch_result(attempt)
        if local_result:
            return bool(local_result.get("final_send_gesture_performed"))
        return bool(
            attempt.debug.get("final_send_gesture_performed")
            or attempt.debug.get("send_key_issued")
        )

    def _normalize_attempt_for_capability(
        self,
        *,
        preview: DiscordDispatchPreview,
        attempt: DiscordDispatchAttempt,
        capability: DiscordRelayCapability,
    ) -> DiscordDispatchAttempt:
        if capability.adapter_kind in {"mock", "stub"} or not capability.dispatch_supported:
            attempt.state = (
                DiscordDispatchState.DISPATCH_NOT_IMPLEMENTED
                if capability.adapter_kind in {"mock", "stub"}
                else DiscordDispatchState.DISPATCH_UNAVAILABLE
            )
            attempt.failure_reason = attempt.failure_reason or capability.unavailable_reason or "dispatch_not_supported"
            attempt.send_summary = (
                "Discord local-client dispatch is not wired yet. I can only prepare the message right now."
                if attempt.state == DiscordDispatchState.DISPATCH_NOT_IMPLEMENTED
                else f"I have the message ready for {preview.destination.label}, but I cannot reach Discord/local automation."
            )
            attempt.debug["dispatch_attempted"] = False
            attempt.debug["final_send_gesture_performed"] = False
            attempt.debug["verification_attempted"] = False
            return attempt
        local_result = self._attempt_local_dispatch_result(attempt)
        if local_result:
            result_state_text = str(local_result.get("result_state") or attempt.state.value).strip()
            try:
                result_state = DiscordDispatchState(result_state_text)
            except ValueError:
                result_state = attempt.state
            final_send_gesture = bool(local_result.get("final_send_gesture_performed"))
            verification_evidence_present = bool(local_result.get("verification_evidence_present"))
            verification_attempted = bool(local_result.get("verification_attempted"))
            failure_step = _clean_text(local_result.get("failure_step"))
            failure_reason = _clean_text(local_result.get("failure_reason"))
            attempt.debug["route_constraint"] = local_result.get("route_constraint") or capability.route_constraint
            attempt.debug["message_inserted"] = bool(local_result.get("message_inserted"))
            attempt.debug["target_identity_verified"] = bool(local_result.get("target_identity_verified"))
            attempt.debug["final_send_gesture_performed"] = final_send_gesture
            attempt.debug["dispatch_attempted"] = bool(
                attempt.debug.get("dispatch_attempted")
                or local_result.get("message_inserted")
                or final_send_gesture
                or result_state == DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED
            )
            attempt.debug["verification_attempted"] = verification_attempted
            attempt.debug["verification_evidence_present"] = verification_evidence_present
            if failure_step:
                attempt.debug["failure_step"] = failure_step
            if failure_reason:
                attempt.failure_reason = attempt.failure_reason or failure_reason
            if result_state in {DiscordDispatchState.SENT_UNVERIFIED, DiscordDispatchState.SENT_VERIFIED}:
                if not capability.can_press_send:
                    attempt.state = DiscordDispatchState.DISPATCH_UNAVAILABLE
                    attempt.failure_reason = attempt.failure_reason or "perform_send_gesture_unsupported"
                    attempt.debug["final_send_gesture_performed"] = False
                    attempt.debug["dispatch_attempted"] = False
                    return attempt
                if not final_send_gesture:
                    attempt.state = DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED
                    attempt.failure_reason = attempt.failure_reason or "send_gesture_not_performed"
                    attempt.debug["final_send_gesture_performed"] = False
                    return attempt
                if result_state == DiscordDispatchState.SENT_VERIFIED:
                    if (
                        capability.verification_supported
                        and capability.can_verify_sent_message
                        and verification_attempted
                        and verification_evidence_present
                        and attempt.verification_strength == "strong"
                    ):
                        attempt.state = DiscordDispatchState.SENT_VERIFIED
                    else:
                        attempt.state = DiscordDispatchState.SENT_UNVERIFIED
                    return attempt
                attempt.state = DiscordDispatchState.SENT_UNVERIFIED
                return attempt
            if result_state == DiscordDispatchState.DISPATCH_FAILED:
                attempt.state = DiscordDispatchState.DISPATCH_FAILED
                return attempt
            if result_state in {
                DiscordDispatchState.DISPATCH_UNAVAILABLE,
                DiscordDispatchState.DISPATCH_BLOCKED,
                DiscordDispatchState.DISPATCH_NOT_IMPLEMENTED,
                DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED,
            }:
                attempt.state = result_state
                return attempt
        if attempt.state == DiscordDispatchState.VERIFIED:
            attempt.state = (
                DiscordDispatchState.SENT_VERIFIED
                if capability.verification_supported
                and capability.can_verify_sent_message
                and attempt.verification_strength == "strong"
                else DiscordDispatchState.SENT_UNVERIFIED
            )
        elif attempt.state in {DiscordDispatchState.STARTED, DiscordDispatchState.UNCERTAIN}:
            attempt.state = (
                DiscordDispatchState.SENT_UNVERIFIED
                if self._attempt_performed_final_send(attempt)
                else DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED
            )
        elif attempt.state == DiscordDispatchState.FAILED:
            attempt.state = DiscordDispatchState.DISPATCH_FAILED
        if attempt.state == DiscordDispatchState.SENT_VERIFIED and not capability.verification_supported:
            attempt.state = DiscordDispatchState.SENT_UNVERIFIED
            attempt.verification_strength = "none"
        if attempt.state == DiscordDispatchState.SENT_VERIFIED and attempt.verification_strength != "strong":
            attempt.state = DiscordDispatchState.SENT_UNVERIFIED
        if attempt.state in {DiscordDispatchState.SENT_UNVERIFIED, DiscordDispatchState.SENT_VERIFIED} and not capability.can_press_send:
            attempt.state = DiscordDispatchState.DISPATCH_UNAVAILABLE
            attempt.failure_reason = attempt.failure_reason or "perform_send_gesture_unsupported"
            attempt.debug["final_send_gesture_performed"] = False
        if attempt.state in {DiscordDispatchState.SENT_UNVERIFIED, DiscordDispatchState.SENT_VERIFIED} and not self._attempt_performed_final_send(attempt):
            attempt.state = DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED
            attempt.failure_reason = attempt.failure_reason or "send_gesture_not_performed"
        attempt.debug.setdefault("dispatch_attempted", self._attempt_attempted_dispatch(attempt))
        attempt.debug.setdefault("final_send_gesture_performed", self._attempt_performed_final_send(attempt))
        attempt.debug.setdefault("verification_attempted", bool(capability.verification_supported))
        return attempt

    def _build_preview_fingerprint(
        self,
        *,
        preview: DiscordDispatchPreview,
        active_context: dict[str, Any],
        workspace_context: dict[str, Any],
    ) -> dict[str, Any]:
        payload_identity = self._payload_identity(preview.payload)
        payload_hash = self._payload_hash(preview.payload)
        source_anchor = self._source_anchor(
            payload=preview.payload,
            active_context=active_context,
            workspace_context=workspace_context,
        )
        payload_source = str(preview.payload.provenance or "unknown").strip() or "unknown"
        note_hash = self._stable_hash(preview.note_text or "") if preview.note_text else None
        fingerprint_id = self._stable_hash(
            {
                "destination_alias": preview.destination.alias,
                "route_mode": preview.route_mode.value,
                "payload_kind": preview.payload.kind.value,
                "payload_source": payload_source,
                "payload_identity": payload_identity,
                "payload_hash": payload_hash,
                "note_hash": note_hash,
            }
        )
        return {
            "fingerprint_id": fingerprint_id,
            "destination_alias": preview.destination.alias,
            "destination_label": preview.destination.label,
            "destination_kind": preview.destination.destination_kind.value,
            "route_mode": preview.route_mode.value,
            "payload_kind": preview.payload.kind.value,
            "payload_source": payload_source,
            "payload_identity": payload_identity,
            "payload_hash": payload_hash,
            "note_hash": note_hash,
            "source_anchor": source_anchor,
        }

    def _payload_identity(self, payload: DiscordPayloadCandidate) -> str:
        if payload.kind == DiscordPayloadKind.PAGE_LINK:
            return str(payload.url or payload.title or payload.summary)
        if payload.kind == DiscordPayloadKind.FILE:
            return str(Path(str(payload.path or "")).resolve()) if payload.path else "missing_file"
        if payload.kind == DiscordPayloadKind.NOTE_ARTIFACT:
            metadata_path = _clean_text(payload.metadata.get("path")) if isinstance(payload.metadata, dict) else None
            return metadata_path or str(payload.title or payload.summary)
        if payload.kind in {DiscordPayloadKind.SELECTED_TEXT, DiscordPayloadKind.CLIPBOARD_TEXT}:
            return f"{payload.provenance}:{payload.kind.value}"
        return str(payload.summary)

    def _payload_hash(self, payload: DiscordPayloadCandidate) -> str:
        if payload.kind == DiscordPayloadKind.FILE:
            return self._file_signature(payload.path)
        if payload.kind == DiscordPayloadKind.PAGE_LINK:
            return self._stable_hash(payload.url or "")
        if payload.kind in {
            DiscordPayloadKind.NOTE_ARTIFACT,
            DiscordPayloadKind.SELECTED_TEXT,
            DiscordPayloadKind.CLIPBOARD_TEXT,
        }:
            return self._stable_hash(payload.text or "")
        return self._stable_hash(payload.preview_text or payload.summary or "")

    def _file_signature(self, path_text: str | None) -> str:
        path_value = _clean_text(path_text)
        if not path_value:
            return "missing_file"
        try:
            path = Path(path_value).resolve()
            stat_result = path.stat()
        except OSError:
            return "missing_file"
        return f"{path}:{stat_result.st_size}:{stat_result.st_mtime_ns}"

    def _stable_hash(self, payload: object) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _source_anchor(
        self,
        *,
        payload: DiscordPayloadCandidate,
        active_context: dict[str, Any],
        workspace_context: dict[str, Any],
    ) -> dict[str, Any]:
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        clipboard = active_context.get("clipboard") if isinstance(active_context.get("clipboard"), dict) else {}
        active_item = workspace_context.get("active_item") if isinstance(workspace_context.get("active_item"), dict) else {}
        if payload.provenance == "active_selection":
            return {
                "kind": "active_selection",
                "selection_kind": _clean_text(selection.get("kind")),
                "url": _clean_text(selection.get("value")) if _looks_like_url(selection.get("value")) else None,
                "path": _clean_text(selection.get("value")) if str(selection.get("kind") or "").strip().lower() in {"file_path", "paths"} else None,
            }
        if payload.provenance == "clipboard":
            return {
                "kind": "clipboard",
                "clipboard_kind": _clean_text(clipboard.get("kind")),
                "url": _clean_text(clipboard.get("value")) if _looks_like_url(clipboard.get("value")) else None,
            }
        if payload.provenance == "recent_entity":
            return {
                "kind": "recent_entity",
                "url": payload.url,
                "path": payload.path,
            }
        return {
            "kind": "workspace_active_item",
            "active_item_kind": _clean_text(active_item.get("kind")),
            "url": _clean_text(active_item.get("url")) or payload.url,
            "path": _clean_text(active_item.get("path")) or payload.path,
            "title": _clean_text(active_item.get("title") or active_item.get("name")) or payload.title,
        }

    def _validate_preview_for_dispatch(
        self,
        *,
        preview: DiscordDispatchPreview,
        active_context: dict[str, Any],
        workspace_context: dict[str, Any],
    ) -> dict[str, Any]:
        fingerprint = preview.fingerprint if isinstance(preview.fingerprint, dict) else {}
        if not fingerprint or not fingerprint.get("fingerprint_id"):
            return {"valid": False, "reason": "preview_missing_fingerprint"}
        if preview.expires_at is not None and float(self.clock()) > float(preview.expires_at):
            return {"valid": False, "reason": "preview_expired"}

        payload = preview.payload
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        clipboard = active_context.get("clipboard") if isinstance(active_context.get("clipboard"), dict) else {}
        recent_entities = active_context.get("recent_entities") if isinstance(active_context.get("recent_entities"), list) else []
        active_item = workspace_context.get("active_item") if isinstance(workspace_context.get("active_item"), dict) else {}
        source_anchor = fingerprint.get("source_anchor") if isinstance(fingerprint.get("source_anchor"), dict) else {}
        payload_hash = str(fingerprint.get("payload_hash") or "")

        if payload.kind == DiscordPayloadKind.PAGE_LINK:
            if payload.provenance == "clipboard":
                current_url = _clean_text(clipboard.get("value"))
                if current_url != payload.url:
                    return {"valid": False, "reason": "clipboard_changed_after_preview"}
            elif payload.provenance == "active_selection":
                current_url = _clean_text(selection.get("value"))
                if current_url != payload.url:
                    return {"valid": False, "reason": "page_changed_after_preview"}
            elif payload.provenance == "recent_entity":
                if not any(_clean_text(entity.get("url")) == payload.url for entity in recent_entities if isinstance(entity, dict)):
                    return {"valid": False, "reason": "payload_candidate_changed"}
            else:
                current_url = _clean_text(active_item.get("url"))
                if current_url != payload.url:
                    return {"valid": False, "reason": "page_changed_after_preview"}

        if payload.kind == DiscordPayloadKind.FILE:
            if payload.provenance == "active_selection":
                selection_value = selection.get("value")
                current_path = selection_value[0] if isinstance(selection_value, list) and selection_value else selection_value
                if _clean_text(current_path) != payload.path:
                    return {"valid": False, "reason": "file_changed_after_preview"}
            elif payload.provenance == "recent_entity":
                if not any(_clean_text(entity.get("path")) == payload.path for entity in recent_entities if isinstance(entity, dict)):
                    return {"valid": False, "reason": "payload_candidate_changed"}
            else:
                current_path = _clean_text(active_item.get("path")) or _clean_text(source_anchor.get("path"))
                if current_path != payload.path:
                    return {"valid": False, "reason": "file_changed_after_preview"}
            current_signature = self._file_signature(payload.path)
            if current_signature == "missing_file":
                return {"valid": False, "reason": "file_missing_after_preview"}
            if payload_hash and current_signature != payload_hash:
                return {"valid": False, "reason": "file_changed_after_preview"}

        if payload.kind == DiscordPayloadKind.CLIPBOARD_TEXT:
            current_text = _clean_text(clipboard.get("value")) or ""
            if self._stable_hash(current_text) != payload_hash:
                return {"valid": False, "reason": "clipboard_changed_after_preview"}

        if payload.kind == DiscordPayloadKind.SELECTED_TEXT:
            current_text = _clean_text(selection.get("value")) or ""
            if self._stable_hash(current_text) != payload_hash:
                return {"valid": False, "reason": "selected_text_changed_after_preview"}

        if payload.kind == DiscordPayloadKind.NOTE_ARTIFACT:
            current_path = _clean_text(active_item.get("path")) or _clean_text(source_anchor.get("path"))
            expected_path = _clean_text(source_anchor.get("path")) or _clean_text(payload.metadata.get("path"))
            if expected_path and current_path and current_path != expected_path:
                return {"valid": False, "reason": "note_changed_after_preview"}
            current_note = self._active_note_text(active_item) or ""
            if self._stable_hash(current_note) != payload_hash:
                return {"valid": False, "reason": "note_changed_after_preview"}

        return {"valid": True, "reason": None}

    def _invalidation_message(self, preview: DiscordDispatchPreview, reason: str) -> str:
        if reason in {"preview_expired", "preview_missing_fingerprint"}:
            return "The preview is stale now. I need to refresh it before sending."
        if reason == "clipboard_changed_after_preview":
            return "The preview is stale now. The clipboard changed after preview, so I stopped before sending."
        if reason == "file_missing_after_preview":
            return "The file disappeared after preview, so I stopped before sending."
        if reason == "file_changed_after_preview":
            return "The file changed after preview, so I stopped before sending."
        if reason == "note_changed_after_preview":
            return "The note changed after preview, so I stopped before sending."
        if reason == "selected_text_changed_after_preview":
            return "The selected text changed after preview, so I stopped before sending."
        if reason == "page_changed_after_preview":
            return "The preview is stale now. The page changed after preview, so I stopped before sending."
        return f"The preview for {preview.destination.label} is stale now. I need to refresh it before sending."

    def _check_duplicate_send(self, preview: DiscordDispatchPreview) -> dict[str, Any]:
        now = float(self.clock())
        expired = [
            fingerprint
            for fingerprint, last_sent_at in self._recent_dispatches.items()
            if (now - last_sent_at) > self.duplicate_window_seconds
        ]
        for fingerprint in expired:
            self._recent_dispatches.pop(fingerprint, None)
        fingerprint_id = str(preview.fingerprint.get("fingerprint_id") or "")
        if not fingerprint_id:
            return {"blocked": False, "within_seconds": None}
        last_sent_at = self._recent_dispatches.get(fingerprint_id)
        if last_sent_at is None:
            return {"blocked": False, "within_seconds": None}
        elapsed = now - last_sent_at
        return {"blocked": elapsed <= self.duplicate_window_seconds, "within_seconds": round(elapsed, 2)}

    def _remember_dispatch(self, preview: DiscordDispatchPreview) -> None:
        fingerprint_id = str(preview.fingerprint.get("fingerprint_id") or "")
        if fingerprint_id:
            self._recent_dispatches[fingerprint_id] = float(self.clock())

    def _preview_contract(
        self,
        preview: DiscordDispatchPreview,
        *,
        capability: DiscordRelayCapability,
    ) -> tuple[str, dict[str, Any]]:
        payload_line = self._payload_summary_line(preview.payload)
        payload_source = _payload_source_details(preview.payload)
        warning_text = ""
        if preview.policy.warnings:
            warning_text = " Warning: " + " ".join(preview.policy.warnings)
        capability_warning = ""
        capability_block = self._dispatch_capability_block(preview=preview, capability=capability)
        if capability_block is not None:
            capability_warning = " Discord local-client dispatch is not available yet; I can only prepare the message right now."
        assistant_response = (
            f"Ready to send {payload_line} to {preview.destination.label}. "
            f"Source: {payload_source['label']}. "
            f"Route: {preview.route_mode.value}. "
            f"I haven't sent anything yet. Reply \"send it\" to continue.{capability_warning}{warning_text}"
        )
        contract = self._adapter_contract_for_route(preview.route_mode)
        execution = build_execution_report(
            contract,
            success=True,
            observed_outcome=ClaimOutcome.PREVIEW,
            evidence=["Built a relay preview without sending anything."],
        )
        return assistant_response, attach_contract_metadata(
            {
                "bearing_title": "Discord Preview",
                "micro_response": f"Ready to send to {preview.destination.label}.",
                "full_response": assistant_response,
                "result_state": DiscordDispatchState.PREVIEW_READY.value,
                "sent": False,
                "verified": False,
                "dispatch_attempted": False,
                "adapter_kind": capability.adapter_kind,
                "dispatch_supported": capability.dispatch_supported,
                "verification_supported": capability.verification_supported,
            },
            contract=contract,
            execution=execution,
        )

    def _dispatch_contract(
        self,
        *,
        preview: DiscordDispatchPreview,
        attempt: DiscordDispatchAttempt,
    ) -> tuple[str, dict[str, Any]]:
        evidence = " ".join(attempt.verification_evidence[:2]).strip()
        transport_failure_kind = _clean_text(attempt.debug.get("transport_failure_kind"))
        if attempt.state == DiscordDispatchState.SENT_VERIFIED:
            assistant_response = (
                f"Sent to {preview.destination.label}. I verified that the message appears in the target Discord thread. "
                f"Route: {attempt.route_mode.value}. {evidence}".strip()
            )
            title = "Discord Verified"
            micro = f"Sent to {preview.destination.label}."
        elif attempt.state == DiscordDispatchState.SENT_UNVERIFIED:
            assistant_response = (
                f"I performed the send action in Discord for {preview.destination.label}, but I could not verify that it appeared. "
                f"Route: {attempt.route_mode.value}. {evidence}".strip()
            )
            title = "Discord Unverified"
            micro = f"Discord send action performed for {preview.destination.label}; not verified."
        elif attempt.state == DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED:
            assistant_response = (
                f"I attempted the Discord dispatch to {preview.destination.label}, but I could not verify a final send. "
                f"Route: {attempt.route_mode.value}. {evidence}".strip()
            )
            title = "Discord Attempted"
            micro = f"Discord dispatch attempt to {preview.destination.label} is unverified."
        elif attempt.state == DiscordDispatchState.DISPATCH_NOT_IMPLEMENTED:
            assistant_response = (
                "Discord local-client dispatch is not wired yet. I can only prepare the message right now. "
                f"Route: {attempt.route_mode.value}."
            )
            title = "Discord Dispatch Unavailable"
            micro = "Discord dispatch is not wired yet."
        elif attempt.state == DiscordDispatchState.DISPATCH_UNAVAILABLE:
            assistant_response = (
                f"I have the message ready for {preview.destination.label}, but I cannot reach Discord/local automation. "
                f"Route: {attempt.route_mode.value}."
            )
            title = "Discord Dispatch Unavailable"
            micro = "Discord local automation is unavailable."
        elif attempt.state == DiscordDispatchState.DISPATCH_BLOCKED:
            assistant_response = (
                f"Discord dispatch to {preview.destination.label} is blocked. "
                f"Route: {attempt.route_mode.value}. {attempt.failure_reason or ''}".strip()
            )
            title = "Discord Blocked"
            micro = f"Discord dispatch to {preview.destination.label} is blocked."
        else:
            if bool(attempt.debug.get("wrong_thread_refusal")):
                assistant_response = (
                    f"I opened Discord, but I could not verify {preview.destination.label}'s thread safely enough to send. "
                    f"Route: {attempt.route_mode.value}."
                )
                title = "Discord Failed"
                micro = f"Discord dispatch to {preview.destination.label} stopped."
            elif attempt.send_summary and not self._send_summary_overclaims_success(attempt.send_summary):
                assistant_response = f"{attempt.send_summary} Route: {attempt.route_mode.value}."
                if transport_failure_kind:
                    assistant_response += f" Transport failure: {transport_failure_kind}."
                    title = "Discord Transport Issue"
                    micro = f"Transport issue prevented sending to {preview.destination.label}."
                else:
                    title = "Discord Failed"
                    micro = f"Failed to send to {preview.destination.label}."
            else:
                reason = _clean_text(attempt.failure_reason) or "The relay attempt failed."
                assistant_response = (
                    f"Discord dispatch to {preview.destination.label} stopped. "
                    f"Route: {attempt.route_mode.value}. {reason}"
                )
                title = "Discord Failed"
                micro = f"Failed to send to {preview.destination.label}."
        contract = self._adapter_contract_for_route(attempt.route_mode)
        observed_outcome = ClaimOutcome.NONE
        if attempt.state == DiscordDispatchState.SENT_VERIFIED:
            observed_outcome = claim_outcome_from_verification_strength(attempt.verification_strength)
        elif attempt.state in {
            DiscordDispatchState.SENT_UNVERIFIED,
            DiscordDispatchState.DISPATCH_ATTEMPTED_UNVERIFIED,
        }:
            observed_outcome = ClaimOutcome.INITIATED
        execution = build_execution_report(
            contract,
            success=attempt.state in {DiscordDispatchState.SENT_VERIFIED, DiscordDispatchState.SENT_UNVERIFIED},
            observed_outcome=observed_outcome,
            evidence=list(attempt.verification_evidence[:3]),
            verification_observed=attempt.verification_strength,
            failure_kind=transport_failure_kind or attempt.failure_reason,
        )
        return assistant_response, attach_contract_metadata(
            {
                "bearing_title": title,
                "micro_response": micro,
                "full_response": assistant_response,
                "result_state": attempt.state.value,
                "sent": attempt.state in {DiscordDispatchState.SENT_UNVERIFIED, DiscordDispatchState.SENT_VERIFIED},
                "verified": attempt.state == DiscordDispatchState.SENT_VERIFIED,
                "dispatch_attempted": self._attempt_attempted_dispatch(attempt),
                "final_send_gesture_performed": self._attempt_performed_final_send(attempt),
            },
            contract=contract,
            execution=execution,
        )

    def _send_summary_overclaims_success(self, summary: str | None) -> bool:
        text = str(summary or "").strip().lower()
        if not text:
            return False
        blocked_phrases = (
            "sent to",
            "message sent",
            "i sent",
            "delivered",
            "delivery verified",
            "verified delivery",
            "succeeded",
            "successfully sent",
            "completed the send",
            "completed the dispatch",
        )
        return any(phrase in text for phrase in blocked_phrases)

    def _adapter_contract_for_route(self, route_mode: DiscordRouteMode) -> Any:
        assessment = self._relay_route_contract_assessment(route_mode)
        contract = assessment.get("contract")
        if assessment.get("healthy") and contract is not None:
            return contract
        route_name = route_mode.value if isinstance(route_mode, DiscordRouteMode) else str(route_mode or "unknown")
        raise ValueError(
            f"Discord route '{route_name}' is unavailable because it is not backed by a valid adapter contract."
        )

    def _relay_route_contract_assessment(self, route_mode: DiscordRouteMode) -> dict[str, Any]:
        registry = default_adapter_contract_registry()
        adapter_id = "relay.discord_local_client"
        if route_mode != DiscordRouteMode.LOCAL_CLIENT_AUTOMATION:
            adapter_id = "relay.discord_official_scaffold"
        try:
            contract = registry.get_contract(adapter_id)
        except KeyError:
            return {
                "contract_required": True,
                "healthy": False,
                "route_mode": route_mode.value,
                "adapter_id": adapter_id,
                "errors": [
                    f"Discord route '{route_mode.value}' selected undeclared adapter contract '{adapter_id}'."
                ],
            }
        return {
            "contract_required": True,
            "healthy": True,
            "route_mode": route_mode.value,
            "adapter_id": adapter_id,
            "errors": [],
            "contract": contract,
        }

    def _dispatch_preview(self, preview: DiscordDispatchPreview) -> DiscordDispatchAttempt:
        if preview.route_mode == DiscordRouteMode.LOCAL_CLIENT_AUTOMATION:
            return self.local_adapter.send(destination=preview.destination, preview=preview)
        return self.official_adapter.send(destination=preview.destination, preview=preview)

    def _payload_summary_line(self, payload: DiscordPayloadCandidate) -> str:
        if payload.kind == DiscordPayloadKind.PAGE_LINK:
            return f'the page link "{payload.title or payload.url or "current page"}"'
        if payload.kind == DiscordPayloadKind.FILE:
            return f'the file "{payload.path or "current file"}"'
        if payload.kind == DiscordPayloadKind.NOTE_ARTIFACT:
            return f'the note/artifact "{payload.title or "current note"}"'
        if payload.kind == DiscordPayloadKind.SCREENSHOT_CANDIDATE:
            return "the requested screenshot payload"
        if payload.kind == DiscordPayloadKind.CLIPBOARD_TEXT:
            return "the clipboard text"
        return "the selected text"

    def _pending_preview_request_state(self, preview: DiscordDispatchPreview) -> dict[str, object]:
        return {
            "family": "discord_relay",
            "subject": preview.destination.alias,
            "request_type": "discord_relay_dispatch",
            "query_shape": "discord_relay_request",
            "route": {
                "tool_name": "",
                "response_mode": "action_result",
                "route_mode": preview.route_mode.value,
            },
            "parameters": {
                "destination_alias": preview.destination.alias,
                "payload_hint": preview.payload.kind.value,
                "note_text": preview.note_text,
                "request_stage": "preview",
                "pending_preview": preview.to_dict(),
                "pending_relay_request_id": str(preview.fingerprint.get("fingerprint_id") or ""),
                "result_state": DiscordDispatchState.PREVIEW_READY.value,
            },
        }

    def _trust_request(self, *, session_id: str, preview: DiscordDispatchPreview) -> TrustActionRequest:
        return TrustActionRequest(
            request_id=f"discord-{preview.destination.alias}-{preview.fingerprint.get('fingerprint_id') or 'preview'}",
            family="discord_relay",
            action_key="discord_relay.dispatch",
            subject=preview.destination.alias,
            session_id=session_id,
            action_kind=TrustActionKind.DISCORD_RELAY,
            approval_required=True,
            preview_allowed=True,
            suggested_scope=PermissionScope.ONCE,
            available_scopes=[PermissionScope.ONCE, PermissionScope.SESSION],
            operator_justification=(
                f"Dispatching to {preview.destination.alias} may send material outside Stormhelm's local workspace."
            ),
            operator_message=(
                f"Approval is required before Stormhelm sends this to {preview.destination.alias}. Choose once or session."
            ),
            verification_label="Relay delivery claims remain explicit and bounded by verification strength.",
            details={
                "destination_alias": preview.destination.alias,
                "payload_kind": preview.payload.kind.value,
                "route_mode": preview.route_mode.value,
                "preview_fingerprint": str(preview.fingerprint.get("fingerprint_id") or ""),
            },
        )

    def _trust_scope(self, value: str | None) -> PermissionScope | None:
        normalized = str(value or "").strip().lower()
        if normalized == PermissionScope.SESSION.value:
            return PermissionScope.SESSION
        if normalized == PermissionScope.ONCE.value:
            return PermissionScope.ONCE
        return None

    def _merge_trust_prompt(self, message: str, trust_prompt: str) -> str:
        text = str(message or "").strip()
        prompt = str(trust_prompt or "").strip()
        if not prompt or prompt in text:
            return text
        return f"{text} {prompt}".strip()

    def _clarification_request_state(
        self,
        *,
        destination: DiscordDestination,
        note_text: str | None,
        choices: list[str],
    ) -> dict[str, object]:
        return {
            "family": "discord_relay",
            "subject": destination.alias,
            "request_type": "discord_relay_dispatch",
            "query_shape": "discord_relay_request",
            "route": {
                "tool_name": "",
                "response_mode": "action_result",
                "route_mode": destination.route_mode.value,
            },
            "parameters": {
                "destination_alias": destination.alias,
                "note_text": note_text,
                "request_stage": "clarify_payload",
                "ambiguity_choices": choices,
            },
        }

    def _trace_for_resolution(
        self,
        *,
        utterance: str,
        stage: str,
        destination: DiscordDestination,
        payload: DiscordPayloadCandidate | None,
        state: DiscordDispatchState,
        policy: DiscordPolicyDecision | None = None,
        screen_awareness_used: bool = False,
        preview_fingerprint: str | None = None,
    ) -> DiscordRelayTrace:
        return DiscordRelayTrace(
            utterance=utterance,
            stage=stage,
            destination_alias=destination.alias,
            route_mode=destination.route_mode.value,
            payload_kind=payload.kind.value if payload is not None else None,
            state=state,
            policy_outcome=policy.outcome if policy is not None else None,
            screen_awareness_used=screen_awareness_used,
            preview_fingerprint=preview_fingerprint,
        )

    def _ambiguity_choices(self, candidates: list[DiscordPayloadCandidate]) -> list[str]:
        ordered: list[str] = []
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            if candidate.kind == DiscordPayloadKind.PAGE_LINK and "page" not in ordered:
                ordered.append("page")
            elif candidate.kind == DiscordPayloadKind.FILE and "file" not in ordered:
                ordered.append("file")
            elif candidate.kind in {DiscordPayloadKind.SELECTED_TEXT, DiscordPayloadKind.CLIPBOARD_TEXT} and "text" not in ordered:
                ordered.append("text")
            elif candidate.kind == DiscordPayloadKind.NOTE_ARTIFACT and "note" not in ordered:
                ordered.append("note")
            elif candidate.kind == DiscordPayloadKind.SCREENSHOT_CANDIDATE and "screenshot" not in ordered:
                ordered.append("screenshot")
        return ordered[:4]

    def _active_note_text(self, active_item: dict[str, Any]) -> str | None:
        for key in ("content", "body", "text", "excerpt", "summary"):
            note_text = _clean_text(active_item.get(key))
            if note_text:
                return note_text
        return None

    def _preview_from_dict(self, payload: dict[str, Any]) -> DiscordDispatchPreview | None:
        if not payload:
            return None
        destination_data = payload.get("destination") if isinstance(payload.get("destination"), dict) else {}
        payload_data = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        policy_data = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
        if not destination_data or not payload_data:
            return None
        return DiscordDispatchPreview(
            destination=DiscordDestination(
                alias=str(destination_data.get("alias") or ""),
                label=str(destination_data.get("label") or destination_data.get("alias") or ""),
                destination_kind=_coerce_destination_kind(destination_data.get("destination_kind")),
                route_mode=_coerce_route_mode(destination_data.get("route_mode")),
                navigation_mode=str(destination_data.get("navigation_mode") or "quick_switch"),
                search_query=_clean_text(destination_data.get("search_query")),
                thread_uri=_clean_text(destination_data.get("thread_uri")),
                trusted=bool(destination_data.get("trusted", True)),
                matched_alias=_clean_text(destination_data.get("matched_alias")),
                confidence=float(destination_data.get("confidence") or 1.0),
            ),
            payload=DiscordPayloadCandidate(
                kind=_coerce_payload_kind(payload_data.get("kind")),
                summary=str(payload_data.get("summary") or ""),
                provenance=str(payload_data.get("provenance") or ""),
                confidence=float(payload_data.get("confidence") or 0.0),
                title=_clean_text(payload_data.get("title")),
                url=_clean_text(payload_data.get("url")),
                path=_clean_text(payload_data.get("path")),
                text=_clean_text(payload_data.get("text")),
                preview_text=_clean_text(payload_data.get("preview_text")),
                metadata=dict(payload_data.get("metadata") or {}) if isinstance(payload_data.get("metadata"), dict) else {},
                warnings=list(payload_data.get("warnings") or []),
                screen_awareness_used=bool(payload_data.get("screen_awareness_used", False)),
            ),
            route_mode=_coerce_route_mode(payload.get("route_mode")),
            note_text=_clean_text(payload.get("note_text")),
            policy=DiscordPolicyDecision(
                outcome=DiscordPolicyOutcome(str(policy_data.get("outcome") or DiscordPolicyOutcome.ALLOWED.value)),
                warnings=list(policy_data.get("warnings") or []),
                blocks=list(policy_data.get("blocks") or []),
                requires_confirmation=bool(policy_data.get("requires_confirmation", True)),
            ),
            state=DiscordDispatchState(str(payload.get("state") or DiscordDispatchState.READY.value)),
            screen_awareness_used=bool(payload.get("screen_awareness_used", False)),
            ambiguity_reason=_clean_text(payload.get("ambiguity_reason")),
            candidate_summaries=list(payload.get("candidate_summaries") or []),
            fingerprint=dict(payload.get("fingerprint") or {}) if isinstance(payload.get("fingerprint"), dict) else {},
            created_at=float(payload.get("created_at")) if payload.get("created_at") not in {None, ""} else None,
            expires_at=float(payload.get("expires_at")) if payload.get("expires_at") not in {None, ""} else None,
        )

    def _remember_trace(self, trace: DiscordRelayTrace) -> None:
        self._recent_traces.append(trace)


def build_discord_relay_subsystem(
    config: DiscordRelayConfig,
    *,
    session_state: ConversationStateStore,
    system_probe: Any | None = None,
    observation_source: Any | None = None,
    local_adapter: Any | None = None,
    official_adapter: Any | None = None,
    trust_service: Any | None = None,
    clock: Callable[[], float] | None = None,
) -> DiscordRelaySubsystem:
    return DiscordRelaySubsystem(
        config=config,
        session_state=session_state,
        system_probe=system_probe,
        observation_source=observation_source,
        local_adapter=local_adapter,
        official_adapter=official_adapter,
        trust_service=trust_service,
        clock=clock or time.time,
    )
