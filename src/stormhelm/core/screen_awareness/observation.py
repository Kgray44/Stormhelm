from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import ScreenObservationScope
from stormhelm.core.screen_awareness.models import ScreenSensitivityLevel
from stormhelm.core.screen_awareness.models import ScreenSourceType
from stormhelm.core.screen_awareness.visual_capture import sensitive_window_level


def _clean_text(value: object) -> str | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    return text or None


def _preview(text: str | None, *, limit: int = 160) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _descriptor_payload(descriptor: object) -> dict[str, Any]:
    if not isinstance(descriptor, dict):
        return {}
    payload = dict(descriptor)
    value = _clean_text(payload.get("value"))
    if value is not None:
        payload["value"] = value
    preview = _clean_text(payload.get("preview"))
    payload["preview"] = preview or _preview(value)
    return payload


def _contains_payload(data: object) -> bool:
    if isinstance(data, dict):
        return any(value not in (None, "") and value != [] and value != {} for value in data.values())
    return bool(data)


def _has_workspace_signal(snapshot: dict[str, Any]) -> bool:
    return bool(
        snapshot.get("workspace")
        or snapshot.get("active_item")
        or snapshot.get("opened_items")
    )


@dataclass(slots=True)
class NativeContextObservationSource:
    system_probe: Any | None = None
    name: str = "native_context"

    def observe(
        self,
        *,
        session_id: str,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, Any],
        workspace_context: dict[str, Any] | None = None,
    ) -> ScreenObservation:
        del session_id
        workspace_context = workspace_context or {}
        selection_descriptor = _descriptor_payload(active_context.get("selection"))
        clipboard_descriptor = _descriptor_payload(active_context.get("clipboard"))
        selected_text = _clean_text(selection_descriptor.get("value"))
        clipboard_text = _clean_text(clipboard_descriptor.get("value"))

        window_status: dict[str, Any] = {}
        if self.system_probe is not None:
            window_status_reader = getattr(self.system_probe, "window_status", None)
            if callable(window_status_reader):
                try:
                    result = window_status_reader()
                    if isinstance(result, dict):
                        window_status = dict(result)
                except Exception:
                    window_status = {}

        focused_window = dict(window_status.get("focused_window") or {}) if isinstance(window_status.get("focused_window"), dict) else {}
        monitors = [
            dict(item)
            for item in (window_status.get("monitors") or [])
            if isinstance(item, dict)
        ]
        windows = [
            dict(item)
            for item in (window_status.get("windows") or [])
            if isinstance(item, dict)
        ]
        notifications = [
            dict(item)
            for item in (window_status.get("notifications") or [])
            if isinstance(item, dict)
        ]
        accessibility_snapshot = (
            dict(active_context.get("accessibility") or {})
            if isinstance(active_context.get("accessibility"), dict)
            else {}
        )
        monitor_index = int(focused_window.get("monitor_index") or 0)
        monitor_metadata = next((item for item in monitors if int(item.get("index") or 0) == monitor_index), {})
        if not monitor_metadata:
            monitor_metadata = next((item for item in monitors if bool(item.get("is_primary"))), monitors[0] if monitors else {})

        workspace_snapshot = {
            "workspace": dict(workspace_context.get("workspace") or active_context.get("workspace") or {})
            if isinstance(workspace_context.get("workspace") or active_context.get("workspace"), dict)
            else {},
            "module": str(workspace_context.get("module") or active_module or "").strip(),
            "section": str(workspace_context.get("section") or "").strip(),
            "active_item": dict(workspace_context.get("active_item") or {})
            if isinstance(workspace_context.get("active_item"), dict)
            else {},
            "opened_items": [
                dict(item)
                for item in (workspace_context.get("opened_items") or [])
                if isinstance(item, dict)
            ][:4],
        }

        source_types_used: list[ScreenSourceType] = []
        quality_notes: list[str] = []
        warnings: list[str] = []

        if focused_window:
            source_types_used.append(ScreenSourceType.FOCUS_STATE)
            quality_notes.append("Focused window identity came from native system state.")
        else:
            warnings.append("Focused window identity was unavailable.")

        if selected_text:
            source_types_used.append(ScreenSourceType.SELECTION)
            quality_notes.append("Selected text provided direct visible content.")
        if clipboard_text:
            source_types_used.append(ScreenSourceType.CLIPBOARD)
            quality_notes.append("Clipboard text provided supporting context.")
        if accessibility_snapshot:
            source_types_used.append(ScreenSourceType.ACCESSIBILITY)
            quality_notes.append("Accessibility focus metadata provided native control context.")
        if _has_workspace_signal(workspace_snapshot):
            source_types_used.append(ScreenSourceType.WORKSPACE_CONTEXT)
            quality_notes.append("Workspace context added native application context.")

        if not selected_text and not clipboard_text:
            warnings.append("No direct visible text was available from selection or clipboard.")

        sensitivity = sensitive_window_level(focused_window)
        if sensitivity == ScreenSensitivityLevel.NORMAL:
            title = str(workspace_snapshot.get("active_item", {}).get("title") or "").strip().lower()
            if any(marker in title for marker in {"password", "account", "billing", "bank", "token", "secret"}):
                sensitivity = ScreenSensitivityLevel.SENSITIVE

        app_identity = str(
            focused_window.get("process_name")
            or workspace_snapshot.get("active_item", {}).get("kind")
            or ""
        ).strip() or None

        focus_metadata = dict(focused_window)
        if accessibility_snapshot:
            focus_metadata["accessibility"] = accessibility_snapshot

        return ScreenObservation(
            captured_at=datetime.now(timezone.utc).isoformat(),
            scope=ScreenObservationScope.ACTIVE_WINDOW,
            source_types_used=source_types_used,
            window_metadata={
                "focused_window": focused_window,
                "windows": windows,
                "monitors": monitors,
                "notifications": notifications,
                "accessibility": accessibility_snapshot,
                "surface_mode": surface_mode,
                "active_module": active_module,
            },
            app_identity=app_identity,
            selected_text=selected_text,
            clipboard_text=clipboard_text,
            workspace_snapshot=workspace_snapshot,
            monitor_metadata=monitor_metadata,
            quality_notes=quality_notes,
            warnings=warnings,
            selection_metadata=selection_descriptor,
            focus_metadata=focus_metadata,
            cursor_metadata={"notifications": notifications[:4]},
            sensitivity=sensitivity,
        )


def has_direct_screen_signal(observation: ScreenObservation) -> bool:
    return bool(
        observation.visual_text
        or has_screen_capture_signal(observation)
        or observation.focus_metadata
        or observation.selected_text
        or _has_workspace_signal(observation.workspace_snapshot)
    )


def has_live_screen_signal(observation: ScreenObservation) -> bool:
    return has_direct_screen_signal(observation)


def has_clipboard_only_signal(observation: ScreenObservation) -> bool:
    return bool(observation.clipboard_text) and not has_live_screen_signal(observation)


def has_accessibility_signal(observation: ScreenObservation) -> bool:
    accessibility = observation.focus_metadata.get("accessibility") if isinstance(observation.focus_metadata, dict) else None
    if not isinstance(accessibility, dict):
        return False
    return _contains_payload(accessibility)


def has_screen_content_signal(observation: ScreenObservation) -> bool:
    return bool(
        observation.selected_text
        or observation.visual_text
        or has_accessibility_signal(observation)
        or observation.workspace_snapshot.get("active_item")
    )


def has_screen_capture_signal(observation: ScreenObservation) -> bool:
    status = observation.visual_metadata.get("screen_capture") if isinstance(observation.visual_metadata, dict) else None
    return bool(isinstance(status, dict) and status.get("captured"))


def has_focus_only_signal(observation: ScreenObservation) -> bool:
    return bool(observation.focus_metadata) and not has_screen_content_signal(observation)


def best_live_visible_text(observation: ScreenObservation) -> str | None:
    for candidate in (
        observation.selected_text,
        observation.visual_text,
        str(observation.workspace_snapshot.get("active_item", {}).get("title") or "").strip() or None,
        str(observation.workspace_snapshot.get("active_item", {}).get("url") or "").strip() or None,
        str(observation.focus_metadata.get("window_title") or "").strip() or None,
    ):
        cleaned = _clean_text(candidate)
        if cleaned:
            return cleaned
    return None


def best_visible_text(observation: ScreenObservation) -> str | None:
    for candidate in (
        best_live_visible_text(observation),
        observation.clipboard_text,
    ):
        cleaned = _clean_text(candidate)
        if cleaned:
            return cleaned
    return None
