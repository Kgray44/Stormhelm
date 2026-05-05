from __future__ import annotations

from typing import Any

from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import ScreenConfidenceLevel
from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import ScreenSourceType
from stormhelm.core.screen_awareness.models import confidence_level_for_score
from stormhelm.core.screen_awareness.observation import has_accessibility_signal
from stormhelm.core.screen_awareness.observation import has_screen_capture_signal


def _confidence(score: float, note: str) -> dict[str, Any]:
    bounded = max(0.0, min(1.0, float(score or 0.0)))
    return ScreenConfidence(
        score=bounded,
        level=confidence_level_for_score(bounded),
        note=note,
    ).to_dict()


def focus_evidence_verified(observation: ScreenObservation | None) -> bool:
    if observation is None:
        return False
    focus = observation.focus_metadata if isinstance(observation.focus_metadata, dict) else {}
    if bool(focus.get("is_focused") or focus.get("focused")):
        return True
    handle = str(focus.get("window_handle") or focus.get("window_id") or "").strip()
    windows = observation.window_metadata.get("windows") if isinstance(observation.window_metadata, dict) else []
    if not isinstance(windows, list):
        return False
    for item in windows:
        if not isinstance(item, dict):
            continue
        item_handle = str(item.get("window_handle") or item.get("window_id") or "").strip()
        if handle and item_handle and item_handle == handle and bool(item.get("is_focused") or item.get("focused")):
            return True
    return False


def _window_title(observation: ScreenObservation | None) -> str:
    if observation is None or not isinstance(observation.focus_metadata, dict):
        return ""
    return str(
        observation.focus_metadata.get("window_title")
        or observation.focus_metadata.get("title")
        or observation.app_identity
        or ""
    ).strip()


def _window_stack(observation: ScreenObservation | None) -> list[dict[str, Any]]:
    if observation is None or not isinstance(observation.window_metadata, dict):
        return []
    windows = observation.window_metadata.get("windows")
    if not isinstance(windows, list):
        return []
    return [dict(item) for item in windows if isinstance(item, dict) and str(item.get("window_title") or item.get("title") or "").strip()]


def _recent_contexts(active_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    active_context = active_context or {}
    recent = active_context.get("recent_context_resolutions")
    if not isinstance(recent, list):
        return []
    return [
        dict(item)
        for item in recent
        if isinstance(item, dict) and str(item.get("kind") or "").strip() == "screen_awareness"
    ]


def _clipboard_text(active_context: dict[str, Any] | None, observation: ScreenObservation | None) -> str:
    if observation is not None and observation.clipboard_text:
        return str(observation.clipboard_text).strip()
    active_context = active_context or {}
    clipboard = active_context.get("clipboard")
    if isinstance(clipboard, dict):
        return str(clipboard.get("value") or clipboard.get("preview") or "").strip()
    return ""


def _entry(
    *,
    source: str,
    tier: int,
    confidence: dict[str, Any],
    freshness: str,
    used_for_summary: bool,
    note: str,
    source_type: ScreenSourceType | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "rank": 0,
        "tier": tier,
        "source": source,
        "source_type": source_type.value if source_type is not None else None,
        "freshness": freshness,
        "confidence": confidence,
        "used_for_summary": used_for_summary,
        "note": note,
    }
    if details:
        payload["details"] = details
    return payload


def rank_screen_evidence(
    observation: ScreenObservation | None,
    *,
    active_context: dict[str, Any] | None = None,
    workspace_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    del workspace_context
    entries: list[dict[str, Any]] = []
    stronger_than_title = False

    if observation is not None and has_screen_capture_signal(observation):
        screen_capture = observation.visual_metadata.get("screen_capture", {})
        score = 0.92 if observation.visual_text else 0.74
        entries.append(
            _entry(
                source="screen_capture",
                tier=1,
                source_type=ScreenSourceType.SCREEN_CAPTURE,
                confidence=_confidence(score, "Fresh screenshot pixels are the strongest current-screen source."),
                freshness="current",
                used_for_summary=True,
                note="Fresh screenshot pixels were captured for this request.",
                details={
                    "scope": str(screen_capture.get("scope") or observation.scope.value),
                    "captured_at": str(screen_capture.get("captured_at") or ""),
                },
            )
        )
        stronger_than_title = True

    if observation is not None and observation.visual_text:
        visual_source = str(observation.visual_metadata.get("visual_text_source") or "").strip()
        source = "provider_vision" if visual_source == "provider_vision" else "local_ocr" if visual_source == "local_ocr" else "visible_text"
        source_type = (
            ScreenSourceType.PROVIDER_VISION
            if source == "provider_vision"
            else ScreenSourceType.LOCAL_OCR
            if source == "local_ocr"
            else None
        )
        score = float(observation.visual_metadata.get("visual_confidence_score") or 0.78)
        entries.append(
            _entry(
                source=source,
                tier=2,
                source_type=source_type,
                confidence=_confidence(score, "Readable text came from the current visual capture or visible text signal."),
                freshness="current",
                used_for_summary=True,
                note="Readable current-screen text is available.",
                details={"preview": observation.visual_text[:160]},
            )
        )
        stronger_than_title = True

    if observation is not None and observation.selected_text:
        entries.append(
            _entry(
                source="selected_text",
                tier=2,
                source_type=ScreenSourceType.SELECTION,
                confidence=_confidence(0.9, "Selected text is direct current visible content when selection provenance is live."),
                freshness="current",
                used_for_summary=True,
                note="Selected visible text was available.",
                details={"preview": observation.selected_text[:160]},
            )
        )
        stronger_than_title = True

    if observation is not None and has_accessibility_signal(observation):
        entries.append(
            _entry(
                source="accessibility_ui_tree",
                tier=3,
                source_type=ScreenSourceType.ACCESSIBILITY,
                confidence=_confidence(0.76, "Accessibility focus metadata provides structured UI context without pixels."),
                freshness="current",
                used_for_summary=True,
                note="Accessibility/UI Automation context was available.",
            )
        )
        stronger_than_title = True

    if observation is not None and any(
        source in observation.source_types_used for source in (ScreenSourceType.APP_ADAPTER, ScreenSourceType.BROWSER_DOM)
    ):
        entries.append(
            _entry(
                source="app_semantic_adapter",
                tier=4,
                source_type=ScreenSourceType.APP_ADAPTER,
                confidence=_confidence(0.7, "App semantic adapters provide structured context below direct visual/OCR evidence."),
                freshness="current",
                used_for_summary=True,
                note="App or browser semantic adapter context was available.",
            )
        )
        stronger_than_title = True

    windows = _window_stack(observation)
    focus_verified = focus_evidence_verified(observation)
    if windows or focus_verified:
        window_titles = [str(item.get("window_title") or item.get("title") or "").strip() for item in windows]
        entries.append(
            _entry(
                source="foreground_window_stack",
                tier=5,
                source_type=ScreenSourceType.FOCUS_STATE,
                confidence=_confidence(
                    0.62 if focus_verified else 0.46,
                    "Foreground/window-stack metadata supports app context but does not describe pixels.",
                ),
                freshness="current",
                used_for_summary=not stronger_than_title,
                note="Window-stack and monitor metadata were available as supporting context.",
                details={
                    "focus_verified": focus_verified,
                    "window_titles": window_titles[:5],
                },
            )
        )

    title = _window_title(observation)
    if title:
        entries.append(
            _entry(
                source="active_window_title",
                tier=6,
                source_type=ScreenSourceType.FOCUS_STATE,
                confidence=_confidence(
                    0.32 if focus_verified else 0.2,
                    "A title is only weak supporting metadata and cannot describe the visible screen by itself.",
                ),
                freshness="current",
                used_for_summary=not stronger_than_title and not windows,
                note="Window title metadata is weak supporting evidence only.",
                details={"title": title, "focus_verified": focus_verified},
            )
        )

    for recent in _recent_contexts(active_context)[:2]:
        entries.append(
            _entry(
                source="stale_recent_context",
                tier=7,
                confidence=_confidence(0.1, "Recent context is historical and must not impersonate the live screen."),
                freshness=str(recent.get("freshness") or "stale"),
                used_for_summary=False,
                note="Historical screen-awareness context was present but not treated as current.",
                details={"summary": str(recent.get("summary") or "")[:160]},
            )
        )

    clipboard = _clipboard_text(active_context, observation)
    if clipboard:
        entries.append(
            _entry(
                source="clipboard_hint",
                tier=8,
                source_type=ScreenSourceType.CLIPBOARD,
                confidence=_confidence(0.08, "Clipboard text may be useful context but is not visible screen truth."),
                freshness="clipboard_hint",
                used_for_summary=False,
                note="Clipboard text was kept as a hint only.",
                details={"preview": clipboard[:160]},
            )
        )

    entries.sort(
        key=lambda item: (
            int(item.get("tier") or 99),
            -float((item.get("confidence") or {}).get("score") or 0.0),
            str(item.get("source") or ""),
        )
    )
    for index, entry in enumerate(entries, start=1):
        entry["rank"] = index
    return entries


def top_evidence_confidence(ranking: list[dict[str, Any]]) -> dict[str, Any]:
    if not ranking:
        return ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No current-screen evidence was available.",
        ).to_dict()
    confidence = ranking[0].get("confidence")
    return dict(confidence) if isinstance(confidence, dict) else _confidence(0.0, "No confidence metadata was available.")


def top_summary_evidence(ranking: list[dict[str, Any]]) -> dict[str, Any]:
    for entry in ranking:
        if bool(entry.get("used_for_summary")):
            return dict(entry)
    return dict(ranking[0]) if ranking else {}


def has_strong_current_evidence(ranking: list[dict[str, Any]]) -> bool:
    entry = top_summary_evidence(ranking)
    if not entry:
        return False
    confidence = entry.get("confidence") if isinstance(entry.get("confidence"), dict) else {}
    try:
        score = float(confidence.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    try:
        tier = int(entry.get("tier") or 99)
    except (TypeError, ValueError):
        tier = 99
    return (
        str(entry.get("freshness") or "").strip().lower() == "current"
        and tier <= 4
        and score >= 0.7
    )
