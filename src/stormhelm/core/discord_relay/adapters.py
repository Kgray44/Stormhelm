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
    DiscordPayloadKind,
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

    def send(self, *, destination: Any, preview: DiscordDispatchPreview) -> DiscordDispatchAttempt:
        if not self.config.local_dm_route_enabled:
            return DiscordDispatchAttempt(
                state=DiscordDispatchState.FAILED,
                route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
                route_basis="local_client_disabled",
                verification_strength="none",
                failure_reason="local_dm_route_disabled",
                debug={
                    "dispatch_side_effects_emitted": False,
                    "send_key_issued": False,
                    "navigation_submission_emitted": False,
                },
            )
        if platform.system().strip().lower() != "windows":
            return DiscordDispatchAttempt(
                state=DiscordDispatchState.FAILED,
                route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
                route_basis="unsupported_platform",
                verification_strength="none",
                failure_reason="unsupported_platform",
                debug={
                    "dispatch_side_effects_emitted": False,
                    "send_key_issued": False,
                    "navigation_submission_emitted": False,
                },
            )

        evidence: list[str] = []
        route_basis = "quick_switch"
        send_key_issued = False
        navigation_submission_emitted = False
        dispatch_side_effects_emitted = False
        failure_stage = "route_navigation"
        try:
            self._ensure_discord_shell()
            focused_window = self._focused_window()
            destination_check = self._verify_destination_focus(destination=destination, focused_window=focused_window)
            if bool(destination_check.get("matched", False)):
                route_basis = "already_focused"
                evidence.append("Discord was already focused on the trusted destination thread.")
            elif destination.thread_uri:
                route_basis = "deep_link"
                self._open_route(destination.thread_uri)
                evidence.append("Opened the Discord destination through a deep link.")
                self.driver.sleep(self.route_settle_seconds)
                focused_window = self._focused_window()
                destination_check = self._verify_destination_focus(destination=destination, focused_window=focused_window)
            else:
                search_query = str(destination.search_query or destination.label or "").strip()
                if not search_query:
                    return DiscordDispatchAttempt(
                        state=DiscordDispatchState.FAILED,
                        route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
                        route_basis="missing_route_target",
                        verification_strength="none",
                        failure_reason="missing_search_query",
                        debug={
                            "dispatch_side_effects_emitted": False,
                            "send_key_issued": False,
                            "navigation_submission_emitted": False,
                        },
                    )
                navigation_submission_emitted = self._quick_switch(search_query)
                evidence.append(f'Used Discord quick switch for "{search_query}".')
                self.driver.sleep(self.route_settle_seconds)
                focused_window = self._focused_window()
                destination_check = self._verify_destination_focus(destination=destination, focused_window=focused_window)

            evidence.extend(destination_check.get("evidence") or [])
            if not bool(destination_check.get("matched", False)):
                return DiscordDispatchAttempt(
                    state=DiscordDispatchState.FAILED,
                    route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
                    route_basis=route_basis,
                    verification_evidence=evidence,
                    verification_strength="none",
                    failure_reason="discord_destination_unverified",
                    send_summary=f"I opened Discord, but I could not verify {destination.label}'s thread safely enough to send.",
                    debug={
                        "destination": destination.to_dict(),
                        "preview": preview.to_dict(),
                        "focused_window": focused_window,
                        "wrong_thread_refusal": True,
                        "destination_verification": dict(destination_check),
                        "dispatch_side_effects_emitted": False,
                        "send_key_issued": False,
                        "navigation_submission_emitted": navigation_submission_emitted,
                    },
                )

            body_text = self._message_body(preview)
            if body_text:
                failure_stage = "payload_insertion"
                self.clipboard.set_text(body_text)
                self.driver.hotkey(["ctrl", "v"])
                evidence.append("Pasted the composed message body into Discord.")
                self.driver.sleep(self.compose_settle_seconds)
                dispatch_side_effects_emitted = True

            if preview.payload.kind == DiscordPayloadKind.FILE and preview.payload.path:
                failure_stage = "payload_insertion"
                self.clipboard.set_file_paths([preview.payload.path])
                self.driver.hotkey(["ctrl", "v"])
                evidence.append("Pasted a file attachment into Discord.")
                self.driver.sleep(self.route_settle_seconds)
                dispatch_side_effects_emitted = True

            failure_stage = "send_submission"
            self._submit_send()
            send_key_issued = True
            dispatch_side_effects_emitted = True
            evidence.append("Issued the Discord send key.")
        except Exception as error:
            classified_failure = self._classify_failure(error=error, failure_stage=failure_stage)
            return DiscordDispatchAttempt(
                state=DiscordDispatchState.FAILED,
                route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
                route_basis=route_basis,
                verification_evidence=evidence,
                verification_strength="none",
                failure_reason=str(classified_failure["failure_reason"]),
                send_summary=classified_failure["send_summary"],
                debug={
                    "destination": destination.to_dict(),
                    "preview": preview.to_dict(),
                    "dispatch_side_effects_emitted": dispatch_side_effects_emitted,
                    "send_key_issued": send_key_issued,
                    "navigation_submission_emitted": navigation_submission_emitted,
                    "failure_stage": classified_failure["failure_stage"],
                    "transport_failure_kind": classified_failure["transport_failure_kind"],
                },
            )

        focused_window = self._focused_window()
        focused_process = str(focused_window.get("process_name") or "").strip().lower()
        focused_title = str(focused_window.get("window_title") or "").strip()
        if focused_process == "discord":
            evidence.append("Discord remained focused after the send command.")
        if focused_title:
            evidence.append(f'Focused Discord window title after send: "{focused_title}".')

        verification_strength = "weak"
        verification_result = self._probe_delivery_verification(
            destination=destination,
            preview=preview,
            focused_window=focused_window,
        )
        if verification_result.get("evidence"):
            evidence.extend(list(verification_result.get("evidence") or []))
        if str(verification_result.get("strength") or "").strip():
            verification_strength = str(verification_result.get("strength")).strip()

        state = DiscordDispatchState.STARTED
        send_summary = "Started the send through the local Discord client."
        if bool(verification_result.get("verified", False)):
            state = DiscordDispatchState.VERIFIED
            send_summary = f"I verified that the message appears in {destination.label}'s thread."
        elif preview.payload.kind == DiscordPayloadKind.FILE:
            state = DiscordDispatchState.UNCERTAIN
            verification_strength = "moderate" if focused_process == "discord" else verification_strength
            evidence.append("File upload completion was not directly verified in this pass.")
            send_summary = "The send appears to have started, but I cannot verify delivery yet."
        elif focused_process == "discord" and self._verify_destination_focus(destination=destination, focused_window=focused_window).get("matched"):
            state = DiscordDispatchState.UNCERTAIN
            verification_strength = "moderate"
            send_summary = "The send appears to have completed, but I cannot verify delivery."
        elif focused_process != "discord":
            verification_strength = "weak"
            send_summary = "The send appears to have started, but I cannot verify delivery yet."

        return DiscordDispatchAttempt(
            state=state,
            route_mode=DiscordRouteMode.LOCAL_CLIENT_AUTOMATION,
            route_basis=route_basis,
            verification_evidence=evidence,
            verification_strength=verification_strength,
            send_summary=send_summary,
            debug={
                "destination": destination.to_dict(),
                "preview": preview.to_dict(),
                "focused_window": focused_window,
                "verification_evidence_strength": verification_strength,
                "dispatch_side_effects_emitted": dispatch_side_effects_emitted,
                "send_key_issued": send_key_issued,
                "navigation_submission_emitted": navigation_submission_emitted,
            },
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

    def send(self, *, destination: Any, preview: DiscordDispatchPreview) -> DiscordDispatchAttempt:
        return DiscordDispatchAttempt(
            state=DiscordDispatchState.FAILED,
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
