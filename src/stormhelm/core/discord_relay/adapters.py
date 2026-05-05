from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import os
import platform
import time
from typing import Any, Callable

from stormhelm.config.models import DiscordRelayConfig
from stormhelm.core.discord_relay.models import (
    DiscordDispatchAttempt,
    DiscordDispatchPreview,
    DiscordDispatchState,
    DiscordLocalDispatchResult,
    DiscordLocalDispatchStep,
    DiscordLocalDispatchStepName,
    DiscordLocalDispatchStepStatus,
    DiscordPayloadKind,
    DiscordRelayCapability,
    DiscordRouteMode,
)
from stormhelm.core.screen_awareness.action import WindowsNativeActionExecutor


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", _POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


class WindowsClipboardBridge:
    _CF_UNICODETEXT = 13
    _CF_HDROP = 15
    _GMEM_MOVEABLE = 0x0002
    _GMEM_ZEROINIT = 0x0040

    def set_text(self, value: str) -> None:
        payload = str(value or "")
        raw = payload.encode("utf-16le") + b"\x00\x00"
        self._set_clipboard_data(self._CF_UNICODETEXT, raw)

    def set_file_paths(self, paths: list[str]) -> None:
        normalized = [str(path).strip() for path in paths if str(path).strip()]
        if not normalized:
            raise ValueError("missing_file_paths")
        joined = ("\0".join(normalized) + "\0\0").encode("utf-16le")
        struct = _DROPFILES()
        struct.pFiles = ctypes.sizeof(_DROPFILES)
        struct.fWide = 1
        raw = ctypes.string_at(ctypes.addressof(struct), ctypes.sizeof(_DROPFILES)) + joined
        self._set_clipboard_data(self._CF_HDROP, raw)

    def _set_clipboard_data(self, clipboard_format: int, raw: bytes) -> None:
        if platform.system().strip().lower() != "windows":
            raise RuntimeError("unsupported_platform")
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        if not user32.OpenClipboard(None):
            raise RuntimeError("clipboard_open_failed")
        handle = None
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(self._GMEM_MOVEABLE | self._GMEM_ZEROINIT, len(raw))
            if not handle:
                raise RuntimeError("clipboard_allocation_failed")
            locked = kernel32.GlobalLock(handle)
            if not locked:
                raise RuntimeError("clipboard_lock_failed")
            try:
                ctypes.memmove(locked, raw, len(raw))
            finally:
                kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(clipboard_format, handle):
                raise RuntimeError("clipboard_set_failed")
            handle = None
        finally:
            if handle:
                kernel32.GlobalFree(handle)
            user32.CloseClipboard()


class WindowsDiscordAutomationDriver:
    def __init__(self, executor: WindowsNativeActionExecutor | None = None) -> None:
        self.executor = executor or WindowsNativeActionExecutor()

    def hotkey(self, sequence: list[str]) -> None:
        self.executor._press_hotkey(list(sequence))

    def key(self, key_name: str) -> None:
        self.executor._press_key(str(key_name or "").strip().lower())

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def submit_navigation(self) -> None:
        self.key("enter")

    def submit_send(self) -> None:
        self.key("enter")


def _normalize_text(value: object) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


@dataclass(slots=True)
class LocalDiscordClientAdapter:
    config: DiscordRelayConfig
    system_probe: Any | None = None
    clipboard: Any | None = None
    driver: Any | None = None
    open_target: Callable[[str], None] | None = None
    route_settle_seconds: float = 0.65
    compose_settle_seconds: float = 0.22

    def __post_init__(self) -> None:
        if self.clipboard is None:
            self.clipboard = WindowsClipboardBridge()
        if self.driver is None:
            self.driver = WindowsDiscordAutomationDriver()
        if self.open_target is None:
            self.open_target = getattr(os, "startfile", None)

    def capability(self) -> DiscordRelayCapability:
        can_launch_client = callable(self.open_target)
        can_focus_client = bool(
            callable(getattr(self.system_probe, "app_control", None))
            or can_launch_client
        )
        can_identify_discord_surface = bool(
            callable(getattr(self.system_probe, "window_status", None))
        )
        can_navigate_dm = bool(
            callable(getattr(self.clipboard, "set_text", None))
            and callable(getattr(self.driver, "hotkey", None))
            and callable(getattr(self.driver, "sleep", None))
            and (
                callable(getattr(self.driver, "submit_navigation", None))
                or callable(getattr(self.driver, "key", None))
            )
        )
        can_insert_text = bool(
            callable(getattr(self.clipboard, "set_text", None))
            and callable(getattr(self.driver, "hotkey", None))
        )
        can_press_send = bool(
            callable(getattr(self.driver, "submit_send", None))
            or callable(getattr(self.driver, "key", None))
        )
        can_locate_message_input = bool(
            can_identify_discord_surface
            and can_insert_text
        )
        verification_supported = bool(
            self.config.verification_enabled
            and callable(getattr(self.system_probe, "discord_relay_verification", None))
        )
        unavailable_reason = None
        if not self.config.local_dm_route_enabled:
            unavailable_reason = "local_dm_route_disabled"
        elif platform.system().strip().lower() != "windows":
            unavailable_reason = "unsupported_platform"
        elif not can_launch_client:
            unavailable_reason = "route_launcher_unavailable"
        elif not can_identify_discord_surface:
            unavailable_reason = "discord_surface_identification_unavailable"
        elif not (can_focus_client and can_insert_text and can_press_send):
            unavailable_reason = "local_client_automation_incomplete"
        elif not can_navigate_dm and can_identify_discord_surface:
            unavailable_reason = None
        route_constraint = "unsupported"
        if can_navigate_dm:
            route_constraint = "can_navigate_to_alias_dm"
        elif can_identify_discord_surface and can_insert_text and can_press_send:
            route_constraint = "current_dm_only"
        dispatch_supported = unavailable_reason is None
        return DiscordRelayCapability(
            route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
            preview_supported=True,
            dispatch_supported=dispatch_supported,
            verification_supported=verification_supported,
            requires_trust_approval=True,
            uses_discord_api_user_token=False,
            uses_discord_user_token=False,
            uses_self_bot=False,
            uses_local_client=dispatch_supported,
            adapter_kind="real" if dispatch_supported else "unavailable",
            unavailable_reason=unavailable_reason,
            route_constraint=route_constraint,
            can_preview=True,
            can_dispatch=dispatch_supported,
            can_verify_send=verification_supported,
            can_focus_client=can_focus_client,
            can_launch_client=can_launch_client,
            can_identify_discord_surface=can_identify_discord_surface,
            can_navigate_dm=can_navigate_dm,
            can_locate_message_input=can_locate_message_input,
            can_insert_text=can_insert_text,
            can_press_send=can_press_send,
            can_verify_sent_message=verification_supported,
            can_report_failure=True,
            rollback_posture="none",
            trust_requirements=["explicit_approval", "trusted_alias", "preview_fingerprint"],
        )

    def diagnostic(self, *, relay_request_id: str = "diagnostic", recipient_alias: str = "") -> DiscordLocalDispatchResult:
        capability = self.capability()
        steps = [
            self._make_step(
                relay_request_id=relay_request_id,
                step_name=DiscordLocalDispatchStepName.CAPABILITY_CHECK,
                status=DiscordLocalDispatchStepStatus.SUCCEEDED
                if capability.dispatch_supported
                else DiscordLocalDispatchStepStatus.UNSUPPORTED,
                capability_required="can_dispatch",
                capability_declared=capability.dispatch_supported,
                evidence_summary=capability.unavailable_reason or "Runtime capability report generated.",
                safe_to_continue=capability.dispatch_supported,
            ),
            self._diagnostic_capability_step(
                relay_request_id,
                DiscordLocalDispatchStepName.FOCUS_CLIENT,
                "can_focus_client",
                capability.can_focus_client,
            ),
            self._diagnostic_capability_step(
                relay_request_id,
                DiscordLocalDispatchStepName.IDENTIFY_DISCORD_SURFACE,
                "can_identify_discord_surface",
                capability.can_identify_discord_surface,
            ),
            self._diagnostic_capability_step(
                relay_request_id,
                DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM,
                "can_navigate_dm",
                capability.can_navigate_dm,
            ),
            self._diagnostic_capability_step(
                relay_request_id,
                DiscordLocalDispatchStepName.LOCATE_MESSAGE_INPUT,
                "can_locate_message_input",
                capability.can_locate_message_input,
            ),
            self._diagnostic_capability_step(
                relay_request_id,
                DiscordLocalDispatchStepName.INSERT_PAYLOAD,
                "can_insert_text",
                capability.can_insert_text,
            ),
            self._diagnostic_capability_step(
                relay_request_id,
                DiscordLocalDispatchStepName.PERFORM_SEND_GESTURE,
                "can_press_send",
                capability.can_press_send,
            ),
            self._diagnostic_capability_step(
                relay_request_id,
                DiscordLocalDispatchStepName.VERIFY_MESSAGE_VISIBLE,
                "can_verify_sent_message",
                capability.can_verify_sent_message,
            ),
        ]
        return DiscordLocalDispatchResult(
            relay_request_id=relay_request_id,
            recipient_alias=recipient_alias,
            adapter_kind=capability.adapter_kind,
            route_constraint=capability.route_constraint,
            dispatch_supported=capability.dispatch_supported,
            verification_supported=capability.verification_supported,
            steps=steps,
            result_state=DiscordDispatchState.DISPATCH_ATTEMPTING
            if capability.dispatch_supported
            else DiscordDispatchState.DISPATCH_UNAVAILABLE,
            failure_step=None if capability.dispatch_supported else "capability_check",
            failure_reason=capability.unavailable_reason,
        )

    def _diagnostic_capability_step(
        self,
        relay_request_id: str,
        step_name: DiscordLocalDispatchStepName,
        capability_required: str,
        capability_declared: bool,
    ) -> DiscordLocalDispatchStep:
        return self._make_step(
            relay_request_id=relay_request_id,
            step_name=step_name,
            status=DiscordLocalDispatchStepStatus.SUCCEEDED
            if capability_declared
            else DiscordLocalDispatchStepStatus.UNSUPPORTED,
            capability_required=capability_required,
            capability_declared=capability_declared,
            evidence_summary="Capability is declared." if capability_declared else "Capability is not declared.",
            safe_to_continue=capability_declared,
        )

    def _make_step(
        self,
        *,
        relay_request_id: str,
        step_name: DiscordLocalDispatchStepName,
        status: DiscordLocalDispatchStepStatus,
        capability_required: str | None,
        capability_declared: bool,
        evidence_summary: str | None = None,
        failure_reason: str | None = None,
        safe_to_continue: bool = False,
    ) -> DiscordLocalDispatchStep:
        now = time.time()
        return DiscordLocalDispatchStep(
            step_id=f"{relay_request_id}:{step_name.value}",
            relay_request_id=relay_request_id,
            step_name=step_name,
            status=status,
            started_at=now,
            completed_at=now,
            adapter_kind=self.capability().adapter_kind,
            capability_required=capability_required,
            capability_declared=capability_declared,
            evidence_summary=evidence_summary,
            failure_reason=failure_reason,
            safe_to_continue=safe_to_continue,
        )

    def _result(
        self,
        *,
        relay_request_id: str,
        recipient_alias: str,
        capability: DiscordRelayCapability,
        steps: list[DiscordLocalDispatchStep],
        result_state: DiscordDispatchState,
        target_identity_verified: bool = False,
        final_send_gesture_performed: bool = False,
        message_inserted: bool = False,
        payload_copied_to_clipboard: bool = False,
        payload_pasted: bool = False,
        verification_attempted: bool = False,
        verification_evidence_present: bool = False,
        verification_evidence_source: str | None = None,
        verification_confidence: str | None = None,
        user_message: str = "",
        failure_step: str | None = None,
        failure_reason: str | None = None,
    ) -> DiscordLocalDispatchResult:
        return DiscordLocalDispatchResult(
            relay_request_id=relay_request_id,
            recipient_alias=recipient_alias,
            adapter_kind=capability.adapter_kind,
            route_constraint=capability.route_constraint,
            dispatch_supported=capability.dispatch_supported,
            verification_supported=capability.verification_supported,
            target_identity_verified=target_identity_verified,
            steps=steps,
            final_send_gesture_performed=final_send_gesture_performed,
            message_inserted=message_inserted,
            payload_copied_to_clipboard=payload_copied_to_clipboard,
            payload_pasted=payload_pasted,
            clipboard_temporarily_used=payload_copied_to_clipboard,
            verification_attempted=verification_attempted,
            verification_evidence_present=verification_evidence_present,
            verification_evidence_source=verification_evidence_source,
            verification_confidence=verification_confidence,
            result_state=result_state,
            sent_claimed=result_state in {DiscordDispatchState.SENT_UNVERIFIED, DiscordDispatchState.SENT_VERIFIED},
            verified_claimed=result_state == DiscordDispatchState.SENT_VERIFIED,
            user_message=user_message,
            failure_step=failure_step,
            failure_reason=failure_reason,
        )

    def _debug_with_result(
        self,
        base: dict[str, Any],
        result: DiscordLocalDispatchResult,
    ) -> dict[str, Any]:
        result_dict = result.to_dict()
        return {
            **base,
            "local_dispatch_result": result_dict,
            "steps": result_dict["steps"],
            "route_constraint": result.route_constraint,
            "target_identity_verified": result.target_identity_verified,
            "message_inserted": result.message_inserted,
            "payload_copied_to_clipboard": result.payload_copied_to_clipboard,
            "payload_pasted": result.payload_pasted,
            "payload_visible_confirmed": result.payload_visible_confirmed,
            "clipboard_temporarily_used": result.clipboard_temporarily_used,
            "verification_evidence_present": result.verification_evidence_present,
            "failure_step": result.failure_step,
            "failure_reason": result.failure_reason,
        }

    def send(self, *, destination: Any, preview: DiscordDispatchPreview) -> DiscordDispatchAttempt:
        capability = self.capability()
        relay_request_id = str(preview.fingerprint.get("fingerprint_id") or f"relay-{int(time.time() * 1000)}")
        recipient_alias = str(getattr(destination, "alias", None) or getattr(destination, "label", "") or "")
        steps: list[DiscordLocalDispatchStep] = []
        evidence: list[str] = []
        route_basis = "quick_switch"
        send_key_issued = False
        navigation_submission_emitted = False
        dispatch_side_effects_emitted = False
        message_inserted = False
        payload_copied_to_clipboard = False
        payload_pasted = False
        target_identity_verified = False
        failure_stage = "route_navigation"
        failure_step = DiscordLocalDispatchStepName.CAPABILITY_CHECK

        def add_step(
            step_name: DiscordLocalDispatchStepName,
            status: DiscordLocalDispatchStepStatus,
            capability_required: str | None,
            capability_declared: bool,
            *,
            evidence_summary: str | None = None,
            failure_reason: str | None = None,
            safe_to_continue: bool = False,
        ) -> None:
            steps.append(
                self._make_step(
                    relay_request_id=relay_request_id,
                    step_name=step_name,
                    status=status,
                    capability_required=capability_required,
                    capability_declared=capability_declared,
                    evidence_summary=evidence_summary,
                    failure_reason=failure_reason,
                    safe_to_continue=safe_to_continue,
                )
            )

        def attempt_from_result(
            *,
            state: DiscordDispatchState,
            route_basis_value: str,
            verification_strength: str = "none",
            verification_evidence: list[str] | None = None,
            failure_reason: str | None = None,
            send_summary: str | None = None,
            focused_window: dict[str, Any] | None = None,
            wrong_thread_refusal: bool = False,
            verification_attempted: bool = False,
            verification_evidence_present: bool = False,
            verification_evidence_source: str | None = None,
            verification_confidence: str | None = None,
            user_message: str = "",
            failure_step_name: str | None = None,
            transport_failure_kind: str | None = None,
            failure_stage_value: str | None = None,
        ) -> DiscordDispatchAttempt:
            result = self._result(
                relay_request_id=relay_request_id,
                recipient_alias=recipient_alias,
                capability=capability,
                steps=steps,
                result_state=state,
                target_identity_verified=target_identity_verified,
                final_send_gesture_performed=send_key_issued,
                message_inserted=message_inserted,
                payload_copied_to_clipboard=payload_copied_to_clipboard,
                payload_pasted=payload_pasted,
                verification_attempted=verification_attempted,
                verification_evidence_present=verification_evidence_present,
                verification_evidence_source=verification_evidence_source,
                verification_confidence=verification_confidence,
                user_message=user_message or send_summary or "",
                failure_step=failure_step_name,
                failure_reason=failure_reason,
            )
            debug = self._debug_with_result(
                {
                    "destination": destination.to_dict(),
                    "preview": preview.to_dict(),
                    "focused_window": focused_window or {},
                    "wrong_thread_refusal": wrong_thread_refusal,
                    "dispatch_side_effects_emitted": dispatch_side_effects_emitted,
                    "dispatch_attempted": dispatch_side_effects_emitted,
                    "final_send_gesture_performed": send_key_issued,
                    "verification_attempted": verification_attempted,
                    "send_key_issued": send_key_issued,
                    "navigation_submission_emitted": navigation_submission_emitted,
                    "failure_stage": failure_stage_value,
                    "transport_failure_kind": transport_failure_kind,
                },
                result,
            )
            return DiscordDispatchAttempt(
                state=state,
                route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
                route_basis=route_basis_value,
                verification_evidence=list(verification_evidence or evidence),
                verification_strength=verification_strength,
                failure_reason=failure_reason,
                send_summary=send_summary,
                debug=debug,
            )

        if not capability.dispatch_supported:
            reason = capability.unavailable_reason or "dispatch_not_supported"
            add_step(
                DiscordLocalDispatchStepName.CAPABILITY_CHECK,
                DiscordLocalDispatchStepStatus.UNSUPPORTED,
                "can_dispatch",
                capability.dispatch_supported,
                evidence_summary=reason,
                failure_reason=reason,
                safe_to_continue=False,
            )
            return attempt_from_result(
                state=DiscordDispatchState.DISPATCH_UNAVAILABLE,
                route_basis_value="capability_unavailable",
                failure_reason=reason,
                send_summary="I have the message ready, but local Discord dispatch is unavailable.",
                failure_step_name=DiscordLocalDispatchStepName.CAPABILITY_CHECK.value,
            )

        add_step(
            DiscordLocalDispatchStepName.CAPABILITY_CHECK,
            DiscordLocalDispatchStepStatus.SUCCEEDED,
            "can_dispatch",
            True,
            evidence_summary="Local Discord dispatch capability is declared.",
            safe_to_continue=True,
        )
        try:
            failure_step = DiscordLocalDispatchStepName.FOCUS_CLIENT
            self._ensure_discord_shell()
            add_step(
                DiscordLocalDispatchStepName.FOCUS_CLIENT,
                DiscordLocalDispatchStepStatus.SUCCEEDED,
                "can_focus_client",
                capability.can_focus_client,
                evidence_summary="Focused or opened the local Discord client route.",
                safe_to_continue=True,
            )

            failure_step = DiscordLocalDispatchStepName.IDENTIFY_DISCORD_SURFACE
            focused_window = self._focused_window()
            focused_process = str(focused_window.get("process_name") or "").strip().lower()
            if focused_process != "discord":
                add_step(
                    DiscordLocalDispatchStepName.IDENTIFY_DISCORD_SURFACE,
                    DiscordLocalDispatchStepStatus.FAILED,
                    "can_identify_discord_surface",
                    capability.can_identify_discord_surface,
                    evidence_summary="Focused surface is not clearly Discord.",
                    failure_reason="discord_surface_not_identified",
                    safe_to_continue=False,
                )
                return attempt_from_result(
                    state=DiscordDispatchState.DISPATCH_UNAVAILABLE,
                    route_basis_value="discord_surface_not_identified",
                    focused_window=focused_window,
                    failure_reason="discord_surface_not_identified",
                    send_summary="I have the message ready, but I cannot confirm that the local Discord client is active.",
                    failure_step_name=DiscordLocalDispatchStepName.IDENTIFY_DISCORD_SURFACE.value,
                )
            add_step(
                DiscordLocalDispatchStepName.IDENTIFY_DISCORD_SURFACE,
                DiscordLocalDispatchStepStatus.SUCCEEDED,
                "can_identify_discord_surface",
                capability.can_identify_discord_surface,
                evidence_summary="The focused local surface is Discord.",
                safe_to_continue=True,
            )

            failure_step = DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM
            destination_check = self._verify_destination_focus(destination=destination, focused_window=focused_window)
            if bool(destination_check.get("matched", False)):
                route_basis = "already_focused"
                target_identity_verified = True
                evidence.append("Discord was already focused on the trusted destination thread.")
                add_step(
                    DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM,
                    DiscordLocalDispatchStepStatus.SUCCEEDED,
                    "can_navigate_dm",
                    capability.can_navigate_dm,
                    evidence_summary="Discord was already focused on the trusted destination thread.",
                    safe_to_continue=True,
                )
            elif capability.route_constraint == "current_dm_only":
                evidence.extend(destination_check.get("evidence") or [])
                add_step(
                    DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM,
                    DiscordLocalDispatchStepStatus.BLOCKED,
                    "can_navigate_dm",
                    capability.can_navigate_dm,
                    evidence_summary="Adapter is constrained to the current DM and could not verify the trusted recipient.",
                    failure_reason="target_identity_not_verified_current_dm_only",
                    safe_to_continue=False,
                )
                return attempt_from_result(
                    state=DiscordDispatchState.DISPATCH_BLOCKED,
                    route_basis_value="current_dm_only_target_unverified",
                    verification_evidence=evidence,
                    focused_window=focused_window,
                    wrong_thread_refusal=True,
                    failure_reason="target_identity_not_verified_current_dm_only",
                    send_summary=(
                        f"I held the message because I cannot verify that the current Discord DM is {destination.label}."
                    ),
                    failure_step_name=DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM.value,
                )
            elif destination.thread_uri:
                route_basis = "deep_link"
                self._open_route(destination.thread_uri)
                evidence.append("Opened the Discord destination through a deep link.")
                self.driver.sleep(self.route_settle_seconds)
                focused_window = self._focused_window()
                destination_check = self._verify_destination_focus(destination=destination, focused_window=focused_window)
                add_step(
                    DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM,
                    DiscordLocalDispatchStepStatus.SUCCEEDED,
                    "can_navigate_dm",
                    capability.can_navigate_dm,
                    evidence_summary="Opened the Discord destination through a deep link.",
                    safe_to_continue=bool(destination_check.get("matched", False)),
                )
            else:
                search_query = str(destination.search_query or destination.label or "").strip()
                if not search_query:
                    add_step(
                        DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM,
                        DiscordLocalDispatchStepStatus.FAILED,
                        "can_navigate_dm",
                        capability.can_navigate_dm,
                        evidence_summary="Trusted alias has no DM search query or deep link.",
                        failure_reason="missing_search_query",
                        safe_to_continue=False,
                    )
                    return attempt_from_result(
                        state=DiscordDispatchState.DISPATCH_FAILED,
                        route_basis_value="missing_route_target",
                        failure_reason="missing_search_query",
                        send_summary="I have the message ready, but the trusted Discord alias has no route target.",
                        failure_step_name=DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM.value,
                    )
                navigation_submission_emitted = self._quick_switch(search_query)
                evidence.append(f'Used Discord quick switch for "{search_query}".')
                self.driver.sleep(self.route_settle_seconds)
                focused_window = self._focused_window()
                destination_check = self._verify_destination_focus(destination=destination, focused_window=focused_window)
                add_step(
                    DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM,
                    DiscordLocalDispatchStepStatus.SUCCEEDED,
                    "can_navigate_dm",
                    capability.can_navigate_dm,
                    evidence_summary=f'Used Discord quick switch for "{search_query}".',
                    safe_to_continue=bool(destination_check.get("matched", False)),
                )

            evidence.extend(destination_check.get("evidence") or [])
            if not bool(destination_check.get("matched", False)):
                add_step(
                    DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM,
                    DiscordLocalDispatchStepStatus.BLOCKED,
                    "can_navigate_dm",
                    capability.can_navigate_dm,
                    evidence_summary="The focused Discord thread did not match the trusted destination.",
                    failure_reason="discord_destination_unverified",
                    safe_to_continue=False,
                )
                return attempt_from_result(
                    state=DiscordDispatchState.DISPATCH_BLOCKED,
                    route_basis_value=route_basis,
                    verification_evidence=evidence,
                    focused_window=focused_window,
                    wrong_thread_refusal=True,
                    failure_reason="discord_destination_unverified",
                    send_summary=f"I opened Discord, but I could not verify {destination.label}'s thread safely enough to send.",
                    failure_step_name=DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM.value,
                )
            target_identity_verified = True

            failure_step = DiscordLocalDispatchStepName.LOCATE_MESSAGE_INPUT
            add_step(
                DiscordLocalDispatchStepName.LOCATE_MESSAGE_INPUT,
                DiscordLocalDispatchStepStatus.SUCCEEDED,
                "can_locate_message_input",
                capability.can_locate_message_input,
                evidence_summary=(
                    "Using the verified Discord thread's focused composer as the paste target; "
                    "input visibility is not independently verified."
                ),
                safe_to_continue=True,
            )

            body_text = self._message_body(preview)
            if body_text:
                failure_step = DiscordLocalDispatchStepName.INSERT_PAYLOAD
                failure_stage = "payload_insertion"
                self.clipboard.set_text(body_text)
                payload_copied_to_clipboard = True
                self.driver.hotkey(["ctrl", "v"])
                payload_pasted = True
                message_inserted = True
                evidence.append("Pasted the composed message body into Discord.")
                self.driver.sleep(self.compose_settle_seconds)
                dispatch_side_effects_emitted = True
                add_step(
                    DiscordLocalDispatchStepName.INSERT_PAYLOAD,
                    DiscordLocalDispatchStepStatus.SUCCEEDED,
                    "can_insert_text",
                    capability.can_insert_text,
                    evidence_summary="Pasted the composed message body into the Discord composer.",
                    safe_to_continue=True,
                )

            if preview.payload.kind == DiscordPayloadKind.FILE and preview.payload.path:
                failure_step = DiscordLocalDispatchStepName.INSERT_PAYLOAD
                failure_stage = "payload_insertion"
                self.clipboard.set_file_paths([preview.payload.path])
                payload_copied_to_clipboard = True
                self.driver.hotkey(["ctrl", "v"])
                payload_pasted = True
                message_inserted = True
                evidence.append("Pasted a file attachment into Discord.")
                self.driver.sleep(self.route_settle_seconds)
                dispatch_side_effects_emitted = True
                add_step(
                    DiscordLocalDispatchStepName.INSERT_PAYLOAD,
                    DiscordLocalDispatchStepStatus.SUCCEEDED,
                    "can_insert_text",
                    capability.can_insert_text,
                    evidence_summary="Pasted the file attachment into the Discord composer.",
                    safe_to_continue=True,
                )
            if not body_text and not (preview.payload.kind == DiscordPayloadKind.FILE and preview.payload.path):
                add_step(
                    DiscordLocalDispatchStepName.INSERT_PAYLOAD,
                    DiscordLocalDispatchStepStatus.SKIPPED,
                    "can_insert_text",
                    capability.can_insert_text,
                    evidence_summary="No sendable payload body or attachment was available.",
                    failure_reason="payload_empty",
                    safe_to_continue=False,
                )
                return attempt_from_result(
                    state=DiscordDispatchState.DISPATCH_FAILED,
                    route_basis_value=route_basis,
                    verification_evidence=evidence,
                    focused_window=focused_window,
                    failure_reason="payload_empty",
                    send_summary="I have the Discord route ready, but there was no payload to insert.",
                    failure_step_name=DiscordLocalDispatchStepName.INSERT_PAYLOAD.value,
                )

            failure_step = DiscordLocalDispatchStepName.PERFORM_SEND_GESTURE
            failure_stage = "send_submission"
            self._submit_send()
            send_key_issued = True
            dispatch_side_effects_emitted = True
            evidence.append("Issued the Discord send key.")
            add_step(
                DiscordLocalDispatchStepName.PERFORM_SEND_GESTURE,
                DiscordLocalDispatchStepStatus.SUCCEEDED,
                "can_press_send",
                capability.can_press_send,
                evidence_summary="Pressed Enter in the verified Discord composer.",
                safe_to_continue=True,
            )
        except Exception as error:
            classified_failure = self._classify_failure(error=error, failure_stage=failure_stage)
            if not any(step.step_name == failure_step for step in steps):
                add_step(
                    failure_step,
                    DiscordLocalDispatchStepStatus.FAILED,
                    {
                        DiscordLocalDispatchStepName.FOCUS_CLIENT: "can_focus_client",
                        DiscordLocalDispatchStepName.IDENTIFY_DISCORD_SURFACE: "can_identify_discord_surface",
                        DiscordLocalDispatchStepName.NAVIGATE_RECIPIENT_DM: "can_navigate_dm",
                        DiscordLocalDispatchStepName.INSERT_PAYLOAD: "can_insert_text",
                        DiscordLocalDispatchStepName.PERFORM_SEND_GESTURE: "can_press_send",
                    }.get(failure_step),
                    True,
                    evidence_summary=str(error),
                    failure_reason=str(classified_failure["failure_reason"]),
                    safe_to_continue=False,
                )
            return attempt_from_result(
                state=DiscordDispatchState.DISPATCH_FAILED,
                route_basis_value=route_basis,
                verification_evidence=evidence,
                failure_reason=str(classified_failure["failure_reason"]),
                send_summary=classified_failure["send_summary"],
                verification_attempted=False,
                failure_step_name=failure_step.value,
                transport_failure_kind=str(classified_failure["transport_failure_kind"] or "") or None,
                failure_stage_value=str(classified_failure["failure_stage"] or "") or None,
            )

        focused_window = self._focused_window()
        focused_process = str(focused_window.get("process_name") or "").strip().lower()
        focused_title = str(focused_window.get("window_title") or "").strip()
        if focused_process == "discord":
            evidence.append("Discord remained focused after the send command.")
        if focused_title:
            evidence.append(f'Focused Discord window title after send: "{focused_title}".')

        verification_strength = "weak"
        verification_attempted = capability.verification_supported
        verification_result = self._probe_delivery_verification(
            destination=destination,
            preview=preview,
            focused_window=focused_window,
        )
        if verification_result.get("evidence"):
            evidence.extend(list(verification_result.get("evidence") or []))
        if str(verification_result.get("strength") or "").strip():
            verification_strength = str(verification_result.get("strength")).strip()

        verification_evidence_present = bool(verification_result.get("evidence"))
        add_step(
            DiscordLocalDispatchStepName.VERIFY_MESSAGE_VISIBLE,
            DiscordLocalDispatchStepStatus.SUCCEEDED
            if bool(verification_result.get("verified", False))
            else DiscordLocalDispatchStepStatus.UNSUPPORTED
            if not capability.verification_supported
            else DiscordLocalDispatchStepStatus.FAILED,
            "can_verify_sent_message",
            capability.can_verify_sent_message,
            evidence_summary="Post-send verification evidence was collected."
            if verification_evidence_present
            else "No post-send message-visible verification evidence is available.",
            failure_reason=None if bool(verification_result.get("verified", False)) else "verification_unavailable",
            safe_to_continue=bool(verification_result.get("verified", False)),
        )

        state = DiscordDispatchState.SENT_UNVERIFIED
        send_summary = "I performed the send action in Discord, but I could not verify that the message appeared."
        if bool(verification_result.get("verified", False)):
            state = DiscordDispatchState.SENT_VERIFIED
            send_summary = f"I verified that the message appears in {destination.label}'s thread."
        elif preview.payload.kind == DiscordPayloadKind.FILE:
            state = DiscordDispatchState.SENT_UNVERIFIED
            verification_strength = "moderate" if focused_process == "discord" else verification_strength
            evidence.append("File upload completion was not directly verified in this pass.")
            send_summary = "I performed the file send action in Discord, but I could not verify that it appeared."
        elif focused_process == "discord" and self._verify_destination_focus(destination=destination, focused_window=focused_window).get("matched"):
            state = DiscordDispatchState.SENT_UNVERIFIED
            verification_strength = "moderate"
            send_summary = "I performed the send action in Discord, but I could not verify that it appeared."
        elif focused_process != "discord":
            verification_strength = "weak"
            send_summary = "I performed the send action in Discord, but Discord focus moved before I could verify it."

        return attempt_from_result(
            state=state,
            route_basis_value=route_basis,
            verification_evidence=evidence,
            verification_strength=verification_strength,
            send_summary=send_summary,
            focused_window=focused_window,
            verification_attempted=verification_attempted,
            verification_evidence_present=verification_evidence_present,
            verification_evidence_source="system_probe.discord_relay_verification"
            if capability.verification_supported
            else None,
            verification_confidence=verification_strength,
            user_message=send_summary,
        )

    def _classify_failure(self, *, error: Exception, failure_stage: str) -> dict[str, Any]:
        failure_kind = str(error).strip() or error.__class__.__name__
        if failure_kind.startswith("clipboard_"):
            if failure_stage == "route_navigation":
                send_summary = "Discord routing stopped because clipboard access failed during destination entry."
            else:
                send_summary = "Payload prepared, but clipboard access failed during the local Discord send path."
            return {
                "failure_reason": "clipboard_transport_failed",
                "send_summary": send_summary,
                "failure_stage": failure_stage,
                "transport_failure_kind": failure_kind,
            }
        return {
            "failure_reason": failure_kind,
            "send_summary": None,
            "failure_stage": failure_stage,
            "transport_failure_kind": None,
        }

    def _ensure_discord_shell(self) -> None:
        app_control = getattr(self.system_probe, "app_control", None) if self.system_probe is not None else None
        if callable(app_control):
            try:
                app_control(action="focus", app_name="discord")
                self.driver.sleep(0.25)
                return
            except Exception:
                pass
        self._open_route("discord://discord.com/app")
        self.driver.sleep(0.45)

    def _open_route(self, target: str) -> None:
        if not callable(self.open_target):
            raise RuntimeError("route_launcher_unavailable")
        self.open_target(target)

    def _quick_switch(self, search_query: str) -> None:
        self.clipboard.set_text(search_query)
        self.driver.hotkey(["ctrl", "k"])
        self.driver.sleep(self.compose_settle_seconds)
        self.driver.hotkey(["ctrl", "v"])
        self.driver.sleep(self.compose_settle_seconds)
        self._submit_navigation()
        return True

    def _submit_navigation(self) -> None:
        submit_navigation = getattr(self.driver, "submit_navigation", None)
        if callable(submit_navigation):
            submit_navigation()
            return
        self.driver.key("enter")

    def _submit_send(self) -> None:
        submit_send = getattr(self.driver, "submit_send", None)
        if callable(submit_send):
            submit_send()
            return
        self.driver.key("enter")

    def _message_body(self, preview: DiscordDispatchPreview) -> str:
        parts: list[str] = []
        if preview.note_text:
            parts.append(preview.note_text.strip())
        payload = preview.payload
        if payload.kind == DiscordPayloadKind.PAGE_LINK:
            if payload.title and payload.url:
                parts.append(f"{payload.title}\n{payload.url}")
            elif payload.url:
                parts.append(payload.url)
        elif payload.kind in {DiscordPayloadKind.SELECTED_TEXT, DiscordPayloadKind.CLIPBOARD_TEXT}:
            if payload.text:
                parts.append(payload.text)
        elif payload.kind == DiscordPayloadKind.NOTE_ARTIFACT:
            text = str(payload.text or "").strip()
            if payload.title and text:
                parts.append(f"{payload.title}\n{text}")
            elif text:
                parts.append(text)
        return "\n\n".join(part for part in parts if part).strip()

    def _focused_window(self) -> dict[str, Any]:
        window_status = getattr(self.system_probe, "window_status", None) if self.system_probe is not None else None
        if not callable(window_status):
            return {}
        try:
            result = window_status()
        except Exception:
            return {}
        if not isinstance(result, dict):
            return {}
        focused = result.get("focused_window")
        return dict(focused) if isinstance(focused, dict) else {}

    def _destination_terms(self, destination: Any) -> list[str]:
        terms: list[str] = []
        for raw_value in (
            getattr(destination, "label", None),
            getattr(destination, "alias", None),
            getattr(destination, "search_query", None),
        ):
            text = str(raw_value or "").strip()
            if not text:
                continue
            normalized = _normalize_text(text)
            if normalized and normalized not in terms:
                terms.append(normalized)
        return terms

    def _verify_destination_focus(self, *, destination: Any, focused_window: dict[str, Any]) -> dict[str, Any]:
        process_name = str(focused_window.get("process_name") or "").strip().lower()
        window_title = str(focused_window.get("window_title") or "").strip()
        normalized_title = _normalize_text(window_title)
        evidence: list[str] = []
        if process_name != "discord":
            evidence.append("Discord did not clearly hold focus after route navigation.")
            return {"matched": False, "evidence": evidence, "strength": "none"}
        if not normalized_title:
            evidence.append("Discord focused, but the window title was not specific enough to verify the destination thread.")
            return {"matched": False, "evidence": evidence, "strength": "none"}
        for term in self._destination_terms(destination):
            if term and term in normalized_title:
                evidence.append(f'Verified the Discord thread title matched "{destination.label}".')
                return {"matched": True, "evidence": evidence, "strength": "strong"}
        evidence.append(f'Focused Discord title "{window_title}" did not match the trusted destination "{destination.label}".')
        return {"matched": False, "evidence": evidence, "strength": "none"}

    def _probe_delivery_verification(
        self,
        *,
        destination: Any,
        preview: DiscordDispatchPreview,
        focused_window: dict[str, Any],
    ) -> dict[str, Any]:
        probe = getattr(self.system_probe, "discord_relay_verification", None) if self.system_probe is not None else None
        if not callable(probe):
            return {}
        try:
            result = probe(destination=destination, preview=preview, focused_window=focused_window)
        except Exception:
            return {}
        return dict(result) if isinstance(result, dict) else {}


@dataclass(slots=True)
class OfficialDiscordScaffoldAdapter:
    config: DiscordRelayConfig
    reason: str = "official_bot_webhook_route_scaffolded"
    debug: dict[str, Any] = field(default_factory=dict)

    def capability(self) -> DiscordRelayCapability:
        return DiscordRelayCapability(
            route_mode=DiscordRouteMode.OFFICIAL_BOT_WEBHOOK,
            preview_supported=True,
            dispatch_supported=False,
            verification_supported=False,
            requires_trust_approval=True,
            uses_discord_api_user_token=False,
            uses_discord_user_token=False,
            uses_self_bot=False,
            uses_local_client=False,
            adapter_kind="stub",
            unavailable_reason=self.reason,
            route_constraint="unsupported",
            can_preview=True,
            can_dispatch=False,
            can_verify_send=False,
            can_focus_client=False,
            can_launch_client=False,
            can_identify_discord_surface=False,
            can_navigate_dm=False,
            can_locate_message_input=False,
            can_insert_text=False,
            can_press_send=False,
            can_verify_sent_message=False,
            can_report_failure=True,
            rollback_posture="none",
            trust_requirements=["explicit_approval", "trusted_alias", "preview_fingerprint"],
        )

    def send(self, *, destination: Any, preview: DiscordDispatchPreview) -> DiscordDispatchAttempt:
        return DiscordDispatchAttempt(
            state=DiscordDispatchState.DISPATCH_NOT_IMPLEMENTED,
            route_mode=DiscordRouteMode.OFFICIAL_BOT_WEBHOOK,
            route_basis="scaffold_only",
            failure_reason=self.reason,
            send_summary="The official Discord bot/webhook route is scaffolded only in this pass.",
            debug={
                "destination": destination.to_dict(),
                "preview": preview.to_dict(),
                **dict(self.debug),
            },
        )
