from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from stormhelm.core.screen_awareness.models import (
    AccessibilitySummary,
    ActionExecutionResult,
    AppAdapterResolution,
    CrossMonitorTargetContext,
    CurrentScreenContext,
    ExtractedEntity,
    ExtractedEntitySet,
    FocusContext,
    GroundingEvidenceChannel,
    GroundingOutcome,
    GroundingProvenance,
    MonitorDescriptor,
    MonitorTopology,
    NavigationOutcome,
    NotificationEvent,
    NotificationSeverity,
    OverlayAnchor,
    OverlayAnchorPrecision,
    OverlayInstruction,
    PlannerPowerFeaturesResult,
    PowerFeatureRequestType,
    PowerFeaturesResult,
    ScreenConfidence,
    ScreenIntentType,
    ScreenInterpretation,
    ScreenObservation,
    VisibleTranslation,
    WorkspaceMap,
    WorkspaceWindow,
    confidence_level_for_score,
)
from stormhelm.core.screen_awareness.observation import best_visible_text


_SPANISH_TRANSLATIONS = {
    "guardar cambios": "Save changes",
    "continuar": "Continue",
    "cancelar": "Cancel",
    "error": "Error",
}

_MONITOR_HINTS = ("display", "monitor", "screen")
_ACCESSIBILITY_HINTS = ("keyboard", "focus", "focused", "accessible", "accessibility", "tab to")
_OVERLAY_HINTS = ("highlight", "overlay", "mark", "point out", "show me where")
_TRANSLATION_HINTS = ("translate", "translation", "what does this say")
_ENTITY_HINTS = ("extract", "version", "error code", "code on screen", "what numbers are on")
_NOTIFICATION_HINTS = ("notification", "toast", "what popped up", "what just appeared")
_WORKSPACE_HINTS = ("what windows", "workspace map", "what else is open", "what apps are open")


def _normalize(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


def _monitor_id(payload: dict[str, Any]) -> str:
    device_name = str(payload.get("device_name") or "").strip()
    if device_name:
        return device_name
    index = int(payload.get("index") or payload.get("monitor_index") or 0)
    return f"DISPLAY{index or 1}"


def _monitor_label(payload: dict[str, Any]) -> str:
    index = int(payload.get("index") or payload.get("monitor_index") or 0)
    if index > 0:
        return f"Display {index}"
    return str(payload.get("device_name") or "Active display").strip() or "Active display"


def _relative_position(bounds: dict[str, Any], *, reference_x: int | None) -> str | None:
    if reference_x is None:
        return None
    x_value = bounds.get("x")
    if not isinstance(x_value, int):
        return None
    if x_value < reference_x:
        return "left"
    if x_value > reference_x:
        return "right"
    return "center"


def _request_type(operator_text: str) -> PowerFeatureRequestType:
    normalized = _normalize(operator_text)
    if any(hint in normalized for hint in _TRANSLATION_HINTS):
        return PowerFeatureRequestType.TRANSLATION_REQUEST
    if any(hint in normalized for hint in _OVERLAY_HINTS):
        return PowerFeatureRequestType.OVERLAY_REQUEST
    if any(hint in normalized for hint in _NOTIFICATION_HINTS):
        return PowerFeatureRequestType.NOTIFICATION_QUERY
    if any(hint in normalized for hint in _ACCESSIBILITY_HINTS):
        return PowerFeatureRequestType.ACCESSIBILITY_QUERY
    if any(hint in normalized for hint in _WORKSPACE_HINTS):
        return PowerFeatureRequestType.WORKSPACE_MAP_QUERY
    if any(hint in normalized for hint in _ENTITY_HINTS):
        return PowerFeatureRequestType.ENTITY_QUERY
    if any(hint in normalized for hint in _MONITOR_HINTS):
        return PowerFeatureRequestType.MONITOR_QUERY
    return PowerFeatureRequestType.AUTO


def _signals_for_provenance(
    *,
    observation: ScreenObservation,
    active_context: dict[str, Any],
    workspace_context: dict[str, Any],
) -> tuple[list[GroundingEvidenceChannel], list[str], GroundingEvidenceChannel | None]:
    channels: list[GroundingEvidenceChannel] = []
    signal_names: list[str] = []

    if observation.focus_metadata or observation.window_metadata.get("monitors") or observation.window_metadata.get("windows"):
        channels.append(GroundingEvidenceChannel.NATIVE_OBSERVATION)
        signal_names.extend(["focused_window", "monitors", "windows"])
    if observation.selected_text or observation.clipboard_text:
        if GroundingEvidenceChannel.NATIVE_OBSERVATION not in channels:
            channels.append(GroundingEvidenceChannel.NATIVE_OBSERVATION)
        signal_names.append("visible_text")
    if active_context.get("accessibility") or active_context.get("notifications"):
        if GroundingEvidenceChannel.NATIVE_OBSERVATION not in channels:
            channels.append(GroundingEvidenceChannel.NATIVE_OBSERVATION)
        if active_context.get("accessibility"):
            signal_names.append("accessibility")
        if active_context.get("notifications"):
            signal_names.append("notifications")
    if workspace_context or observation.workspace_snapshot:
        channels.append(GroundingEvidenceChannel.WORKSPACE_CONTEXT)
        signal_names.append("workspace")

    dominant = channels[0] if channels else None
    deduped_channels: list[GroundingEvidenceChannel] = []
    for channel in channels:
        if channel not in deduped_channels:
            deduped_channels.append(channel)
    return deduped_channels, list(dict.fromkeys(signal_names)), dominant


def _build_monitor_topology(observation: ScreenObservation) -> MonitorTopology | None:
    raw_monitors = observation.window_metadata.get("monitors")
    monitors_payload = [dict(item) for item in raw_monitors if isinstance(item, dict)] if isinstance(raw_monitors, list) else []
    if not monitors_payload and observation.monitor_metadata:
        monitors_payload = [dict(observation.monitor_metadata)]
    if not monitors_payload:
        return None

    ordered = sorted(monitors_payload, key=lambda item: int((item.get("bounds") or {}).get("x") or 0))
    reference_x = int((ordered[0].get("bounds") or {}).get("x") or 0) if ordered else None
    active_monitor_index = int(observation.focus_metadata.get("monitor_index") or observation.monitor_metadata.get("index") or 0)
    descriptors: list[MonitorDescriptor] = []
    active_monitor_id: str | None = None
    active_monitor_label: str | None = None

    for payload in ordered:
        bounds = dict(payload.get("bounds") or {}) if isinstance(payload.get("bounds"), dict) else {}
        descriptor = MonitorDescriptor(
            monitor_id=_monitor_id(payload),
            label=_monitor_label(payload),
            is_primary=bool(payload.get("is_primary", False)),
            bounds=bounds,
            scale=float(payload.get("scale")) if isinstance(payload.get("scale"), (int, float)) else None,
            relative_position=_relative_position(bounds, reference_x=reference_x),
        )
        descriptors.append(descriptor)
        if int(payload.get("index") or payload.get("monitor_index") or 0) == active_monitor_index:
            active_monitor_id = descriptor.monitor_id
            active_monitor_label = descriptor.label

    if active_monitor_id is None and descriptors:
        primary = next((item for item in descriptors if item.is_primary), descriptors[0])
        active_monitor_id = primary.monitor_id
        active_monitor_label = primary.label

    summary = (
        f"The focused window appears on {active_monitor_label}."
        if active_monitor_label
        else "Monitor topology is partially available."
    )
    return MonitorTopology(
        monitors=descriptors,
        active_monitor_id=active_monitor_id,
        active_monitor_label=active_monitor_label,
        summary=summary,
        confidence=_confidence(0.86 if len(descriptors) > 1 else 0.72, "Monitor topology came from native window state."),
    )


def _window_monitor_id(window_payload: dict[str, Any], topology: MonitorTopology | None) -> str | None:
    explicit = str(window_payload.get("monitor_id") or "").strip()
    if explicit:
        return explicit
    index = int(window_payload.get("monitor_index") or 0)
    if index <= 0 or topology is None:
        return None
    for monitor in topology.monitors:
        if monitor.label.endswith(str(index)) or monitor.monitor_id.endswith(str(index)):
            return monitor.monitor_id
    return topology.active_monitor_id


def _build_workspace_map(observation: ScreenObservation, topology: MonitorTopology | None) -> WorkspaceMap | None:
    raw_windows = observation.window_metadata.get("windows")
    windows_payload = [dict(item) for item in raw_windows if isinstance(item, dict)] if isinstance(raw_windows, list) else []
    if not windows_payload and observation.focus_metadata:
        windows_payload = [dict(observation.focus_metadata)]
    if not windows_payload:
        return None

    windows: list[WorkspaceWindow] = []
    active_window_id: str | None = None
    for payload in windows_payload:
        window_id = str(payload.get("window_handle") or payload.get("window_id") or uuid4().hex).strip()
        title = str(payload.get("window_title") or payload.get("title") or "Window").strip()
        focused = bool(payload.get("is_focused") or payload.get("focused"))
        window = WorkspaceWindow(
            window_id=window_id,
            title=title,
            app_identity=str(payload.get("process_name") or payload.get("app_identity") or "").strip() or None,
            monitor_id=_window_monitor_id(payload, topology),
            focused=focused,
            minimized=bool(payload.get("minimized", False)),
            modal_owner_id=str(payload.get("modal_owner_id") or "").strip() or None,
            bounds=dict(payload.get("bounds") or {}) if isinstance(payload.get("bounds"), dict) else {},
            task_relevance="active" if focused else "background",
        )
        windows.append(window)
        if focused:
            active_window_id = window.window_id

    return WorkspaceMap(
        windows=windows,
        active_window_id=active_window_id or (windows[0].window_id if windows else None),
        summary=f"I can map {len(windows)} visible windows across the current workspace.",
        confidence=_confidence(0.8 if len(windows) > 1 else 0.68, "Workspace windows came from native window state."),
    )


def _build_accessibility_summary(
    *,
    active_context: dict[str, Any],
    grounding_result: GroundingOutcome | None,
) -> AccessibilitySummary | None:
    payload = active_context.get("accessibility")
    if not isinstance(payload, dict) or not payload:
        return None
    label = str(payload.get("focused_label") or "").strip() or None
    role = str(payload.get("focused_role") or "").strip() or None
    keyboard_hint = str(payload.get("keyboard_hint") or "").strip() or None
    enabled_value = payload.get("enabled") if isinstance(payload.get("enabled"), bool) else None
    narration = None
    if label and role:
        narration = f'Focus is on the {role} "{label}".'
    elif label:
        narration = f'Focus is on "{label}".'
    elif grounding_result is not None and grounding_result.winning_target is not None:
        narration = f'Grounded focus appears near "{grounding_result.winning_target.label}".'
    return AccessibilitySummary(
        focused_label=label,
        focused_role=role,
        enabled=enabled_value,
        keyboard_hint=keyboard_hint,
        narration_summary=narration,
        simplified_summary=narration,
        confidence=_confidence(0.82, "Accessibility guidance came from native focus context."),
    )


def _build_focus_context(
    *,
    active_context: dict[str, Any],
    topology: MonitorTopology | None,
    workspace_map: WorkspaceMap | None,
) -> FocusContext | None:
    payload = active_context.get("accessibility")
    if not isinstance(payload, dict) or not payload:
        return None
    return FocusContext(
        focus_path=[str(item).strip() for item in payload.get("focus_path", []) if str(item).strip()],
        control_label=str(payload.get("focused_label") or "").strip() or None,
        control_role=str(payload.get("focused_role") or "").strip() or None,
        enabled=bool(payload.get("enabled")) if isinstance(payload.get("enabled"), bool) else None,
        monitor_id=topology.active_monitor_id if topology is not None else None,
        window_id=workspace_map.active_window_id if workspace_map is not None else None,
        keyboard_traversal=str(payload.get("keyboard_hint") or "").strip() or None,
    )


def _translated_phrase(label: str | None) -> tuple[str, str] | None:
    normalized = _normalize(label)
    if normalized in _SPANISH_TRANSLATIONS:
        return str(label).strip(), _SPANISH_TRANSLATIONS[normalized]
    return None


def _build_translations(
    *,
    observation: ScreenObservation,
    active_context: dict[str, Any],
) -> list[VisibleTranslation]:
    translations: list[VisibleTranslation] = []
    accessibility = active_context.get("accessibility")
    if isinstance(accessibility, dict):
        translated = _translated_phrase(accessibility.get("focused_label"))
        if translated is not None:
            source_text, translated_text = translated
            translations.append(
                VisibleTranslation(
                    source_text=source_text,
                    translated_text=translated_text,
                    source_language="es",
                    target_language="en",
                    role_context=str(accessibility.get("focused_role") or "").strip() or None,
                    direct_translation=True,
                    confidence=_confidence(0.86, "Translation came from a deterministic visible-label phrase map."),
                )
            )

    visible_text = observation.selected_text or best_visible_text(observation) or ""
    for source_text, translated_text in list(_SPANISH_TRANSLATIONS.items()):
        pattern = re.compile(rf"\b{re.escape(source_text)}\b", flags=re.IGNORECASE)
        match = pattern.search(visible_text)
        if not match:
            continue
        exact = visible_text[match.start() : match.end()]
        if any(existing.source_text.lower() == exact.lower() for existing in translations):
            continue
        translations.append(
            VisibleTranslation(
                source_text=exact,
                translated_text=translated_text,
                source_language="es",
                target_language="en",
                direct_translation=True,
                confidence=_confidence(0.78, "Translation came from deterministic visible-text matching."),
            )
        )
    return translations


def _build_entity_set(observation: ScreenObservation) -> ExtractedEntitySet | None:
    source_text = observation.selected_text or best_visible_text(observation)
    if not source_text:
        return None

    entities: list[ExtractedEntity] = []
    version_match = re.search(r"\b(?:version|versi[oó]n)\s*([0-9]+(?:\.[0-9]+)+)\b", source_text, flags=re.IGNORECASE)
    if version_match:
        entities.append(
            ExtractedEntity(
                entity_id=f"entity-version-{uuid4().hex}",
                entity_type="version",
                raw_value=version_match.group(0),
                normalized_value=version_match.group(1),
                source_text=source_text,
                confidence=_confidence(0.9, "Version was extracted directly from visible text."),
            )
        )
    for match in re.finditer(r"\b([A-Z]+-\d{2,})\b", source_text):
        entities.append(
            ExtractedEntity(
                entity_id=f"entity-error-{uuid4().hex}",
                entity_type="error_code",
                raw_value=match.group(1),
                normalized_value=match.group(1),
                source_text=source_text,
                confidence=_confidence(0.88, "Error code was extracted directly from visible text."),
            )
        )
    time_match = re.search(r"\b(\d{1,2}:\d{2})\b", source_text)
    if time_match:
        entities.append(
            ExtractedEntity(
                entity_id=f"entity-time-{uuid4().hex}",
                entity_type="time",
                raw_value=time_match.group(1),
                normalized_value=time_match.group(1),
                source_text=source_text,
                confidence=_confidence(0.86, "Time was extracted directly from visible text."),
            )
        )
    if not entities:
        return None
    summary = ", ".join(f"{entity.entity_type}={entity.normalized_value or entity.raw_value}" for entity in entities[:4])
    return ExtractedEntitySet(
        entities=entities,
        summary=f"Visible entities: {summary}.",
        confidence=_confidence(0.84, "Structured entities came from deterministic visible-text extraction."),
    )


def _notification_severity(payload: dict[str, Any]) -> NotificationSeverity:
    raw = _normalize(str(payload.get("severity") or "info"))
    if raw == "error":
        return NotificationSeverity.ERROR
    if raw == "warning":
        return NotificationSeverity.WARNING
    return NotificationSeverity.INFO


def _build_notification_events(
    *,
    observation: ScreenObservation,
    active_context: dict[str, Any],
) -> list[NotificationEvent]:
    raw_events: list[dict[str, Any]] = []
    for source in (observation.window_metadata.get("notifications"), active_context.get("notifications")):
        if isinstance(source, list):
            raw_events.extend(dict(item) for item in source if isinstance(item, dict))

    events: list[NotificationEvent] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for payload in raw_events:
        title = str(payload.get("title") or "").strip()
        body = str(payload.get("body") or "").strip()
        kind = str(payload.get("kind") or "").strip() or None
        key = (_normalize(title), _normalize(body), str(kind or ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        severity = _notification_severity(payload)
        blocker = severity in {NotificationSeverity.WARNING, NotificationSeverity.ERROR} or any(
            marker in _normalize(f"{title} {body} {kind or ''}")
            for marker in ("permission", "required", "approve", "battery low", "system warning")
        )
        passive = not blocker and severity == NotificationSeverity.INFO
        events.append(
            NotificationEvent(
                notification_id=f"notification-{uuid4().hex}",
                title=title or "Notification",
                body=body,
                app_identity=str(payload.get("app_identity") or "").strip() or None,
                severity=severity,
                blocker=blocker,
                passive=passive,
                monitor_id=str(payload.get("monitor_id") or "").strip() or None,
                kind=kind,
                observed_at=_timestamp(),
                confidence=_confidence(0.8 if blocker else 0.68, "Notification awareness came from native notification state."),
            )
        )
    events.sort(key=lambda item: (not item.blocker, item.passive, item.title.lower()))
    return events


def _find_workspace_target(
    *,
    observation: ScreenObservation,
    grounding_result: GroundingOutcome | None,
    notification_events: list[NotificationEvent],
) -> dict[str, Any] | None:
    workspace_snapshot = observation.workspace_snapshot if isinstance(observation.workspace_snapshot, dict) else {}
    candidates: list[dict[str, Any]] = []
    active_item = workspace_snapshot.get("active_item")
    if isinstance(active_item, dict):
        candidates.append(dict(active_item))
    opened_items = workspace_snapshot.get("opened_items")
    if isinstance(opened_items, list):
        candidates.extend(dict(item) for item in opened_items if isinstance(item, dict))

    labels: list[str] = []
    if grounding_result is not None and grounding_result.winning_target is not None:
        labels.extend(
            [
                str(grounding_result.winning_target.label or "").strip(),
                str(grounding_result.winning_target.visible_text or "").strip(),
            ]
        )
    labels.extend(item.title for item in notification_events if item.blocker)
    normalized_labels = {_normalize(label) for label in labels if label}
    if not normalized_labels:
        return candidates[0] if candidates else None

    for candidate in candidates:
        candidate_title = _normalize(str(candidate.get("title") or candidate.get("label") or ""))
        if candidate_title and candidate_title in normalized_labels:
            return candidate
    for candidate in candidates:
        candidate_title = _normalize(str(candidate.get("title") or candidate.get("label") or ""))
        if any(label and label in candidate_title for label in normalized_labels):
            return candidate
    return candidates[0] if candidates else None


def _build_overlay_instructions(
    *,
    request_type: PowerFeatureRequestType,
    observation: ScreenObservation,
    topology: MonitorTopology | None,
    grounding_result: GroundingOutcome | None,
    notification_events: list[NotificationEvent],
) -> list[OverlayInstruction]:
    if request_type != PowerFeatureRequestType.OVERLAY_REQUEST:
        return []

    workspace_target = _find_workspace_target(
        observation=observation,
        grounding_result=grounding_result,
        notification_events=notification_events,
    )
    if workspace_target is None and grounding_result is None:
        return []

    target_label = ""
    target_candidate_id: str | None = None
    bounds: dict[str, Any] = {}
    monitor_id: str | None = None
    precision = OverlayAnchorPrecision.APPROXIMATE
    provenance_note = "The overlay anchor is approximate."

    if grounding_result is not None and grounding_result.winning_target is not None:
        target_label = grounding_result.winning_target.label or grounding_result.winning_target.visible_text or "visible target"
        target_candidate_id = grounding_result.winning_target.candidate_id
        bounds = dict(grounding_result.winning_target.bounds or {})
        precision = OverlayAnchorPrecision.GROUNDED if bounds else OverlayAnchorPrecision.CANDIDATE
        provenance_note = "The overlay anchor reuses the grounded screen target."

    if workspace_target is not None:
        target_label = target_label or str(workspace_target.get("title") or workspace_target.get("label") or "visible target")
        monitor_id = str(workspace_target.get("monitor_id") or "").strip() or monitor_id
        if isinstance(workspace_target.get("bounds"), dict) and workspace_target.get("bounds"):
            bounds = dict(workspace_target.get("bounds") or {})
            precision = OverlayAnchorPrecision.GROUNDED if target_candidate_id else OverlayAnchorPrecision.CANDIDATE
            provenance_note = "The overlay anchor comes from visible workspace bounds."

    if monitor_id is None and notification_events:
        monitor_id = next((item.monitor_id for item in notification_events if item.blocker and item.monitor_id), None)
    if monitor_id is None and topology is not None:
        monitor_id = topology.active_monitor_id
    if not target_label:
        target_label = "visible warning"

    return [
        OverlayInstruction(
            overlay_id=f"overlay-{uuid4().hex}",
            kind="highlight",
            label=f'Highlight "{target_label}"',
            anchor=OverlayAnchor(
                monitor_id=monitor_id,
                window_id=str(observation.focus_metadata.get("window_handle") or "").strip() or None,
                target_candidate_id=target_candidate_id,
                bounds=bounds,
                precision=precision,
                provenance_note=provenance_note,
            ),
            numbered_step=1,
            expires_after_seconds=18.0,
            confidence=_confidence(0.82 if bounds else 0.62, "Overlay anchor only points to observed visible bounds."),
        )
    ]


def _build_cross_monitor_context(
    *,
    topology: MonitorTopology | None,
    observation: ScreenObservation,
    grounding_result: GroundingOutcome | None,
) -> CrossMonitorTargetContext | None:
    if topology is None or grounding_result is None or grounding_result.winning_target is None:
        return None
    target_monitor_id = str(
        grounding_result.winning_target.semantic_metadata.get("monitor_id")
        or grounding_result.winning_target.parent_container
        or ""
    ).strip() or None
    if target_monitor_id is None:
        workspace_snapshot = observation.workspace_snapshot if isinstance(observation.workspace_snapshot, dict) else {}
        opened_items = workspace_snapshot.get("opened_items")
        if isinstance(opened_items, list):
            for item in opened_items:
                if not isinstance(item, dict):
                    continue
                if _normalize(str(item.get("title") or "")) == _normalize(grounding_result.winning_target.label):
                    target_monitor_id = str(item.get("monitor_id") or "").strip() or None
                    break
    if target_monitor_id is None:
        return None
    summary = (
        f'The grounded target "{grounding_result.winning_target.label}" sits on {target_monitor_id} while focus is on {topology.active_monitor_id}.'
        if target_monitor_id != topology.active_monitor_id
        else f'The grounded target "{grounding_result.winning_target.label}" is on the active display.'
    )
    return CrossMonitorTargetContext(
        target_candidate_id=grounding_result.winning_target.candidate_id,
        active_monitor_id=topology.active_monitor_id,
        target_monitor_id=target_monitor_id,
        summary=summary,
        confidence=_confidence(0.7 if target_monitor_id != topology.active_monitor_id else 0.82, "Cross-monitor context is based on visible monitor identifiers."),
    )


def _explanation_summary(
    *,
    request_type: PowerFeatureRequestType,
    topology: MonitorTopology | None,
    accessibility_summary: AccessibilitySummary | None,
    translations: list[VisibleTranslation],
    entity_set: ExtractedEntitySet | None,
    notification_events: list[NotificationEvent],
    overlays: list[OverlayInstruction],
    workspace_map: WorkspaceMap | None,
) -> str:
    if request_type == PowerFeatureRequestType.MONITOR_QUERY and topology is not None:
        focus_note = ""
        if accessibility_summary is not None and accessibility_summary.focused_label:
            focus_note = f' The current accessibility focus is "{accessibility_summary.focused_label}".'
        return f"{topology.summary}{focus_note}"
    if request_type == PowerFeatureRequestType.TRANSLATION_REQUEST and translations:
        first = translations[0]
        suffix = f" I also extracted {len(entity_set.entities)} visible entity markers." if entity_set is not None and entity_set.entities else ""
        return f'I can translate "{first.source_text}" as "{first.translated_text}" from the visible UI.{suffix}'
    if request_type == PowerFeatureRequestType.OVERLAY_REQUEST and overlays:
        return f'{overlays[0].anchor.provenance_note} I can highlight the visible warning without claiming a verified outcome.'
    if request_type == PowerFeatureRequestType.NOTIFICATION_QUERY and notification_events:
        primary = notification_events[0]
        if primary.blocker:
            return f'The most salient visible notification is "{primary.title}", which may need attention before treating the flow as clear.'
        return f'The latest visible notification is "{primary.title}".'
    if request_type == PowerFeatureRequestType.ACCESSIBILITY_QUERY and accessibility_summary is not None:
        return accessibility_summary.narration_summary or "Accessibility focus context is available."
    if request_type == PowerFeatureRequestType.WORKSPACE_MAP_QUERY and workspace_map is not None:
        return workspace_map.summary
    if entity_set is not None and entity_set.entities:
        return entity_set.summary
    if topology is not None:
        return topology.summary
    return "Power-feature context is partially available from current native and workspace evidence."


class DeterministicPowerFeaturesEngine:
    def assess(
        self,
        *,
        operator_text: str,
        intent: ScreenIntentType,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        verification_result: Any | None,
        action_result: ActionExecutionResult | None,
        continuity_result: Any | None,
        adapter_resolution: AppAdapterResolution | None,
        active_context: dict[str, Any] | None,
        workspace_context: dict[str, Any] | None,
    ) -> PowerFeaturesResult:
        del intent, interpretation, continuity_result
        active_context = active_context or {}
        workspace_context = workspace_context or {}
        request_type = _request_type(operator_text)

        monitor_topology = _build_monitor_topology(observation)
        workspace_map = _build_workspace_map(observation, monitor_topology)
        accessibility_summary = _build_accessibility_summary(
            active_context=active_context,
            grounding_result=grounding_result,
        )
        focus_context = _build_focus_context(
            active_context=active_context,
            topology=monitor_topology,
            workspace_map=workspace_map,
        )
        translations = _build_translations(observation=observation, active_context=active_context)
        extracted_entities = _build_entity_set(observation)
        notification_events = _build_notification_events(observation=observation, active_context=active_context)
        overlay_instructions = _build_overlay_instructions(
            request_type=request_type,
            observation=observation,
            topology=monitor_topology,
            grounding_result=grounding_result,
            notification_events=notification_events,
        )
        cross_monitor_context = _build_cross_monitor_context(
            topology=monitor_topology,
            observation=observation,
            grounding_result=grounding_result,
        )
        explanation_summary = _explanation_summary(
            request_type=request_type,
            topology=monitor_topology,
            accessibility_summary=accessibility_summary,
            translations=translations,
            entity_set=extracted_entities,
            notification_events=notification_events,
            overlays=overlay_instructions,
            workspace_map=workspace_map,
        )
        channels, signal_names, dominant = _signals_for_provenance(
            observation=observation,
            active_context=active_context,
            workspace_context=workspace_context,
        )

        score = 0.55
        if request_type == PowerFeatureRequestType.AUTO:
            score = 0.58 if monitor_topology or workspace_map else 0.45
        elif request_type == PowerFeatureRequestType.MONITOR_QUERY and monitor_topology is not None:
            score = 0.86
        elif request_type == PowerFeatureRequestType.TRANSLATION_REQUEST and translations:
            score = 0.84
        elif request_type == PowerFeatureRequestType.OVERLAY_REQUEST and overlay_instructions:
            score = 0.8
        elif request_type == PowerFeatureRequestType.NOTIFICATION_QUERY and notification_events:
            score = 0.82
        elif request_type == PowerFeatureRequestType.ACCESSIBILITY_QUERY and accessibility_summary is not None:
            score = 0.82
        elif request_type == PowerFeatureRequestType.WORKSPACE_MAP_QUERY and workspace_map is not None:
            score = 0.78
        elif request_type == PowerFeatureRequestType.ENTITY_QUERY and extracted_entities is not None:
            score = 0.8

        planner_result = PlannerPowerFeaturesResult(
            resolved=True,
            request_type=request_type,
            monitor_count=len(monitor_topology.monitors) if monitor_topology is not None else 0,
            workspace_window_count=len(workspace_map.windows) if workspace_map is not None else 0,
            translation_count=len(translations),
            entity_count=len(extracted_entities.entities) if extracted_entities is not None else 0,
            notification_count=len(notification_events),
            overlay_instruction_count=len(overlay_instructions),
            explanation_summary=explanation_summary,
        )
        result = PowerFeaturesResult(
            request_type=request_type,
            monitor_topology=monitor_topology,
            workspace_map=workspace_map,
            accessibility_summary=accessibility_summary,
            focus_context=focus_context,
            overlay_instructions=overlay_instructions,
            translations=translations,
            extracted_entities=extracted_entities,
            notification_events=notification_events,
            cross_monitor_target_context=cross_monitor_context,
            explanation_summary=explanation_summary,
            planner_result=planner_result,
            provenance=GroundingProvenance(
                channels_used=channels,
                dominant_channel=dominant,
                signal_names=signal_names,
            ),
            confidence=_confidence(score, "Power features stay bounded to current observed monitor, workspace, accessibility, and visible text signals."),
            reused_grounding=grounding_result is not None,
            reused_navigation=navigation_result is not None,
            reused_verification=verification_result is not None,
            reused_action=action_result is not None,
            reused_continuity=current_context is not None,
            reused_adapter=adapter_resolution is not None and adapter_resolution.available,
        )

        current_context.monitor_topology = monitor_topology
        current_context.workspace_map = workspace_map
        current_context.accessibility_summary = accessibility_summary
        current_context.focus_context = focus_context
        current_context.visible_translations = list(translations)
        current_context.extracted_entity_set = extracted_entities
        current_context.notification_events = list(notification_events)
        if request_type == PowerFeatureRequestType.AUTO and explanation_summary and not current_context.summary:
            current_context.summary = explanation_summary
        return result

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "supported_request_types": [request_type.value for request_type in PowerFeatureRequestType],
            "translation_languages": ["es->en"],
            "structured_entity_types": ["version", "error_code", "time"],
        }
